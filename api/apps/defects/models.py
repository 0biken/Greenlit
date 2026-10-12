from django.db import models
from django.utils import timezone

from apps.core.choices import Origin, Priority, ReviewState
from apps.core.models import Project, TenantModel
from apps.runs.models import CaseResult, Release

# The two statuses are kept apart (DATA §7): `tracker_status` is the issue tracker's view,
# `qa_status` is Greenlit's. Only `apps.defects.status` may change either of them.


class TrackerStatus(models.TextChoices):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    CLOSED = "closed"


class QaStatus(models.TextChoices):
    NOT_RETESTED = "not_retested"
    VERIFIED = "verified"
    RETEST_FAILED = "retest_failed"
    WONT_FIX = "wont_fix"
    DEFERRED = "deferred"


class Defect(TenantModel):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    release = models.ForeignKey(
        Release, null=True, blank=True, on_delete=models.PROTECT, related_name="defects"
    )
    display_no = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    steps = models.TextField(blank=True)
    expected = models.TextField(blank=True)
    actual = models.TextField(blank=True)
    severity = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    tracker_status = models.CharField(
        max_length=12, choices=TrackerStatus.choices, default=TrackerStatus.OPEN
    )
    qa_status = models.CharField(
        max_length=14, choices=QaStatus.choices, default=QaStatus.NOT_RETESTED
    )
    owner = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    fixed_at = models.DateTimeField(null=True, blank=True)
    fixed_by = models.ForeignKey(  # for the fixer-cannot-verify rule (M5-08)
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    # When `qa_status` last changed; ages in the Inbox count from here.
    qa_status_at = models.DateTimeField(default=timezone.now)
    # Won't fix and Deferred need a reason and an approver (DATA §7 rule 4).
    decision_reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    found_in_result = models.ForeignKey(
        CaseResult, null=True, blank=True, on_delete=models.PROTECT, related_name="defects"
    )
    review_state = models.CharField(
        max_length=10, choices=ReviewState.choices, default=ReviewState.ACCEPTED
    )
    origin = models.CharField(max_length=10, choices=Origin.choices, default=Origin.HUMAN)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "display_no"], name="defect_no_unique")
        ]


class RetestOutcome(models.TextChoices):
    PASSED = "passed"
    FAILED = "failed"


class Retest(TenantModel):
    """One row per retest, never overwritten (the table is append-only). Evidence is linked
    through `runs.EvidenceLink` and is required for both outcomes."""

    defect = models.ForeignKey(Defect, on_delete=models.PROTECT, related_name="retests")
    outcome = models.CharField(max_length=8, choices=RetestOutcome.choices)
    tested_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    tested_at = models.DateTimeField(default=timezone.now)
    build = models.CharField(max_length=100, blank=True)
    environment = models.CharField(max_length=100, blank=True)
