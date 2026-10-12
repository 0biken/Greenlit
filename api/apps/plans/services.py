"""Plan and case rules needed by runs and reports (M3-01, M3-03 core).

The editing API, diff, rollback and screens arrive with the rest of M3.
"""

from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.choices import Origin, Priority, ReviewState
from apps.core.models import CounterKind, Project
from apps.core.numbering import next_number
from apps.core.services import ServiceError
from apps.plans.models import (
    CaseRequirement,
    CaseRevision,
    PlanVersion,
    PlanVersionCase,
    TestCase,
    TestPlan,
    VersionState,
)
from apps.requirements.models import Requirement


def create_plan(project: Project, actor, *, title: str, scope: str = "") -> TestPlan:
    """A new plan, with an empty draft version to add cases to."""
    with transaction.atomic():
        plan = TestPlan.objects.create(
            org_id=project.org_id,
            project=project,
            display_no=next_number(project.pk, project.org_id, CounterKind.TEST_PLAN),
            title=title,
            scope=scope,
            created_by=actor,
        )
        PlanVersion.objects.create(org_id=project.org_id, plan=plan, created_by=actor)
        audit.record("plan.created", "test_plan", plan.pk, actor=actor, after={"title": title})
    return plan


def draft_of(plan: TestPlan) -> PlanVersion:
    draft = PlanVersion.objects.filter(plan=plan, state=VersionState.DRAFT).first()
    if draft is None:
        raise ServiceError("This plan has no draft. Open one to make changes.")
    return draft


def add_case(
    draft: PlanVersion,
    actor,
    *,
    title: str,
    steps: list[str],
    expected: str,
    preconditions: str = "",
    priority: str = Priority.MEDIUM,
    requirements: Iterable[Requirement] = (),
    review_state: str = ReviewState.ACCEPTED,
    origin: str = Origin.HUMAN,
) -> CaseRevision:
    """Add a new case to a draft: a test case, its first revision and the draft's pointer."""
    if draft.state != VersionState.DRAFT:
        raise ServiceError("Only a draft plan version can change.")
    if not title.strip() or not expected.strip() or not steps:
        raise ServiceError("A case needs a title, at least one step and an expected result.")
    plan = draft.plan
    with transaction.atomic():
        case = TestCase.objects.create(
            org_id=plan.org_id,
            project_id=plan.project_id,
            display_no=next_number(plan.project_id, plan.org_id, CounterKind.TEST_CASE),
            created_by=actor,
        )
        revision = CaseRevision.objects.create(
            org_id=plan.org_id,
            test_case=case,
            rev_no=1,
            title=title,
            preconditions=preconditions,
            steps=list(steps),
            expected=expected,
            priority=priority,
            review_state=review_state,
            origin=origin,
            created_by=actor,
        )
        for requirement in requirements:
            CaseRequirement.objects.create(
                org_id=plan.org_id,
                case_revision=revision,
                requirement=requirement,
                req_revision_seen=requirement.revision,
            )
        position = PlanVersionCase.objects.filter(plan_version=draft).count() + 1
        PlanVersionCase.objects.create(
            org_id=plan.org_id, plan_version=draft, case_revision=revision, position=position
        )
    return revision


def _next_number(plan: TestPlan, major: bool) -> str:
    numbers = [
        tuple(int(p) for p in n.split("."))
        for n in PlanVersion.objects.filter(plan=plan)
        .exclude(number="")
        .values_list("number", flat=True)
    ]
    if not numbers:
        return "1.0"
    high, low = max(numbers)
    return f"{high + 1}.0" if major else f"{high}.{low + 1}"


def approve(draft: PlanVersion, actor, *, major: bool = False) -> PlanVersion:
    """Publish a draft (M3-03): next minor number by default; the previous version is
    superseded and the plan's current version moves. The caller checks the approve-plan role."""
    if draft.state != VersionState.DRAFT:
        raise ServiceError("Only a draft can be approved.")
    plan = draft.plan
    with transaction.atomic():
        previous = plan.current_version
        draft.number = _next_number(plan, major)
        draft.state = VersionState.PUBLISHED
        draft.approved_by = actor
        draft.approved_at = timezone.now()
        draft.save(update_fields=["number", "state", "approved_by", "approved_at", "updated_at"])
        if previous is not None:
            previous.state = VersionState.SUPERSEDED
            previous.save(update_fields=["state", "updated_at"])
        plan.current_version = draft
        plan.save(update_fields=["current_version", "updated_at"])
        audit.record(
            "plan.approved",
            "test_plan",
            plan.pk,
            actor=actor,
            before={"version": previous.number if previous else None},
            after={"version": draft.number},
        )
    return draft
