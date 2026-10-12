"""The signed release report as a PDF (M8-07, FR-RPT-04).

Built only from the stored, signed report body and the sign-off record, never from live data,
so the PDF always says what was signed. Laid out as the brand's ledger page: a narrow margin
column for section numbers and status marks, a hairline, and the content to its right, ending
in a sign-off line with a name and a date.

Fonts are the PDF's built-in serif, sans and mono, which are the brand's stated fallbacks.
The output is deterministic: the same signed report always gives the same bytes.
"""

from datetime import UTC, datetime
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

INK = HexColor("#161812")
INK_2 = HexColor("#4A4C40")
INK_3 = HexColor("#686A5E")
PAPER = HexColor("#F2EFE4")
PAPER_2 = HexColor("#E8E4D3")
RULE = HexColor("#CBC8B5")
TICK = HexColor("#15692C")
STOP = HexColor("#C93A22")
HOLD = HexColor("#8A5F00")
GRAPHITE = HexColor("#565950")

SERIF, SERIF_BOLD, SERIF_ITALIC = "Times-Roman", "Times-Bold", "Times-Italic"
SANS, SANS_BOLD, MONO = "Helvetica", "Helvetica-Bold", "Courier-Bold"

WIDTH, HEIGHT = A4
SIDE, TOP, BOTTOM = 15 * mm, 15 * mm, 14 * mm
MARGIN_COL, GUTTER = 24 * mm, 7 * mm
RULE_X = SIDE + MARGIN_COL + GUTTER / 2
LEFT = SIDE + MARGIN_COL + GUTTER
RIGHT = WIDTH - SIDE
CONTENT = RIGHT - LEFT

BLOCKER_LABEL = {
    "closed_failed_retest": ("Closed with a failed retest", "fail"),
    "open_critical": ("Open critical defect", "fail"),
    "needs_retest": ("Fixed but not retested", "hold"),
    "unfiled_failure": ("Failure without a defect", "fail"),
    "uncovered_critical": ("Critical requirement without tests", "open"),
}


class _Page:
    """A cursor that moves down the page and starts a new one when it runs out of room."""

    def __init__(self, canvas: Canvas, footer: str):
        self.c = canvas
        self.footer = footer
        self.number = 0
        self.y = 0.0
        self.new()

    def new(self) -> None:
        if self.number:
            self.c.showPage()
        self.number += 1
        c = self.c
        c.setFillColor(PAPER)
        c.rect(0, 0, WIDTH, HEIGHT, stroke=0, fill=1)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(RULE_X, 0, RULE_X, HEIGHT)
        c.setFillColor(INK_3)
        c.setFont(SANS, 7)
        c.drawString(SIDE, HEIGHT - 10 * mm, "RELEASE REPORT")
        c.drawRightString(RIGHT, HEIGHT - 10 * mm, self.footer.upper())
        c.line(LEFT, BOTTOM + 4 * mm, RIGHT, BOTTOM + 4 * mm)
        c.drawString(LEFT, BOTTOM, "Signed copy. Made with Greenlit.")
        c.setFillColor(INK)
        c.setFont(MONO, 8)
        c.drawString(SIDE, BOTTOM, f"{self.number:02d}")
        self.y = HEIGHT - TOP - 10 * mm

    def room(self, needed: float) -> None:
        if self.y - needed < BOTTOM + 10 * mm:
            self.new()

    def text(
        self, text: str, font: str, size: float, colour=INK, leading: float | None = None, gap=0.0
    ) -> None:
        leading = leading or size * 1.4
        for line in simpleSplit(text, font, size, CONTENT):
            self.room(leading)
            self.c.setFillColor(colour)
            self.c.setFont(font, size)
            self.c.drawString(LEFT, self.y - size, line)
            self.y -= leading
        self.y -= gap

    def margin_text(self, text: str, font: str, size: float, colour=INK, dy: float = 0) -> None:
        self.c.setFillColor(colour)
        self.c.setFont(font, size)
        self.c.drawRightString(SIDE + MARGIN_COL, self.y - size + dy, text)

    def rule(self, strong: bool = False) -> None:
        self.c.setStrokeColor(INK if strong else RULE)
        self.c.setLineWidth(0.8 if strong else 0.6)
        self.c.line(LEFT, self.y, RIGHT, self.y)

    def mark(self, kind: str, size: float = 9) -> None:
        """A status mark in the margin, drawn as the brand draws them: tick, cross, dash, box."""
        c = self.c
        x = SIDE + MARGIN_COL - size
        y = self.y - size - 1
        u = size / 16
        c.setLineWidth(1.3)
        c.setLineCap(1)
        c.setLineJoin(1)

        def at(px: float, py: float) -> tuple[float, float]:
            return x + px * u, y + (16 - py) * u  # the marks' grid has y pointing down

        path = c.beginPath()
        if kind == "pass":
            c.setStrokeColor(TICK)
            path.moveTo(*at(3, 8.7))
            path.lineTo(*at(6.2, 12))
            path.lineTo(*at(13, 3.6))
        elif kind == "fail":
            c.setStrokeColor(STOP)
            path.moveTo(*at(3.6, 3.6))
            path.lineTo(*at(12.4, 12.4))
            path.moveTo(*at(12.4, 3.6))
            path.lineTo(*at(3.6, 12.4))
        elif kind == "hold":
            c.setStrokeColor(HOLD)
            path.moveTo(*at(3, 8))
            path.lineTo(*at(13, 8))
        else:
            c.setStrokeColor(GRAPHITE)
            path.rect(x + 3 * u, y + 3 * u, 10 * u, 10 * u)
        c.drawPath(path, stroke=1, fill=0)


