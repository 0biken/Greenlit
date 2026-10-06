"""Error tracking with personal data and document text scrubbed (ARCH §3, SEC §5, SEC §10).

Greenlit handles unreleased product plans and evidence, so an error report must carry the
failing code path and record IDs, never request bodies, cookies, query strings, local variables,
SQL, or log text, any of which can hold document content.
"""

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

Event = dict[str, Any]


def scrub_event(event: Event, hint: dict[str, Any]) -> Event:
    request = event.get("request")
    if request:
        for key in ("data", "cookies", "query_string", "headers", "env"):
            request.pop(key, None)

    # Keep who it happened to as an ID only.
    user = event.get("user")
    if user:
        event["user"] = {"id": user["id"]} if "id" in user else {}

    # Local variables can hold document text.
    for exception in event.get("exception", {}).get("values", []):
        for frame in (exception.get("stacktrace") or {}).get("frames", []):
            frame.pop("vars", None)
        # Exception messages can quote input; keep the type only.
        exception["value"] = ""

    event.pop("breadcrumbs", None)
    event.pop("extra", None)
    event.pop("logentry", None)
    return event


def init_sentry(dsn: str, environment: str, traces_sample_rate: float = 0.0) -> bool:
    """Start error reporting. Does nothing, and returns False, when no DSN is configured."""
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=traces_sample_rate,
        before_send=scrub_event,  # type: ignore[arg-type]  # sentry types Event as a TypedDict
        before_breadcrumb=lambda breadcrumb, hint: None,
    )
    return True
