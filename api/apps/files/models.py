from django.db import models

from apps.core.models import Project, TenantModel


class FileState(models.TextChoices):
    PENDING = "pending"  # upload link issued, bytes not confirmed yet
    SCANNING = "scanning"  # bytes received; identifying and scanning
    AVAILABLE = "available"
    REJECTED = "rejected"  # content is not a type this upload accepts
    INFECTED = "infected"


class StoredFile(TenantModel):
    """One uploaded file (DATA §3 `stored_file`). Never served until `available`."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20)  # apps.files.types.KINDS
    original_name = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=200, unique=True)
    declared_mime = models.CharField(max_length=120)
    detected_type = models.CharField(max_length=20, blank=True)  # apps.files.types.TYPES
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=20, choices=FileState.choices, default=FileState.PENDING)
    rejection_reason = models.CharField(max_length=200, blank=True)
    available_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["org_id", "state"])]
