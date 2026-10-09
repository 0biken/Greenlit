"""Per-project thresholds (DATA §3 `project.settings`, spec gap G-08).

Stored as JSON on the project; anything missing falls back to the defaults below, which come
from the specs. Later modules read them through `project_settings(project)`.
"""

from copy import deepcopy

from apps.core.services import ServiceError

DEFAULTS: dict = {
    # A test case with no passed or failed result for this long is Stale (FR-TC-05).
    "stale_after_days": 30,
    # A defect in Needs retest escalates to its owner, then also to the QA lead (FR-INB-02).
    "retest_escalation_hours": [48, 96],
    # An open defect older than this, by severity, is Aging (DATA §9, proposed).
    "aging_days": {"critical": 2, "high": 7, "medium": 14, "low": 30},
    # The person who set a defect to Fixed cannot be the only one to verify it (SEC §4, proposed).
    "fixer_cannot_verify": True,
}
SEVERITIES = ("critical", "high", "medium", "low")


def project_settings(project) -> dict:
    """The project's settings, with defaults for anything it has not set."""
    merged = deepcopy(DEFAULTS)
    merged.update(project.settings or {})
    return merged


def _whole_number(value, low: int, high: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ServiceError(f"{what} must be a whole number from {low} to {high}.")
    return value


def clean_settings(current: dict, changes: dict) -> dict:
    """Apply `changes` over `current` and return a complete, valid set, or raise ServiceError."""
    unknown = set(changes) - set(DEFAULTS)
    if unknown:
        raise ServiceError(f"Unknown setting: {', '.join(sorted(unknown))}.")
    merged = deepcopy(DEFAULTS)
    merged.update(current or {})
    merged.update(changes)

    merged["stale_after_days"] = _whole_number(
        merged["stale_after_days"], 1, 365, "Days before a test is stale"
    )

    hours = merged["retest_escalation_hours"]
    if not isinstance(hours, list) or len(hours) != 2:
        raise ServiceError("Retest escalation needs two times: to the owner, then to the QA lead.")
    first, second = (_whole_number(h, 1, 720, "Escalation hours") for h in hours)
    if second <= first:
        raise ServiceError("The QA lead escalation must come after the owner escalation.")
    merged["retest_escalation_hours"] = [first, second]

    aging = merged["aging_days"]
    if not isinstance(aging, dict) or set(aging) != set(SEVERITIES):
        raise ServiceError("Aging needs a number of days for critical, high, medium and low.")
    merged["aging_days"] = {
        s: _whole_number(aging[s], 1, 365, f"Aging days for {s}") for s in SEVERITIES
    }

    if not isinstance(merged["fixer_cannot_verify"], bool):
        raise ServiceError("fixer_cannot_verify must be true or false.")
    return merged
