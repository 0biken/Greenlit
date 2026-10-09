"""The file service (M1-14, PRD §9 file types, SEC §6 and §8, UX §9), end to end through local
storage, as the restricted app role."""

import base64
import hashlib
import io
import json
import uuid
import zipfile
from urllib.parse import unquote

import pytest
from django.core import signing
from django.db import connection
from django.test import Client

from apps.core import checks
from apps.core.models import (
    Membership,
    MembershipStatus,
    Organisation,
    Project,
    ProjectMember,
    Role,
    User,
)
from apps.core.tenancy import org_scope
from apps.files import types
from apps.files.models import StoredFile
from apps.files.scanner import EICAR, TEST_MARKER, is_infected
from apps.files.storage import LocalStorage, S3Storage, get_storage
from apps.files.types import KINDS, UploadKind, identify, unsupported_message
from apps.files.views import start_upload

pytestmark = pytest.mark.django_db

# --- Sample content ----------------------------------------------------------------------------


def zipped(names: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "<x/>")
    return buffer.getvalue()


PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 40
SAMPLES = {
    "pdf": b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n",
    "docx": zipped(["[Content_Types].xml", "word/document.xml"]),
    "png": PNG,
    "jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 40,
    "gif": b"GIF89a" + b"\x00" * 40,
    "webp": b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 30,
    "mp4": b"\x00\x00\x00\x18ftypisom" + b"\x00" * 30,
    "mov": b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 30,
    "webm": bytes.fromhex("1a45dfa3") + b"\x00" * 40,
}


@pytest.mark.parametrize(
    "data,name,expected",
    [
        *[(data, f"file.{key}", key) for key, data in SAMPLES.items()],
        (b"# Release notes\nAll good.", "notes.md", "markdown"),
        (b"2026-10-09 12:00 ERROR timeout", "app.log", "text"),
        (b'{"build": "2.4.1"}', "result.json", "json"),
        # Content, not the name, decides:
        (SAMPLES["pdf"], "renamed.png", "pdf"),
        (b"<!DOCTYPE html><script>alert(1)</script>", "page.png", None),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>", "logo.png", None),
        (b"<?xml version='1.0'?><svg/>", "drawing.txt", None),
        (b"  \n<html><body>hi</body></html>", "notes.md", None),
        (b"MZ\x90\x00\x03" + b"\x00" * 40, "invoice.pdf", None),
        (zipped(["payload.exe"]), "report.docx", None),
        (b"text with a \x00 byte", "app.log", None),
        (b"{not json", "result.json", None),
        (b"", "empty.txt", None),
    ],
)
def test_files_are_identified_by_their_content(data, name, expected):
    assert identify(io.BytesIO(data), name) == expected


def test_the_allow_list_matches_prd_section_9():
    accepted = {kind: set(k.types) for kind, k in KINDS.items()}
    assert accepted == {
        "prd": {"pdf", "docx", "markdown", "text"},
        "screenshot": {"png", "jpeg", "webp"},
        "qa_report": {"pdf", "docx"},
        "evidence": {"png", "jpeg", "webp", "gif", "mp4", "webm", "mov", "pdf", "text", "json"},
    }
    assert KINDS["prd"].max_bytes == 20 * 1024 * 1024
    assert KINDS["evidence"].max_bytes == 200 * 1024 * 1024


@pytest.mark.parametrize(
    "kind,message",
    [
        ("prd", "This file type isn't supported here. Use PDF, DOCX, Markdown or plain text."),
        ("screenshot", "This file type isn't supported here. Use PNG, JPEG or WebP."),
        ("qa_report", "This file type isn't supported here. Use PDF or DOCX."),
    ],
)
def test_the_refusal_names_the_types_this_upload_accepts(kind, message):
    assert unsupported_message(kind) == message


# --- The flow ---------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def app_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


