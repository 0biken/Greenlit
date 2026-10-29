from django.db import models

from apps.core.choices import Origin, Priority, ReviewState
from apps.core.models import Project, TenantModel


class Requirement(TenantModel):
    """One requirement, optionally traced to the exact source passage (DATA §3)."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    source_document = models.ForeignKey(
        "requirements.SourceDocument",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="requirements",
    )
    display_no = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    text = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    revision = models.PositiveIntegerField(default=1)
    source_locator = models.JSONField(default=dict, blank=True)
    review_state = models.CharField(
        max_length=10, choices=ReviewState.choices, default=ReviewState.DRAFT
    )
    origin = models.CharField(max_length=10, choices=Origin.choices, default=Origin.HUMAN)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "display_no"], name="requirement_no_unique")
        ]


class RequirementRevision(TenantModel):
    """Append-only snapshot of a requirement's authored content and source provenance."""

    requirement = models.ForeignKey(Requirement, on_delete=models.PROTECT, related_name="revisions")
    revision = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    text = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices)
    source_document = models.ForeignKey(
        "requirements.SourceDocument",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="requirement_revisions",
    )
    source_locator = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["requirement", "revision"], name="requirement_revision_unique"
            )
        ]
        ordering = ["requirement_id", "revision"]


class SourceDocument(TenantModel):
    """Pasted PRD or Markdown source. File uploads and extraction are a later M2 slice."""

    class Kind(models.TextChoices):
        PRD = "prd", "PRD"
        SCREENSHOT_SET = "screenshot_set", "Screenshot set"
        QA_REPORT = "qa_report", "QA report"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="sources")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PRD)
    title = models.CharField(max_length=200)
    content_text = models.TextField()
    page_count = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["org_id", "project"])]
