"""Sign-up, passwords, lockout, recovery and sessions through allauth's headless API (M1-07).

Everything runs as the restricted app role, so the table grants for sessions, email addresses
and authenticators are proved too. Settings under test: SEC §3.
"""

import hashlib
from datetime import datetime, timedelta

import pytest
import requests
from allauth.account.models import EmailAddress
from allauth.usersessions.models import UserSession
from django.conf import settings as django_settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from apps.core.models import User
from apps.core.validators import BreachedPasswordValidator
from tests.support import GOOD_PASSWORD, Browser, latest_link_key

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def app_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


def flow_ids(response) -> list[str]:
    return [f["id"] for f in response.json()["data"]["flows"]]


# --- Sign-up and email verification -----------------------------------------------------------


def test_sign_up_then_verify_then_sign_in():
    browser = Browser()
    response = browser.sign_up("ada@example.com", name="Ada Lovelace")
    assert response.status_code == 401
    assert "verify_email" in flow_ids(response)

    # Until the address is verified there is no way in, even with the right password.
    assert browser.log_in("ada@example.com").status_code == 401
    assert not browser.is_signed_in()

    message = mail.outbox[0]
    assert message.to == ["ada@example.com"]
    assert message.subject.startswith("[Greenlit]")
    assert f"{django_settings.FRONTEND_URL}/verify-email/" in message.body

    assert browser.verify_email().status_code == 401  # verified, but the person still signs in
    assert not browser.is_signed_in()
    assert browser.log_in("ada@example.com").status_code == 200
    assert browser.is_signed_in()

    me = browser.api("get", "/api/me/").json()
    assert (me["email"], me["name"]) == ("ada@example.com", "Ada Lovelace")
    user = User.objects.get(email="ada@example.com")
    assert user.auth_provider == "email"
    assert user.password.startswith("argon2$")
    address = EmailAddress.objects.get(user=user)
    assert address.verified and address.primary


def test_an_address_cannot_be_registered_twice_without_saying_so():
    Browser().sign_up_and_in("dup@example.com")
    again = Browser().sign_up("dup@example.com")
    # allauth answers as for a fresh sign-up and emails the holder instead of revealing it.
    assert again.status_code == 401
    assert "verify_email" in flow_ids(again)
    assert User.objects.filter(email="dup@example.com").count() == 1


def test_a_wrong_verification_key_is_refused():
    browser = Browser()
    browser.sign_up("badkey@example.com")
    response = browser.auth("post", "/auth/email/verify", {"key": "not-a-real-key"})
    assert response.status_code == 400
    assert not EmailAddress.objects.get(email="badkey@example.com").verified


# --- Passwords --------------------------------------------------------------------------------


@pytest.mark.parametrize("password", ["short1!", "elevenchars", "123456789012"])
def test_weak_passwords_are_refused(password):
    response = Browser().sign_up("weak@example.com", password)
    assert response.status_code == 400
    assert [e["param"] for e in response.json()["errors"]] == ["password"]
    assert not User.objects.filter(email="weak@example.com").exists()


def test_twelve_characters_is_enough():
    assert Browser().sign_up("twelve@example.com", "plum-kettle-9x").status_code == 401


class FakeResponse:
    def __init__(self, text: str = "", fail: bool = False):
        self.text, self._fail = text, fail

    def raise_for_status(self):
        if self._fail:
            raise requests.HTTPError("503")


def breached_service(monkeypatch, password: str, count: int = 9):
    """Make the breach service report `password`, and record what was asked of it."""
    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(f"0018A45C4D1DEF81644B54AB7F969B88D65:1\r\n{digest[5:]}:{count}\r\n")

    monkeypatch.setattr("apps.core.validators.requests.get", fake_get)
    return calls


def test_a_breached_password_is_refused_and_only_a_hash_prefix_leaves(settings, monkeypatch):
    settings.BREACHED_PASSWORD_CHECK = True
    calls = breached_service(monkeypatch, "Tr0ub4dor&3 horse")
    with pytest.raises(ValidationError) as caught:
        BreachedPasswordValidator().validate("Tr0ub4dor&3 horse")
    assert caught.value.code == "password_breached"

    ((url, kwargs),) = calls
    digest = hashlib.sha1(b"Tr0ub4dor&3 horse", usedforsecurity=False).hexdigest().upper()
    assert url.endswith("/range/" + digest[:5])
    assert digest[5:] not in url and "Tr0ub4dor" not in url
    assert kwargs["timeout"] <= 2


def test_a_breached_password_is_refused_at_sign_up(settings, monkeypatch):
    settings.BREACHED_PASSWORD_CHECK = True
    breached_service(monkeypatch, "winter-is-coming-1")
    response = Browser().sign_up("breach@example.com", "winter-is-coming-1")
    assert response.status_code == 400
    assert not User.objects.filter(email="breach@example.com").exists()


