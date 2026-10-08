"""Two-step verification: enrolment, the second step at sign-in, enforcement for owners and
admins, and encryption of the stored secret (M1-07, SEC §3, SEC §6)."""

import importlib
import json

import pytest
from allauth.mfa.models import Authenticator
from cryptography.fernet import Fernet, InvalidToken
from django.core.checks import Error
from django.db import connection

from apps.core import checks
from apps.core.auth_adapter import MFAAdapter
from apps.core.models import Membership, MembershipStatus, Role, User
from apps.core.tenancy import org_scope
from tests.support import Browser, totp_code

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def app_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


@pytest.fixture
def enforced(settings):
    settings.ENFORCE_MFA_ROLES = ["owner", "admin"]


def flow_ids(response) -> list[str]:
    return [f["id"] for f in response.json()["data"]["flows"]]


# --- Enrolment and the second step -----------------------------------------------------------


def test_enrolling_marks_the_account_as_protected():
    browser = Browser()
    browser.sign_up_and_in("mfa1@example.com")
    assert browser.api("get", "/api/me/").json()["mfa_enabled"] is False
    browser.enrol_totp()
    assert browser.api("get", "/api/me/").json()["mfa_enabled"] is True


def test_a_wrong_code_does_not_enrol():
    browser = Browser()
    browser.sign_up_and_in("mfa2@example.com")
    browser.auth("get", "/account/authenticators/totp")
    response = browser.auth("post", "/account/authenticators/totp", {"code": "000000"})
    assert response.status_code == 400
    assert not Authenticator.objects.filter(user__email="mfa2@example.com").exists()


def test_signing_in_needs_the_second_step_once_enrolled():
    first = Browser()
    first.sign_up_and_in("mfa3@example.com")
    secret = first.enrol_totp()

    later = Browser()
    step_one = later.log_in("mfa3@example.com")
    assert step_one.status_code == 401
    assert "mfa_authenticate" in flow_ids(step_one)
    assert not later.is_signed_in()

    wrong = later.auth("post", "/auth/2fa/authenticate", {"code": "000000"})
    assert wrong.status_code == 400
    assert not later.is_signed_in()

    right = later.auth("post", "/auth/2fa/authenticate", {"code": totp_code(secret)})
    assert right.status_code == 200
    assert later.is_signed_in()


def test_a_recovery_code_works_once():
    first = Browser()
    first.sign_up_and_in("mfa4@example.com")
    first.enrol_totp()
    codes = first.auth("get", "/account/authenticators/recovery-codes").json()["data"]
    assert codes["total_code_count"] == 10
    code = codes["unused_codes"][0]

    one = Browser()
    one.log_in("mfa4@example.com")
    assert one.auth("post", "/auth/2fa/authenticate", {"code": code}).status_code == 200

    two = Browser()
    two.log_in("mfa4@example.com")
    assert two.auth("post", "/auth/2fa/authenticate", {"code": code}).status_code == 400


# --- The secret is encrypted at rest ----------------------------------------------------------


def test_the_authenticator_secret_is_not_stored_in_the_clear():
    browser = Browser()
    browser.sign_up_and_in("enc@example.com")
    secret = browser.enrol_totp()
    row = Authenticator.objects.get(user__email="enc@example.com", type=Authenticator.Type.TOTP)
    assert secret not in json.dumps(row.data)
    assert MFAAdapter().decrypt(row.data["secret"]) == secret


def test_keys_can_be_rotated_without_locking_anyone_out(settings):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    adapter = MFAAdapter()

    settings.FIELD_ENCRYPTION_KEYS = [old]
    sealed_before = adapter.encrypt("JBSWY3DPEHPK3PXP")

    settings.FIELD_ENCRYPTION_KEYS = [new, old]  # rotation: new encrypts, both decrypt
    assert adapter.decrypt(sealed_before) == "JBSWY3DPEHPK3PXP"
    sealed_after = adapter.encrypt("JBSWY3DPEHPK3PXP")

    settings.FIELD_ENCRYPTION_KEYS = [new]  # the old key can now be retired
    assert adapter.decrypt(sealed_after) == "JBSWY3DPEHPK3PXP"
    with pytest.raises(InvalidToken):
        adapter.decrypt(sealed_before)


def test_without_configured_keys_a_key_is_derived_from_the_secret_key(settings):
    settings.FIELD_ENCRYPTION_KEYS = []
    settings.SECRET_KEY = "one-secret"
    sealed = MFAAdapter().encrypt("abc")
    assert MFAAdapter().decrypt(sealed) == "abc"
    settings.SECRET_KEY = "another-secret"
    with pytest.raises(InvalidToken):
        MFAAdapter().decrypt(sealed)