class Team:
    """An organisation with a project, an engineer on it, and helpers to upload as them."""

    def __init__(self, slug: str):
        self.org_id = uuid.uuid4()
        with org_scope(self.org_id):
            self.org = Organisation.objects.create(id=self.org_id, name=slug.title(), slug=slug)
            self.project = Project.objects.create(org_id=self.org_id, name="App", key="APP")
        self.engineer = self.member(Role.QA_ENGINEER, on_project=True)

    def member(self, role: str, on_project: bool = False) -> Client:
        user = User.objects.create_user(
            f"{role}-{self.org.slug}-{uuid.uuid4().hex[:6]}@x.test", "x" * 14
        )
        with org_scope(self.org_id):
            Membership.objects.create(
                org_id=self.org_id, user=user, role=role, status=MembershipStatus.ACTIVE
            )
            if on_project:
                ProjectMember.objects.create(org_id=self.org_id, project=self.project, user=user)
        client = Client()
        client.force_login(user)
        return client

    def start(self, kind: str, name: str, size: int, client: Client | None = None):
        return (client or self.engineer).post(
            "/api/projects/app/files/",
            data={"kind": kind, "name": name, "size": size},
            content_type="application/json",
            headers={"X-Org": self.org.slug},
        )

    def send(self, upload: dict, data: bytes):
        return Client().put(
            upload["url"], data=data, content_type=upload["headers"]["Content-Type"]
        )

    def complete(self, file_id: str, capture, client: Client | None = None):
        with capture(execute=True):
            return (client or self.engineer).post(
                f"/api/files/{file_id}/complete/", headers={"X-Org": self.org.slug}
            )

    def detail(self, file_id: str, client: Client | None = None):
        return (client or self.engineer).get(
            f"/api/files/{file_id}/", headers={"X-Org": self.org.slug}
        )

    def download(self, file_id: str):
        return self.engineer.get(
            f"/api/files/{file_id}/download/", headers={"X-Org": self.org.slug}
        )

    def upload(self, kind: str, name: str, data: bytes, capture) -> dict:
        started = self.start(kind, name, len(data))
        assert started.status_code == 201, started.content
        body = started.json()
        assert self.send(body["upload"], data).status_code == 204
        assert self.complete(body["file"]["id"], capture).status_code == 202
        return self.detail(body["file"]["id"]).json()


@pytest.fixture
def team():
    return Team("files")


