"""Background jobs for sources (ARCH §5, §6; docs/jobs.md). Arguments are IDs only, and every
message a person may see comes from `JobFailure`.

    scan_file (apps.files) -> parse_source -> draft_requirements
"""

from apps.ai import checks, client, drafts, usage
from apps.ai.features import DRAFT_REQUIREMENTS
from apps.core.choices import Origin, ReviewState
from apps.core.jobs import JobFailure, job_handler
from apps.core.models import CounterKind
from apps.core.numbering import format_display_id
from apps.files.models import StoredFile
from apps.files.storage import get_storage
from apps.requirements.models import Requirement
from apps.requirements.services import create_requirement
from apps.sources import parsing, services
from apps.sources.models import SourceDocument, SourceExtraction, SourceState


def file_became_available(stored: StoredFile) -> None:
    """Called by the file service when a scan passes: parse any source waiting on that file."""
    for document in SourceDocument.objects.filter(file=stored, state=SourceState.WAITING):
        services.start_parsing(document, stored.created_by)


def _fail(document: SourceDocument, message: str) -> None:
    document.state, document.failure = SourceState.FAILED, message[:300]
    document.save(update_fields=["state", "failure", "updated_at"])


@job_handler("parse_source", max_retries=3)
def parse_source(job, source_id: str) -> None:
    """Read the text out of an uploaded document, then queue requirement drafting."""
    document = SourceDocument.objects.select_related("file", "project").filter(pk=source_id).first()
    if document is None or document.state != SourceState.PARSING or document.file is None:
        return
    job.set_progress(1, 2, "Reading the document")
    try:
        with get_storage().open(document.file.storage_key) as handle:
            parsed = parsing.parse_file(handle, document.file.detected_type)
    except parsing.Unreadable as error:
        _fail(document, error.message)
        raise JobFailure(error.message) from error
    services.store_extraction(document, parsed)
    job.set_progress(
        2, 2, f"Read {len(parsed.pages)} {'page' if len(parsed.pages) == 1 else 'pages'}"
    )
    services._draft_if_allowed(document, document.created_by)


def _pages_label(pages: list[dict], start: int, end: int) -> str:
    first, last = parsing.page_of(pages, start), parsing.page_of(pages, max(end - 1, start))
    return f"Reading page {first}" if first == last else f"Reading pages {first} to {last}"


def _existing(document: SourceDocument) -> list[dict]:
    """This project's own requirements, so the model does not repeat them. Nothing else.
    Those drafted from this same document are left out: they are what is being drafted, and
    leaving them out keeps the request the same when the job runs again (so it is reused)."""
    rows = (
        Requirement.objects.filter(project=document.project)
        .exclude(review_state=ReviewState.REJECTED)
        .exclude(source_document=document)
    )
    return [
        {
            "display_id": format_display_id(CounterKind.REQUIREMENT, r.display_no),
            "title": r.title,
            "text": r.text,
        }
        for r in rows.order_by("display_no")
    ]


@job_handler("draft_requirements", max_retries=1)
def draft_requirements(job, source_id: str) -> None:
    """F1 (AI §3): draft requirements from a source, one section at a time, so drafts appear as
    each section finishes. Safe to run twice: a passage that already has a draft is skipped."""
    document = SourceDocument.objects.select_related("project").filter(pk=source_id).first()
    extraction = SourceExtraction.objects.filter(document_id=source_id).first()
    if document is None or extraction is None:
        return
    text = checks.Document(extraction.text)
    sections = extraction.sections or [
        {"heading": "", "page": 1, "start": 0, "end": len(extraction.text)}
    ]
    created = dropped = 0
    for index, section in enumerate(sections, start=1):
        start, end = section["start"], section["end"]
        job.set_progress(index - 1, len(sections), _pages_label(extraction.pages, start, end))
        existing = _existing(document)
        try:
            result = client.run(
                DRAFT_REQUIREMENTS,
                org_id=document.org_id,
                document=extraction.text[start:end],
                existing=existing,
                source_id=document.pk,
                job_id=job.pk,
            )
        except (usage.AllowanceUsedUp, client.AiUnavailable) as error:
            raise JobFailure(error.message) from error
        checked = checks.check_requirements(
            result.reply["requirements"], text, section=(start, end), existing=existing
        )
        client.record_drops(result.call, checked.dropped)
        dropped += len(checked.dropped)
        taken = {
            (r.source_locator.get("start"), r.source_locator.get("end"))
            for r in Requirement.objects.filter(source_document=document)
        }
        for item in checked.kept:
            if (item["start"], item["end"]) in taken:
                continue  # drafted on an earlier run of this job
            taken.add((item["start"], item["end"]))
            requirement = create_requirement(
                document.project,
                None,
                title=item["title"],
                text=item["text"],
                priority=item["priority"],
                review_state=ReviewState.DRAFT,
                origin=Origin.AI,
                source_document=document,
                source_locator={
                    "document": str(document.pk),
                    "page": parsing.page_of(extraction.pages, item["start"]),
                    "start": item["start"],
                    "end": item["end"],
                },
            )
            drafts.note_draft(
                result.call,
                "requirement",
                requirement.pk,
                {
                    "vague": bool(item.get("vague")),
                    "possible_duplicate_of": item.get("possible_duplicate_of"),
                    "assumptions": item.get("assumptions", []),
                },
            )
            created += 1
    summary = f"{created} {'draft' if created == 1 else 'drafts'} created."
    if dropped:
        was = "was" if dropped == 1 else "were"
        summary += f" {dropped} {was} left out because their source could not be confirmed."
    job.set_progress(len(sections), len(sections), summary)
