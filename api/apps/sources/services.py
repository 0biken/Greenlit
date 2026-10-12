"""Source documents: adding one, and deciding on the drafts made from it (M2-01, M2-07).

Reading is in `queries.py`; the slow work (parsing, drafting) is in `jobs.py`.
"""

import hashlib

from django.db import transaction

from apps.ai import drafts, usage
from apps.core import audit
from apps.core.choices import ReviewState
from apps.core.jobs import enqueue
from apps.core.models import Project
from apps.core.services import ServiceError
from apps.files.models import FileState, StoredFile
from apps.requirements import services as requirements
from apps.requirements.models import Requirement
from apps.sources import parsing
from apps.sources.models import SourceDocument, SourceExtraction, SourceKind, SourceState

MAX_PASTED_CHARS = parsing.MAX_PAGES * parsing.PASTED_PAGE_CHARS
USABLE_FILE_STATES = (FileState.PENDING, FileState.SCANNING, FileState.AVAILABLE)


def store_extraction(document: SourceDocument, parsed: parsing.Parsed) -> SourceExtraction:
    extraction, _ = SourceExtraction.objects.update_or_create(
        document=document,
        defaults={
            "org_id": document.org_id,
            "text": parsed.text,
            "pages": parsed.pages,
            "sections": parsed.sections,
        },
    )
    document.page_count = len(parsed.pages)
    document.text_sha256 = hashlib.sha256(parsed.text.encode()).hexdigest()
    document.state, document.failure = SourceState.READY, ""
    document.save(update_fields=["page_count", "text_sha256", "state", "failure", "updated_at"])
    return extraction


def _queue(document: SourceDocument, kind: str, actor) -> None:
    job = enqueue(kind, org_id=document.org_id, user=actor, source_id=str(document.pk))
    document.job_id = job.pk
    document.save(update_fields=["job_id", "updated_at"])


def queue_drafting(document: SourceDocument, actor) -> None:
    """Start requirement drafting, unless the organisation's AI allowance is used up. A source
    is still usable without drafts: requirements can be added by hand."""
    if document.state != SourceState.READY:
        raise ServiceError("This document is not ready to draft from yet.", code="conflict")
    usage.ensure_allowance(document.org_id)
    _queue(document, "draft_requirements", actor)


def create_from_text(project: Project, actor, *, title: str, text: str) -> SourceDocument:
    """A PRD pasted as text (FR-PLAN-01). It is read at once; drafting follows as a job."""
    title = title.strip()
    if not title:
        raise ServiceError("Give the document a title.")
    if len(text) > MAX_PASTED_CHARS:
        raise ServiceError(
            f"That is more than about {parsing.MAX_PAGES} pages. Paste it in parts, by area."
        )
    try:
        parsed = parsing.parse_text(text)
    except parsing.Unreadable as error:
        raise ServiceError(error.message) from error
    with transaction.atomic():
        document = SourceDocument.objects.create(
            org_id=project.org_id,
            project=project,
            kind=SourceKind.PRD,
            title=title[:200],
            state=SourceState.PARSING,
            created_by=actor,
        )
        store_extraction(document, parsed)
        audit.record(
            "source.added", "source_document", document.pk, actor=actor, after={"pages": 1}
        )
        _draft_if_allowed(document, actor)
    return document


def create_from_file(project: Project, actor, *, file_id, title: str = "") -> SourceDocument:
    """A PRD uploaded through the file service. It is parsed once the file has passed its
    checks: now if it already has, otherwise when the scan finishes."""
    stored = StoredFile.objects.filter(pk=file_id, project=project, kind="prd").first()
    if stored is None or stored.state not in USABLE_FILE_STATES:
        raise ServiceError("Upload the document again: that file cannot be used.")
    if SourceDocument.objects.filter(file=stored).exists():
        raise ServiceError("That file is already one of this project's sources.", code="conflict")
    with transaction.atomic():
        document = SourceDocument.objects.create(
            org_id=project.org_id,
            project=project,
            kind=SourceKind.PRD,
            title=(title.strip() or stored.original_name)[:200],
            file=stored,
            created_by=actor,
        )
        audit.record("source.added", "source_document", document.pk, actor=actor)
        if stored.state == FileState.AVAILABLE:
            start_parsing(document, actor)
    return document


def start_parsing(document: SourceDocument, actor=None) -> None:
    document.state = SourceState.PARSING
    document.save(update_fields=["state", "updated_at"])
    _queue(document, "parse_source", actor)


def _draft_if_allowed(document: SourceDocument, actor) -> None:
    try:
        queue_drafting(document, actor)
    except usage.AllowanceUsedUp:
        pass  # the source page shows the allowance message; the document itself is fine


def decide(
    project: Project,
    requirement: Requirement,
    actor,
    decision: str,
    *,
    reason: str = "",
    viewed_ms: int | None = None,
) -> Requirement:
    """Accept or reject one drafted requirement (FR-PLAN-04, AI-01, AI-02)."""
    with transaction.atomic():
        draft = drafts.record_decision(
            "requirement", requirement.pk, actor, decision, reason=reason, viewed_ms=viewed_ms
        )
        model = draft.call.model if draft and draft.call else ""
        return requirements.review(requirement, actor, decision, model=model)


def accept_many(document: SourceDocument, actor, numbers: list[int], viewed_ms: int | None) -> int:
    """Accept several drafts of this source at once: never more than 20 (AI §6 "Over-trust")."""
    if len(numbers) > drafts.ACCEPT_ALL_MAX:
        raise ServiceError(f"Accept at most {drafts.ACCEPT_ALL_MAX} drafts at a time.")
    rows = list(
        Requirement.objects.filter(
            source_document=document,
            display_no__in=numbers,
            review_state=ReviewState.DRAFT,
        )
    )
    if len(rows) != len(set(numbers)):
        raise ServiceError("One of those drafts is not waiting for review on this document.")
    each = None if viewed_ms is None else viewed_ms // max(len(rows), 1)
    with transaction.atomic():
        for requirement in rows:
            decide(document.project, requirement, actor, ReviewState.ACCEPTED, viewed_ms=each)
    return len(rows)
