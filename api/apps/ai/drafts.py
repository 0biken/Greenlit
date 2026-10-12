"""What the AI said about each drafted record, and what a person decided (G-06; AI §6, §9)."""

from django.utils import timezone

from apps.ai.models import AiCall, AiDraft, Decision, RejectReason
from apps.core.services import ServiceError

FAST_ACCEPT_MS = 2000  # an accept quicker than this was probably not read (AI §6 "Over-trust")
ACCEPT_ALL_MAX = 20


def note_draft(call: AiCall, target_type: str, target_id, flags: dict) -> AiDraft:
    return AiDraft.objects.create(
        org_id=call.org_id, target_type=target_type, target_id=target_id, call=call, flags=flags
    )


def drafts_for(target_type: str, target_ids: list) -> dict:
    rows = AiDraft.objects.filter(target_type=target_type, target_id__in=target_ids).select_related(
        "call"
    )
    return {row.target_id: row for row in rows}


def record_decision(
    target_type: str,
    target_id,
    actor,
    decision: str,
    *,
    reason: str = "",
    viewed_ms: int | None = None,
) -> AiDraft | None:
    """Note the decision on the AI's draft. Returns None for a record no AI drafted."""
    if decision not in Decision.values:
        raise ServiceError("Choose accept or reject.")
    if reason and reason not in RejectReason.values:
        raise ServiceError("Choose a reason: wrong, duplicate, too vague or not testable.")
    draft = AiDraft.objects.filter(target_type=target_type, target_id=target_id).first()
    if draft is None:
        return None
    draft.decision = decision
    draft.reject_reason = reason if decision == Decision.REJECTED else ""
    draft.decided_by, draft.decided_at = actor, timezone.now()
    draft.fast_accept = (
        decision == Decision.ACCEPTED and viewed_ms is not None and viewed_ms < FAST_ACCEPT_MS
    )
    draft.save()
    return draft
