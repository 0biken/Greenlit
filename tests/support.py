"""Helpers shared by the permission table and the isolation suite."""

import re

from django.urls import URLPattern, URLResolver, get_resolver

from apps.core.policy import AuthenticatedOnly, Public, TokenAccess

HANDLED = ("get", "post", "put", "patch", "delete")

# Values for URL parameters in sample calls.
# Placeholders for URL parameters; suites that need a real record pass their own.
PARAMS = {
    "key": "SAMPLE",
    "job_id": "00000000-0000-0000-0000-000000000000",
    "file_id": "00000000-0000-0000-0000-000000000000",
    "user_id": "00000000-0000-0000-0000-000000000000",
    "invite_id": "00000000-0000-0000-0000-000000000000",
    "version": "0.0.0",
    "defect_id": "1",
    "requirement_id": "1",
    "plan_id": "1",
    "case_id": "1",
    "source_id": "00000000-0000-0000-0000-000000000000",
    "run_id": "1",
    "token": "no-such-token",
    "link_id": "00000000-0000-0000-0000-000000000000",
    "result_id": "00000000-0000-0000-0000-000000000000",
    "item_id": "requirement.00000000-0000-0000-0000-000000000000",
}


def api_endpoints():
    """Yield (route, view class) for every route under api/."""

    def walk(patterns, prefix=""):
        for p in patterns:
            route = prefix + str(p.pattern)
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, route)
            elif isinstance(p, URLPattern) and route.startswith("api/"):
                cls = getattr(p.callback, "cls", None) or getattr(p.callback, "view_class", None)
                yield route, cls

    yield from walk(get_resolver().url_patterns)


def declared(view_cls):
    """'public', 'authenticated', a {METHOD: Action} dict, or None if nothing is declared."""
    perms = list(view_cls.permission_classes)
    for perm in perms:
        actions = getattr(perm, "actions", None)
        if actions is not None:
            return actions
    if any(issubclass(p, Public) for p in perms):
        return "public"
    if any(issubclass(p, TokenAccess) for p in perms):
        return "token"  # a share link: the token in the URL is the only credential
    if any(issubclass(p, AuthenticatedOnly) for p in perms):
        return "authenticated"
    return None


def methods_of(view_cls):
    return [m for m in HANDLED if hasattr(view_cls, m)]


def url_for(route: str, params: dict[str, str] | None = None) -> str:
    values = {**PARAMS, **(params or {})}
    return "/" + re.sub(r"<(?:\w+:)?(\w+)>", lambda m: values[m.group(1)], route)


# --- Sign-in helpers (used by tests/security) -------------------------------------------------

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import re as _re  # noqa: E402
import struct  # noqa: E402
import time  # noqa: E402
from base64 import b32decode  # noqa: E402
from datetime import timedelta  # noqa: E402
from urllib.parse import unquote  # noqa: E402

from django.core import mail  # noqa: E402
from django.test import Client  # noqa: E402
from django.utils import timezone  # noqa: E402

AUTH_BASE = "/_allauth/browser/v1"
GOOD_PASSWORD = "correct horse battery staple"


def totp_code(secret: str, at: float | None = None) -> str:
    """The 6-digit code an authenticator app would show now (RFC 6238, SHA-1, 30 seconds)."""
    key = b32decode(secret.upper() + "=" * (-len(secret) % 8))
    counter = int((time.time() if at is None else at) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10**6:06d}"


def latest_link_key(pattern: str) -> str:
    """The key in the newest email's link, e.g. pattern 'verify-email/' or 'reset-password/'."""
    body = str(mail.outbox[-1].body)
    match = _re.search(_re.escape(pattern) + r"(\S+)", body)
    assert match, f"no {pattern} link in: {body[:200]}"
    return unquote(match.group(1))


class Browser:
    """A browser talking to the sign-in API and the app API, with CSRF checks switched on."""

    def __init__(self, **client_kwargs):
        self.client = Client(enforce_csrf_checks=True, **client_kwargs)
        self.client.get(f"{AUTH_BASE}/config")  # sets the CSRF cookie, as the app does on load

    def _send(self, method: str, url: str, body=None, org: str | None = None):
        headers = {"X-CSRFToken": self.client.cookies["csrftoken"].value}
        if org:
            headers["X-Org"] = org
        kwargs: dict = {"headers": headers}
        if body is not None:
            kwargs.update(data=json.dumps(body), content_type="application/json")
        return getattr(self.client, method)(url, **kwargs)

    def auth(self, method: str, path: str, body=None):
        return self._send(method, AUTH_BASE + path, body)

    def api(self, method: str, path: str, body=None, org: str | None = None):
        return self._send(method, path, body, org)

    # Common steps
    def sign_up(self, email: str, password: str = GOOD_PASSWORD, name: str = ""):
        return self.auth(
            "post", "/auth/signup", {"email": email, "password": password, "name": name}
        )

    def verify_email(self):
        return self.auth("post", "/auth/email/verify", {"key": latest_link_key("verify-email/")})

    def log_in(self, email: str, password: str = GOOD_PASSWORD):
        return self.auth("post", "/auth/login", {"email": email, "password": password})

    def is_signed_in(self) -> bool:
        return self.auth("get", "/auth/session").status_code == 200

    def enrol_totp(self) -> str:
        """Set up an authenticator app and return its secret."""
        secret = self.auth("get", "/account/authenticators/totp").json()["meta"]["secret"]
        response = self.auth("post", "/account/authenticators/totp", {"code": totp_code(secret)})
        assert response.status_code == 200, response.content
        return secret

    def sign_up_and_in(self, email: str, password: str = GOOD_PASSWORD, name: str = ""):
        assert self.sign_up(email, password, name).status_code == 401  # verification pending
        assert self.verify_email().status_code == 401  # verified, but not signed in yet
        response = self.log_in(email, password)
        assert response.status_code == 200, response.content
        return response


