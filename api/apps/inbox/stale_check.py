"""The nightly stale check (M6-02; FR-TC-05; ARCH §6).

Staleness is derived, never stored: `derived.stale` reads the last passed or failed result and
the requirement revisions each time, so it cannot drift from the records. This pass therefore
marks nothing. It counts what is stale per project so the nightly job can report it (and
monitoring can alert on it), and it runs inside the organisation's scope like every job.

People are not emailed from here. Stale tests are an Inbox group and are carried by the daily
digest (`reminders.run_digest`), so a second message would only repeat it.
"""

from datetime import datetime

from django.utils import timezone

from apps.core.models import Project
from apps.inbox import derived


def run_stale_check(org_id, now: datetime | None = None) -> dict[str, int]:
    """Stale test cases per project key for one organisation (projects with none are omitted)."""
    now = now or timezone.now()
    counts: dict[str, int] = {}
    for item in derived.stale(Project.objects.filter(org_id=org_id), now):
        counts[item.project.key] = counts.get(item.project.key, 0) + 1
    return counts
