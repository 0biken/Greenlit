"""Plan and case rules (M3-01 to M3-07; DATA "Versioning"). Reading is in `queries.py`.

Published versions and the revisions they use never change (the database refuses it). Every
edit happens in the plan's one draft; approving the draft publishes it as the next version.
"""

from collections.abc import Iterable

from django.db import transaction
from django.db.models import Max
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

MAX_STEPS = 50
CASE_FIELDS = ("title", "preconditions", "steps", "expected", "priority")


def create_plan(project: Project, actor, *, title: str, scope: str = "") -> TestPlan:
    """A new plan, with an empty draft version to add cases to."""
    if not title.strip():
        raise ServiceError("Give the plan a title.")
    with transaction.atomic():
        plan = TestPlan.objects.create(
            org_id=project.org_id,
            project=project,
            display_no=next_number(project.pk, project.org_id, CounterKind.TEST_PLAN),
            title=title.strip(),
            scope=scope,
            created_by=actor,
        )
        PlanVersion.objects.create(org_id=project.org_id, plan=plan, created_by=actor)
        audit.record("plan.created", "test_plan", plan.pk, actor=actor, after={"title": title})
    return plan


def draft_of(plan: TestPlan) -> PlanVersion:
    draft = PlanVersion.objects.filter(plan=plan, state=VersionState.DRAFT).first()
    if draft is None:
        raise ServiceError("This plan has no draft. Open one to make changes.", code="no_draft")
    return draft


# --- cases in a draft (M3-02) ----------------------------------------------------------------


def _clean_case(project_id, values: dict, requirements: list[Requirement]) -> dict:
    """Validate what a case is saved with (FR-TC-01). Returns the values, tidied."""
    title = str(values["title"]).strip()
    steps = [str(s).strip() for s in values["steps"] if str(s).strip()]
    expected = str(values["expected"]).strip()
    if not title or not expected or not steps:
        raise ServiceError("A case needs a title, at least one step and an expected result.")
    if len(title) > 200:
        raise ServiceError("Keep the title to 200 characters.")
    if len(steps) > MAX_STEPS:
        raise ServiceError(f"A case can have up to {MAX_STEPS} steps. Split it into two cases.")
    if values["priority"] not in Priority.values:
        raise ServiceError("Choose a priority: Critical, High, Medium or Low.")
    for requirement in requirements:
        if requirement.project_id != project_id:
            raise ServiceError("A linked requirement belongs to another project.")
        if requirement.review_state != ReviewState.ACCEPTED:
            raise ServiceError("Only accepted requirements can be linked to a case.")
    return {
        "title": title,
        "preconditions": str(values.get("preconditions", "")).strip(),
        "steps": steps,
        "expected": expected,
        "priority": values["priority"],
    }


def _require_draft(draft: PlanVersion) -> None:
    if draft.state != VersionState.DRAFT:
        raise ServiceError("Only a draft plan version can change.")


def _changed(draft: PlanVersion) -> None:
    """The draft is no longer what was handed over for approval."""
    if draft.submitted_at is not None:
        draft.submitted_at = draft.submitted_by = None
        draft.save(update_fields=["submitted_at", "submitted_by", "updated_at"])


def _link(revision: CaseRevision, requirements: Iterable[Requirement]) -> None:
    """Make the revision's requirement links exactly these, each seen at its current text."""
    wanted = {r.pk: r for r in requirements}
    for link in CaseRequirement.all_objects.filter(case_revision=revision):
        requirement = wanted.pop(link.requirement_id, None)
        if requirement is None:
            if link.deleted_at is None:
                link.delete()
        else:
            link.req_revision_seen = requirement.revision
            link.deleted_at = None
            link.save(update_fields=["req_revision_seen", "deleted_at", "updated_at"])
    for requirement in wanted.values():
        CaseRequirement.objects.create(
            org_id=revision.org_id,
            case_revision=revision,
            requirement=requirement,
            req_revision_seen=requirement.revision,
        )


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
    _require_draft(draft)
    plan = draft.plan
    requirements = list(requirements)
    values = _clean_case(
        plan.project_id,
        {
            "title": title,
            "steps": steps,
            "expected": expected,
            "preconditions": preconditions,
            "priority": priority,
        },
        requirements,
    )
    with transaction.atomic():
        revision = _new_case(plan, actor, values, requirements, review_state, origin)
        _append(draft, revision)
    return revision


def _new_case(
    plan: TestPlan,
    actor,
    values: dict,
    requirements: list[Requirement],
    review_state: str,
    origin: str,
    case_type: str = "",
) -> CaseRevision:
    """A new test case and its first revision. No plan version points at it yet."""
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
        review_state=review_state,
        origin=origin,
        case_type=case_type,
        created_by=actor,
        **values,
    )
    _link(revision, requirements)
    return revision


