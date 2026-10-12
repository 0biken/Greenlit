"""Reminders and the daily digest (M6-05, M6-06, M6-07; FR-INB-02, FR-INB-03).

`run_reminders` and `run_digest` each work on one organisation, inside its scope; the job
handlers in `jobs.py` call them. What people are told:

- A fix waiting for its retest past the first escalation time (48 hours by default): the
  owner is reminded, and the item rises to the top of their Inbox.
- Past the second time (96 hours): the project's leads are told as well.
- A defect closed while its retest had failed: owner and leads are told at once, by email.
  This is the one thing that never waits for the digest.
- The digest: one email a day per person, at 07:00 in their own time zone, only if something
  is open for them. It carries IDs, titles and links, never document text (SEC §10).

Each of these is recorded in `notification` first, and the unique rule there makes sure nobody
is told the same thing twice, however often the job runs.
"""

from datetime import datetime, timedelta
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
    prefix, _, number = item.display_id.partition("-")
    path = KIND_PATH.get(prefix, "records")
    return f"{settings.FRONTEND_URL}/{item.project.key.lower()}/{path}/{int(number)}"


def _notify_once(user_id, level: str, item: Item, cycle: str, now: datetime) -> bool:
    """Record that this person was told. False if they already were."""
    try:
        with transaction.atomic():
            Notification.objects.create(
                org_id=item.project.org_id,
                user_id=user_id,
                level=level,
                target_type=item.target_type,
                target_id=item.target_id,
                cycle=cycle,
                sent_at=now,
            )
    except IntegrityError:
        return False
    return True


def _leads_on(project: Project, members: list[Membership]) -> list[Membership]:
    return [
        m
        for m in members
        if m.role in LEADS and visible_projects(Project.objects.filter(pk=project.pk), m).exists()
    ]


def _send(to: User, subject: str, lines: list[str]) -> None:
    body = "\n".join(lines)
    # Sent when the surrounding work commits, so nobody is emailed about a change that was
    # rolled back.
    transaction.on_commit(lambda: send_mail(subject, body, None, [to.email]))


def run_reminders(org_id, now: datetime | None = None) -> dict[str, int]:
    """One pass for one organisation. Returns how many people were told at each level."""
    now = now or timezone.now()
    projects = Project.objects.filter(org_id=org_id)
    members = list(Membership.objects.filter(status=MembershipStatus.ACTIVE).select_related("user"))
    by_user = {str(m.user_id): m for m in members}
    told = {"48h": 0, "96h": 0, "critical": 0}

    for item in derived.needs_retest(projects):
        first, second = project_settings(item.project)["retest_escalation_hours"]
        waited = now - item.since
        cycle = item.since.isoformat()
        if waited >= timedelta(hours=first) and item.owner_id in by_user:
            told["48h"] += _notify_once(item.owner_id, NotificationLevel.FIRST, item, cycle, now)
        if waited >= timedelta(hours=second):
            for lead in _leads_on(item.project, members):
                told["96h"] += _notify_once(
                    lead.user_id, NotificationLevel.SECOND, item, cycle, now
                )

    for item in derived.closed_failed_retest(projects):
        cycle = item.since.isoformat()
        people = {m.user_id: m for m in _leads_on(item.project, members)}
        if item.owner_id in by_user:
            people[by_user[item.owner_id].user_id] = by_user[item.owner_id]
        for member in people.values():
            if _notify_once(member.user_id, NotificationLevel.CRITICAL, item, cycle, now):
                told["critical"] += 1
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
        try:
            with transaction.atomic():
                Notification.objects.create(
                    org_id=org_id,
                    user_id=member.user_id,
                    level=NotificationLevel.DIGEST,
                    target_type="digest",
                    target_id=member.user_id,
                    cycle=day,
                    sent_at=now,
                )
        except IntegrityError:
            continue  # already sent today
        count = len(items)
        subject = f"Greenlit: {count} {'item needs' if count == 1 else 'items need'} you"
        _send(member.user, subject, digest_lines(items, now))
        sent += 1
    return sent
