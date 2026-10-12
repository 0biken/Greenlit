"""How much of its AI allowance an organisation has used (AI §8, AI-06).

Stand-ins until real costs are measured: a credit is `AI_TOKENS_PER_CREDIT` tokens, the period
is the calendar month, and an organisation with no allowance of its own gets
`AI_DEFAULT_ALLOWANCE`. Only AI drafting stops at the cap; nothing else in Greenlit is affected.
"""

from dataclasses import dataclass
from datetime import datetime
from functools import partial
from math import ceil

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Sum
from django.utils import timezone

from apps.ai.models import AiCall, CallOutcome
from apps.core.models import Membership, MembershipStatus, Organisation, Role
from apps.core.services import ServiceError

WARN_AT = 0.8


@dataclass(frozen=True)
class Usage:
    used: int
    allowance: int
    resets_on: datetime

    @property
    def left(self) -> int:
        return max(self.allowance - self.used, 0)


def _period_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_period(now: datetime) -> datetime:
    start = _period_start(now)
    return (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )


def usage(org_id, now: datetime | None = None) -> Usage:
    now = now or timezone.now()
    totals = (
        AiCall.objects.filter(created_at__gte=_period_start(now))
        .exclude(outcome=CallOutcome.REUSED)
        .aggregate(tokens_in=Sum("tokens_in"), tokens_out=Sum("tokens_out"))
    )
    tokens = (totals["tokens_in"] or 0) + (totals["tokens_out"] or 0)
    organisation = Organisation.objects.get(pk=org_id)
    return Usage(
        used=ceil(tokens / settings.AI_TOKENS_PER_CREDIT),
        allowance=organisation.ai_allowance or settings.AI_DEFAULT_ALLOWANCE,
        resets_on=_next_period(now),
    )


class AllowanceUsedUp(ServiceError):
    def __init__(self, resets_on: datetime):
        day = f"{resets_on.day} {resets_on:%B}"
        super().__init__(
            f"Your AI allowance for this month is used. Drafts resume on {day}, "
            "or an owner can top up.",
            code="allowance",
        )


def ensure_allowance(org_id, now: datetime | None = None) -> Usage:
    """Raise `AllowanceUsedUp` if this organisation may not start more AI work this period."""
    current = usage(org_id, now)
    if current.used >= current.allowance:
        raise AllowanceUsedUp(current.resets_on)
    return current


def _warn(email: str, current: Usage) -> None:
    send_mail(
        "Greenlit: 80% of this month's AI allowance is used",
        f"{current.used} of {current.allowance} AI credits are used. At 100%, AI drafting "
        f"stops until {current.resets_on.day} {current.resets_on:%B}; everything else keeps "
        "working. An owner can top up.",
        None,
        [email],
    )


def warn_if_nearly_used(org_id, now: datetime | None = None) -> bool:
    """Tell owners and admins, once a month, when 80% of the allowance is used (AI §8)."""
    from apps.inbox.models import NotificationLevel
    from apps.inbox.reminders import notify_once

    now = now or timezone.now()
    current = usage(org_id, now)
    if current.allowance == 0 or current.used < WARN_AT * current.allowance:
        return False
    told = False
    people = Membership.objects.filter(
        status=MembershipStatus.ACTIVE, role__in=(Role.OWNER, Role.ADMIN)
    ).select_related("user")
    for member in people:
        told |= notify_once(
            org_id,
            member.user_id,
            NotificationLevel.AI_80,
            "organisation",
            org_id,
            f"{now:%Y-%m}",
            now,
            email=partial(_warn, member.user.email, current),
        )
    return told
