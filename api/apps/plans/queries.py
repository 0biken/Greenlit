"""Reading plans, versions and cases for the plan screens (M3-10). Writing is in `services.py`."""

from django.db.models import Count

from apps.core.choices import ReviewState
from apps.core.models import CounterKind, Membership, Project, display_name
from apps.core.numbering import format_display_id
from apps.core.policy import Action, can
from apps.inbox import derived
from apps.plans.models import (
    CaseRequirement,
    CaseRevision,
    PlanVersion,
    PlanVersionCase,
    TestCase,
    TestPlan,
    VersionState,
)


def plan_id(plan: TestPlan) -> str:
    return format_display_id(CounterKind.TEST_PLAN, plan.display_no)


def case_id(case: TestCase) -> str:
    return format_display_id(CounterKind.TEST_CASE, case.display_no)


def _case_counts(version_ids: list) -> dict:
    return dict(
        PlanVersionCase.objects.filter(plan_version_id__in=version_ids)
        .values_list("plan_version_id")
        .annotate(n=Count("id"))
    )


def plan_list(project: Project) -> list[dict]:
    """Every plan. `version` is empty until the plan is first approved; only plans with a
    version can have a run started from them."""
    plans = list(
        TestPlan.objects.filter(project=project)
        .select_related("current_version")
        .order_by("display_no")
    )
    drafts = {
        d.plan_id: d for d in PlanVersion.objects.filter(plan__in=plans, state=VersionState.DRAFT)
    }
    counts = _case_counts(
        [p.current_version_id for p in plans if p.current_version_id]
        + [d.pk for d in drafts.values()]
    )
    waiting = waiting_drafts(plans)
    rows = []
    for p in plans:
        draft = drafts.get(p.pk)
        shown = p.current_version_id or (draft.pk if draft else None)
        rows.append(
            {
                "display_id": plan_id(p),
                "number": p.display_no,
                "title": p.title,
                "version": p.current_version.number if p.current_version else None,
                "cases": counts.get(shown, 0),
                "has_draft": draft is not None,
                "draft_submitted": bool(draft and draft.submitted_at),
                "case_drafts": waiting.get(str(p.pk), 0),
            }
        )
    return rows


def plan_detail(plan: TestPlan, membership: Membership) -> dict:
    versions = list(
        PlanVersion.objects.filter(plan=plan)
        .select_related("approved_by", "submitted_by")
        .order_by("-created_at")
    )
    counts = _case_counts([v.pk for v in versions])
    draft = next((v for v in versions if v.state == VersionState.DRAFT), None)
    role = membership.role
    uncovered = derived.uncovered(Project.objects.filter(pk=plan.project_id))
    return {
        "display_id": plan_id(plan),
        "number": plan.display_no,
        "title": plan.title,
        "scope": plan.scope,
        "case_drafts": waiting_drafts([plan]).get(str(plan.pk), 0),
        "version": plan.current_version.number if plan.current_version else None,
        "versions": [
            {
                "number": v.number,
                "state": v.state,
                "cases": counts.get(v.pk, 0),
                "approved_by": display_name(v.approved_by),
                "approved_at": v.approved_at,
            }
            for v in versions
            if v.state != VersionState.DRAFT
        ],
        "draft": (
            {
                "cases": counts.get(draft.pk, 0),
                "submitted_by": display_name(draft.submitted_by),
                "submitted_at": draft.submitted_at,
            }
            if draft
            else None
        ),
        # FR-PLAN-06: accepted requirements that no accepted case in a current version covers.
        "uncovered": [
            {"display_id": i.display_id, "title": i.title, "priority": i.severity}
            for i in sorted(uncovered, key=lambda i: i.display_id)
        ],
        "actions": {
            "edit": can(role, Action.WRITE_TESTING),
            "approve": can(role, Action.APPROVE_PLAN),
        },
    }


def _requirements(revision_ids: list) -> dict:
    """{case_revision_id: [requirement row, ...]}"""
    out: dict = {rid: [] for rid in revision_ids}
    links = CaseRequirement.objects.filter(case_revision_id__in=revision_ids).select_related(
        "requirement"
    )
    for link in links.order_by("requirement__display_no"):
        out[link.case_revision_id].append(
            {
                "display_id": format_display_id(
                    CounterKind.REQUIREMENT, link.requirement.display_no
                ),
                "number": link.requirement.display_no,
                "title": link.requirement.title,
                "stale": link.req_revision_seen < link.requirement.revision,
            }
        )
    return out


def _case_row(revision: CaseRevision, requirements: list) -> dict:
    return {
        "case": case_id(revision.test_case),
        "number": revision.test_case.display_no,
        "revision": revision.rev_no,
        "title": revision.title,
        "preconditions": revision.preconditions,
        "steps": revision.steps,
        "expected": revision.expected,
        "priority": revision.priority,
        "requirements": requirements,
    }


def version_detail(version: PlanVersion) -> dict:
    pointers = list(
        PlanVersionCase.objects.filter(plan_version=version)
        .select_related("case_revision__test_case")
        .order_by("position")
    )
    requirements = _requirements([p.case_revision_id for p in pointers])
    return {
        "number": version.number,
        "state": version.state,
        "cases": [_case_row(p.case_revision, requirements[p.case_revision_id]) for p in pointers],
    }