def _append(draft: PlanVersion, revision: CaseRevision) -> None:
    """Put the revision last in the draft."""
    position = PlanVersionCase.objects.filter(plan_version=draft).count() + 1
    PlanVersionCase.objects.create(
        org_id=draft.org_id, plan_version=draft, case_revision=revision, position=position
    )
    _changed(draft)


def _pointer(draft: PlanVersion, case: TestCase) -> PlanVersionCase:
    pointer = (
        PlanVersionCase.objects.filter(plan_version=draft, case_revision__test_case=case)
        .select_related("case_revision")
        .first()
    )
    if pointer is None:
        raise ServiceError("That case is not in this draft.", code="not_found")
    return pointer


def _used_elsewhere(revision: CaseRevision, draft: PlanVersion) -> bool:
    """Whether anything but this draft relies on the revision staying as it is."""
    from apps.runs.models import CaseResult

    return (
        PlanVersionCase.objects.filter(case_revision=revision).exclude(plan_version=draft).exists()
        or CaseResult.objects.filter(case_revision=revision).exists()
    )


def edit_case(
    draft: PlanVersion,
    case: TestCase,
    actor,
    *,
    requirements: Iterable[Requirement] | None = None,
    **fields,
) -> CaseRevision:
    """Change a case inside a draft (DATA "Versioning" step 2). A revision that a published
    version or a run relies on is never touched: the edit becomes revision n+1 and the draft
    points at it. A revision made in this draft, which nothing else uses, is changed in place.
    Saving also records that the case was written against each requirement's current text."""
    _require_draft(draft)
    unknown = set(fields) - set(CASE_FIELDS)
    if unknown:
        raise ServiceError(f"Cannot change: {', '.join(sorted(unknown))}.")
    pointer = _pointer(draft, case)
    current = pointer.case_revision
    links = list(
        CaseRequirement.objects.filter(case_revision=current).select_related("requirement")
    )
    keep = requirements is None
    wanted = [link.requirement for link in links] if keep else list(requirements or [])
    values = _clean_case(
        draft.plan.project_id,
        {**{name: getattr(current, name) for name in CASE_FIELDS}, **fields},
        [] if keep else wanted,  # links kept as they are were checked when they were made
    )
    same_content = all(getattr(current, name) == values[name] for name in CASE_FIELDS)
    same_links = {link.requirement_id for link in links} == {r.pk for r in wanted} and all(
        link.req_revision_seen == link.requirement.revision for link in links
    )
    if same_content and same_links:
        return current
    with transaction.atomic():
        if _used_elsewhere(current, draft):
            highest = CaseRevision.all_objects.filter(test_case=case).aggregate(n=Max("rev_no"))
            revision = CaseRevision.objects.create(
                org_id=current.org_id,
                test_case=case,
                rev_no=highest["n"] + 1,
                review_state=ReviewState.ACCEPTED,
                origin=current.origin,
                created_by=actor,
                **values,
            )
            pointer.case_revision = revision
            pointer.save(update_fields=["case_revision", "updated_at"])
        else:
            revision = current
            for name in CASE_FIELDS:
                setattr(revision, name, values[name])
            revision.save(update_fields=[*CASE_FIELDS, "updated_at"])
        _link(revision, wanted)
        _changed(draft)
    return revision


def _renumber(draft: PlanVersion, order: list[PlanVersionCase]) -> None:
    for position, pointer in enumerate(order, start=1):
        if pointer.position != position:
            pointer.position = position
            pointer.save(update_fields=["position", "updated_at"])


def remove_case(draft: PlanVersion, case: TestCase, actor) -> None:
    """Take a case out of the draft. Only the pointer goes; the case and its history remain."""
    _require_draft(draft)
    with transaction.atomic():
        _pointer(draft, case).delete()
        _renumber(
            draft, list(PlanVersionCase.objects.filter(plan_version=draft).order_by("position"))
        )
        _changed(draft)


def move_case(draft: PlanVersion, case: TestCase, position: int) -> None:
    """Put the case at `position` (1 is first) in the draft's order."""
    _require_draft(draft)
    with transaction.atomic():
        moving = _pointer(draft, case)
        order = [
            p
            for p in PlanVersionCase.objects.filter(plan_version=draft).order_by("position")
            if p.pk != moving.pk
        ]
        order.insert(min(max(position, 1), len(order) + 1) - 1, moving)
        _renumber(draft, order)
        _changed(draft)


# --- drafts (M3-04, M3-05) -------------------------------------------------------------------


def _copy_pointers(source: PlanVersion, draft: PlanVersion) -> None:
    PlanVersionCase.objects.bulk_create(
        PlanVersionCase(
            org_id=draft.org_id,
            plan_version=draft,
            case_revision_id=pointer.case_revision_id,
            position=pointer.position,
        )
        for pointer in PlanVersionCase.objects.filter(plan_version=source).order_by("position")
    )


