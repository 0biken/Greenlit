"""Reminders and the daily digest (M6-05, M6-06, M6-07; FR-INB-02, FR-INB-03).

`run_reminders` and `run_digest` each work on one organisation, inside its scope; the job
handlers in `jobs.py` call them. What people are told:

- A fix waiting for its retest past the first escalation time (48 hours by default): the
  item rises to the top of the owner's Inbox. No email of its own; the digest carries it.
- Past the second time (96 hours): it appears in the project's leads' Inboxes as well.
- A defect closed while its retest had failed: owner and leads are told at once, by email.
  This is the one thing that never waits for the digest.
- The digest: one email a day per person, at 07:00 in their own time zone, only if something
  is open for them. It carries IDs, titles and links, never document text (SEC §10).

Each of these is recorded in `notification`, and the unique rule there makes sure nobody is
told the same thing twice, however often the job runs. A record and its email succeed or fail
together: if the email cannot be sent the record is not kept, and the job's retry sends it.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import Membership, MembershipStatus, Project, User
from apps.core.policy import visible_projects
from apps.core.project_settings import project_settings
from apps.inbox import derived
from apps.inbox.derived import Item
from apps.inbox.models import Notification, NotificationLevel, Snooze
from apps.inbox.services import GROUPS, LEADS, items_for

DIGEST_HOUR = 7
DIGEST_WINDOW_HOURS = 3  # a late or retried job still sends it, but not in the afternoon
GROUP_TITLES = {
    "closed_failed_retest": "Closed with a failed retest",
    "needs_retest": "Fixed but not retested",
    "aging_defects": "Ageing defects",
    "unfiled_failures": "Failures without a defect",
    "missing_evidence": "Missing evidence",
    "stale_tests": "Stale tests",
    "uncovered": "Requirements without tests",
}
KIND_PATH = {"BUG": "bugs", "TC": "cases", "REQ": "requirements"}


def _link(item: Item) -> str:
    base = f"{settings.FRONTEND_URL}/{item.project.key.lower()}"
    if item.target_type == "case_result" and "run" in item.extra:
        # A failed result is worked on in its run, not on the test case's own page.
        return f"{base}/runs/{int(item.extra['run'].rpartition('-')[2])}"
    prefix, _, number = item.display_id.partition("-")
    path = KIND_PATH.get(prefix, "records")
    return f"{base}/{path}/{int(number)}"


def _notify_once(
    org_id,
    user_id,
    level: str,
    target_type: str,
    target_id,
    cycle: str,
    now: datetime,
    email: Callable[[], None] | None = None,
) -> bool:
    """Record that this person was told, and send `email` with it. False if they already were.

    The row and the email stand or fall together: if sending fails, the row is rolled back and
    the error goes up to the job, whose retry tells them then. So an alert may rarely arrive
    twice, but it is never recorded as sent when it was not."""
    try:
        with transaction.atomic():
            Notification.objects.create(
                org_id=org_id,
                user_id=user_id,
                level=level,
                target_type=target_type,
                target_id=target_id,
                cycle=cycle,
                sent_at=now,
            )
            if email is not None:
                email()
    except IntegrityError:
        return False
    return True


def _notify_item(user_id, level: str, item: Item, now: datetime, email=None) -> bool:
    return _notify_once(
        item.project.org_id,
        user_id,
        level,
        item.target_type,
        item.target_id,
        item.since.isoformat(),
        now,
        email,
    )


class _Leads:
    """The leads who can see each project, looked up once per project for a whole pass."""

    def __init__(self, members: list[Membership]):
        self._leads = [m for m in members if m.role in LEADS]
        self._by_project: dict = {}

    def on(self, project: Project) -> list[Membership]:
        if project.pk not in self._by_project:
            self._by_project[project.pk] = [
                m
                for m in self._leads
                if visible_projects(Project.objects.filter(pk=project.pk), m).exists()
            ]
        return self._by_project[project.pk]


def _send(to: User, subject: str, lines: list[str]) -> None:
    send_mail(subject, "\n".join(lines), None, [to.email])


def _critical_alert(member: Membership, item: Item) -> None:
    _send(
        member.user,
        f"{item.project.key}-{item.display_id} was closed, but its retest failed",
        [
            f"{item.display_id} {item.title}",
            f"Project: {item.project.name}",
            "",
            "It is marked closed in the tracker, but the last retest failed.",
            "It blocks the release until it is fixed and retested, or a lead decides.",
            "",
            _link(item),
        ],
    )


def run_reminders(org_id, now: datetime | None = None) -> dict[str, int]:
    """One pass for one organisation. Returns how many people were told at each level."""
    now = now or timezone.now()
    projects = Project.objects.filter(org_id=org_id)
    members = list(Membership.objects.filter(status=MembershipStatus.ACTIVE).select_related("user"))
    by_user = {str(m.user_id): m for m in members}
    leads = _Leads(members)
    told = {"48h": 0, "96h": 0, "critical": 0}

    for item in derived.needs_retest(projects):
        first, second = project_settings(item.project)["retest_escalation_hours"]
        waited = now - item.since
        if waited >= timedelta(hours=first) and item.owner_id in by_user:
            told["48h"] += _notify_item(item.owner_id, NotificationLevel.FIRST, item, now)
        if waited >= timedelta(hours=second):
            for lead in leads.on(item.project):
                told["96h"] += _notify_item(lead.user_id, NotificationLevel.SECOND, item, now)

    for item in derived.closed_failed_retest(projects):
        people = {m.user_id: m for m in leads.on(item.project)}
        if item.owner_id in by_user:
            people[by_user[item.owner_id].user_id] = by_user[item.owner_id]
        for member in people.values():
            told["critical"] += _notify_item(
                member.user_id,
                NotificationLevel.CRITICAL,
                item,
                now,
                email=partial(_critical_alert, member, item),
            )
    return told


def _local_now(user: User, now: datetime) -> datetime:
    try:
        return now.astimezone(ZoneInfo(user.time_zone or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        return now.astimezone(ZoneInfo("UTC"))


def digest_lines(items: list[Item], now: datetime) -> list[str]:
    """The body of a digest: IDs, titles, ages and links, grouped as the Inbox groups them."""
    lines = [
        f"{len(items)} {'item needs' if len(items) == 1 else 'items need'} you in Greenlit.",
        "",
    ]
    for group in GROUPS:
        in_group = [i for i in items if i.group == group]
        if not in_group:
            continue
        lines.append(f"{GROUP_TITLES[group]} ({len(in_group)})")
        for item in in_group:
            days = item.age_days(now)
            age = "today" if days == 0 else f"{days} day{'' if days == 1 else 's'}"
            lines.append(f"  {item.project.key}-{item.display_id}  {item.title}  ({age})")
            lines.append(f"  {_link(item)}")
        lines.append("")
    lines.append(f"Your Inbox: {settings.FRONTEND_URL}/inbox")
    return lines


def run_digest(org_id, now: datetime | None = None) -> int:
    """Send today's digest to everyone in this organisation whose morning it is and who has
    something open. Returns how many emails were queued."""
    now = now or timezone.now()
    sent = 0
    members = Membership.objects.filter(status=MembershipStatus.ACTIVE).select_related("user")
    for member in members:
        local = _local_now(member.user, now)
        if not DIGEST_HOUR <= local.hour < DIGEST_HOUR + DIGEST_WINDOW_HOURS:
            continue
        snoozed = {
            f"{s.target_type}.{s.target_id}"
            for s in Snooze.objects.filter(user_id=member.user_id, until__gt=now)
        }
        items = [i for i in items_for(member, now) if i.key not in snoozed]
        if not items:
            continue  # nobody gets an empty digest
        day = local.date().isoformat()
        count = len(items)
        subject = f"Greenlit: {count} {'item needs' if count == 1 else 'items need'} you"
        sent += _notify_once(
            org_id,
            member.user_id,
            NotificationLevel.DIGEST,
            "digest",
            member.user_id,
            day,
            now,
            email=partial(_send, member.user, subject, digest_lines(items, now)),
        )
    return sent
