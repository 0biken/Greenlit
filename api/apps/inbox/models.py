from django.db import models

from apps.core.models import TenantModel


class Snooze(TenantModel):
    """Hides one Inbox item from one person until a date (FR-INB-04). Snoozed items still
    count towards readiness. Unsnoozing soft-deletes the row, so the history stays."""

    user = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    target_type = models.CharField(max_length=20)  # defect, case_result, test_case, requirement
    target_id = models.UUIDField()
    until = models.DateTimeField()
    reason = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "target_type", "target_id"],
                condition=models.Q(deleted_at__isnull=True),
                name="one_snooze_per_item",
            )
        ]


class NotificationLevel(models.TextChoices):
    FIRST = "48h"  # the first escalation time: the owner is reminded
    SECOND = "96h"  # the second: the project's leads are told as well
    CRITICAL = "critical"  # closed with a failed retest: told at once
    DIGEST = "digest"  # the daily email


class Notification(TenantModel):
    """One thing one person was told, once (spec gap G-01, FR-INB-02, FR-INB-03).

    The unique rule is what makes "each level notified once" true even when the reminders job
    runs twice or two workers overlap. `cycle` separates one wait from the next: for a defect
    it is when the current wait began, so a defect that is fixed again later is reminded again;
    for a digest it is the person's local date."""

    user = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    level = models.CharField(max_length=10, choices=NotificationLevel.choices)
    target_type = models.CharField(max_length=20)
    target_id = models.UUIDField()
    cycle = models.CharField(max_length=40)
    sent_at = models.DateTimeField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "level", "target_type", "target_id", "cycle"],
                name="notified_once",
            )
        ]
