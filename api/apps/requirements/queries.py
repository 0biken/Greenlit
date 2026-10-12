"""Reading requirements: the list and the detail page (M2-08). Writing is in `services.py`."""

from django.db.models import Q

from apps.core.models import AuditEvent, CounterKind, Membership, Project, display_name
from apps.core.numbering import format_display_id
from apps.core.policy import Action, can
from apps.inbox.derived import current_case_pointers
from apps.plans.models import CaseRequirement
from apps.requirements.models import Requirement, RequirementRevision

HISTORY = {
    "requirement.created": lambda a: "added this requirement",
    "requirement.edited": lambda a: "edited " + ", ".join(a.get("fields", [])),
    "requirement.text_changed": lambda a: f"changed the text (revision {a.get('revision', '')})",
}


def req_id(requirement: Requirement) -> str:
    return format_display_id(CounterKind.REQUIREMENT, requirement.display_no)


def _links(project: Project) -> dict:
    """{requirement_id: [(link, plan), ...]} for accepted cases in each plan's current version."""
    current = current_case_pointers(Project.objects.filter(pk=project.pk)).select_related(
        "plan_version__plan"
    )
    plan_of = {p.case_revision_id: p.plan_version.plan for p in current}
    out: dict = {}
    links = CaseRequirement.objects.filter(case_revision_id__in=plan_of).select_related(
        "case_revision__test_case"
    )
    for link in links.order_by("case_revision__test_case__display_no"):
        out.setdefault(link.requirement_id, []).append((link, plan_of[link.case_revision_id]))
    return out


def _row(requirement: Requirement, links: list) -> dict:
    return {
        "id": requirement.pk,
        "display_id": req_id(requirement),
        "number": requirement.display_no,
        "title": requirement.title,
        "priority": requirement.priority,
        "revision": requirement.revision,
        "review_state": requirement.review_state,
        "origin": requirement.origin,
        "covered": bool(links),
        "cases": len(links),
        "stale_cases": sum(1 for link, _ in links if link.req_revision_seen < requirement.revision),
        "updated_at": requirement.updated_at,
    }


def requirement_list(
    project: Project, *, q: str = "", priority: str = "", coverage: str = ""
) -> list[dict]:
    rows = Requirement.objects.filter(project=project)
    if priority:
        rows = rows.filter(priority=priority)
    if q.strip():
        term = q.strip()
        number = term.upper().removeprefix("REQ-")
        match = Q(title__icontains=term) | Q(text__icontains=term)
        if number.isdigit():
            match |= Q(display_no=int(number))
        rows = rows.filter(match)
    links = _links(project)
    out = [_row(r, links.get(r.pk, [])) for r in rows.order_by("display_no")[:500]]
    if coverage in ("covered", "uncovered"):
        out = [r for r in out if r["covered"] == (coverage == "covered")]
    return out


def detail(requirement: Requirement, membership: Membership) -> dict:
    links = _links(requirement.project).get(requirement.pk, [])
    kept = list(
        RequirementRevision.objects.filter(requirement=requirement)
        .select_related("created_by")
        .order_by("-revision")
    )
    revisions = [
        {
            "revision": r.revision,
            "text": r.text,
            "at": r.created_at,
            "by": display_name(r.created_by),
        }
        for r in kept
    ]
    if not kept or kept[0].revision != requirement.revision:
        # Made before revisions were kept: its current text is its only known revision.
        revisions.insert(
            0,
            {
                "revision": requirement.revision,
                "text": requirement.text,
                "at": requirement.updated_at,
                "by": None,
            },
        )
    events = AuditEvent.objects.filter(
        target_type="requirement", target_id=str(requirement.pk)
    ).select_related("actor")
    return {
        **_row(requirement, links),
        "text": requirement.text,
        "created_by": display_name(requirement.created_by),
        "created_at": requirement.created_at,
        "linked_cases": [
            {
                "display_id": format_display_id(
                    CounterKind.TEST_CASE, link.case_revision.test_case.display_no
                ),
                "number": link.case_revision.test_case.display_no,
                "title": link.case_revision.title,
                "plan": plan.title,
                "plan_no": plan.display_no,
                "stale": link.req_revision_seen < requirement.revision,
            }
            for link, plan in links
        ],
        "revisions": revisions,
        "history": [
            {
                "at": e.at,
                "actor": display_name(e.actor) or "Greenlit",
                "text": HISTORY[e.action](e.after or {}),
            }
            for e in events.order_by("-at")
            if e.action in HISTORY
        ],
        "actions": {"edit": can(membership.role, Action.WRITE_TESTING)},
    }
