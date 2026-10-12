from django.db import models

from apps.core.models import Project, TenantModel
from apps.files.models import StoredFile


class SourceKind(models.TextChoices):
    PRD = "prd"
    SCREENSHOT_SET = "screenshot_set"
    QA_REPORT = "qa_report"


class SourceState(models.TextChoices):
    WAITING = "waiting"  # the uploaded file is still being checked
    PARSING = "parsing"
    READY = "ready"
    FAILED = "failed"


class SourceDocument(TenantModel):
    """Something requirements or drafts are made from (DATA §3 `source_document`, M2-01): an
    uploaded PRD, or text pasted in. `file` is empty for pasted text."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20, choices=SourceKind.choices, default=SourceKind.PRD)
    title = models.CharField(max_length=200)
    file = models.ForeignKey(
        StoredFile, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    page_count = models.PositiveIntegerField(default=0)
    state = models.CharField(
        max_length=10, choices=SourceState.choices, default=SourceState.WAITING
    )
    failure = models.CharField(max_length=300, blank=True)  # written for people
    text_sha256 = models.CharField(max_length=64, blank=True)
    # The newest parsing or drafting job, for showing progress.
    job_id = models.UUIDField(null=True, blank=True)


class SourceExtraction(TenantModel):
    """The text read out of a source, with where each page and section sits in it (M2-02).
    A draft's quote is looked up in `text`, and the position found is its provenance (AI §5)."""

    document = models.OneToOneField(
        SourceDocument, on_delete=models.PROTECT, related_name="extraction"
    )
    text = models.TextField()
    pages = models.JSONField(default=list)  # [{"page": 1, "start": 0, "end": 1840}]
    sections = models.JSONField(default=list)  # [{"heading": "...", "page": 1, "start", "end"}]
