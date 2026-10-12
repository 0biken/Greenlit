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
