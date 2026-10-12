from django.db import models

from apps.core.choices import Origin, Priority, ReviewState
from apps.core.models import Project, TenantModel


class Requirement(TenantModel):
    """One requirement (DATA §3). `revision` goes up when `text` changes, which makes the
    cases written against the old text Stale (`case_requirement.req_revision_seen`).

    `source_locator` says where in `source_document` it is stated: page and character
    positions for a passage (AI §5).
    """

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    display_no = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    text = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    revision = models.PositiveIntegerField(default=1)
    source_document = models.ForeignKey(
        "sources.SourceDocument",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="requirements",
    )
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
    """The text a requirement had at one `revision` (spec gap G-07). A row is written when a
    revision becomes current and never changed afterwards, so the passage a case was written
    against can still be read after the requirement moves on (AI §5)."""

    requirement = models.ForeignKey(Requirement, on_delete=models.PROTECT, related_name="revisions")
    revision = models.PositiveIntegerField()
    text = models.TextField()
    source_locator = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["requirement", "revision"], name="requirement_revision_unique"
            )
        ]
