"""Security headers, CSRF and rate limits (M1-16, SEC §8).

Endpoints are discovered from the URL config, so a new endpoint is covered automatically.
"""

import importlib
import uuid

import pytest
from django.db import connection
from django.test import Client
from rest_framework.throttling import SimpleRateThrottle

from apps.core import services
from apps.core.models import Membership, MembershipStatus, Role, User
from apps.core.tenancy import org_scope
from apps.core.throttles import AiJobThrottle, IpThrottle, OrgThrottle, UploadThrottle, UserThrottle
from tests.support import api_endpoints, methods_of, url_for

pytestmark = pytest.mark.django_db

JSON = "application/json"


def make_user(email: str) -> User:
    return User.objects.create_user(email, "x" * 14)


def signed_in(user: User, **client_kwargs) -> Client:
    client = Client(**client_kwargs)
    client.force_login(user)
    return client


# --- Headers ---------------------------------------------------------------------------------


def directives(policy: str) -> dict[str, list[str]]:
    parsed = {}
    for part in policy.split(";"):
        name, *values = part.split()
        parsed[name] = values
    return parsed


def test_responses_carry_the_security_headers():
    response = Client().get("/api/health/")
    assert response.status_code == 200

    csp = directives(response.headers["Content-Security-Policy"])
    assert csp["default-src"] == ["'none'"]
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["base-uri"] == ["'none'"]
    assert csp["object-src"] == ["'none'"]
    assert csp["form-action"] == ["'self'"]

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    permissions = response.headers["Permissions-Policy"]
    assert "camera=(self)" in permissions and "microphone=()" in permissions


def test_the_script_policy_never_allows_inline_or_eval():
    csp = directives(Client().get("/api/health/").headers["Content-Security-Policy"])
    for name in ("script-src", "style-src"):
        assert "'unsafe-inline'" not in csp[name], name
        assert "'unsafe-eval'" not in csp[name], name
    assert "'unsafe-eval'" not in csp["script-src"]
    # Django adds a nonce only when a template uses one, so a JSON response has none.
    assert "'self'" in csp["script-src"] and "https:" not in csp["script-src"]


def test_every_endpoint_gets_the_headers_even_when_it_refuses():
    for route, _ in api_endpoints():
        response = Client().get(url_for(route))
        assert "Content-Security-Policy" in response.headers, route
        assert response.headers["X-Content-Type-Options"] == "nosniff", route


def test_hsts_is_sent_over_https(settings):
    settings.SECURE_HSTS_SECONDS = 63072000
    settings.SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    response = Client().get("/api/health/", secure=True)
    assert "max-age=63072000" in response.headers["Strict-Transport-Security"]
    assert "includeSubDomains" in response.headers["Strict-Transport-Security"]


def test_production_settings_turn_the_protections_on():
    production = importlib.import_module("config.settings.production")
    assert production.DEBUG is False
    assert production.SECURE_SSL_REDIRECT is True
    assert production.SECURE_HSTS_SECONDS >= 31536000
    assert production.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
    assert production.SESSION_COOKIE_SECURE is True
    assert production.CSRF_COOKIE_SECURE is True
    assert production.SESSION_COOKIE_HTTPONLY is True
    assert production.SESSION_COOKIE_SAMESITE in ("Lax", "Strict")
    assert production.X_FRAME_OPTIONS == "DENY"


# --- CSRF -------------------------------------------------------------------------------------


def state_changing_calls():
    for route, view_cls in api_endpoints():
        if view_cls is None:
            continue
        for method in methods_of(view_cls):
            if method != "get":
                yield route, method


def test_there_are_state_changing_endpoints_to_check():
    assert len(list(state_changing_calls())) >= 4


def test_every_state_changing_endpoint_refuses_a_request_without_a_csrf_token():
    client = signed_in(make_user("csrf@example.com"), enforce_csrf_checks=True)
    for route, method in state_changing_calls():
        response = getattr(client, method)(url_for(route), data={}, content_type=JSON)
        assert response.status_code == 403, f"{method.upper()} {route}: {response.status_code}"
        assert b"CSRF" in response.content, (
            f"{method.upper()} {route} was refused for another reason"
        )


