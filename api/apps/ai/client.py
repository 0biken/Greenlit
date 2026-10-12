"""The only code that calls the model provider (M2-04; ARCH §4, AI §2, §6, §8).

    result = client.run(DRAFT_REQUIREMENTS, org_id=..., document=section_text, existing=[...])

A feature module asks for a draft and gets back a reply that already matches the feature's
schema, with the call metered. What the reply's items point at is checked by the caller with
`apps.ai.checks`, because only the caller knows its own records.

Logs and error reports from here carry IDs, hashes and counts. Document text and model output
are stored in tenant tables and never logged.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass

from django.conf import settings

from apps.ai import usage
from apps.ai.checks import matches_schema
from apps.ai.features import GROUND_RULES, Feature
from apps.ai.models import AiCall, AiDroppedItem, CallOutcome
from apps.ai.providers import ProviderUnavailable, Reply, Request, get_provider
from apps.core.services import ServiceError

log = logging.getLogger("greenlit.ai")

UNAVAILABLE = "AI drafting is unavailable right now. You can add items by hand."


class AiUnavailable(ServiceError):
    def __init__(self):
        super().__init__(UNAVAILABLE, code="ai_unavailable")


@dataclass
class Result:
    call: AiCall
    reply: dict


def _existing_text(existing: list[dict]) -> str:
    return "\n".join(f"{r['display_id']}: {r['title']}" for r in existing)


def _hash(feature: Feature, document: str, existing: str) -> str:
    payload = json.dumps([feature.key, feature.prompt_version, document, existing])
    return hashlib.sha256(payload.encode()).hexdigest()


def _ask(request: Request) -> Reply:
    """Call the provider, trying again three times with growing waits if it cannot be reached."""
    waits = settings.AI_RETRY_WAITS
    for attempt in range(len(waits) + 1):
        try:
            return get_provider().complete(request)
        except ProviderUnavailable:
            if attempt == len(waits):
                raise
            time.sleep(waits[attempt])
    raise ProviderUnavailable  # unreachable; keeps the type checker honest


def run(
    feature: Feature,
    *,
    org_id,
    document: str,
    existing: list[dict],
    source_id=None,
    job_id=None,
) -> Result:
    """One call for one organisation. `existing` are that organisation's own records the model
    should know about (`[{display_id, title, ...}]`); nothing else of anyone's is sent.

    Raises `usage.AllowanceUsedUp`, or `AiUnavailable` when the provider cannot be reached or
    answers outside the schema twice."""
    existing_text = _existing_text(existing)
    input_hash = _hash(feature, document, existing_text)
    common = {
        "org_id": org_id,
        "feature": feature.key,
        "prompt_version": feature.prompt_version,
        "input_hash": input_hash,
        "source_id": source_id,
        "job_id": job_id,
    }

    # Unchanged input: hand back what was stored, and spend nothing (AI §8 "Reuse").
    earlier = (
        AiCall.objects.filter(
            feature=feature.key,
            prompt_version=feature.prompt_version,
            input_hash=input_hash,
            outcome=CallOutcome.OK,
        )
        .order_by("-created_at")
        .first()
    )
    if earlier is not None:
        call = AiCall.objects.create(
            **common,
            model=earlier.model,
            outcome=CallOutcome.REUSED,
            reply=earlier.reply,
            gaps=earlier.gaps,
        )
        return Result(call, earlier.reply)

    usage.ensure_allowance(org_id)
    request = Request(
        feature=feature.key,
        instructions=f"{GROUND_RULES}\n\n{feature.instructions}",
        document=document,
        existing=existing_text,
        schema=feature.schema,
    )
    started = time.monotonic()
    tokens_in = tokens_out = 0
    cost, model = 0.0, ""
    parsed: dict | None = None
    outcome = CallOutcome.BAD_OUTPUT
    try:
        for _ in range(2):  # a reply outside the schema is asked for once more, never patched
            reply = _ask(request)
            tokens_in, tokens_out = tokens_in + reply.tokens_in, tokens_out + reply.tokens_out
            cost, model = cost + reply.cost_usd, reply.model
            try:
                candidate = json.loads(reply.text)
            except ValueError:
                continue
            if matches_schema(candidate, feature.schema):
                parsed, outcome = candidate, CallOutcome.OK
                break
    except ProviderUnavailable:
        outcome = CallOutcome.UNAVAILABLE

    call = AiCall.objects.create(
        **common,
        model=model,
        outcome=outcome,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        duration_ms=int((time.monotonic() - started) * 1000),
        reply=parsed,
        gaps=(parsed or {}).get("gaps", []),
    )
    log.info(
        "ai call",
        extra={
            "call_id": str(call.pk),
            "feature": feature.key,
            "outcome": outcome,
            "org_id": str(org_id),
        },
    )
    usage.warn_if_nearly_used(org_id)
    if parsed is None:
        raise AiUnavailable()
    return Result(call, parsed)


def record_drops(call: AiCall, dropped: list[tuple[str, dict]]) -> None:
    """Keep what the checks refused, for quality review (AI §2). Logged by ID and reason only."""
    for reason, item in dropped:
        row = AiDroppedItem.objects.create(org_id=call.org_id, call=call, reason=reason, item=item)
        log.info(
            "ai item dropped",
            extra={"call_id": str(call.pk), "drop_id": str(row.pk), "reason": reason},
        )
