"""Uploads and downloads (M1-14, ARCH §5 steps 1 to 4, SEC §8).

1. `request_upload` checks the kind, the name, the size and the organisation's quota, records a
   pending file, and returns a short-lived upload link scoped to `{org_id}/{project_id}/`.
2. The browser sends the bytes straight to storage.
3. `complete_upload` queues the `scan_file` job.
4. The job identifies the content, hashes it and scans it; only then is the file available.
"""

import hashlib
import uuid

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.core.jobs import JobFailure, enqueue, job_handler
from apps.core.models import Membership, Project
from apps.core.services import ServiceError
from apps.files import scanner
from apps.files.models import FileState, StoredFile
from apps.files.storage import UploadTarget, get_storage
from apps.files.types import KINDS, TYPES, identify, type_for_name, unsupported_message

COUNTED_STATES = (FileState.PENDING, FileState.SCANNING, FileState.AVAILABLE)


def request_upload(
    membership: Membership, project: Project, kind: str, name: str, size: int
) -> tuple[StoredFile, UploadTarget]:
    """Validate and record an upload, and return where to send the bytes."""
    if kind not in KINDS:
        raise ServiceError("Choose what kind of file this is.", code="invalid_kind")
    name = name.strip()[:255]
    claimed = type_for_name(kind, name)
    if not name or claimed is None:
        raise ServiceError(unsupported_message(kind), code="unsupported_type")
    limit = KINDS[kind].max_bytes
    if size <= 0:
        raise ServiceError("The file is empty.", code="empty")
    if size > limit:
        raise ServiceError(
            f"The file is too large. The limit is {limit // (1024 * 1024)} MB.", code="too_large"
        )
    used = (
        StoredFile.objects.filter(state__in=COUNTED_STATES).aggregate(total=Sum("size_bytes"))[
            "total"
        ]
        or 0
    )
    if used + size > settings.ORG_STORAGE_QUOTA_BYTES:
        raise ServiceError(
            "Your organisation's file storage is full. Delete files or ask an owner to upgrade.",
            code="quota",
        )

    file_id = uuid.uuid4()
    key = f"{membership.org_id}/{project.pk}/{file_id}"
    stored = StoredFile.objects.create(
        id=file_id,
        org_id=membership.org_id,
        project=project,
        kind=kind,
        original_name=name,
        storage_key=key,
        declared_mime=TYPES[claimed].mime,
        size_bytes=size,
        created_by=membership.user,
    )
    return stored, get_storage().upload_target(key, TYPES[claimed].mime, limit)


def complete_upload(stored: StoredFile, user) -> StoredFile:
    """The browser says the bytes are sent. Safe to call again."""
    if stored.state != FileState.PENDING:
        return stored
    if not get_storage().exists(stored.storage_key):
        raise ServiceError("The upload has not arrived yet. Try again.", code="not_uploaded")
    stored.state = FileState.SCANNING
    stored.save(update_fields=["state", "updated_at"])
    enqueue("scan_file", org_id=stored.org_id, user=user, file_id=str(stored.pk))
    return stored


def _refuse(stored: StoredFile, state: str, reason: str) -> None:
    get_storage().delete(stored.storage_key)
    StoredFile.objects.filter(pk=stored.pk).update(
        state=state, rejection_reason=reason, updated_at=timezone.now()
    )


@job_handler("scan_file", max_retries=5)
def scan_file(job, file_id: str) -> None:
    stored = StoredFile.objects.filter(pk=file_id).first()
    if stored is None or stored.state != FileState.SCANNING:
        return
    storage = get_storage()
    if not storage.exists(stored.storage_key):
        raise JobFailure("The uploaded file could not be found.")

    job.set_progress(1, 3, "Checking the file")
    limit = KINDS[stored.kind].max_bytes
    # Decide while the file is open; act after closing it (an open file cannot be deleted on
    # every platform).
    refusal: tuple[str, str] | None = None
    with storage.open(stored.storage_key) as handle:
        digest, size = hashlib.sha256(), 0
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        detected = identify(handle, stored.original_name) if 0 < size <= limit else None
        if size == 0 or size > limit:
            refusal = (FileState.REJECTED, "The file is empty or larger than allowed.")
        elif detected not in KINDS[stored.kind].types:
            refusal = (FileState.REJECTED, unsupported_message(stored.kind))
        else:
            job.set_progress(2, 3, "Scanning for malware")
            if scanner.is_infected(handle):  # ScannerUnavailable makes the job retry
                refusal = (FileState.INFECTED, "This file failed the malware scan.")

    if refusal is not None:
        _refuse(stored, *refusal)
        return
    StoredFile.objects.filter(pk=stored.pk).update(
        state=FileState.AVAILABLE,
        detected_type=detected,
        size_bytes=size,
        sha256=digest.hexdigest(),
        available_at=timezone.now(),
        updated_at=timezone.now(),
    )
    job.set_progress(3, 3, "Ready")


def download_url(stored: StoredFile) -> str:
    if stored.state != FileState.AVAILABLE:
        raise ServiceError("This file is not available.", code="not_available")
    file_type = TYPES.get(stored.detected_type)
    content_type = file_type.mime if file_type else "application/octet-stream"
    return get_storage().download_url(stored.storage_key, stored.original_name, content_type)