def test_a_request_with_the_token_goes_through():
    user = make_user("csrf2@example.com")
    client = signed_in(user, enforce_csrf_checks=True)
    token = client.get("/api/csrf/").json()["csrfToken"]
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")
    response = client.post(
        "/api/orgs/", data={"name": "Csrf Works"}, content_type=JSON, headers={"X-CSRFToken": token}
    )
    assert response.status_code == 201, response.content


def test_a_wrong_token_is_refused():
    client = signed_in(make_user("csrf3@example.com"), enforce_csrf_checks=True)
    client.get("/api/csrf/")
    response = client.post(
        "/api/orgs/", data={"name": "Nope"}, content_type=JSON, headers={"X-CSRFToken": "wrong"}
    )
    assert response.status_code == 403


# --- Rate limits ------------------------------------------------------------------------------


@pytest.fixture
def limits(settings, monkeypatch):
    """A real cache and low limits, set per test."""

    def apply(**rates: str) -> None:
        settings.CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": f"throttle-{uuid.uuid4()}",
            }
        }
        full = {"ip": "1000/min", "user": "1000/min", "org": "1000/min", **rates}
        monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", full)

    return apply


def test_every_api_view_uses_all_three_default_throttles():
    expected = {IpThrottle, UserThrottle, OrgThrottle}
    for route, view_cls in api_endpoints():
        assert view_cls is not None
        assert expected <= set(view_cls.throttle_classes), f"{route} opts out of rate limits"


def test_a_user_who_goes_over_the_limit_gets_429_with_retry_after(limits):
    limits(user="3/min")
    ada, bob = make_user("ada@example.com"), make_user("bob@example.com")
    client = signed_in(ada)
    assert [client.get("/api/me/").status_code for _ in range(3)] == [200, 200, 200]
    over = client.get("/api/me/")
    assert over.status_code == 429
    assert int(over.headers["Retry-After"]) > 0
    assert signed_in(bob).get("/api/me/").status_code == 200  # someone else is unaffected


def test_people_in_one_organisation_share_its_limit_and_other_organisations_do_not(limits):
    limits(org="3/min")
    ada, bob, cy = (make_user(f"{n}@example.com") for n in ("ada2", "bob2", "cy2"))
    alpha = services.create_organisation(ada, "Alpha Limits", "alpha-limits")
    beta = services.create_organisation(cy, "Beta Limits", "beta-limits")
    with org_scope(alpha.id):
        Membership.objects.create(
            org_id=alpha.id, user=bob, role=Role.VIEWER, status=MembershipStatus.ACTIVE
        )
    ada_client, bob_client, cy_client = signed_in(ada), signed_in(bob), signed_in(cy)
    headers = {"X-Org": "alpha-limits"}
    assert ada_client.get("/api/org/", headers=headers).status_code == 200
    assert bob_client.get("/api/org/", headers=headers).status_code == 200
    assert ada_client.get("/api/org/", headers=headers).status_code == 200
    assert bob_client.get("/api/org/", headers=headers).status_code == 429
    assert ada_client.get("/api/org/", headers=headers).status_code == 429
    assert cy_client.get("/api/org/", headers={"X-Org": beta.slug}).status_code == 200


def test_anonymous_requests_are_limited_by_address_and_a_faked_header_does_not_help(limits):
    limits(ip="3/min")
    client = Client()
    assert [client.get("/api/health/").status_code for _ in range(3)] == [200, 200, 200]
    for fake in ("1.1.1.1", "2.2.2.2", "3.3.3.3, 4.4.4.4"):
        response = client.get("/api/health/", headers={"X-Forwarded-For": fake})
        assert response.status_code == 429, fake


def test_a_different_address_has_its_own_allowance(limits):
    limits(ip="2/min")
    assert [Client().get("/api/health/").status_code for _ in range(3)] == [200, 200, 429]
    other = Client(REMOTE_ADDR="10.9.8.7")
    assert other.get("/api/health/").status_code == 200


def test_the_extra_scopes_are_configured(settings):
    # Instantiating a throttle fails if its scope has no rate in the settings.
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["upload"]
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["ai_job"]
    assert UploadThrottle().scope == "upload" and AiJobThrottle().scope == "ai_job"