PNG_BYTES = bytes.fromhex("89504e470d0a1a0a") + b"0" * 32


def stored_file(org, project, name: str, data: bytes = PNG_BYTES):
    """An uploaded, scanned, available file with its bytes in storage. Call in the org's scope."""
    import hashlib as _hashlib
    import uuid as _uuid

    from apps.files.models import FileState, StoredFile
    from apps.files.storage import get_storage

    file_id = _uuid.uuid4()
    key = f"{org.id}/{project.id}/{file_id}"
    get_storage().put_bytes(key, data)
    return StoredFile.objects.create(
        id=file_id,
        org_id=org.id,
        project=project,
        kind="evidence",
        original_name=name,
        storage_key=key,
        declared_mime="image/png",
        detected_type="png",
        size_bytes=len(data),
        sha256=_hashlib.sha256(data).hexdigest(),
        state=FileState.AVAILABLE,
    )


def seed_spine(org, project, lead, tester, upload, label: str = "Sample"):
    """One of everything in the requirement-to-sign-off chain, made through the services so
    every rule applies: a requirement covered by a published case, a release, a run with a
    failed result, a defect filed from it, fixed and retested with evidence, a snooze and a
    signed-off release with its frozen report. Call in the org's scope. Returns the records."""
    from apps.core.choices import Priority
    from apps.core.models import Membership
    from apps.defects import status
    from apps.inbox.models import Notification, Snooze
    from apps.plans import services as plans
    from apps.reports import services as reports
    from apps.reports import sharing
    from apps.requirements.services import create_requirement
    from apps.runs import services as runs
    from apps.runs.models import CaseResult

    requirement = create_requirement(
        project, lead, title=f"{label} checkout", text=f"{label} users can pay by card."
    )
    plan = plans.create_plan(project, lead, title=f"{label} checkout plan")
    plans.add_case(
        plans.draft_of(plan),
        lead,
        title=f"{label} pays by card",
        steps=["Add an item", "Pay by card"],
        expected="The order is confirmed.",
        requirements=[requirement],
    )
    version = plans.approve(plans.draft_of(plan), lead)
    release = runs.create_release(project, lead, name="1.0")
    run = runs.start_run(release, version, tester, build="100", environment="staging")
    result = CaseResult.objects.get(run=run)
    runs.record_result(result, tester, "failed", note=f"{label} payment times out")
    defect = status.create_defect(
        project,
        tester,
        title=f"{label} payment times out",
        severity=Priority.HIGH,
        owner=tester,
        release=release,
        found_in_result=result,
        evidence_file_ids=[upload.pk],
    )
    defect = status.set_tracker_status(defect, lead, "fixed")
    retest = status.record_retest(defect, tester, outcome="failed", evidence_file_ids=[upload.pk])
    defect.refresh_from_db()
    snooze = Snooze.objects.create(
        org_id=org.id,
        user=tester,
        target_type="requirement",
        target_id=requirement.pk,
        until=timezone.now() + timedelta(days=1),
        reason=f"{label} waiting",
    )
    sign_off = reports.sign_off(
        release, Membership.objects.get(user=lead), reason=f"{label} accepted the risk"
    )
    share_link, share_token = sharing.create_link(release, lead)
    Notification.objects.create(
        org_id=org.id,
        user=tester,
        level="48h",
        target_type="defect",
        target_id=defect.pk,
        cycle=f"{label} cycle",
        sent_at=timezone.now(),
    )
    # A pasted PRD with requirements drafted from it (the stub provider answers from the text),
    # and one draft the checks refused.
    from apps.ai.models import AiCall, AiDroppedItem
    from apps.core.models import Job
    from apps.sources import jobs as source_jobs
    from apps.sources import services as sources

    source = sources.create_from_text(
        project,
        lead,
        title=f"{label} PRD",
        text=f"{label} users must be able to pay by card at the till. "
        f"{label} shoppers can also collect their order in the shop.",
    )
    source_jobs.draft_requirements(Job.objects.get(pk=source.job_id), str(source.pk))
    AiDroppedItem.objects.create(
        org_id=org.id,
        call=AiCall.objects.filter(source_id=source.pk).first(),
        reason="quote_not_found",
        item={"title": f"{label} invented requirement"},
    )
    return {
        "source": source,
        "share_link": share_link,
        "share_token": share_token,
        "requirement": requirement,
        "plan": plan,
        "case": plans.TestCase.objects.get(project=project),
        "release": release,
        "run": run,
        "result": result,
        "defect": defect,
        "retest": retest,
        "snooze": snooze,
        "sign_off": sign_off,
    }
