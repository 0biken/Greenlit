from django.db import models
from django.utils import timezone

from apps.core.models import Project, TenantModel
from apps.files.models import StoredFile
from apps.plans.models import CaseRevision, PlanVersion


class ReleaseState(models.TextChoices):
    OPEN = "open"
    SIGNED_OFF = "signed_off"
    CANCELLED = "cancelled"


class Release(TenantModel):
    """Groups runs, defects and the report (DATA §3). `name` is the version, e.g. 2.4.1."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=60)
    target_date = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=12, choices=ReleaseState.choices, default=ReleaseState.OPEN)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="release_name_unique")
        ]


class RunState(models.TextChoices):
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


class TestRun(TenantModel):
    """Fixed to one plan version for life (FR-RUN-01)."""

    __test__ = False  # not a pytest test class

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    display_no = models.PositiveIntegerField()
    release = models.ForeignKey(Release, on_delete=models.PROTECT, related_name="runs")
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT, related_name="+")
    build = models.CharField(max_length=100, blank=True)
    environment = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=12, choices=RunState.choices, default=RunState.IN_PROGRESS)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "display_no"], name="test_run_no_unique")
        ]


class Outcome(models.TextChoices):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"


class CaseResult(TenantModel):
    """One row per case per run, pointing at the exact revision tested. Latest write wins;
    the history of outcomes is in the audit log."""

    run = models.ForeignKey(TestRun, on_delete=models.PROTECT, related_name="results")
    case_revision = models.ForeignKey(CaseRevision, on_delete=models.PROTECT, related_name="+")
    outcome = models.CharField(max_length=10, choices=Outcome.choices, default=Outcome.NOT_RUN)
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    recorded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "case_revision"], name="one_result_per_case")
        ]


class Evidence(TenantModel):
    """File metadata for a piece of evidence (EV-nnnn); the bytes live in `apps.files`."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    display_no = models.PositiveIntegerField()
    file = models.ForeignKey(StoredFile, on_delete=models.PROTECT, related_name="+")
    mime = models.CharField(max_length=120)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64, blank=True)
    environment = models.CharField(max_length=100, blank=True)
    captured_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "display_no"], name="evidence_no_unique")
        ]


class EvidenceTarget(models.TextChoices):
    CASE_RESULT = "case_result"
    TEST_RUN = "test_run"
    DEFECT = "defect"
    RETEST = "retest"


class EvidenceLink(TenantModel):
    """One file can support several results, defects or retests."""

    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT, related_name="links")
    target_type = models.CharField(max_length=12, choices=EvidenceTarget.choices)
    target_id = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["evidence", "target_type", "target_id"], name="evidence_link_unique"
            )
        ]
        indexes = [models.Index(fields=["target_type", "target_id"])]
