"""The sign-in surface as a whole: which routes exist, that all of them are CSRF-protected,
that allauth's own pages are off, and the Google sign-in rules (M1-07, SEC §3).

allauth's routes live outside `api/`, so the permission table and isolation suite do not see
them. The list below is checked by hand, and a new route fails the test until it is reviewed.
"""

import pytest
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection
from django.test import Client, RequestFactory
from django.urls import URLPattern, URLResolver, get_resolver

from apps.core.auth_adapter import SocialAccountAdapter
from apps.core.models import User
from tests.support import Browser, methods_of

pytestmark = pytest.mark.django_db

# Every route under `_allauth/browser/v1/`, reviewed. "Anonymous" routes can be called by
# anyone: they start a sign-in, sign-up or recovery, and are rate limited by allauth.
EXPECTED_AUTH_ROUTES = {
    "_allauth/browser/v1/config",
    "_allauth/browser/v1/auth/session",
    "_allauth/browser/v1/auth/reauthenticate",
    "_allauth/browser/v1/auth/code/confirm",
    "_allauth/browser/v1/auth/login",
    "_allauth/browser/v1/auth/signup",
    "_allauth/browser/v1/auth/email/verify",
    "_allauth/browser/v1/auth/email/verify/resend",
    "_allauth/browser/v1/auth/phone/verify",
    "_allauth/browser/v1/auth/phone/verify/resend",
    "_allauth/browser/v1/auth/code/request",
    "_allauth/browser/v1/auth/code/resend",
    "_allauth/browser/v1/auth/password/request",
    "_allauth/browser/v1/auth/password/reset",
    "_allauth/browser/v1/auth/provider/redirect",
    "_allauth/browser/v1/auth/provider/token",
    "_allauth/browser/v1/auth/provider/signup",
    "_allauth/browser/v1/auth/2fa/authenticate",
    "_allauth/browser/v1/auth/2fa/reauthenticate",
    "_allauth/browser/v1/auth/2fa/trust",
    "_allauth/browser/v1/auth/sessions",
    "_allauth/browser/v1/account/password/change",
    "_allauth/browser/v1/account/email",
    "_allauth/browser/v1/account/phone",
    "_allauth/browser/v1/account/providers",
    "_allauth/browser/v1/account/authenticators",
    "_allauth/browser/v1/account/authenticators/totp",
    "_allauth/browser/v1/account/authenticators/recovery-codes",
}


def discovered_routes(prefix: str) -> dict[str, type]:
    found = {}

    def walk(patterns, base=""):
        for p in patterns:
            route = base + str(p.pattern)
            if isinstance(p, URLResolver):
                walk(p.url_patterns, route)
            elif isinstance(p, URLPattern) and route.startswith(prefix):
                found[route.rstrip("/")] = getattr(p.callback, "view_class", None) or getattr(
                    p.callback, "cls", None
                )

    walk(get_resolver().url_patterns)
    return found


def test_the_set_of_sign_in_routes_is_the_reviewed_one():
    routes = set(discovered_routes("_allauth/browser/"))
    assert len(routes) >= 15, "route discovery found almost nothing"
    assert routes - EXPECTED_AUTH_ROUTES == set(), "new allauth route: review it, then add it here"
    # Routes that depend on switched-off features may be absent, but no hardware-key or
    # phone route should exist while those are off.
    assert not [r for r in routes if "webauthn" in r or "passkey" in r]


def test_only_the_browser_client_is_enabled():
    assert Client().get("/_allauth/app/v1/config").status_code == 404


def test_allauths_own_pages_are_off_so_the_single_page_app_is_the_only_sign_in():
    for path in (
        "/accounts/login/",
        "/accounts/signup/",
        "/accounts/password/reset/",
        "/accounts/2fa/",
    ):
        assert Client().get(path).status_code == 404, path


def test_the_config_offers_only_what_is_meant_to_be_offered():
    config = Browser().auth("get", "/config").json()["data"]
    assert config["account"]["login_methods"] == ["email"]
    assert config["mfa"]["supported_types"] == ["totp", "recovery_codes"]
    assert config["mfa"]["passkey_login_enabled"] is False
    assert [p["id"] for p in config["socialaccount"]["providers"]] == ["google"]


def test_every_state_changing_sign_in_route_refuses_a_request_without_a_csrf_token():
    client = Client(enforce_csrf_checks=True)
    checked = 0
    for route, view_cls in discovered_routes("_allauth/browser/").items():
        for method in methods_of(view_cls):
            if method == "get":
                continue
            response = getattr(client, method)(
                "/" + route, data="{}", content_type="application/json"
            )
            assert response.status_code == 403, f"{method.upper()} {route}: {response.status_code}"
            checked += 1
    assert checked >= 10


def test_the_sign_in_routes_are_rate_limited(real_cache):
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")
    statuses = [Browser().sign_up(f"flood{n}@example.com").status_code for n in range(25)]
    assert statuses[0] == 401  # a normal sign-up, waiting for verification
    assert 429 in statuses


# --- Google sign-in ---------------------------------------------------------------------------


def request_with_session():
    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    request._messages = FallbackStorage(request)
    request.user = AnonymousUser()
    return request


def test_a_new_google_account_is_marked_as_google_and_its_email_counts_as_verified():
    request = request_with_session()
    adapter = SocialAccountAdapter()
    login = SocialLogin(
        user=User(),
        account=SocialAccount(provider="google", uid="gid-1", extra_data={}),
        email_addresses=[EmailAddress(email="gina@example.com", verified=True, primary=True)],
    )
    adapter.populate_user(
        request, login, {"email": "gina@example.com", "first_name": "Gina", "last_name": "Hart"}
    )
    login.save(request)

    user = User.objects.get(email="gina@example.com")
    assert (user.auth_provider, user.name) == ("google", "Gina Hart")
    assert EmailAddress.objects.get(user=user, email="gina@example.com").verified
    assert SocialAccount.objects.filter(user=user, provider="google", uid="gid-1").exists()


def test_google_is_never_silently_attached_to_an_existing_password_account(settings):
    """If it were, anyone controlling a Google address could take over the matching account."""
    assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION is False
    assert settings.SOCIALACCOUNT_LOGIN_ON_GET is False


def test_the_google_client_comes_from_the_environment_not_the_code(settings):
    app = settings.SOCIALACCOUNT_PROVIDERS["google"]["APP"]
    assert set(app) == {"client_id", "secret", "key"}
    assert app["key"] == ""
    # Until real credentials are configured the provider is offered but cannot finish a login.
    assert (
        Browser()
        .auth("get", "/config")
        .json()["data"]["socialaccount"]["providers"][0]["client_id"]
        == app["client_id"]
    )
