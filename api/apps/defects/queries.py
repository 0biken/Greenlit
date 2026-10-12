"""Reading defects: the list and the detail page (M5-09). Writing is in `status.py`."""

from django.db.models import Case, IntegerField, Q, QuerySet, When
from django.utils import timezone

from apps.core.models import AuditEvent, CounterKind, Membership, Project, display_name
from apps.core.numbering import format_display_id
from apps.core.policy import Action, can
from apps.defects import status
from apps.defects.models import Defect, QaStatus, TrackerStatus
from apps.plans.models import CaseRequirement
from apps.runs.models import EvidenceTarget
from apps.runs.queries import evidence_for

OPEN = (TrackerStatus.OPEN, TrackerStatus.IN_PROGRESS)
FIXED_OR_CLOSED = (TrackerStatus.FIXED, TrackerStatus.CLOSED)
DECIDED = (QaStatus.WONT_FIX, QaStatus.DEFERRED)

# The list's `state` filter, in the order open work is shown.
STATES: dict[str, Q] = {
    "retest_failed": Q(qa_status=QaStatus.RETEST_FAILED),
    "needs_retest": Q(tracker_status__in=FIXED_OR_CLOSED, qa_status=QaStatus.NOT_RETESTED),
    "open": Q(tracker_status__in=OPEN, qa_status=QaStatus.NOT_RETESTED),
    "verified": Q(qa_status=QaStatus.VERIFIED),
    "decided": Q(qa_status__in=DECIDED),
}


def bug_id(defect: Defect) -> str:
    return format_display_id(CounterKind.DEFECT, defect.display_no)


def defect_list(
    project: Project, *, state: str = "", severity: str = "", release: str = "", q: str = ""
) -> QuerySet[Defect]:
    rows = Defect.objects.filter(project=project).select_related("owner", "release")
    if state in STATES:
        rows = rows.filter(STATES[state])
    if severity:
        rows = rows.filter(severity=severity)
    if release:
        rows = rows.filter(release__name=release)
    if q.strip():
        term = q.strip()
        number = term.upper().removeprefix("BUG-")
        match = Q(title__icontains=term)
        if number.isdigit():
            match |= Q(display_no=int(number))
        rows = rows.filter(match)
    # Open work first: what needs action sorts above what is settled (UX design rule 1).
    rank = Case(
        *[When(condition, then=i) for i, condition in enumerate(STATES.values())],
        default=len(STATES),
        output_field=IntegerField(),
    )
    return rows.annotate(rank=rank).order_by("rank", "-created_at")[:300]


def list_row(defect: Defect) -> dict:
    return {
        "id": defect.pk,
        "display_id": bug_id(defect),
        "title": defect.title,
        "severity": defect.severity,
        "tracker_status": defect.tracker_status,
        "qa_status": defect.qa_status,
        "shown_as": status.shown_as(defect),
        "chip": status.chip(defect),
        "owner_name": display_name(defect.owner),
        "release": defect.release.name if defect.release else None,
        "age_days": max((timezone.now() - defect.created_at).days, 0),
        "created_at": defect.created_at,
    }


HISTORY = {
    "defect.created": lambda a: "filed this defect",
    "defect.edited": lambda a: "edited " + ", ".join(a.get("fields", [])),
    "defect.status_changed": lambda a: (
        "set it to " + str(a.get("tracker_status", "")).replace("_", " ")
    ),
    "defect.reopened": lambda a: "reopened it after it was verified",
    "defect.retested": lambda a: (
        "retested it: " + ("passed" if a.get("qa_status") == QaStatus.VERIFIED else "failed")
    ),
    "defect.decided": lambda a: "marked it " + str(a.get("qa_status", "")).replace("_", " "),
}


def allowed_actions(defect: Defect, membership: Membership) -> dict:
    """What this person may do to this defect now, so the page shows only real choices."""
    role = membership.role
    can_set = can(role, Action.SET_FIXED)
    return {
        "edit": can(role, Action.WRITE_TESTING),
        "set_status": [s for s in TrackerStatus.values if s != defect.tracker_status]
        if can_set
        else [],
        "retest": can(role, Action.MARK_VERIFIED) and defect.tracker_status in FIXED_OR_CLOSED,
        "decide": can(role, Action.APPROVE_WONTFIX) and defect.qa_status not in DECIDED,
    }


def detail(defect: Defect, membership: Membership) -> dict:
    retests = list(defect.retests.select_related("tested_by").order_by("-tested_at"))
    retest_evidence = evidence_for(EvidenceTarget.RETEST, [r.pk for r in retests])
    found = None
    requirements = []
    result = defect.found_in_result
    if result is not None:
        revision = result.case_revision
        found = {
            "run": format_display_id(CounterKind.TEST_RUN, result.run.display_no),
            "run_no": result.run.display_no,
            "case": format_display_id(CounterKind.TEST_CASE, revision.test_case.display_no),
            "case_title": revision.title,
            "result_id": result.pk,
        }
        # The requirements this defect threatens: those the failed case covers (DATA §5).
        for link in CaseRequirement.objects.filter(case_revision=revision).select_related(
            "requirement"
        ):
            requirements.append(
                {
                    "display_id": format_display_id(
                        CounterKind.REQUIREMENT, link.requirement.display_no
                    ),
                    "title": link.requirement.title,
                }
            )
    events = AuditEvent.objects.filter(
        target_type="defect", target_id=str(defect.pk)
    ).select_related("actor")
    history = [
        {
            "at": e.at,
            "actor": display_name(e.actor) or "Greenlit",
            "text": HISTORY[e.action](e.after or {}),
        }
        for e in events.order_by("-at")
        if e.action in HISTORY
    ]
    decided = defect.qa_status in DECIDED
    return {
        **list_row(defect),
        "steps": defect.steps,
        "expected": defect.expected,
        "actual": defect.actual,
        "owner_id": defect.owner_id,
        "created_by": display_name(defect.created_by),
        "fixed_at": defect.fixed_at,
        "fixed_by": display_name(defect.fixed_by),
        "decision": (
            {
                "decision": defect.qa_status,
                "reason": defect.decision_reason,
                "by": display_name(defect.decided_by),
            }
            if decided
            else None
        ),
        "found_in": found,
        "requirements": requirements,
        "evidence": evidence_for(EvidenceTarget.DEFECT, [defect.pk])[defect.pk],
        "retests": [
            {
                "id": r.pk,
                "outcome": r.outcome,
                "by": display_name(r.tested_by),
                "at": r.tested_at,
                "build": r.build,
                "environment": r.environment,
                "evidence": retest_evidence[r.pk],
            }
            for r in retests
        ],
        "history": history,
        "actions": allowed_actions(defect, membership),
    }
