"""Derived states (DATA §9, M6-01), computed from stored rows and never typed in by hand.

One function per state. Each takes the projects to look in and returns `Item`s; who sees which
item is decided in `apps.inbox.services`. These are ORM queries run when a page loads; they can
become database views later without changing their callers (docs/derived-states.md).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db.models import Exists, F, Max, OuterRef, QuerySet

from apps.core.choices import ReviewState
from apps.core.models import CounterKind, Project
from apps.core.numbering import format_display_id
from apps.core.project_settings import project_settings
from apps.defects.models import Defect, QaStatus, TrackerStatus
from apps.plans.models import CaseRequirement, PlanVersionCase, TestPlan
from apps.requirements.models import Requirement
from apps.runs.models import CaseResult, EvidenceLink, EvidenceTarget, Outcome

TERMINAL_QA = (QaStatus.VERIFIED, QaStatus.WONT_FIX, QaStatus.DEFERRED)


@dataclass
class Item:
    group: str
    target_type: str
    target_id: str
    status: str  # a StatusChip status in the web app
    display_id: str
    title: str
    project: Project
    since: datetime
    next_action: str
    critical: bool = False
    owner_id: str | None = None  # who it belongs to: defect owner or result recorder
    owner_name: str | None = None
    severity: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.target_type}.{self.target_id}"

    def age_days(self, now: datetime) -> int:
        return max((now - self.since).days, 0)


def _defect_item(
    d: Defect, group: str, status: str, since: datetime, action: str, critical=False
) -> Item:
    return Item(
        group=group,
        target_type="defect",
        target_id=str(d.pk),
        status=status,
        display_id=format_display_id(CounterKind.DEFECT, d.display_no),
        title=d.title,
        project=d.project,
        since=since,
        next_action=action,
        critical=critical,
        owner_id=str(d.owner_id) if d.owner_id else None,
        owner_name=(d.owner.name or d.owner.email) if d.owner else None,
        severity=d.severity,
    )


def _defects(projects: QuerySet[Project]) -> QuerySet[Defect]:
    return Defect.objects.filter(
        project__in=projects, review_state=ReviewState.ACCEPTED
    ).select_related("project", "owner")


def needs_retest(projects: QuerySet[Project]) -> list[Item]:
    """Tracker says fixed or closed; QA has not retested it."""
    rows = _defects(projects).filter(
        tracker_status__in=(TrackerStatus.FIXED, TrackerStatus.CLOSED),
        qa_status=QaStatus.NOT_RETESTED,
    )
    return [
        _defect_item(
            d, "needs_retest", "needs_retest", d.fixed_at or d.closed_at or d.qa_status_at, "retest"
        )
        for d in rows
    ]


def closed_failed_retest(projects: QuerySet[Project]) -> list[Item]:
    """Closed in the tracker, but the latest retest failed. Critical."""
    rows = _defects(projects).filter(
        tracker_status=TrackerStatus.CLOSED, qa_status=QaStatus.RETEST_FAILED
    )
    return [
        _defect_item(
            d, "closed_failed_retest", "retest_failed", d.closed_at or d.qa_status_at, "open", True
        )
        for d in rows
    ]


def aging(projects: QuerySet[Project], now: datetime) -> list[Item]:
    """Open longer than its severity allows (project setting `aging_days`)."""
    rows = (
        _defects(projects)
        .filter(tracker_status__in=(TrackerStatus.OPEN, TrackerStatus.IN_PROGRESS))
        .exclude(qa_status__in=TERMINAL_QA)
    )
    items = []
    for d in rows:
        limit = project_settings(d.project)["aging_days"][d.severity]
        if now - d.created_at > timedelta(days=limit):
            status = "retest_failed" if d.qa_status == QaStatus.RETEST_FAILED else "open"
            items.append(_defect_item(d, "aging_defects", status, d.created_at, "open"))
    return items


def _failed_results(projects: QuerySet[Project]) -> QuerySet[CaseResult]:
    return CaseResult.objects.filter(
        run__project__in=projects, outcome=Outcome.FAILED
    ).select_related("run__project", "case_revision__test_case", "recorded_by")


def _result_item(r: CaseResult, group: str, action: str) -> Item:
    return Item(
        group=group,
        target_type="case_result",
        target_id=str(r.pk),
        status="failed",
        display_id=format_display_id(CounterKind.TEST_CASE, r.case_revision.test_case.display_no),
        title=r.case_revision.title,
        project=r.run.project,
        since=r.recorded_at or r.updated_at,
        next_action=action,
        owner_id=str(r.recorded_by_id) if r.recorded_by_id else None,
        owner_name=(r.recorded_by.name or r.recorded_by.email) if r.recorded_by else None,
        extra={"run": format_display_id(CounterKind.TEST_RUN, r.run.display_no)},
    )


def unfiled_failures(projects: QuerySet[Project]) -> list[Item]:
    """A failed result with no defect pointing at it."""
    rows = _failed_results(projects).filter(
        ~Exists(Defect.objects.filter(found_in_result=OuterRef("pk")))
    )
    return [_result_item(r, "unfiled_failures", "file_defect") for r in rows]


def missing_evidence(projects: QuerySet[Project]) -> list[Item]:
    """A failed result with no evidence linked."""
    linked = EvidenceLink.objects.filter(
        target_type=EvidenceTarget.CASE_RESULT, target_id=OuterRef("pk")
    )
    rows = _failed_results(projects).filter(~Exists(linked))
    return [_result_item(r, "missing_evidence", "attach_evidence") for r in rows]


def current_case_pointers(projects: QuerySet[Project]) -> QuerySet[PlanVersionCase]:
    """Accepted case revisions in each plan's current (published) version."""
    current = TestPlan.objects.filter(project__in=projects).values("current_version_id")
    return PlanVersionCase.objects.filter(
        plan_version_id__in=current, case_revision__review_state=ReviewState.ACCEPTED
    ).select_related("case_revision__test_case__project")


