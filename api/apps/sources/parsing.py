"""Read the text out of a source document, keeping where each page and section sits (M2-02).

Every parser returns a `Parsed`: the whole text, page offsets into it and section offsets into
it. Nothing here calls the network or the AI; a file that cannot be read raises `Unreadable`
with a message for the person who uploaded it.
"""

import re
from dataclasses import dataclass, field
from typing import IO

MAX_PAGES = 200  # AI §8 input limit for a PRD
PASTED_PAGE_CHARS = 3000  # pasted text has no pages; this is what "a page" means for its limit
SECTION_CHARS = 12_000  # a section longer than this is cut at a paragraph, to keep requests small

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$", re.MULTILINE)


class Unreadable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Parsed:
    text: str
    pages: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)


def page_of(pages: list[dict], position: int) -> int:
    for page in pages:
        if page["start"] <= position < page["end"]:
            return page["page"]
    return pages[-1]["page"] if pages else 1


def _split_long(heading: str, start: int, end: int, text: str) -> list[tuple[str, int, int]]:
    """Cut a long stretch into parts that end at a paragraph break where there is one."""
    parts = []
    while end - start > SECTION_CHARS:
        cut = text.rfind("\n\n", start, start + SECTION_CHARS)
        cut = cut if cut > start else start + SECTION_CHARS
        parts.append((heading, start, cut))
        start = cut
    parts.append((heading, start, end))
    return parts


def _sections(text: str, pages: list[dict], marks: list[tuple[int, str]]) -> list[dict]:
    """`marks` are (position, heading) where each section starts, in order."""
    if not marks or marks[0][0] > 0:
        marks = [(0, ""), *marks]
    out = []
    for (start, heading), (end, _) in zip(marks, [*marks[1:], (len(text), "")], strict=True):
        for name, a, b in _split_long(heading, start, end, text):
            if text[a:b].strip():
                out.append({"heading": name, "page": page_of(pages, a), "start": a, "end": b})
    return out


def parse_text(text: str) -> Parsed:
    """Plain text or Markdown. Markdown headings (`#`) start sections."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise Unreadable("There is no text in this document.")
    pages = [{"page": 1, "start": 0, "end": len(text)}]
    marks = [(m.start(), m.group(2).strip()) for m in _HEADING.finditer(text)]
    return Parsed(text, pages, _sections(text, pages, marks))


def parse_pdf(handle: IO[bytes]) -> Parsed:
    import pdfplumber

    try:
        with pdfplumber.open(handle) as pdf:  # type: ignore[arg-type]
            if len(pdf.pages) > MAX_PAGES:
                raise Unreadable(
                    f"This document has {len(pdf.pages)} pages. The limit is {MAX_PAGES}."
                )
            texts = [(page.extract_text() or "").strip() for page in pdf.pages]
    except Unreadable:
        raise
    except Exception as error:  # noqa: BLE001 (a damaged PDF can fail in many ways)
        raise Unreadable(
            "This PDF could not be read. Export it again, or paste the text."
        ) from error
    if not any(texts):
        raise Unreadable("This PDF has no text Greenlit can read. Paste the text instead.")
    text, pages = "", []
    for number, page_text in enumerate(texts, start=1):
        start = len(text)
        text += page_text + "\n\n"
        pages.append({"page": number, "start": start, "end": len(text)})
    # A PDF's headings cannot be told from its body reliably, so each page is a section.
    marks = [(p["start"], f"Page {p['page']}") for p in pages]
    return Parsed(text, pages, _sections(text, pages, marks))


def parse_docx(handle: IO[bytes]) -> Parsed:
    import docx

    try:
        document = docx.Document(handle)
    except Exception as error:  # noqa: BLE001
        raise Unreadable(
            "This DOCX could not be read. Save it again, or paste the text."
        ) from error
    text, marks = "", []
    for paragraph in document.paragraphs:
        line = paragraph.text.strip()
        if not line:
            continue
        style = paragraph.style.name if paragraph.style else ""
        if (style or "").lower().startswith(("heading", "title")):
            marks.append((len(text), line))
        text += line + "\n\n"
    if not text.strip():
        raise Unreadable("There is no text in this document.")
    # Word does not store page breaks in a way that survives reading; pages are by length.
    pages = [
        {"page": i + 1, "start": start, "end": min(start + PASTED_PAGE_CHARS, len(text))}
        for i, start in enumerate(range(0, len(text), PASTED_PAGE_CHARS))
    ]
    if len(pages) > MAX_PAGES:
        raise Unreadable(f"This document is too long. The limit is about {MAX_PAGES} pages.")
    return Parsed(text, pages, _sections(text, pages, marks))


def parse_file(handle: IO[bytes], detected_type: str) -> Parsed:
    if detected_type == "pdf":
        return parse_pdf(handle)
    if detected_type == "docx":
        return parse_docx(handle)
    if detected_type in ("markdown", "text"):
        try:
            return parse_text(handle.read().decode("utf-8"))
        except UnicodeDecodeError as error:
            raise Unreadable(
                "This file is not UTF-8 text. Save it as UTF-8, or paste the text."
            ) from error
    raise Unreadable("This file type cannot be read as a document.")