def open_draft(plan: TestPlan, actor) -> PlanVersion:
    """Start editing a published plan: a draft that points at the same revisions as the
    current version. Nothing is copied but the pointers (DATA "Versioning" step 1)."""
    if PlanVersion.objects.filter(plan=plan, state=VersionState.DRAFT).exists():
        raise ServiceError("This plan already has a draft.", code="conflict")
    with transaction.atomic():
        draft = PlanVersion.objects.create(org_id=plan.org_id, plan=plan, created_by=actor)
        # Read from the database, not from `plan`, which the caller may have loaded earlier.
        current = PlanVersion.objects.filter(plan=plan, state=VersionState.PUBLISHED).first()
        if current is not None:
            _copy_pointers(current, draft)
        audit.record("plan.draft_opened", "test_plan", plan.pk, actor=actor)
    return draft


def discard_draft(draft: PlanVersion, actor) -> None:
    """Throw a draft away, with the revisions (and brand-new cases) only it used (DATA
    "Versioning" step 5). A plan that was never published keeps an empty draft to start from."""
    from apps.runs.models import CaseResult

    _require_draft(draft)
    plan = draft.plan
    with transaction.atomic():
        pointers = list(PlanVersionCase.objects.filter(plan_version=draft))
        revision_ids = [p.case_revision_id for p in pointers]
        for pointer in pointers:
            pointer.delete()
        kept = set(
            PlanVersionCase.objects.filter(case_revision_id__in=revision_ids).values_list(
                "case_revision_id", flat=True
            )
        ) | set(
            CaseResult.objects.filter(case_revision_id__in=revision_ids).values_list(
                "case_revision_id", flat=True
            )
        )
        for revision in CaseRevision.objects.filter(pk__in=set(revision_ids) - kept):
            for link in CaseRequirement.objects.filter(case_revision=revision):
                link.delete()
            revision.delete()
            case = revision.test_case
            if not CaseRevision.objects.filter(test_case=case).exists():
                case.delete()
        if PlanVersion.objects.filter(plan=plan, state=VersionState.PUBLISHED).exists():
            draft.delete()
        else:
            _changed(draft)
        audit.record(
            "plan.draft_discarded",
            "test_plan",
            plan.pk,
            actor=actor,
            after={"cases": len(pointers)},
        )


# --- submit, approve, roll back (M3-03, M3-07) -----------------------------------------------


def submit(draft: PlanVersion, actor) -> PlanVersion:
    """Hand the draft to a lead for approval (UX Flow 1 step 6)."""
    _require_draft(draft)
    if not PlanVersionCase.objects.filter(plan_version=draft).exists():
        raise ServiceError("Add at least one case before submitting the plan.")
    if draft.submitted_at is None:
        with transaction.atomic():
            draft.submitted_at, draft.submitted_by = timezone.now(), actor
            draft.save(update_fields=["submitted_at", "submitted_by", "updated_at"])
            audit.record("plan.submitted", "test_plan", draft.plan_id, actor=actor)
    return draft


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
    with transaction.atomic():
        # Read from the database and hold the plan: the caller's copy may be from before the
        # last approval, and two approvals must not both think they are next.
        plan = TestPlan.objects.select_for_update().get(pk=draft.plan_id)
        previous = PlanVersion.objects.filter(plan=plan, state=VersionState.PUBLISHED).first()
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
        draft.plan = plan
        audit.record(
            "plan.approved",
            "test_plan",
            plan.pk,
            actor=actor,
            before={"version": previous.number if previous else None},
            after={"version": draft.number},
        )
    return draft


def roll_back(plan: TestPlan, target: PlanVersion, actor) -> PlanVersion:
    """Publish a new version whose cases equal an old version's (FR-TC-04). History is never
    rewritten: 1.2 stays as it was and the plan moves on to, say, 1.5."""
    if target.plan_id != plan.pk or target.state == VersionState.DRAFT:
        raise ServiceError("Choose a published version of this plan to roll back to.")
    if target.pk == plan.current_version_id:
        raise ServiceError(f"Version {target.number} is already the current version.")
    if PlanVersion.objects.filter(plan=plan, state=VersionState.DRAFT).exists():
        raise ServiceError(
            "This plan has a draft. Approve or discard it before rolling back.", code="conflict"
        )
    with transaction.atomic():
        draft = PlanVersion.objects.create(org_id=plan.org_id, plan=plan, created_by=actor)
        _copy_pointers(target, draft)
        version = approve(draft, actor)
        audit.record(
            "plan.rolled_back",
            "test_plan",
            plan.pk,
            actor=actor,
            after={"to": target.number, "version": version.number},
        )
    return version
