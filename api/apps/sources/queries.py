"""Reading sources: the list, and one source with its text and the drafts made from it."""

from django.db.models import Count

from apps.ai import drafts, usage
from apps.ai.models import AiCall, AiDraft, AiDroppedItem
from apps.core.choices import ReviewState
from apps.core.models import CounterKind, Job, JobState, Membership, Project, display_name
from apps.core.numbering import format_display_id
from apps.core.policy import Action, can
from apps.files.models import FileState
from apps.inbox.services import LEADS
from apps.requirements.models import Requirement
from apps.sources.models import SourceDocument, SourceExtraction, SourceState

RUNNING = (JobState.QUEUED, JobState.RUNNING, JobState.FAILED)  # failed: waiting to be retried


def _job(document: SourceDocument, jobs: dict) -> dict | None:
    job = jobs.get(document.job_id)
    if job is None:
        return None
    return {
        "id": job.pk,
        "kind": job.kind,
        "state": job.state,
        "running": job.state in RUNNING,
        "progress": (job.progress or {}).get("label", ""),
        "done": (job.progress or {}).get("done", 0),
        "total": (job.progress or {}).get("total", 0),
        # Only a message written for people: a job that gave up, never a retried error's class.
        "error": job.error if job.state == JobState.DEAD else "",
    }


def _state(document: SourceDocument) -> tuple[str, str]:
    """The state to show, and why it failed. A file the scan refused fails its source."""
    file = document.file
    if (
        document.state == SourceState.WAITING
        and file
        and file.state
        in (
            FileState.REJECTED,
            FileState.INFECTED,
        )
    ):
        return SourceState.FAILED, file.rejection_reason or "This file was refused."
    return document.state, document.failure


def _row(document: SourceDocument, counts: dict, jobs: dict) -> dict:
    state, failure = _state(document)
    return {
        "id": document.pk,
        "title": document.title,
        "kind": document.kind,
        "state": state,
        "failure": failure,
        "pages": document.page_count,
        "pasted": document.file_id is None,
        "file_name": document.file.original_name if document.file else None,
        "added_by": display_name(document.created_by),
        "added_at": document.created_at,
        "drafts": counts.get((document.pk, ReviewState.DRAFT), 0),
        "accepted": counts.get((document.pk, ReviewState.ACCEPTED), 0),
        "rejected": counts.get((document.pk, ReviewState.REJECTED), 0),
        "job": _job(document, jobs),
    }


def _counts(documents: list[SourceDocument]) -> dict:
    rows = (
        Requirement.objects.filter(source_document__in=documents)
        .values_list("source_document_id", "review_state")
        .annotate(n=Count("id"))
    )
    return {(source, state): n for source, state, n in rows}


def _jobs(documents: list[SourceDocument]) -> dict:
    ids = [d.job_id for d in documents if d.job_id]
    return {job.pk: job for job in Job.objects.filter(pk__in=ids)}


def source_list(project: Project) -> list[dict]:
    documents = list(
        SourceDocument.objects.filter(project=project)
        .select_related("file", "created_by")
        .order_by("-created_at")[:200]
    )
    counts, jobs = _counts(documents), _jobs(documents)
    return [_row(d, counts, jobs) for d in documents]


def detail(document: SourceDocument, membership: Membership) -> dict:
    extraction = SourceExtraction.objects.filter(document=document).first()
    requirements = list(Requirement.objects.filter(source_document=document).order_by("display_no"))
    notes = drafts.drafts_for("requirement", [r.pk for r in requirements])
    calls = AiCall.objects.filter(source_id=document.pk)
    gaps: list[str] = []
    for found in calls.order_by("created_at").values_list("gaps", flat=True):
        gaps += [g for g in found if g not in gaps]
    try:
        usage.ensure_allowance(document.org_id)
        allowance_message = ""
    except usage.AllowanceUsedUp as error:
        allowance_message = error.message
    pages = (
        [
            {"page": p["page"], "start": p["start"], "text": extraction.text[p["start"] : p["end"]]}
            for p in extraction.pages
        ]
        if extraction
        else []
    )
    role = membership.role
    fast = AiDraft.objects.filter(
        target_type="requirement", target_id__in=[r.pk for r in requirements], fast_accept=True
    ).count()
    return {
        **_row(document, _counts([document]), _jobs([document])),
        "text_pages": pages,
        "items": [
            {
                "id": r.pk,
                "number": r.display_no,
                "display_id": format_display_id(CounterKind.REQUIREMENT, r.display_no),
                "title": r.title,
                "text": r.text,
                "priority": r.priority,
                "review_state": r.review_state,
                "origin": r.origin,
                "page": r.source_locator.get("page"),
                "start": r.source_locator.get("start"),
                "end": r.source_locator.get("end"),
                "vague": bool(notes[r.pk].flags.get("vague")) if r.pk in notes else False,
                "possible_duplicate_of": (
                    notes[r.pk].flags.get("possible_duplicate_of") if r.pk in notes else None
                ),
                "assumptions": notes[r.pk].flags.get("assumptions", []) if r.pk in notes else [],
            }
            for r in requirements
        ],
        "gaps": gaps,
        "left_out": AiDroppedItem.objects.filter(call__in=calls).count(),
        "allowance_message": allowance_message,
        # Accepts made in under two seconds each, for whoever answers for the plan (AI §6).
        "fast_accepts": fast if role in LEADS else None,
        "actions": {"review": can(role, Action.WRITE_TESTING)},
    }