def _when(moment: datetime) -> str:
    moment = moment.astimezone(UTC)
    return f"{moment.day} {moment.strftime('%B %Y, %H:%M')} UTC"


def render_report(
    *,
    project: str,
    release: str,
    report_id: str,
    body: dict,
    signed_by: str,
    signed_at: datetime,
    readiness: str,
    reason: str,
) -> bytes:
    """The PDF for one signed report. `body` is the stored `report.body`."""
    out = BytesIO()
    # Uncompressed on purpose: these files are a few kilobytes, and plain text streams can be
    # searched and checked (by people, by archives and by the tests).
    canvas = Canvas(out, pagesize=A4, invariant=1, pageCompression=0)
    canvas.setTitle(f"{project} {release} release report")
    canvas.setAuthor("Greenlit")
    page = _Page(canvas, f"{report_id}  ·  {project}")
    ready = readiness == "ready"

    # --- 01: the decision ---------------------------------------------------------------------
    page.margin_text("01", SERIF_BOLD, 26)
    page.text(f"{project}", SANS, 9, INK_3, gap=1)
    page.text(f"Release {release}", SERIF_BOLD, 30, leading=34, gap=2)
    page.text(
        "Ready" if ready else "Not ready yet", SERIF_ITALIC, 17, TICK if ready else INK, gap=6
    )
    page.text(body.get("summary", ""), SERIF, 12.5, leading=17, gap=8)

    blockers = body.get("facts", {}).get("blockers", [])
    if blockers:
        page.room(30)
        page.text(f"BLOCKERS AT SIGN-OFF  ·  {len(blockers)}", SANS_BOLD, 7, INK_3, gap=2)
        page.rule(strong=True)
        page.y -= 3
        for b in blockers:
            label, mark = BLOCKER_LABEL.get(b.get("type", ""), ("Blocker", "open"))
            page.room(26)
            page.mark(mark)
            page.c.setFillColor(INK)
            page.c.setFont(MONO, 9)
            page.c.drawString(LEFT, page.y - 9, b.get("display_id", ""))
            id_width = page.c.stringWidth(b.get("display_id", ""), MONO, 9) + 8
            page.c.setFont(SANS, 9.5)
            title = simpleSplit(b.get("title", ""), SANS, 9.5, CONTENT - id_width)
            page.c.drawString(LEFT + id_width, page.y - 9, title[0] if title else "")
            page.y -= 12
            page.text(label, SANS, 7.5, INK_3, gap=3)
            page.rule()
            page.y -= 3
        page.y -= 8

    # --- the report's own sections -------------------------------------------------------------
    for number, section in enumerate(body.get("sections", []), start=2):
        page.room(40)
        page.margin_text(f"{number:02d}", SERIF_BOLD, 26)
        page.text(section.get("heading", ""), SERIF_BOLD, 15, leading=19, gap=3)
        page.rule(strong=True)
        page.y -= 4
        for line in section.get("lines", []):
            page.text(line.get("text", ""), SANS, 9.5, leading=13.5, gap=1)
            refs = "   ".join(line.get("refs", []))
            if refs:
                page.text(refs, MONO, 7.5, INK_2, gap=2)
            page.rule()
            page.y -= 4
        page.y -= 10

    # --- the sign-off line ----------------------------------------------------------------------
    # The whole reason is part of the record, so the box grows to hold all of it.
    reason_lines = simpleSplit(reason, SANS, 9, CONTENT - 10 * mm) if reason else []
    box_height = (36 + 4.2 * len(reason_lines)) * mm if reason else 30 * mm
    page.room(box_height)
    top = page.y
    c = page.c
    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    c.rect(LEFT, top - box_height, CONTENT, box_height, stroke=1, fill=0)
    inner = LEFT + 5 * mm
    date_x = RIGHT - 62 * mm
    c.setFillColor(INK)
    c.setFont(SERIF, 14)
    c.drawString(inner, top - 12 * mm, signed_by)
    c.setFont(MONO, 9)
    c.drawString(date_x, top - 12 * mm, _when(signed_at))
    c.line(inner, top - 14 * mm, date_x - 6 * mm, top - 14 * mm)
    c.line(date_x, top - 14 * mm, RIGHT - 5 * mm, top - 14 * mm)
    c.setFillColor(INK_3)
    c.setFont(SANS, 7)
    c.drawString(inner, top - 18 * mm, "SIGNED OFF BY")
    c.drawString(date_x, top - 18 * mm, "DATE")
    c.drawString(
        inner, top - 24 * mm, f"READINESS AT SIGN-OFF: {'READY' if ready else 'NOT READY YET'}"
    )
    if reason:
        c.drawString(inner, top - 30 * mm, "REASON FOR SIGNING OFF WHILE NOT READY")
        c.setFillColor(INK)
        c.setFont(SANS, 9)
        y = top - 34.5 * mm
        for line in reason_lines:
            c.drawString(inner, y, line)
            y -= 4.2 * mm

    canvas.save()
    return out.getvalue()
