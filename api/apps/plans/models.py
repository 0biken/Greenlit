from django.db import models

from apps.core.choices import Origin, Priority, ReviewState
from apps.core.models import Project, TenantModel
from apps.requirements.models import Requirement

# Test cases are a stable identity (`test_case`) plus immutable content snapshots
# (`case_revision`). A plan version is a list of pointers to revisions (DATA §3, §6).
# The database refuses changes to published versions and to the revisions they use
# (migration 0002), so a past run always shows exactly what was tested.


class TestPlan(TenantModel):
    __test__ = False  # not a pytest test class

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    display_no = models.PositiveIntegerField()
    title = models.CharField(max_length=200)  # also the "area" a release report groups by
    scope = models.TextField(blank=True)
    current_version = models.ForeignKey(
        "plans.PlanVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # The newest AI case-drafting job for this plan, for showing progress (M3-08).
    draft_job_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "display_no"], name="test_plan_no_unique")
        ]


class VersionState(models.TextChoices):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class PlanVersion(TenantModel):
    plan = models.ForeignKey(TestPlan, on_delete=models.PROTECT, related_name="versions")
    number = models.CharField(max_length=12, blank=True)  # "1.4"; empty while a draft
    state = models.CharField(
        max_length=12, choices=VersionState.choices, default=VersionState.DRAFT
    )
    approved_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # A draft handed to a lead for approval (UX Flow 1 step 6). Cleared by any later edit.
    submitted_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan"],
                condition=models.Q(state="draft", deleted_at__isnull=True),
                name="one_draft_per_plan",
            ),
            models.UniqueConstraint(
                fields=["plan", "number"],
                condition=~models.Q(number=""),
                name="plan_version_number_unique",
            ),
        ]


class TestCase(TenantModel):
    """Identity only; content lives in revisions."""

    __test__ = False  # not a pytest test class

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    display_no = models.PositiveIntegerField()
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "display_no"], name="test_case_no_unique")
        ]


class CaseType(models.TextChoices):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    EDGE = "edge"
    ACCESSIBILITY = "accessibility"


class CaseRevision(TenantModel):
    test_case = models.ForeignKey(TestCase, on_delete=models.PROTECT, related_name="revisions")
    rev_no = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    preconditions = models.TextField(blank=True)
    steps = models.JSONField(default=list)  # ordered list of strings, one action each
    expected = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    review_state = models.CharField(
        max_length=10, choices=ReviewState.choices, default=ReviewState.DRAFT
    )
    origin = models.CharField(max_length=10, choices=Origin.choices, default=Origin.HUMAN)
    # What kind of check it is (AI §3 F2). Empty for cases nobody has classified.
    case_type = models.CharField(max_length=15, choices=CaseType.choices, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["test_case", "rev_no"], name="case_revision_unique")
        ]


class PlanVersionCase(TenantModel):
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT, related_name="cases")
    case_revision = models.ForeignKey(CaseRevision, on_delete=models.PROTECT, related_name="+")
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "case_revision"], name="plan_version_case_unique"
            )
        ]


class CaseRequirement(TenantModel):
    """Which requirements a case revision covers, and which requirement text it was written
    against. A requirement whose `revision` is above `req_revision_seen` makes the case Stale."""

    case_revision = models.ForeignKey(
        CaseRevision, on_delete=models.PROTECT, related_name="requirement_links"
    )
    requirement = models.ForeignKey(Requirement, on_delete=models.PROTECT, related_name="+")
    req_revision_seen = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case_revision", "requirement"], name="case_requirement_unique"
            )
        ]
