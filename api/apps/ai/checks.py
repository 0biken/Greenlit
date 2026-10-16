"""Checks on what the model said, before any of it becomes a draft (M2-05; AI §4, §5).

Pure functions: they take the parsed reply and this project's own data, and return what may be
kept and what was dropped and why. A dropped item is never repaired: an invented quote, an ID
that does not exist or a title that is too long means the item is left out and counted.
"""

from bisect import bisect_left
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import jsonschema

TITLE_MAX = 120
STEPS_MAX = 20
QUOTE_WORDS = (5, 30)
DUPLICATE_RATIO = 0.9

# Reasons an item is dropped. Stored on `AiDroppedItem.reason`.
QUOTE_NOT_FOUND = "quote_not_found"
QUOTE_LENGTH = "quote_length"
UNKNOWN_ID = "unknown_id"
TOO_LONG = "too_long"
OUTSIDE_IMAGE = "outside_image"
NO_REQUIREMENT = "no_requirement"
EMPTY_STEP = "empty_step"


def matches_schema(reply: object, schema: dict) -> bool:
    try:
        jsonschema.validate(reply, schema)
    except jsonschema.ValidationError:
        return False
    return True


def _normalised(text: str) -> tuple[str, list[int]]:
    """The text with every run of whitespace as one space, and for each character of it the
    position it came from. Only whitespace is normalised: a quote must match word for word."""
    out: list[str] = []
    origin: list[int] = []
    in_space = False
    for position, char in enumerate(text):
        if char.isspace():
            if not in_space and out:
                out.append(" ")
                origin.append(position)
            in_space = True
        else:
            out.append(char)
            origin.append(position)
            in_space = False
    return "".join(out), origin


class Document:
    """A source's stored text, ready to look quotes up in."""

    def __init__(self, text: str):
        self.text = text
        self._flat, self._origin = _normalised(text)

    def find(self, quote: str, start: int = 0, end: int | None = None) -> tuple[int, int] | None:
        """Where `quote` is in the text, word for word, as (start, end) positions; else None.
        Looked for between `start` and `end` first (the section it was drafted from)."""
        flat_quote = " ".join(quote.split())
        if not flat_quote:
            return None
        found = -1
        if end is not None:
            lo, hi = bisect_left(self._origin, start), bisect_left(self._origin, end)
            found = self._flat.find(flat_quote, lo, hi)
        if found < 0:
            found = self._flat.find(flat_quote)
        if found < 0:
            return None
        last = found + len(flat_quote) - 1
        return self._origin[found], self._origin[last] + 1


def quote_length_ok(quote: str) -> bool:
    return QUOTE_WORDS[0] <= len(quote.split()) <= QUOTE_WORDS[1]


def region_ok(region: dict) -> bool:
    """An image region as x, y, width, height, each 0 to 1, lying inside the image (AI §5)."""
    try:
        x, y, w, h = (float(region[k]) for k in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= x and 0 <= y and w > 0 and h > 0 and x + w <= 1 and y + h <= 1


def possible_duplicate(title: str, text: str, existing: list[dict]) -> str | None:
    """The display ID of an existing record this one nearly repeats, if any."""
    for record in existing:
        same_title = SequenceMatcher(None, title.lower(), record["title"].lower()).ratio()
        same_text = SequenceMatcher(None, text.lower(), record.get("text", "").lower()).ratio()
        if max(same_title, same_text) >= DUPLICATE_RATIO:
            return record["display_id"]
    return None


@dataclass
class Checked:
    kept: list[dict] = field(default_factory=list)
    dropped: list[tuple[str, dict]] = field(default_factory=list)  # (reason, the item as sent)


def check_requirements(
    items: list[dict],
    document: Document,
    *,
    section: tuple[int, int],
    existing: list[dict],
) -> Checked:
    """F1. Each kept item gains `start` and `end` (where its quote is in the document) and
    `possible_duplicate_of` when it nearly repeats a record in `existing`
    (`[{display_id, title, text}]`, this project's requirements)."""
    known = {record["display_id"].upper() for record in existing}
    out = Checked()
    for item in items:
        if len(item["title"]) > TITLE_MAX:
            out.dropped.append((TOO_LONG, item))
            continue
        cited = item.get("duplicate_of")
        if cited and cited.upper() not in known:
            out.dropped.append((UNKNOWN_ID, item))
            continue
        if not quote_length_ok(item["quote"]):
            out.dropped.append((QUOTE_LENGTH, item))
            continue
        where = document.find(item["quote"], *section)
        if where is None:
            out.dropped.append((QUOTE_NOT_FOUND, item))
            continue
        duplicate = (cited.upper() if cited else None) or possible_duplicate(
            item["title"], item["text"], existing
        )
        out.kept.append(
            {**item, "start": where[0], "end": where[1], "possible_duplicate_of": duplicate}
        )
    return out


def _same_steps(steps: list[str], other: list[str]) -> bool:
    a, b = "\n".join(steps).lower(), "\n".join(other).lower()
    return SequenceMatcher(None, a, b).ratio() >= DUPLICATE_RATIO


def check_cases(items: list[dict], *, asked: set[str], existing: list[dict]) -> Checked:
    """F2. `asked` are the requirement IDs sent in this request: a case may cite only those,
    so an ID the model made up, or one it was not given, drops the case. `existing` are this
    project's accepted cases (`[{display_id, steps, requirement_ids}]`). Each kept item has
    its `requirement_ids` in upper case and `possible_duplicate_of` when an accepted case on
    one of the same requirements has nearly the same steps."""
    asked = {r.upper() for r in asked}
    out = Checked()
    for item in items:
        cited = [r.upper() for r in item["requirement_ids"]]
        if len(item["title"]) > TITLE_MAX or len(item["steps"]) > STEPS_MAX:
            out.dropped.append((TOO_LONG, item))
        elif not cited:
            out.dropped.append((NO_REQUIREMENT, item))
        elif not set(cited) <= asked:
            out.dropped.append((UNKNOWN_ID, item))
        elif not item["steps"] or not all(step.strip() for step in item["steps"]):
            out.dropped.append((EMPTY_STEP, item))
        else:
            duplicate = next(
                (
                    case["display_id"]
                    for case in existing
                    if set(cited) & {r.upper() for r in case["requirement_ids"]}
                    and _same_steps(item["steps"], case["steps"])
                ),
                None,
            )
            out.kept.append({**item, "requirement_ids": cited, "possible_duplicate_of": duplicate})
    return out
