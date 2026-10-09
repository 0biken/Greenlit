"""Where file bytes live. Only `apps.files` touches storage; everything else holds file IDs.

Two backends behind one interface:
- `S3Storage` for staging and production: private bucket, presigned POST for uploads (with a
  size limit the bucket enforces) and presigned GET for downloads, both valid 15 minutes.
- `LocalStorage` for development: files in a folder, uploads and downloads through two small
  Django views (`views.local_upload`, `views.local_download`) that accept the same kind of
  short-lived signed token.

Downloads are always served as attachments with `nosniff`, never rendered in the app (SEC §8).
"""

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import IO

from django.conf import settings
from django.core import signing
from django.utils import timezone

LINK_SALT = "greenlit.files.link"


@dataclass
class UploadTarget:
    method: str  # "PUT": send the raw bytes; "POST": multipart form with `fields`, file last
    url: str
    fields: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    expires_at: datetime | None = None


class Storage:
    def upload_target(self, key: str, content_type: str, max_bytes: int) -> UploadTarget:
        raise NotImplementedError

    def download_url(self, key: str, filename: str, content_type: str) -> str:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def open(self, key: str) -> IO[bytes]:
        raise NotImplementedError

    def put_bytes(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


def link_ttl() -> timedelta:
    return timedelta(seconds=settings.FILE_LINK_TTL_SECONDS)


def safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip(" .")
    return cleaned[:150] or "file"


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("storage key escapes the storage folder")
        return path

    def _token(self, payload: dict) -> str:
        return signing.dumps(payload, salt=LINK_SALT)

    def upload_target(self, key, content_type, max_bytes):
        token = self._token({"op": "put", "key": key, "max": max_bytes, "type": content_type})
        return UploadTarget(
            method="PUT",
            url=f"/files/local/upload/{token}/",
            headers={"Content-Type": content_type},
            expires_at=timezone.now() + link_ttl(),
        )

    def download_url(self, key, filename, content_type):
        token = self._token({"op": "get", "key": key, "name": filename, "type": content_type})
        return f"/files/local/download/{token}/"

    @staticmethod
    def read_token(token: str, op: str) -> dict | None:
        try:
            payload = signing.loads(token, salt=LINK_SALT, max_age=settings.FILE_LINK_TTL_SECONDS)
        except signing.BadSignature:  # also raised when expired
            return None
        return payload if payload.get("op") == op else None

    def exists(self, key):
        return self._path(key).is_file()

    def open(self, key):
        return self._path(key).open("rb")

    def put_bytes(self, key, data):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_stream(self, key: str, stream: IO[bytes], max_bytes: int) -> int | None:
        """Copy an upload to disk; None (and nothing kept) if it is larger than allowed."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with path.open("wb") as out:
            while chunk := stream.read(64 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    break
                out.write(chunk)
        if written > max_bytes:
            path.unlink(missing_ok=True)
            return None
        return written

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)

    def wipe(self) -> None:
        """Remove every file. Tests only."""
        shutil.rmtree(self.root, ignore_errors=True)


class S3Storage(Storage):
    def __init__(self):
        import boto3
        from botocore.config import Config

        self.bucket = settings.FILE_STORAGE_BUCKET
        self.client = boto3.client(
            "s3",
            config=Config(signature_version="s3v4"),
            endpoint_url=settings.FILE_STORAGE_ENDPOINT or None,
            region_name=settings.FILE_STORAGE_REGION or None,
            aws_access_key_id=settings.FILE_STORAGE_ACCESS_KEY or None,
            aws_secret_access_key=settings.FILE_STORAGE_SECRET_KEY or None,
        )

    def upload_target(self, key, content_type, max_bytes):
        seconds = settings.FILE_LINK_TTL_SECONDS
        post = self.client.generate_presigned_post(
            self.bucket,
            key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=seconds,
        )
        return UploadTarget(
            method="POST",
            url=post["url"],
            fields=post["fields"],
            expires_at=timezone.now() + link_ttl(),
        )

    def download_url(self, key, filename, content_type):
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{safe_filename(filename)}"',
                "ResponseContentType": content_type,
            },
            ExpiresIn=settings.FILE_LINK_TTL_SECONDS,
        )

    def exists(self, key):
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def open(self, key):
        import tempfile

        spooled = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115
        self.client.download_fileobj(self.bucket, key, spooled)
        spooled.seek(0)
        return spooled  # type: ignore[return-value]

    def put_bytes(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)


@cache
def _storage_for(backend: str, root: str) -> Storage:
    if backend == "local":
        return LocalStorage(Path(root))
    if backend == "s3":
        return S3Storage()
    raise ValueError(f"Unknown FILE_STORAGE_BACKEND {backend!r}")


def get_storage() -> Storage:
    return _storage_for(settings.FILE_STORAGE_BACKEND, str(settings.FILE_STORAGE_LOCAL_ROOT))
