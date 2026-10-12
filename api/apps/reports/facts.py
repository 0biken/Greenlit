"""The facts builder (M8-03): the one function that computes what Greenlit claims about a
release. Readiness, verified coverage, the dashboard summary and the report all read from it,
so they can never disagree.

Definitions (DATA §9):
- A release is Not ready yet if it has a defect in Needs retest, an open critical defect, a
  defect closed with a failed retest, an uncovered requirement of critical priority, or an
  unfiled failure. Otherwise it is Ready.
- A requirement is verified for the release when every accepted case linked to it passed in the
  release's latest run, and every defect found against those cases is Verified, Won't fix or
  Deferred. Verified coverage = verified requirements / accepted requirements in the project.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass, field

from django.db.models import Q

from apps.core.choices import Priority, ReviewState
from apps.core.models import CounterKind, Project
from apps.core.numbering import format_display_id
from apps.defects.models import Defect, QaStatus, TrackerStatus
from apps.inbox.derived import TERMINAL_QA, covered_requirement_ids, current_case_pointers
from apps.plans.models import CaseRequirement
from apps.requirements.models import Requirement
from apps.runs.models import CaseResult, Outcome, Release, TestRun

BLOCKER_ORDER = (
    "closed_failed_retest",
    "open_critical",
    "needs_retest",
    "unfiled_failure",
    "uncovered_critical",
)


@dataclass
class Blocker:
    type: str
    display_id: str
    title: str
    since: str
    owner_name: str | None
    target_id: str


@dataclass
class RunFacts:
    display_id: str
    plan: str  # the plan title: the "area" the report groups by
    plan_version: str
    total: int
    passed: int
    failed: int
    blocked: int
    not_run: int
    failed_cases: list[str] = field(default_factory=list)
    filed_defects: list[str] = field(default_factory=list)


@dataclass
class Coverage:
    verified: int
    on_hold: int
    failed: int
    not_run: int
    total_requirements: int

    @property
    def verified_pct(self) -> int:
        return (
            round(100 * self.verified / self.total_requirements) if self.total_requirements else 0
        )


@dataclass
class Facts:
    project_key: str
    release: str
    readiness: str  # "ready" or "not_ready"
    blockers: list[Blocker]
    coverage: Coverage
    runs: list[RunFacts]
    open_defects: list[dict]
    risks: list[dict]

    def as_dict(self) -> dict:
        data = asdict(self)
        data["coverage"]["verified_pct"] = self.coverage.verified_pct
        return data


def _name(user) -> str | None:
    return (user.name or user.email) if user else None


def latest_runs(release: Release) -> list[TestRun]:
    """The latest run of each plan in the release."""
    latest: dict = {}
    for run in (
        TestRun.objects.filter(release=release)
        .select_related("plan_version__plan")
        .order_by("created_at")
    ):
        latest[run.plan_version.plan_id] = run
    return list(latest.values())


def release_defects(release: Release, runs: list[TestRun]):
    return (
        Defect.objects.filter(review_state=ReviewState.ACCEPTED)
        .filter(Q(release=release) | Q(found_in_result__run__release=release))
        .select_related("owner", "found_in_result__case_revision")
        .distinct()
    )


def build_facts(release: Release) -> Facts:
    project: Project = release.project
    projects = Project.objects.filter(pk=project.pk)
    runs = latest_runs(release)
    results = list(
        CaseResult.objects.filter(run__in=runs).select_related("case_revision__test_case", "run")
    )
    defects = list(release_defects(release, runs))

    # --- blockers ------------------------------------------------------------------------
    blockers: list[Blocker] = []

    def add(kind: str, display_id: str, title: str, since, owner, target_id) -> None:
        blockers.append(
            Blocker(kind, display_id, title, since.isoformat(), _name(owner), str(target_id))
        )

    for d in defects:
        did = format_display_id(CounterKind.DEFECT, d.display_no)
        if d.tracker_status == TrackerStatus.CLOSED and d.qa_status == QaStatus.RETEST_FAILED:
            add("closed_failed_retest", did, d.title, d.closed_at or d.qa_status_at, d.owner, d.pk)
        elif (
            d.tracker_status in (TrackerStatus.FIXED, TrackerStatus.CLOSED)
            and d.qa_status == QaStatus.NOT_RETESTED
        ):
            add("needs_retest", did, d.title, d.fixed_at or d.qa_status_at, d.owner, d.pk)
        elif (
            d.severity == Priority.CRITICAL
            and d.tracker_status in (TrackerStatus.OPEN, TrackerStatus.IN_PROGRESS)
            and d.qa_status not in TERMINAL_QA
        ):
            add("open_critical", did, d.title, d.created_at, d.owner, d.pk)

    filed_results = {d.found_in_result_id for d in defects if d.found_in_result_id}
    for r in results:
        if r.outcome == Outcome.FAILED and r.pk not in filed_results:
            # Unfiled failures count wherever their defect would be; check the whole project.
            if not Defect.objects.filter(found_in_result=r).exists():
                cid = format_display_id(CounterKind.TEST_CASE, r.case_revision.test_case.display_no)
                add(
                    "unfiled_failure",
                    cid,
                    r.case_revision.title,
                    r.recorded_at or r.updated_at,
                    r.recorded_by,
                    r.pk,
                )

    requirements = list(
        Requirement.objects.filter(project=project, review_state=ReviewState.ACCEPTED)
    )
    covered = covered_requirement_ids(projects)
    for req in requirements:
        if req.priority == Priority.CRITICAL and req.pk not in covered:
            rid = format_display_id(CounterKind.REQUIREMENT, req.display_no)
            add("uncovered_critical", rid, req.title, req.created_at, None, req.pk)

    blockers.sort(key=lambda b: (BLOCKER_ORDER.index(b.type), b.since))

    # --- verified coverage -----------------------------------------------------------------
    current_revisions = set(
        current_case_pointers(projects).values_list("case_revision_id", flat=True)
    )
    cases_by_req: dict = defaultdict(set)
    for link in CaseRequirement.objects.filter(
        case_revision_id__in=current_revisions
    ).select_related("case_revision"):
        cases_by_req[link.requirement_id].add(link.case_revision.test_case_id)
    outcome_by_case = {r.case_revision.test_case_id: r.outcome for r in results}
    defects_by_case: dict = defaultdict(list)
    for d in defects:
        if d.found_in_result_id:
            defects_by_case[d.found_in_result.case_revision.test_case_id].append(d)

    verified = on_hold = failed = not_run = 0
    for req in requirements:
        cases = cases_by_req.get(req.pk, set())
        outcomes = [outcome_by_case.get(c, Outcome.NOT_RUN) for c in cases]
        case_defects = [d for c in cases for d in defects_by_case.get(c, [])]
        if (
            cases
            and all(o == Outcome.PASSED for o in outcomes)
            and all(d.qa_status in TERMINAL_QA for d in case_defects)
        ):
            verified += 1
        elif any(o == Outcome.FAILED for o in outcomes) or any(
            d.qa_status == QaStatus.RETEST_FAILED for d in case_defects
        ):
            failed += 1
        elif any(o == Outcome.BLOCKED for o in outcomes) or (
            outcomes and all(o == Outcome.PASSED for o in outcomes)
        ):
            on_hold += 1  # blocked, or passed but a defect is still waiting for its retest
        else:
            not_run += 1
    coverage = Coverage(verified, on_hold, failed, not_run, len(requirements))

    # --- runs, open defects, risks -----------------------------------------------------------
    run_facts = []
    by_run: dict = defaultdict(list)
    for r in results:
        by_run[r.run_id].append(r)
    for run in runs:
        rs = by_run.get(run.pk, [])
        count = {o: sum(1 for r in rs if r.outcome == o) for o in Outcome.values}
        failed_rs = [r for r in rs if r.outcome == Outcome.FAILED]
        run_facts.append(
            RunFacts(
                display_id=format_display_id(CounterKind.TEST_RUN, run.display_no),
                plan=run.plan_version.plan.title,
                plan_version=run.plan_version.number,
                total=len(rs),
                passed=count[Outcome.PASSED],
                failed=count[Outcome.FAILED],
                blocked=count[Outcome.BLOCKED],
                not_run=count[Outcome.NOT_RUN],
                failed_cases=[
                    format_display_id(CounterKind.TEST_CASE, r.case_revision.test_case.display_no)
                    for r in failed_rs
                ],
                filed_defects=[
                    format_display_id(CounterKind.DEFECT, d.display_no)
                    for d in defects
                    if d.found_in_result_id in {r.pk for r in failed_rs}
                ],
            )
        )

    open_defects = [
        {
            "display_id": format_display_id(CounterKind.DEFECT, d.display_no),
            "title": d.title,
            "severity": d.severity,
            "tracker_status": d.tracker_status,
            "qa_status": d.qa_status,
        }
        for d in defects
        if d.qa_status not in TERMINAL_QA
    ]
    risks = [
        {
            "display_id": format_display_id(CounterKind.REQUIREMENT, req.display_no),
            "title": req.title,
            "kind": "uncovered",
        }
        for req in requirements
        if req.pk not in covered
    ]

    return Facts(
        project_key=project.key,
        release=release.name,
        readiness="ready" if not blockers else "not_ready",
        blockers=blockers,
        coverage=coverage,
        runs=run_facts,
        open_defects=open_defects,
        risks=risks,
    )
