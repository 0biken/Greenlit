from django.db import models

from apps.core.models import Project, TenantModel
from apps.runs.models import Release


class ReportState(models.TextChoices):
    DRAFT = "draft"
    SIGNED = "signed"


class Report(TenantModel):
    """A release report (DATA §3). A signed report is a frozen copy: the database refuses
    any change to it (migration 0002), so it is never recomputed."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    release = models.ForeignKey(Release, on_delete=models.PROTECT, related_name="reports")
    display_no = models.PositiveIntegerField()
    body = models.JSONField(default=dict)
    state = models.CharField(max_length=8, choices=ReportState.choices, default=ReportState.DRAFT)
    snapshot_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "display_no"], name="report_no_unique")
        ]


class Readiness(models.TextChoices):
    READY = "ready"
    NOT_READY = "not_ready"


class SignOff(TenantModel):
    """A named person's approval of a release, with readiness at that moment (append-only).
    Signing off while not ready needs a written reason."""

    release = models.ForeignKey(Release, on_delete=models.PROTECT, related_name="sign_offs")
    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="+")
    signed_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    signed_at = models.DateTimeField()
    readiness_at_signing = models.CharField(max_length=10, choices=Readiness.choices)
    override_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(readiness_at_signing="ready") | ~models.Q(override_reason=""),
                name="sign_off_reason_when_not_ready",
            )
        ]
