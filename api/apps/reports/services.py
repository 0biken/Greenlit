"""Release report and sign-off (M8-01, M8-02, M8-06; the report body until F5 lands).

The draft report is written from the facts, line by line, and every line names the records it
came from. When the AI provider is chosen (D-008), F5 replaces how the words are written, not
what they are built from. The draft is computed each time it is read; signing off stores it
once, frozen (the database refuses later changes).
"""

from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import CounterKind, Membership
from apps.core.numbering import format_display_id, next_number
from apps.core.policy import Action, can
from apps.core.services import ServiceError
from apps.reports.facts import Facts, build_facts
from apps.reports.models import Readiness, Report, ReportState, SignOff
from apps.runs.models import Release, ReleaseState


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def report_body(facts: Facts) -> dict:
    """A plain report: summary, results by area, open defects, risks. No adjectives, no
    recommendation to ship (AI §3 F5 rules apply to this version too)."""
    cov = facts.coverage
    n = len(facts.blockers)
    readiness_line = (
        "Ready. Every blocker is resolved."
        if facts.readiness == "ready"
        else f"Not ready yet. {_plural(n, 'blocker remains', 'blockers remain')}."
    )
    summary = (
        f"{cov.verified_pct}% of requirements are verified with evidence "
        f"({cov.verified} of {cov.total_requirements}). {readiness_line}"
    )

    results = []
    for run in facts.runs:
        text = f"{run.plan}: {run.passed} of {run.total} cases passed in {run.display_id}"
        if run.failed:
            text += f"; {run.failed} failed"
            if run.failed_filed == run.failed:
                text += " and was filed" if run.failed == 1 else " and were filed"
            else:
                text += f", {run.failed_filed} filed"
        if run.blocked:
            text += f"; {run.blocked} blocked"
        if run.not_run:
            text += f"; {run.not_run} not run"
        results.append({"text": text + ".", "refs": [run.display_id, *run.filed_defects]})

    open_lines = [
        {"text": f"{d['display_id']}: {d['title']} ({d['severity']}).", "refs": [d["display_id"]]}
        for d in facts.open_defects
    ]
    risk_lines = [
        {
            "text": f"{r['display_id']} has no test case yet: {r['title']}.",
            "refs": [r["display_id"]],
        }
        for r in facts.risks
    ]
    sections = [{"heading": "Results by area", "lines": results}]
    if open_lines:
        sections.append({"heading": "Open defects", "lines": open_lines})
    if risk_lines:
        sections.append({"heading": "Risks", "lines": risk_lines})
    return {"summary": summary, "sections": sections, "facts": facts.as_dict()}


def signed_report(release: Release) -> Report | None:
    return release.reports.filter(state=ReportState.SIGNED).order_by("-created_at").first()


def sign_off(release: Release, membership: Membership, reason: str | None) -> SignOff:
    """M8-06. The role is checked again here, at the moment of the action, and readiness is
    recomputed: what the person saw a minute ago may have changed."""
    if not can(membership.role, Action.SIGN_OFF):
        raise ServiceError(
            "Only owners, admins and QA leads can sign off a release.", code="forbidden"
        )
    if release.state == ReleaseState.SIGNED_OFF:
        raise ServiceError(f"Release {release.name} is already signed off.", code="conflict")
    if release.state == ReleaseState.CANCELLED:
        raise ServiceError(f"Release {release.name} was cancelled.", code="conflict")
    reason = (reason or "").strip()
    actor = membership.user
    with transaction.atomic():
        release = Release.objects.select_for_update().get(pk=release.pk)
        body = report_body(build_facts(release))  # fresh facts, inside the lock
        readiness = body["facts"]["readiness"]
        if readiness != Readiness.READY and not reason:
            raise ServiceError(
                "Say why you are signing off while the release is not ready.", code="reason"
            )
        now = timezone.now()
        # Drafts are computed when read; the report is stored once, already signed and frozen.
        report = Report.objects.create(
            org_id=release.org_id,
            project_id=release.project_id,
            release=release,
            display_no=next_number(release.project_id, release.org_id, CounterKind.REPORT),
            body=body,
            state=ReportState.SIGNED,
            snapshot_at=now,
            created_by=actor,
        )
        record = SignOff.objects.create(
            org_id=release.org_id,
            release=release,
            report=report,
            signed_by=actor,
            signed_at=now,
            readiness_at_signing=readiness,
            override_reason=reason if readiness != Readiness.READY else "",
            created_by=actor,
        )
        release.state = ReleaseState.SIGNED_OFF
        release.save(update_fields=["state", "updated_at"])
        audit.record(
            "release.signed_off",
            "release",
            release.pk,
            actor=actor,
            before={"state": ReleaseState.OPEN},
            after={
                "state": ReleaseState.SIGNED_OFF,
                "readiness": readiness,
                "report": format_display_id(CounterKind.REPORT, report.display_no),
                "override": bool(record.override_reason),
            },
        )
    return record