def test_outside_development_the_project_refuses_to_run_without_real_keys(settings):
    settings.DEBUG, settings.FIELD_ENCRYPTION_KEYS = False, []
    errors = checks.field_encryption_keys_set(None)
    assert [e.id for e in errors] == ["greenlit.E001"] and isinstance(errors[0], Error)

    settings.FIELD_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]
    assert checks.field_encryption_keys_set(None) == []

    settings.DEBUG, settings.FIELD_ENCRYPTION_KEYS = True, []
    assert checks.field_encryption_keys_set(None) == []


# --- Enforcement for owners and admins --------------------------------------------------------


def organisation_with(browser: Browser, slug: str):
    """A signed-in user creates an organisation through the API and becomes its owner."""
    response = browser.api("post", "/api/orgs/", {"name": slug.title(), "slug": slug})
    assert response.status_code == 201, response.content
    return response.json()


def join(org_id: str, user: User, role: str) -> None:
    with org_scope(org_id):
        Membership.objects.create(
            org_id=org_id, user=user, role=role, status=MembershipStatus.ACTIVE
        )


def test_an_owner_can_create_an_organisation_but_not_use_it_until_enrolled(enforced):
    owner = Browser()
    owner.sign_up_and_in("owner@example.com")
    organisation_with(owner, "needs-mfa")  # creating one is allowed without two-step verification

    me = owner.api("get", "/api/me/").json()
    assert me["memberships"][0]["needs_mfa"] is True and me["mfa_enabled"] is False

    for method, path, body in [
        ("get", "/api/org/", None),
        ("get", "/api/members/", None),
        ("get", "/api/projects/", None),
        ("post", "/api/projects/", {"name": "Blocked", "key": "BLK"}),
        ("post", "/api/invites/", {"email": "x@example.com", "role": "viewer"}),
    ]:
        response = owner.api(method, path, body, org="needs-mfa")
        assert response.status_code == 403, (path, response.status_code)
        assert response.json()["code"] == "mfa_required", path

    owner.enrol_totp()
    assert owner.api("get", "/api/org/", org="needs-mfa").status_code == 200
    assert owner.api("get", "/api/me/").json()["memberships"][0]["needs_mfa"] is False


def test_the_same_requirement_applies_to_admins_but_not_to_other_roles(enforced):
    owner = Browser()
    owner.sign_up_and_in("boss@example.com")
    org = organisation_with(owner, "mixed-roles")
    owner.enrol_totp()

    results = {}
    for role in (Role.ADMIN, Role.QA_LEAD, Role.QA_ENGINEER, Role.DEVELOPER, Role.VIEWER):
        email = f"{role.value}@example.com"
        browser = Browser()
        browser.sign_up_and_in(email)
        join(org["id"], User.objects.get(email=email), role.value)
        results[role.value] = browser.api("get", "/api/org/", org="mixed-roles").status_code

    assert results == {
        "admin": 403,
        "qa_lead": 200,
        "qa_engineer": 200,
        "developer": 200,
        "viewer": 200,
    }


def test_a_user_who_has_enrolled_is_not_blocked_whatever_their_role(enforced):
    browser = Browser()
    browser.sign_up_and_in("protected@example.com")
    browser.enrol_totp()
    organisation_with(browser, "protected-org")
    assert browser.api("get", "/api/org/", org="protected-org").status_code == 200


def test_enforcement_can_be_switched_off_by_configuration(settings):
    settings.ENFORCE_MFA_ROLES = []
    browser = Browser()
    browser.sign_up_and_in("optional@example.com")
    organisation_with(browser, "optional-org")
    assert browser.api("get", "/api/org/", org="optional-org").status_code == 200


def test_the_endpoints_a_new_owner_needs_to_get_enrolled_stay_open(enforced):
    browser = Browser()
    browser.sign_up_and_in("onboard@example.com")
    organisation_with(browser, "onboard-org")
    assert browser.api("get", "/api/me/").status_code == 200
    assert browser.api("get", "/api/flags/").status_code == 200
    assert browser.auth("get", "/account/authenticators/totp").status_code == 404  # secret offered


def test_sign_in_with_the_wrong_password_never_reaches_the_second_step():
    first = Browser()
    first.sign_up_and_in("pwfirst@example.com")
    first.enrol_totp()
    response = Browser().log_in("pwfirst@example.com", "not-the-password-1")
    assert response.status_code == 400
    assert "mfa_authenticate" not in json.dumps(response.json())


# --- The defaults that ship --------------------------------------------------------------------


@pytest.mark.parametrize("module", ["base", "local", "production"])
def test_owners_and_admins_are_required_to_enrol_by_default(module):
    settings_module = importlib.import_module(f"config.settings.{module}")
    assert list(settings_module.ENFORCE_MFA_ROLES) == ["owner", "admin"]
