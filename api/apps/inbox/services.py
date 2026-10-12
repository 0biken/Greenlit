"""The QA Inbox (M6-03) and snoozing (M6-04).

One list per person across the projects they can see, built from the derived states. Who sees
an item follows DATA §9:
- Defects in Needs retest: their owner at once; QA leads, admins and owners once the second
  escalation time has passed (96 hours by default).
- Defects closed with a failed retest: owner and leads, at once. Critical.
- Ageing defects: owner and leads.
- Failures without a defect, and failures without evidence: whoever recorded the result.
- Stale tests: the people who test (QA engineers, leads, admins, owners).
- Requirements without tests: leads, admins and owners.
Snoozed items leave the person's Inbox until the snooze ends, and still count towards readiness.
"""

from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import Membership, Project, Role
from apps.core.policy import visible_projects
from apps.core.project_settings import project_settings
from apps.core.services import ServiceError
from apps.defects.models import Defect
from apps.inbox.derived import Item, all_items
from apps.inbox.models import Snooze
from apps.plans.models import TestCase
from apps.requirements.models import Requirement
from apps.runs.models import CaseResult, Release, ReleaseState

GROUPS = (
    "closed_failed_retest",
    "needs_retest",
    "aging_defects",
    "unfiled_failures",
    "missing_evidence",
    "stale_tests",
    "uncovered",
)
LEADS = {Role.OWNER, Role.ADMIN, Role.QA_LEAD}
TESTERS = LEADS | {Role.QA_ENGINEER}
MAX_SNOOZE = timedelta(days=90)


def _sees(item: Item, membership: Membership, now: datetime) -> bool:
    mine = item.owner_id == str(membership.user_id)
    lead = membership.role in LEADS
    if item.group == "needs_retest":
        escalate_after = project_settings(item.project)["retest_escalation_hours"][1]
        return mine or (lead and now - item.since >= timedelta(hours=escalate_after))
    if item.group in ("closed_failed_retest", "aging_defects"):
        return mine or lead
    if item.group in ("unfiled_failures", "missing_evidence"):
        return mine
    if item.group == "stale_tests":
        return membership.role in TESTERS
    if item.group == "uncovered":
        return lead
    return False


def items_for(membership: Membership, now: datetime | None = None) -> list[Item]:
    now = now or timezone.now()
    projects = visible_projects(Project.objects.all(), membership)
    items = [i for i in all_items(projects, now) if _sees(i, membership, now)]
    # Critical first, then by group, oldest first within a group.
    items.sort(key=lambda i: (not i.critical, GROUPS.index(i.group), i.since))
    return items


def _active_snoozes(membership: Membership, now: datetime) -> dict[str, Snooze]:
    rows = Snooze.objects.filter(user_id=membership.user_id, until__gt=now)
    return {f"{s.target_type}.{s.target_id}": s for s in rows}


def _serialise(item: Item, now: datetime, snooze: Snooze | None) -> dict:
    return {
        "id": item.key,
        "group": item.group,
        "critical": item.critical,
        "status": item.status,
        "display_id": item.display_id,
        "title": item.title,
        "project_key": item.project.key,
        "project_name": item.project.name,
        "age_days": item.age_days(now),
        "since": item.since,
        "next_action": item.next_action,
        "owner_name": item.owner_name,
        "snoozed_until": snooze.until if snooze else None,
        "snooze_reason": snooze.reason if snooze else None,
    }


def inbox(membership: Membership, *, snoozed: bool = False, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    items = items_for(membership, now)
    snoozes = _active_snoozes(membership, now)
    active = [i for i in items if i.key not in snoozes]
    shown = [i for i in items if i.key in snoozes] if snoozed else active
    counts = dict.fromkeys(GROUPS, 0)
    for i in active:
        counts[i.group] += 1
    projects = visible_projects(Project.objects.all(), membership)
    upcoming = (
        Release.objects.filter(
            project__in=projects, state=ReleaseState.OPEN, target_date__gte=now.date()
        )
        .select_related("project")
        .order_by("target_date")
        .first()
    )
    return {
        "items": [_serialise(i, now, snoozes.get(i.key)) for i in shown],
        "counts": counts,
        "snoozed": len(items) - len(active),
        "next_release": (
            {
                "project_key": upcoming.project.key,
                "version": upcoming.name,
                "due": upcoming.target_date,
            }
            if upcoming
            else None
        ),
    }


def _target(membership: Membership, key: str) -> tuple[str, UUID]:
    """The record an Inbox item stands for. It must be in a project you can see; anything
    else is simply not found. A snooze only changes your own Inbox, so any record you can see
    may be snoozed."""
    kind, _, raw = key.partition(".")
    try:
        target_id = UUID(raw)
    except ValueError as error:
        raise ServiceError("Not found.", code="not_found") from error
    projects = visible_projects(Project.objects.all(), membership)
    lookups = {
        "defect": Defect.objects.filter(project__in=projects),
        "case_result": CaseResult.objects.filter(run__project__in=projects),
        "test_case": TestCase.objects.filter(project__in=projects),
        "requirement": Requirement.objects.filter(project__in=projects),
    }
    rows = lookups.get(kind)
    if rows is None or not rows.filter(pk=target_id).exists():
        raise ServiceError("Not found.", code="not_found")
    return kind, target_id


def snooze(membership: Membership, key: str, until: datetime, reason: str) -> Snooze:
    kind, target_id = _target(membership, key)
    now = timezone.now()
    if not reason.strip():
        raise ServiceError("Give a reason for snoozing it.")
    if until <= now or until - now > MAX_SNOOZE:
        raise ServiceError("Snooze until a date within the next 90 days.")
    with transaction.atomic():
        Snooze.objects.filter(
            user_id=membership.user_id, target_type=kind, target_id=target_id
        ).delete()
        row = Snooze.objects.create(
            org_id=membership.org_id,
            user_id=membership.user_id,
            target_type=kind,
            target_id=target_id,
            until=until,
            reason=reason.strip(),
            created_by=membership.user,
        )
        audit.record(
            "inbox.snoozed",
            kind,
            target_id,
            actor=membership.user,
            after={"until": until.isoformat()},
        )
    return row


def unsnooze(membership: Membership, key: str) -> None:
    """Bring an item back. Nothing to do if it was not snoozed."""
    kind, target_id = _target(membership, key)
    rows = Snooze.objects.filter(user_id=membership.user_id, target_type=kind, target_id=target_id)
    if not rows.exists():
        return
    with transaction.atomic():
        rows.delete()  # soft delete keeps the history
        audit.record("inbox.unsnoozed", kind, target_id, actor=membership.user)
