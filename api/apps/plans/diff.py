"""Compare two versions of a plan (M3-06, FR-TC-03; DATA "Versioning", "Diff").

The two versions' pointers are matched by test case. A case in both that points at the same
revision is unchanged; one that points at different revisions is compared field by field, and
its steps as an ordered list, so a step that only changed place shows as moved.
"""

from difflib import SequenceMatcher

from apps.core.models import CounterKind
from apps.core.numbering import format_display_id
from apps.plans.models import CaseRevision, PlanVersion, PlanVersionCase

TEXT_FIELDS = ("title", "preconditions", "expected", "priority")


def diff_steps(old: list[str], new: list[str]) -> list[dict]:
    """Every step of either list, in reading order, as same, added, removed or moved.
    `before` and `after` are 1-based step numbers in the old and new lists."""
    rows: list[dict] = []
    removed: list[int] = []
    added: list[int] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if op == "equal":
            rows += [
                {"op": "same", "text": old[i], "before": i + 1, "after": j + 1}
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            ]
        else:
            removed += range(i1, i2)
            added += range(j1, j2)
    for i in removed:
        match = next((j for j in added if new[j] == old[i]), None)
        if match is None:
            rows.append({"op": "removed", "text": old[i], "before": i + 1, "after": None})
        else:
            added.remove(match)
            rows.append({"op": "moved", "text": old[i], "before": i + 1, "after": match + 1})
    rows += [{"op": "added", "text": new[j], "before": None, "after": j + 1} for j in added]
    # New order first; a removed step sits where it used to be.
    rows.sort(key=lambda r: (r["after"] or r["before"], r["after"] is not None))
    return rows


def _pointers(version: PlanVersion) -> dict:
    rows = (
        PlanVersionCase.objects.filter(plan_version=version)
        .select_related("case_revision__test_case")
        .order_by("position")
    )
    return {p.case_revision.test_case_id: p.case_revision for p in rows}


def _case(revision: CaseRevision) -> dict:
    return {
        "case": format_display_id(CounterKind.TEST_CASE, revision.test_case.display_no),
        "number": revision.test_case.display_no,
        "title": revision.title,
    }


def diff_versions(old: PlanVersion, new: PlanVersion, include_unchanged: bool = False) -> dict:
    before, after = _pointers(old), _pointers(new)
    changed, unchanged = [], []
    for case_id, revision in after.items():
        previous = before.get(case_id)
        if previous is None:
            continue
        if previous.pk == revision.pk:
            unchanged.append(_case(revision))
            continue
        changes = [
            {"field": name, "before": getattr(previous, name), "after": getattr(revision, name)}
            for name in TEXT_FIELDS
            if getattr(previous, name) != getattr(revision, name)
        ]
        steps = diff_steps(list(previous.steps), list(revision.steps))
        steps_changed = any(row["op"] != "same" for row in steps)
        if not changes and not steps_changed:
            # A new revision with the same content (only its requirement links were renewed).
            unchanged.append(_case(revision))
            continue
        changed.append(
            {**_case(revision), "changes": changes, "steps": steps if steps_changed else []}
        )
    return {
        "added": [_case(r) for case_id, r in after.items() if case_id not in before],
        "removed": [_case(r) for case_id, r in before.items() if case_id not in after],
        "changed": changed,
        "unchanged_count": len(unchanged),
        "unchanged": unchanged if include_unchanged else [],
    }
