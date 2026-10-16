"""Drafting test cases from requirements with AI, and deciding on the drafts (M3-08; AI §3 F2).

A drafted case is a real test case with one revision in `review_state = draft` that no plan
version points at. Runs, coverage, stale checks and readiness all read a version's pointers, so
a draft counts nowhere. Accepting it adds the pointer to the plan's draft version; from there
the ordinary submit and approve flow takes over.
"""

from collections.abc import Iterable

from django.db import transaction

from apps.ai import checks, client, drafts, usage
from apps.ai.features import DRAFT_CASES
from apps.ai.models import AiDraft, Decision
from apps.core import audit
from apps.core.choices import Origin, ReviewState
from apps.core.jobs import JobFailure, enqueue, job_handler
from apps.core.models import CounterKind, Project
from apps.core.numbering import format_display_id
from apps.core.services import ServiceError
from apps.inbox import derived
from apps.plans import services
from apps.plans.models import (
    CaseRequirement,
    CaseRevision,
    PlanVersion,
    TestPlan,
    VersionState,
)
from apps.requirements.models import Requirement

TARGET = "case_revision"
BATCH = 10  # requirements per request
MAX_REQUIREMENTS = 50  # per drafting run


def _req_id(requirement: Requirement) -> str:
    return format_display_id(CounterKind.REQUIREMENT, requirement.display_no)


def undecided(plan: TestPlan):
    """This plan's AI drafts nobody has accepted or rejected yet."""
    return AiDraft.objects.filter(target_type=TARGET, decision="", flags__plan=str(plan.pk))


def uncovered_requirements(project: Project) -> list[Requirement]:
    """Accepted requirements no accepted case in a current version covers: what drafting is
    offered for when nobody chooses."""
    covered = derived.covered_requirement_ids(Project.objects.filter(pk=project.pk))
    return list(
        Requirement.objects.filter(project=project, review_state=ReviewState.ACCEPTED)
        .exclude(pk__in=covered)
        .order_by("display_no")
    )


def queue_case_drafting(plan: TestPlan, actor, requirements: Iterable[Requirement]):
    """Start drafting cases for these requirements, unless the AI allowance is used up."""
    requirements = list(requirements)
    if not requirements:
        raise ServiceError("There are no accepted requirements to draft cases for.")
    if len(requirements) > MAX_REQUIREMENTS:
        raise ServiceError(f"Draft cases for at most {MAX_REQUIREMENTS} requirements at a time.")
    for requirement in requirements:
        if requirement.project_id != plan.project_id:
            raise ServiceError("A requirement belongs to another project.")
        if requirement.review_state != ReviewState.ACCEPTED:
            raise ServiceError("Cases are drafted for accepted requirements only.")
    usage.ensure_allowance(plan.org_id)
    job = enqueue(
        "draft_cases",
        org_id=plan.org_id,
        user=actor,
        plan_id=str(plan.pk),
        requirement_ids=[str(r.pk) for r in requirements],
    )
    plan.draft_job_id = job.pk
    plan.save(update_fields=["draft_job_id", "updated_at"])
    return job


def _existing_cases(project: Project) -> list[dict]:
    """This project's accepted cases in current versions, so the model does not repeat them."""
    pointers = list(derived.current_case_pointers(Project.objects.filter(pk=project.pk)))
    links: dict = {}
    for link in CaseRequirement.objects.filter(
        case_revision_id__in=[p.case_revision_id for p in pointers]
    ).select_related("requirement"):
        links.setdefault(link.case_revision_id, []).append(_req_id(link.requirement))
    return [
        {
            "display_id": format_display_id(
                CounterKind.TEST_CASE, p.case_revision.test_case.display_no
            ),
            "title": p.case_revision.title,
            "steps": p.case_revision.steps,
            "requirement_ids": links.get(p.case_revision_id, []),
        }
        for p in pointers
    ]


@job_handler("draft_cases", max_retries=1)
def draft_cases(job, plan_id: str, requirement_ids: list[str]) -> None:
    """F2: draft cases for the given requirements, ten at a time, so drafts appear as each
    batch finishes. Safe to run twice: a requirement that already has an undecided draft for
    this plan is skipped."""
    plan = TestPlan.objects.select_related("project").filter(pk=plan_id).first()
    if plan is None:
        return
    waiting = CaseRequirement.objects.filter(
        case_revision_id__in=undecided(plan).values("target_id")
    ).values_list("requirement_id", flat=True)
    requirements = list(
        Requirement.objects.filter(
            pk__in=requirement_ids, project=plan.project, review_state=ReviewState.ACCEPTED
        )
        .exclude(pk__in=waiting)
        .order_by("display_no")
    )
    batches = [requirements[i : i + BATCH] for i in range(0, len(requirements), BATCH)]
    created = dropped = 0
    for index, batch in enumerate(batches, start=1):
        by_id = {_req_id(r): r for r in batch}
        label = f"Drafting cases for {_req_id(batch[0])}"
        if len(batch) > 1:
            label += f" to {_req_id(batch[-1])}"
        job.set_progress(index - 1, len(batches), label)
        existing = _existing_cases(plan.project)
        document = "\n\n".join(f"[{rid}] {r.title}\n{r.text}" for rid, r in by_id.items())
        try:
            result = client.run(
                DRAFT_CASES,
                org_id=plan.org_id,
                document=document,
                existing=existing,
                source_id=plan.pk,
                job_id=job.pk,
            )
        except (usage.AllowanceUsedUp, client.AiUnavailable) as error:
            raise JobFailure(error.message) from error
        checked = checks.check_cases(result.reply["cases"], asked=set(by_id), existing=existing)
        client.record_drops(result.call, checked.dropped)
        dropped += len(checked.dropped)
        for item in checked.kept:
            linked = [by_id[rid] for rid in item["requirement_ids"]]
            try:
                values = services._clean_case(
                    plan.project_id,
                    {
                        "title": item["title"],
                        "steps": item["steps"],
                        "expected": item["expected"],
                        "preconditions": item.get("preconditions", ""),
                        "priority": item["priority"],
                    },
                    linked,
                )
            except ServiceError:
                client.record_drops(result.call, [("invalid", item)])
                dropped += 1
                continue
            with transaction.atomic():
                revision = services._new_case(
                    plan, None, values, linked, ReviewState.DRAFT, Origin.AI, item["type"]
                )
                drafts.note_draft(
                    result.call,
                    TARGET,
                    revision.pk,
                    {
                        "plan": str(plan.pk),
                        "possible_duplicate_of": item["possible_duplicate_of"],
                        "assumptions": item.get("assumptions", []),
                    },
                )
            created += 1
    summary = f"{created} {'draft' if created == 1 else 'drafts'} created."
    if dropped:
        was = "was" if dropped == 1 else "were"
        summary += f" {dropped} {was} left out because their source could not be confirmed."
    job.set_progress(len(batches), len(batches), summary)


