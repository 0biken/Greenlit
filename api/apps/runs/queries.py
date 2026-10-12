"""Reading releases, plans and runs for the run screens (M4). Writing is in `services.py`."""

from collections import defaultdict

from django.db.models import Count

from apps.core.models import CounterKind, Project, display_name
from apps.core.numbering import format_display_id
from apps.defects import status as defect_status
from apps.defects.models import Defect
from apps.plans.models import PlanVersionCase
from apps.runs.models import (
    CaseResult,
    Evidence,
    EvidenceLink,
    EvidenceTarget,
    Outcome,
    Release,
    TestRun,
)


def evidence_row(evidence: Evidence) -> dict:
    return {
        "display_id": format_display_id(CounterKind.EVIDENCE, evidence.display_no),
        "file_id": evidence.file_id,
        "name": evidence.file.original_name,
        "mime": evidence.mime,
        "state": evidence.file.state,
    }


def evidence_for(target_type: str, target_ids: list) -> dict:
    """Evidence for several records at once: {target_id: [evidence row, ...]}."""
    by_evidence: dict = defaultdict(list)
    for link in EvidenceLink.objects.filter(target_type=target_type, target_id__in=target_ids):
        by_evidence[link.evidence_id].append(link.target_id)
    out: dict = {target_id: [] for target_id in target_ids}
    for ev in (
        Evidence.objects.filter(pk__in=by_evidence).select_related("file").order_by("display_no")
    ):
        row = evidence_row(ev)
        for target_id in by_evidence[ev.pk]:
            out[target_id].append(row)
    return out


def run_id(run: TestRun) -> str:
    return format_display_id(CounterKind.TEST_RUN, run.display_no)


def releases(project: Project) -> list[dict]:
    rows = (
        Release.objects.filter(project=project)
        .annotate(run_count=Count("runs"))
        .order_by("-created_at")
    )
    return [
        {"version": r.name, "due": r.target_date, "state": r.state, "runs": r.run_count}
        for r in rows
    ]


def _counts(results) -> dict:
    counts = dict.fromkeys(Outcome.values, 0)
    for r in results:
        counts[r.outcome] += 1
    return counts


def run_row(run: TestRun, results: list[CaseResult]) -> dict:
    return {
        "display_id": run_id(run),
        "number": run.display_no,
        "plan": run.plan_version.plan.title,
        "plan_version": run.plan_version.number,
        "release": run.release.name,
        "build": run.build,
        "environment": run.environment,
        "state": run.state,
        "started_by": display_name(run.created_by),
        "started_at": run.created_at,
        "total": len(results),
        **_counts(results),
    }


def run_list(project: Project) -> list[dict]:
    runs = list(
        TestRun.objects.filter(project=project)
        .select_related("plan_version__plan", "release", "created_by")
        .order_by("-created_at")[:200]
    )
    by_run: dict = defaultdict(list)
    for result in CaseResult.objects.filter(run__in=runs).only("run_id", "outcome"):
        by_run[result.run_id].append(result)
    return [run_row(run, by_run[run.pk]) for run in runs]


def run_detail(run: TestRun) -> dict:
    positions = dict(
        PlanVersionCase.objects.filter(plan_version_id=run.plan_version_id).values_list(
            "case_revision_id", "position"
        )
    )
    results = sorted(
        CaseResult.objects.filter(run=run).select_related(
            "case_revision__test_case", "recorded_by"
        ),
        key=lambda r: positions.get(r.case_revision_id, 0),
    )
    ids = [r.pk for r in results]
    evidence = evidence_for(EvidenceTarget.CASE_RESULT, ids)
    defects: dict = defaultdict(list)
    for d in Defect.objects.filter(found_in_result_id__in=ids).order_by("display_no"):
        defects[d.found_in_result_id].append(
            {
                "display_id": format_display_id(CounterKind.DEFECT, d.display_no),
                "number": d.display_no,
                "shown_as": defect_status.shown_as(d),
                "chip": defect_status.chip(d),
            }
        )
    return {
        **run_row(run, results),
        "cases": [
            {
                "result_id": r.pk,
                "case": format_display_id(
                    CounterKind.TEST_CASE, r.case_revision.test_case.display_no
                ),
                "title": r.case_revision.title,
                "preconditions": r.case_revision.preconditions,
                "steps": r.case_revision.steps,
                "expected": r.case_revision.expected,
                "priority": r.case_revision.priority,
                "outcome": r.outcome,
                "note": r.note,
                "recorded_by": display_name(r.recorded_by),
                "recorded_at": r.recorded_at,
                "evidence": evidence[r.pk],
                "defects": defects[r.pk],
            }
            for r in results
        ],
    }
