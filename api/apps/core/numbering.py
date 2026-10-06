"""Short display IDs people type and say: REQ-102, BUG-1042, HUBE-BUG-1042 (M1-13, DATA §4).

Numbers come from a per-project counter incremented in the same transaction as the insert, so
they never repeat and are never reused. A gap in the sequence is normal.
"""

import re
from typing import NamedTuple
from uuid import UUID

from django.db import transaction

from apps.core.models import CounterKind, ProjectCounter

# Minimum digits per kind, from the examples in DATA §4 (REQ-102, TP-3, TC-0042, RUN-019,
# EV-0310, BUG-1042, RPT-008). Longer numbers are never cut.
PAD = {
    CounterKind.REQUIREMENT: 1,
    CounterKind.TEST_PLAN: 1,
    CounterKind.TEST_CASE: 4,
    CounterKind.TEST_RUN: 3,
    CounterKind.EVIDENCE: 4,
    CounterKind.DEFECT: 1,
    CounterKind.REPORT: 3,
}

_KINDS = "|".join(sorted((k.value for k in CounterKind), key=len, reverse=True))
_DISPLAY_ID = re.compile(
    rf"^(?:(?P<key>[A-Za-z]{{2,6}})-)?(?P<kind>{_KINDS})-(?P<no>\d+)$", re.IGNORECASE
)


class ParsedId(NamedTuple):
    project_key: str | None
    kind: CounterKind
    number: int


def next_number(project_id: UUID, org_id: UUID, kind: CounterKind) -> int:
    """Take the next number for this project and kind. Call inside the inserting transaction.

    The counter row is locked until that transaction ends, so two inserts can never get the
    same number, and a rollback releases the lock without using the number.
    """
    with transaction.atomic():
        counter, _ = ProjectCounter.objects.select_for_update().get_or_create(
            project_id=project_id, kind=kind, defaults={"org_id": org_id, "next_no": 1}
        )
        number = counter.next_no
        counter.next_no = number + 1
        counter.save(update_fields=["next_no", "updated_at"])
    return number


def format_display_id(kind: CounterKind, number: int, project_key: str | None = None) -> str:
    """`BUG-1042`, or `HUBE-BUG-1042` where it appears outside its project."""
    core = f"{kind.value}-{number:0{PAD[kind]}d}"
    return f"{project_key.upper()}-{core}" if project_key else core


def parse_display_id(text: str) -> ParsedId | None:
    """Read a display ID typed by a person or taken from a URL; None if it is not one."""
    match = _DISPLAY_ID.match(text.strip())
    if match is None:
        return None
    key = match["key"]
    return ParsedId(
        key.upper() if key else None, CounterKind(match["kind"].upper()), int(match["no"])
    )
