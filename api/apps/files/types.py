"""Which files each upload kind accepts, decided by their content (PRD §9 "File types", SEC §8).

A file's name only decides whether to start an upload; after the upload the bytes themselves
are identified, and a file whose content is not on the kind's list is refused, whatever it was
called. HTML and SVG are never accepted.
"""

import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO

MB = 1024 * 1024


@dataclass(frozen=True)
class FileType:
    key: str
    label: str  # shown to people in error messages
    extensions: tuple[str, ...]
    mime: str


TYPES = {
    t.key: t
    for t in (
        FileType("pdf", "PDF", (".pdf",), "application/pdf"),
        FileType(
            "docx",
            "DOCX",
            (".docx",),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        FileType("markdown", "Markdown", (".md", ".markdown"), "text/markdown"),
        FileType("text", "plain text", (".txt", ".log"), "text/plain"),
        FileType("json", "JSON", (".json",), "application/json"),
        FileType("png", "PNG", (".png",), "image/png"),
        FileType("jpeg", "JPEG", (".jpg", ".jpeg"), "image/jpeg"),
        FileType("webp", "WebP", (".webp",), "image/webp"),
        FileType("gif", "GIF", (".gif",), "image/gif"),
        FileType("mp4", "MP4", (".mp4",), "video/mp4"),
        FileType("webm", "WebM", (".webm",), "video/webm"),
        FileType("mov", "MOV", (".mov",), "video/quicktime"),
    )
}


@dataclass(frozen=True)
class UploadKind:
    key: str
    types: tuple[str, ...]
    max_bytes: int


# PRD §9: the per-kind allow-list. Sizes: 20 MB for documents (FR-PLAN-01), 200 MB per evidence
# file (PRD §9 "Evidence storage"); screenshots and reports use the document limit (proposed).
KINDS = {
    k.key: k
    for k in (
        UploadKind("prd", ("pdf", "docx", "markdown", "text"), 20 * MB),
        UploadKind("screenshot", ("png", "jpeg", "webp"), 20 * MB),
        UploadKind("qa_report", ("pdf", "docx"), 20 * MB),
        UploadKind(
            "evidence",
            ("png", "jpeg", "webp", "gif", "mp4", "webm", "mov", "pdf", "text", "json"),
            200 * MB,
        ),
    )
}


def accepted_labels(kind: str) -> str:
    """'PDF, DOCX, Markdown or plain text', for the UX §9 message."""
    labels = list(dict.fromkeys(TYPES[t].label for t in KINDS[kind].types))
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " or " + labels[-1]


def unsupported_message(kind: str) -> str:
    return f"This file type isn't supported here. Use {accepted_labels(kind)}."


def type_for_name(kind: str, name: str) -> str | None:
    """The allowed type a file name claims, or None. Only a first filter; content decides."""
    lower = name.lower()
    for key in KINDS[kind].types:
        if lower.endswith(TYPES[key].extensions):
            return key
    return None


# --- Identifying content ------------------------------------------------------------------------

HEAD_BYTES = 64 * 1024
_MARKUP_STARTS = (b"<!doctype html", b"<html", b"<svg", b"<?xml", b"<head", b"<body", b"<script")


def _is_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multi-byte character cut off at the end of the sample is still text.
        if exc.start < len(head) - 4:
            return False
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return not stripped.startswith(_MARKUP_STARTS)


def _is_docx(file: IO[bytes]) -> bool:
    file.seek(0)
    try:
        with zipfile.ZipFile(file) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False
    finally:
        file.seek(0)
    return "[Content_Types].xml" in names and "word/document.xml" in names


def _is_json(file: IO[bytes]) -> bool:
    file.seek(0)
    try:
        json.loads(file.read().decode("utf-8"))
        return True
    except (UnicodeDecodeError, ValueError):
        return False
    finally:
        file.seek(0)


Sniffer = Callable[[bytes, IO[bytes]], bool]

_SIGNATURES: list[tuple[str, Sniffer]] = [
    ("pdf", lambda h, f: h.startswith(b"%PDF-")),
    ("png", lambda h, f: h.startswith(b"\x89PNG\r\n\x1a\n")),
    ("jpeg", lambda h, f: h.startswith(b"\xff\xd8\xff")),
    ("gif", lambda h, f: h[:6] in (b"GIF87a", b"GIF89a")),
    ("webp", lambda h, f: h[:4] == b"RIFF" and h[8:12] == b"WEBP"),
    ("mov", lambda h, f: h[4:8] == b"ftyp" and h[8:10] == b"qt"),
    ("mp4", lambda h, f: h[4:8] == b"ftyp" and h[8:10] != b"qt"),
    ("webm", lambda h, f: h.startswith(b"\x1a\x45\xdf\xa3")),
    ("docx", lambda h, f: h.startswith(b"PK\x03\x04") and _is_docx(f)),
]


def identify(file: IO[bytes], name: str) -> str | None:
    """The type the bytes really are, or None if they are nothing this service accepts.

    Binary formats are recognised by their signatures. Text has none, so for text the name
    chooses between Markdown, plain text and JSON, and the content must then be that.
    """
    file.seek(0)
    head = file.read(HEAD_BYTES)
    file.seek(0)
    for key, matches in _SIGNATURES:
        if matches(head, file):
            return key
    if not head or not _is_text(head):
        return None
    lower = name.lower()
    if lower.endswith(TYPES["json"].extensions):
        return "json" if _is_json(file) else None
    if lower.endswith(TYPES["markdown"].extensions):
        return "markdown"
    return "text"
