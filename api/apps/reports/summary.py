"""The project dashboard (UX screen 4): the next release, verified coverage, open work and
recent activity. Readiness and coverage come from the facts builder, open work from the derived
states, so the dashboard always agrees with the Inbox and the release page."""

from datetime import datetime

from django.utils import timezone

from apps.core.choices import ReviewState
from apps.core.models import AuditEvent, CounterKind, Project
from apps.core.numbering import format_display_id
from apps.defects.models import Defect
from apps.inbox.derived import TERMINAL_QA, all_items, current_case_pointers
from apps.plans.models import TestPlan
from apps.reports.facts import build_facts
from apps.requirements.models import Requirement
from apps.runs.models import Release, ReleaseState, TestRun

OPEN_WORK = {
    "closed_failed_retest": "retest_failed",
    "needs_retest": "needs_retest",
    "unfiled_failures": "unfiled_failures",
    "missing_evidence": "missing_evidence",
    "stale_tests": "stale",
    "uncovered": "uncovered",
}


def next_release(project: Project) -> Release | None:
    """The open release due soonest, or the newest open one if none has a date."""
    open_releases = Release.objects.filter(project=project, state=ReleaseState.OPEN)
    dated = open_releases.filter(target_date__isnull=False).order_by("target_date").first()
    return dated or open_releases.order_by("-created_at").first()


def _activity(project: Project, limit: int = 10) -> list[dict]:
    defects = {
        str(d.pk): format_display_id(CounterKind.DEFECT, d.display_no)
        for d in Defect.objects.filter(project=project)
    }
    runs = {
        str(r.pk): format_display_id(CounterKind.TEST_RUN, r.display_no)
        for r in TestRun.objects.filter(project=project)
    }
    plans = {
        str(p.pk): format_display_id(CounterKind.TEST_PLAN, p.display_no)
        for p in TestPlan.objects.filter(project=project)
    }
    releases = {str(r.pk): r.name for r in Release.objects.filter(project=project)}
    reqs = {
        str(r.pk): format_display_id(CounterKind.REQUIREMENT, r.display_no)
        for r in Requirement.objects.filter(project=project)
    }
    ids = {**defects, **runs, **plans, **releases, **reqs}
    events = (
        AuditEvent.objects.filter(target_id__in=list(ids))
        .exclude(action__in=("result.recorded", "evidence.attached"))
        .select_related("actor")
        .order_by("-at")[:limit]
    )
    lines = []
    for e in events:
        ref = ids[e.target_id]
        after = e.after or {}
        tracker = str(after.get("tracker_status", "")).replace("_", " ")
        qa = str(after.get("qa_status", "")).replace("_", " ")
        retest = "passed" if qa == "verified" else "failed"
        text = {
            "requirement.created": f"added {ref}",
            "requirement.text_changed": f"changed the text of {ref}",
            "plan.created": f"created {ref}",
            "plan.approved": f"approved {ref} v{after.get('version', '')}",
            "release.created": f"created release {ref}",
            "release.signed_off": f"signed off release {ref}",
            "run.started": f"started {ref}",
            "defect.created": f"filed {ref}",
            "defect.status_changed": f"set {ref} to {tracker}",
            "defect.retested": f"retested {ref}: {retest}",
            "defect.reopened": f"reopened {ref}",
            "defect.decided": f"marked {ref} {qa}",
        }.get(e.action)
        if text is None:
            continue
        refs = [ref] if e.target_type != "release" else []
        lines.append(
            {
                "at": e.at,
                "actor": (e.actor.name or e.actor.email) if e.actor else "Greenlit",
                "text": text,
                "refs": refs,
            }
        )
    return lines


def project_summary(project: Project, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    projects = Project.objects.filter(pk=project.pk)
    requirements = Requirement.objects.filter(
        project=project, review_state=ReviewState.ACCEPTED
    ).count()
    cases = current_case_pointers(projects).count()
    runs = TestRun.objects.filter(project=project).count()
    open_defects = Defect.objects.filter(project=project).exclude(qa_status__in=TERMINAL_QA).count()
    releases = Release.objects.filter(project=project).exists()

    release = next_release(project)
    release_data = coverage = None
    if release is not None:
        facts = build_facts(release)
        release_data = {
            "version": release.name,
            "name": f"Release {release.name}",
            "due": release.target_date,
            "readiness": facts.readiness,
            "blockers": len(facts.blockers),
        }
        coverage = {**facts.as_dict()["coverage"]}

    work: dict[str, dict] = {
        kind: {"kind": kind, "count": 0, "oldest_days": None} for kind in OPEN_WORK.values()
    }
    for item in all_items(projects, now):
        kind = OPEN_WORK.get(item.group)
        if kind is None:
            continue
        row = work[kind]
        row["count"] += 1
        age = item.age_days(now)
        row["oldest_days"] = age if row["oldest_days"] is None else max(row["oldest_days"], age)

    return {
        "key": project.key,
        "name": project.name,
        "client_name": project.client_name,
        "is_new": not (requirements or cases or runs or releases),
        "release": release_data,
        "coverage": coverage,
        "open_work": list(work.values()),
        "activity": _activity(project),
        "counts": {
            "requirements": requirements,
            "cases": cases,
            "runs": runs,
            "open_defects": open_defects,
        },
    }