def case_detail(case: TestCase) -> dict:
    """A test case as it stands: its current content, where it is used and how it last went."""
    from apps.runs.models import CaseResult

    pointers = list(
        PlanVersionCase.objects.filter(
            case_revision__test_case=case,
            plan_version__state__in=(VersionState.PUBLISHED, VersionState.DRAFT),
        ).select_related("plan_version__plan", "case_revision")
    )
    published = [p for p in pointers if p.plan_version.state == VersionState.PUBLISHED]
    revisions = list(
        CaseRevision.objects.filter(test_case=case)
        .select_related("created_by", "test_case")
        .order_by("-rev_no")
    )
    accepted = [r for r in revisions if r.review_state == ReviewState.ACCEPTED]
    # What a tester would run today: the published revision, else the newest.
    current = published[0].case_revision if published else (accepted or revisions)[0]
    current.test_case = case
    results = (
        CaseResult.objects.filter(case_revision__test_case=case, recorded_at__isnull=False)
        .select_related("run", "case_revision")
        .order_by("-recorded_at")[:10]
    )
    return {
        **_case_row(current, _requirements([current.pk])[current.pk]),
        "retired": case.retired_at is not None,
        "plans": [
            {
                "display_id": plan_id(p.plan_version.plan),
                "number": p.plan_version.plan.display_no,
                "title": p.plan_version.plan.title,
                "version": p.plan_version.number or None,
                "revision": p.case_revision.rev_no,
            }
            for p in sorted(
                pointers, key=lambda p: (p.plan_version.plan.display_no, p.plan_version.state)
            )
        ],
        "revisions": [
            {
                "revision": r.rev_no,
                "title": r.title,
                "at": r.created_at,
                "by": display_name(r.created_by),
            }
            for r in revisions
        ],
        "results": [
            {
                "run": format_display_id(CounterKind.TEST_RUN, r.run.display_no),
                "run_no": r.run.display_no,
                "outcome": r.outcome,
                "at": r.recorded_at,
                "revision": r.case_revision.rev_no,
            }
            for r in results
        ],
    }


def waiting_drafts(plans: list[TestPlan]) -> dict:
    """{plan id: how many AI-drafted cases wait for review}"""
    from apps.ai.models import AiDraft

    counts: dict = {}
    rows = AiDraft.objects.filter(
        target_type="case_revision", decision="", flags__plan__in=[str(p.pk) for p in plans]
    )
    for plan_id in rows.values_list("flags__plan", flat=True):
        counts[plan_id] = counts.get(plan_id, 0) + 1
    return counts


def case_drafts(plan: TestPlan, membership: Membership) -> dict:
    """Everything the case review screen shows for one plan: the drafts with the requirements
    each covers, what the AI could not answer, and the progress of a drafting job."""
    from apps.ai import usage
    from apps.ai.models import AiCall, AiDraft, AiDroppedItem
    from apps.core.jobs import describe
    from apps.core.models import Job
    from apps.inbox.services import LEADS

    notes = {
        n.target_id: n
        for n in AiDraft.objects.filter(target_type="case_revision", flags__plan=str(plan.pk))
    }
    revisions = list(
        CaseRevision.objects.filter(pk__in=notes)
        .select_related("test_case")
        .order_by("test_case__display_no")
    )
    links: dict = {r.pk: [] for r in revisions}
    for link in (
        CaseRequirement.objects.filter(case_revision__in=revisions)
        .select_related("requirement")
        .order_by("requirement__display_no")
    ):
        links[link.case_revision_id].append(
            {
                "display_id": format_display_id(
                    CounterKind.REQUIREMENT, link.requirement.display_no
                ),
                "number": link.requirement.display_no,
                "title": link.requirement.title,
                "text": link.requirement.text,
            }
        )
    calls = AiCall.objects.filter(source_id=plan.pk, feature="draft_cases")
    gaps: list[str] = []
    for found in calls.order_by("created_at").values_list("gaps", flat=True):
        gaps += [g for g in found if g not in gaps]
    try:
        usage.ensure_allowance(plan.org_id)
        allowance_message = ""
    except usage.AllowanceUsedUp as error:
        allowance_message = error.message
    states = [r.review_state for r in revisions]
    role = membership.role
    return {
        "plan": plan_id(plan),
        "plan_no": plan.display_no,
        "title": plan.title,
        "drafts": states.count(ReviewState.DRAFT),
        "accepted": states.count(ReviewState.ACCEPTED),
        "rejected": states.count(ReviewState.REJECTED),
        "items": [
            {
                "case": case_id(r.test_case),
                "number": r.test_case.display_no,
                "title": r.title,
                "case_type": r.case_type,
                "priority": r.priority,
                "preconditions": r.preconditions,
                "steps": r.steps,
                "expected": r.expected,
                "review_state": r.review_state,
                "requirements": links[r.pk],
                "assumptions": notes[r.pk].flags.get("assumptions", []),
                "possible_duplicate_of": notes[r.pk].flags.get("possible_duplicate_of"),
            }
            for r in revisions
        ],
        "gaps": gaps,
        "left_out": AiDroppedItem.objects.filter(call__in=calls).count(),
        "job": describe(Job.objects.filter(pk=plan.draft_job_id).first()),
        "allowance_message": allowance_message,
        "fast_accepts": (
            sum(1 for n in notes.values() if n.fast_accept) if role in LEADS else None
        ),
        "actions": {"review": can(role, Action.WRITE_TESTING)},
    }