def test_padding_entries_with_a_zero_count_are_not_matches(settings, monkeypatch):
    settings.BREACHED_PASSWORD_CHECK = True
    breached_service(monkeypatch, "an-unbreached-phrase-7", count=0)
    BreachedPasswordValidator().validate("an-unbreached-phrase-7")  # does not raise


@pytest.mark.parametrize("failure", ["down", "error"])
def test_the_check_fails_open_when_the_service_is_unavailable(settings, monkeypatch, failure):
    settings.BREACHED_PASSWORD_CHECK = True

    def fake_get(url, **kwargs):
        if failure == "down":
            raise requests.ConnectionError("no route")
        return FakeResponse(fail=True)

    monkeypatch.setattr("apps.core.validators.requests.get", fake_get)
    BreachedPasswordValidator().validate("anything-at-all-123")  # does not raise


def test_the_check_can_be_switched_off(settings, monkeypatch):
    settings.BREACHED_PASSWORD_CHECK = False
    called = breached_service(monkeypatch, "x" * 14)
    BreachedPasswordValidator().validate("x" * 14)
    assert called == []


# --- Brute force ------------------------------------------------------------------------------


def failures(browser: Browser, email: str, n: int) -> list[int]:
    return [browser.log_in(email, "wrong-password-here").status_code for _ in range(n)]


def test_five_failures_lock_the_account_even_for_the_right_password_and_warn_its_owner(real_cache):
    Browser().sign_up_and_in("lock@example.com")
    attacker = Browser()
    assert failures(attacker, "lock@example.com", 5) == [400] * 5

    refused = attacker.log_in("lock@example.com", GOOD_PASSWORD)
    assert refused.status_code != 200 and not attacker.is_signed_in()

    warnings = [m for m in mail.outbox if "trying to sign in" in m.subject]
    assert [m.to for m in warnings] == [["lock@example.com"]]  # once, not once per attempt


def test_the_lockout_looks_the_same_for_an_address_that_has_no_account(real_cache):
    Browser().sign_up_and_in("real@example.com")
    known = failures(Browser(REMOTE_ADDR="10.0.0.1"), "real@example.com", 7)
    unknown = failures(Browser(REMOTE_ADDR="10.0.0.2"), "nobody@example.com", 7)
    assert known == unknown
    assert not [m for m in mail.outbox if "nobody@example.com" in m.to and "trying" in m.subject]


def test_failures_from_one_address_lock_that_address_but_not_others(real_cache):
    Browser().sign_up_and_in("target@example.com")
    attacker = Browser(REMOTE_ADDR="10.9.9.9")
    for n in range(5):  # a different address each time, so no account is the one being guessed
        attacker.log_in(f"guess{n}@example.com", "wrong-password-here")
    assert attacker.log_in("target@example.com", GOOD_PASSWORD).status_code != 200

    elsewhere = Browser(REMOTE_ADDR="10.8.8.8")
    assert elsewhere.log_in("target@example.com", GOOD_PASSWORD).status_code == 200


def test_a_successful_sign_in_does_not_reset_the_failure_count(real_cache):
    """Otherwise an attacker could slip in one valid login to keep guessing forever."""
    Browser().sign_up_and_in("persist@example.com")
    address = "10.7.7.7"

    def attempt(password: str) -> int:
        return Browser(REMOTE_ADDR=address).log_in("persist@example.com", password).status_code

    assert [attempt("wrong-password-here") for _ in range(3)] == [400, 400, 400]
    assert attempt(GOOD_PASSWORD) == 200  # a real sign-in in the middle
    assert [attempt("wrong-password-here") for _ in range(2)] == [400, 400]
    # Five failures in total, so the next attempt is refused even with the right password.
    assert attempt(GOOD_PASSWORD) != 200
    assert len([m for m in mail.outbox if "trying to sign in" in m.subject]) == 1


# --- Recovery ---------------------------------------------------------------------------------


def reset_requests(email: str):
    return Browser().auth("post", "/auth/password/request", {"email": email})


def test_password_reset_does_not_reveal_whether_an_address_is_registered():
    Browser().sign_up_and_in("known@example.com")
    mail.outbox.clear()
    known, unknown = reset_requests("known@example.com"), reset_requests("unknown@example.com")
    assert known.status_code == unknown.status_code == 200
    assert known.content == unknown.content
    with_link = [m for m in mail.outbox if "reset-password/" in str(m.body)]
    assert [m.to for m in with_link] == [["known@example.com"]]


def test_a_reset_link_sets_a_new_password_once():
    Browser().sign_up_and_in("reset@example.com")
    reset_requests("reset@example.com")
    key = latest_link_key("reset-password/")

    browser = Browser()
    done = browser.auth(
        "post", "/auth/password/reset", {"key": key, "password": "a-brand-new-phrase-5"}
    )
    assert done.status_code in (200, 401), done.content
    assert Browser().log_in("reset@example.com", GOOD_PASSWORD).status_code == 400
    assert Browser().log_in("reset@example.com", "a-brand-new-phrase-5").status_code == 200

    again = Browser().auth(
        "post", "/auth/password/reset", {"key": key, "password": "yet-another-phrase-6"}
    )
    assert again.status_code == 400