def test_an_upload_is_scanned_hashed_and_then_downloadable(
    team, django_capture_on_commit_callbacks
):
    result = team.upload("evidence", "checkout.png", PNG, django_capture_on_commit_callbacks)
    assert result["state"] == "available"
    assert result["detected_type"] == "png"
    assert result["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert result["size_bytes"] == len(PNG)

    link = team.download(result["id"])
    assert link.status_code == 200
    fetched = Client().get(link.json()["url"])
    assert fetched.status_code == 200
    assert b"".join(fetched.streaming_content) == PNG
    assert fetched.headers["Content-Disposition"].startswith("attachment;")
    assert fetched.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in fetched.headers["Content-Security-Policy"]


def test_files_are_stored_under_their_organisation_and_project(
    team, django_capture_on_commit_callbacks
):
    result = team.upload("evidence", "a.png", PNG, django_capture_on_commit_callbacks)
    with org_scope(team.org_id):
        key = StoredFile.objects.get(pk=result["id"]).storage_key
    assert key.startswith(f"{team.org_id}/{team.project.id}/")


def test_a_document_is_accepted_for_a_prd(team, django_capture_on_commit_callbacks):
    result = team.upload("prd", "spec.docx", SAMPLES["docx"], django_capture_on_commit_callbacks)
    assert (result["state"], result["detected_type"]) == ("available", "docx")


def test_a_name_the_kind_does_not_accept_is_refused_before_upload(team):
    response = team.start("qa_report", "notes.md", 100)
    assert response.status_code == 400
    assert response.json()["detail"] == "This file type isn't supported here. Use PDF or DOCX."


def test_content_that_does_not_match_is_refused_and_deleted(
    team, django_capture_on_commit_callbacks
):
    html = b"<!DOCTYPE html><script>steal()</script>"
    result = team.upload("evidence", "screenshot.png", html, django_capture_on_commit_callbacks)
    assert result["state"] == "rejected"
    assert result["rejection_reason"] == unsupported_message("evidence")
    with org_scope(team.org_id):
        key = StoredFile.objects.get(pk=result["id"]).storage_key
    assert not get_storage().exists(key)
    assert team.download(result["id"]).status_code == 409


def test_an_infected_file_is_never_made_available(team, django_capture_on_commit_callbacks):
    sample = b"2026-10-09 log line. " + TEST_MARKER
    result = team.upload("evidence", "log.txt", sample, django_capture_on_commit_callbacks)
    assert result["state"] == "infected"
    with org_scope(team.org_id):
        key = StoredFile.objects.get(pk=result["id"]).storage_key
    assert not get_storage().exists(key)
    assert team.download(result["id"]).status_code == 409


def test_a_file_cannot_be_downloaded_before_it_is_scanned(team):
    started = team.start("evidence", "late.png", len(PNG)).json()
    assert team.download(started["file"]["id"]).status_code == 409


def test_completing_before_the_bytes_arrive_is_refused(team):
    started = team.start("evidence", "nothing.png", len(PNG)).json()
    response = team.engineer.post(
        f"/api/files/{started['file']['id']}/complete/", headers={"X-Org": team.org.slug}
    )
    assert response.status_code == 400 and response.json()["code"] == "not_uploaded"


@pytest.mark.parametrize("size,code", [(0, "empty"), (20 * 1024 * 1024 + 1, "too_large")])
def test_sizes_outside_the_limits_are_refused(team, size, code):
    response = team.start("prd", "spec.pdf", size)
    assert response.status_code == 400 and response.json()["code"] == code


def test_sending_more_bytes_than_the_limit_allows_is_cut_off(team, monkeypatch):
    monkeypatch.setitem(
        types.KINDS, "evidence", UploadKind("evidence", KINDS["evidence"].types, 64)
    )
    started = team.start("evidence", "big.png", 10).json()
    assert team.send(started["upload"], PNG + b"0" * 100).status_code == 413


def test_the_organisations_storage_quota_is_enforced(
    team, settings, django_capture_on_commit_callbacks
):
    settings.ORG_STORAGE_QUOTA_BYTES = 100
    team.upload("evidence", "one.png", PNG, django_capture_on_commit_callbacks)  # 48 bytes
    response = team.start("evidence", "two.png", 60)
    assert response.status_code == 400 and response.json()["code"] == "quota"


# --- Links ------------------------------------------------------------------------------------


def token_of(url: str) -> str:
    return unquote(url.rstrip("/").rsplit("/", 1)[1])


def test_a_tampered_or_misused_link_is_refused(team, django_capture_on_commit_callbacks):
    started = team.start("evidence", "x.png", len(PNG)).json()
    upload_url = started["upload"]["url"]
    assert (
        Client().put(upload_url[:-6] + "AAAAA/", data=PNG, content_type="image/png").status_code
        == 403
    )
    # The type was fixed when the link was issued.
    assert Client().put(upload_url, data=PNG, content_type="text/html").status_code == 400


def test_upload_and_download_links_cannot_stand_in_for_each_other(
    team, django_capture_on_commit_callbacks
):
    """A download link goes to anyone who can view; it must never let them overwrite evidence."""
    result = team.upload("evidence", "kept.png", PNG, django_capture_on_commit_callbacks)
    download = team.download(result["id"]).json()["url"]
    as_upload = download.replace("/download/", "/upload/")
    assert Client().put(as_upload, data=b"forged", content_type="image/png").status_code == 403
    fetched = Client().get(download)
    assert b"".join(fetched.streaming_content) == PNG  # untouched

    started = team.start("evidence", "next.png", len(PNG)).json()
    assert team.send(started["upload"], PNG).status_code == 204  # the bytes now exist
    as_download = started["upload"]["url"].replace("/upload/", "/download/")
    assert Client().get(as_download).status_code == 403


def test_links_expire_after_15_minutes(team, monkeypatch, django_capture_on_commit_callbacks):
    result = team.upload("evidence", "old.png", PNG, django_capture_on_commit_callbacks)
    url = team.download(result["id"]).json()["url"]
    real_time = signing.time.time
    monkeypatch.setattr(signing.time, "time", lambda: real_time() + 15 * 60 + 5)
    assert Client().get(url).status_code == 403


def test_a_storage_key_cannot_climb_out_of_the_storage_folder():
    with pytest.raises(ValueError):
        get_storage().put_bytes("../../outside.txt", b"x")


# --- Who can do what --------------------------------------------------------------------------


def test_a_viewer_cannot_upload(team):
    assert (
        team.start(
            "evidence", "x.png", 10, client=team.member(Role.VIEWER, on_project=True)
        ).status_code
        == 403
    )


def test_someone_not_on_the_project_cannot_see_its_files(team, django_capture_on_commit_callbacks):
    result = team.upload("evidence", "private.png", PNG, django_capture_on_commit_callbacks)
    outsider = team.member(Role.QA_ENGINEER, on_project=False)
    assert team.detail(result["id"], client=outsider).status_code == 404
    assert team.start("evidence", "x.png", 10, client=outsider).status_code == 404


def test_uploads_have_their_own_rate_limit():
    assert "UploadThrottle" in {c.__name__ for c in start_upload.cls.throttle_classes}


# --- When the scanner is down ------------------------------------------------------------------


def test_an_unreachable_scanner_retries_and_never_releases_the_file(
    team, settings, django_capture_on_commit_callbacks
):
    settings.MALWARE_SCANNER, settings.CLAMAV_HOST, settings.CLAMAV_PORT = "clamav", "127.0.0.1", 1
    result = team.upload("evidence", "waiting.png", PNG, django_capture_on_commit_callbacks)
    assert result["state"] == "scanning"
    assert team.download(result["id"]).status_code == 409
    with org_scope(team.org_id):
        from apps.core.models import Job

        job = Job.objects.get(kind="scan_file")
    assert (job.state, job.error) == ("dead", "ScannerUnavailable")  # an admin can re-run it


# --- Production configuration -----------------------------------------------------------------


def test_outside_development_the_stub_scanner_and_local_storage_are_refused(settings):
    settings.DEBUG = False
    settings.MALWARE_SCANNER, settings.FILE_STORAGE_BACKEND = "stub", "local"
    assert {e.id for e in checks.production_file_handling(None)} == {
        "greenlit.E002",
        "greenlit.E003",
    }
    settings.MALWARE_SCANNER, settings.FILE_STORAGE_BACKEND = "clamav", "s3"
    assert checks.production_file_handling(None) == []


def test_s3_upload_links_carry_the_size_limit_and_downloads_are_attachments(settings):
    settings.FILE_STORAGE_BUCKET = "greenlit-test"
    settings.FILE_STORAGE_ENDPOINT = "https://s3.example.test"
    settings.FILE_STORAGE_REGION = "eu-west-1"
    settings.FILE_STORAGE_ACCESS_KEY, settings.FILE_STORAGE_SECRET_KEY = "AKIATEST", "secret"
    storage = S3Storage()  # nothing is sent: links are signed locally

    target = storage.upload_target("org/project/file", "image/png", 1234)
    assert target.method == "POST" and target.fields["key"] == "org/project/file"
    policy = json.loads(base64.b64decode(target.fields["policy"]))
    assert ["content-length-range", 1, 1234] in policy["conditions"]
    assert {"Content-Type": "image/png"} in policy["conditions"]

    url = storage.download_url("org/project/file", "evidence.png", "image/png")
    assert "response-content-disposition=attachment" in url
    assert "X-Amz-Expires=900" in url


def test_local_storage_is_what_development_uses(settings):
    assert isinstance(get_storage(), LocalStorage)


def test_the_stub_also_recognises_the_standard_eicar_test_file():
    """Kept in memory: written to disk, desktop antivirus would quarantine it."""
    assert is_infected(io.BytesIO(b"prefix " + EICAR)) is True
    assert is_infected(io.BytesIO(b"an ordinary log line")) is False