def stale(projects: QuerySet[Project], now: datetime) -> list[Item]:
    """No passed or failed result in `stale_after_days`, or a linked requirement has changed
    since the case was written (`revision` above `req_revision_seen`)."""
    items = []
    for pointer in current_case_pointers(projects).filter(
        case_revision__test_case__retired_at__isnull=True
    ):
        revision = pointer.case_revision
        case = revision.test_case
        project = case.project
        last = CaseResult.objects.filter(
            case_revision__test_case=case, outcome__in=(Outcome.PASSED, Outcome.FAILED)
        ).aggregate(at=Max("recorded_at"))["at"]
        limit = timedelta(days=project_settings(project)["stale_after_days"])
        changed = CaseRequirement.objects.filter(
            case_revision=revision, req_revision_seen__lt=F("requirement__revision")
        ).exists()
        too_old = last is None or now - last > limit
        if not (changed or too_old):
            continue
        items.append(
            Item(
                group="stale_tests",
                target_type="test_case",
                target_id=str(case.pk),
                status="stale",
                display_id=format_display_id(CounterKind.TEST_CASE, case.display_no),
                title=revision.title,
                project=project,
                since=last or case.created_at,
                next_action="run",
                extra={"requirement_changed": changed},
            )
        )
    return items


def covered_requirement_ids(projects: QuerySet[Project]) -> set:
    revisions = current_case_pointers(projects).values("case_revision_id")
    return set(
        CaseRequirement.objects.filter(case_revision_id__in=revisions).values_list(
            "requirement_id", flat=True
        )
    )


def uncovered(projects: QuerySet[Project]) -> list[Item]:
    """Accepted requirements with no accepted case in any plan's current version."""
    covered = covered_requirement_ids(projects)
    rows = (
        Requirement.objects.filter(project__in=projects, review_state=ReviewState.ACCEPTED)
        .exclude(pk__in=covered)
        .select_related("project")
    )
    return [
        Item(
            group="uncovered",
            target_type="requirement",
            target_id=str(r.pk),
            status="uncovered",
            display_id=format_display_id(CounterKind.REQUIREMENT, r.display_no),
            title=r.title,
            project=r.project,
            since=r.created_at,
            next_action="add_case",
            severity=r.priority,
        )
        for r in rows
    ]


def all_items(projects: QuerySet[Project], now: datetime) -> list[Item]:
    return [
        *closed_failed_retest(projects),
        *needs_retest(projects),
        *aging(projects, now),
        *unfiled_failures(projects),
        *missing_evidence(projects),
        *stale(projects, now),
        *uncovered(projects),
    ]