@pytest.mark.parametrize("minutes,works", [(29, True), (31, False)])
def test_a_reset_link_works_for_30_minutes(monkeypatch, minutes, works):
    Browser().sign_up_and_in(f"expiry{minutes}@example.com")
    reset_requests(f"expiry{minutes}@example.com")
    key = latest_link_key("reset-password/")
    later = datetime.now() + timedelta(minutes=minutes)
    monkeypatch.setattr(PasswordResetTokenGenerator, "_now", lambda self: later)
    response = Browser().auth(
        "post", "/auth/password/reset", {"key": key, "password": "fresh-phrase-for-me-8"}
    )
    assert (response.status_code in (200, 401)) is works, response.content


def test_the_configured_reset_lifetime_is_30_minutes():
    assert django_settings.PASSWORD_RESET_TIMEOUT == 30 * 60


# --- Sessions ---------------------------------------------------------------------------------


def signed_in_twice(email: str) -> tuple[Browser, Browser]:
    first = Browser()
    first.sign_up_and_in(email)
    second = Browser()
    assert second.log_in(email).status_code == 200
    return first, second


def test_changing_the_password_ends_every_other_session_but_not_this_one():
    first, second = signed_in_twice("change@example.com")
    response = first.auth(
        "post",
        "/account/password/change",
        {"current_password": GOOD_PASSWORD, "new_password": "my-changed-phrase-3"},
    )
    assert response.status_code == 200, response.content
    assert first.is_signed_in()
    assert not second.is_signed_in()


def test_sign_out_everywhere_ends_all_sessions_including_this_one():
    first, second = signed_in_twice("everywhere@example.com")
    assert first.api("post", "/api/sessions/end-all/").status_code == 204
    assert not first.is_signed_in()
    assert not second.is_signed_in()
    assert UserSession.objects.filter(user__email="everywhere@example.com").count() == 0


def test_a_session_ends_30_days_after_sign_in_however_active():
    browser = Browser()
    browser.sign_up_and_in("thirty@example.com")
    assert browser.api("get", "/api/me/").status_code == 200

    session = browser.client.session
    session["login_at"] = int(timezone.now().timestamp()) - (30 * 24 * 60 * 60 + 60)
    session.save()
    assert browser.api("get", "/api/me/").status_code in (401, 403)
    assert not browser.is_signed_in()


def test_a_session_just_inside_30_days_still_works():
    browser = Browser()
    browser.sign_up_and_in("twentynine@example.com")
    session = browser.client.session
    session["login_at"] = int(timezone.now().timestamp()) - (29 * 24 * 60 * 60)
    session.save()
    assert browser.api("get", "/api/me/").status_code == 200


def test_a_session_idle_for_12_hours_ends():
    browser = Browser()
    browser.sign_up_and_in("idle@example.com")
    Session.objects.update(expire_date=timezone.now() - timedelta(seconds=1))
    assert not browser.is_signed_in()


def test_the_idle_timeout_is_12_hours_and_renews_on_each_request():
    assert django_settings.SESSION_COOKIE_AGE == 12 * 60 * 60
    assert django_settings.SESSION_SAVE_EVERY_REQUEST is True


def test_the_session_cookie_is_not_readable_by_scripts_and_is_not_sent_cross_site():
    browser = Browser()
    browser.sign_up_and_in("cookie@example.com")
    cookie = browser.client.cookies["sessionid"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"


# --- Invitations and sign-in together ----------------------------------------------------------


def test_an_invited_person_signs_up_verifies_and_joins(django_capture_on_commit_callbacks):
    owner = Browser()
    owner.sign_up_and_in("host@example.com", name="Host")
    created = owner.api("post", "/api/orgs/", {"name": "Joinable", "slug": "joinable"})
    assert created.status_code == 201

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        sent = owner.api(
            "post",
            "/api/invites/",
            {"email": "guest@example.com", "role": "qa_engineer"},
            org="joinable",
        )
    assert sent.status_code == 201
    token = latest_link_key("/invite/")

    guest = Browser()
    assert guest.sign_up("guest@example.com").status_code == 401
    # Not verified, so not signed in, so the invitation cannot be used yet.
    assert guest.api("post", "/api/invites/accept/", {"token": token}).status_code in (401, 403)
    assert guest.verify_email().status_code == 401
    assert guest.log_in("guest@example.com").status_code == 200

    joined = guest.api("post", "/api/invites/accept/", {"token": token})
    assert joined.status_code == 200 and joined.json()["slug"] == "joinable"
    assert guest.api("get", "/api/org/", org="joinable").json()["role"] == "qa_engineer"