# --- deciding on a draft ---------------------------------------------------------------------


def draft_revision(plan: TestPlan, case) -> CaseRevision:
    """The undecided AI draft of this case for this plan; `not_found` if there is none."""
    revision = CaseRevision.objects.filter(
        test_case=case, review_state=ReviewState.DRAFT, pk__in=undecided(plan).values("target_id")
    ).first()
    if revision is None:
        raise ServiceError("That case is not waiting for review on this plan.", code="not_found")
    return revision


def decide_case(
    plan: TestPlan,
    revision: CaseRevision,
    actor,
    decision: str,
    *,
    reason: str = "",
    viewed_ms: int | None = None,
) -> CaseRevision:
    """Accept or reject one drafted case (FR-PLAN-04, AI-01, AI-02). An accepted case joins
    the plan's draft version, which is opened if the plan has none."""
    if revision.review_state != ReviewState.DRAFT:
        raise ServiceError("Only a draft can be accepted or rejected.", code="conflict")
    with transaction.atomic():
        note = drafts.record_decision(
            TARGET, revision.pk, actor, decision, reason=reason, viewed_ms=viewed_ms
        )
        revision.review_state = decision
        revision.save(update_fields=["review_state", "updated_at"])
        linked = [
            link.requirement
            for link in CaseRequirement.objects.filter(case_revision=revision).select_related(
                "requirement"
            )
        ]
        if decision == Decision.ACCEPTED:
            version = PlanVersion.objects.filter(plan=plan, state=VersionState.DRAFT).first()
            if version is None:
                version = services.open_draft(plan, actor)
            services._link(revision, linked)  # accepted against each requirement's text today
            services._append(version, revision)
        audit.record(
            f"case.{decision}",
            "test_case",
            revision.test_case_id,
            actor=actor,
            before={"review_state": ReviewState.DRAFT},
            after={
                "review_state": decision,
                "origin": revision.origin,
                "model": note.call.model if note and note.call else "",
                "plan": str(plan.pk),
                "requirements": [_req_id(r) for r in linked],
            },
        )
    return revision


def accept_cases(plan: TestPlan, actor, numbers: list[int], viewed_ms: int | None) -> int:
    """Accept several drafted cases at once: never more than 20 (AI §6 "Over-trust")."""
    if len(numbers) > drafts.ACCEPT_ALL_MAX:
        raise ServiceError(f"Accept at most {drafts.ACCEPT_ALL_MAX} drafts at a time.")
    rows = list(
        CaseRevision.objects.filter(
            pk__in=undecided(plan).values("target_id"),
            review_state=ReviewState.DRAFT,
            test_case__display_no__in=numbers,
        ).order_by("test_case__display_no")
    )
    if len(rows) != len(set(numbers)):
        raise ServiceError("One of those cases is not waiting for review on this plan.")
    each = None if viewed_ms is None else viewed_ms // max(len(rows), 1)
    with transaction.atomic():
        for revision in rows:
            decide_case(plan, revision, actor, Decision.ACCEPTED, viewed_ms=each)
    return len(rows)


def edit_case_draft(
    plan: TestPlan,
    revision: CaseRevision,
    actor,
    *,
    requirements: list[Requirement] | None = None,
    **fields,
) -> CaseRevision:
    """Change a drafted case before deciding on it. It stays a draft."""
    unknown = set(fields) - set(services.CASE_FIELDS)
    if unknown:
        raise ServiceError(f"Cannot change: {', '.join(sorted(unknown))}.")
    current = [
        link.requirement
        for link in CaseRequirement.objects.filter(case_revision=revision).select_related(
            "requirement"
        )
    ]
    linked = current if requirements is None else requirements
    if not linked:
        raise ServiceError("A drafted case must cover at least one requirement.")
    values = services._clean_case(
        plan.project_id,
        {**{name: getattr(revision, name) for name in services.CASE_FIELDS}, **fields},
        linked,
    )
    with transaction.atomic():
        for name in services.CASE_FIELDS:
            setattr(revision, name, values[name])
        revision.save(update_fields=[*services.CASE_FIELDS, "updated_at"])
        services._link(revision, linked)
    return revision
