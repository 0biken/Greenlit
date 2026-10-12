"""The one place that changes a defect's `tracker_status` or `qa_status` (M5-03, DATA §7).

Transitions Greenlit applies:
1. Setting the tracker status to fixed sets `fixed_at` and, if the QA status is retest_failed,
   resets it to not_retested.
2. A passed retest sets the QA status to verified. A failed retest sets it to retest_failed
   and, in v1, sets the tracker status to open. Both need evidence.
3. Moving the tracker status from fixed or closed back to open or in_progress resets the QA
   status to not_retested; if it was verified, that is counted as a reopen.
4. Won't fix and Deferred need a reason and an approver with that right.
Every change is audited with the fields that changed.
"""

from collections.abc import Iterable
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.choices import Priority
from apps.core.models import CounterKind, Project
from apps.core.numbering import next_number
from apps.core.project_settings import project_settings
from apps.core.services import ServiceError
from apps.defects.models import Defect, QaStatus, Retest, RetestOutcome, TrackerStatus
from apps.runs.models import CaseResult, EvidenceLink, EvidenceTarget, Release
from apps.runs.services import attach_evidence

FIXED_OR_CLOSED = (TrackerStatus.FIXED, TrackerStatus.CLOSED)
OPEN_STATES = (TrackerStatus.OPEN, TrackerStatus.IN_PROGRESS)


def _snapshot(defect: Defect) -> dict:
    return {"tracker_status": defect.tracker_status, "qa_status": defect.qa_status}


def _set_qa(defect: Defect, qa_status: str, now) -> None:
    if defect.qa_status != qa_status:
        defect.qa_status = qa_status
        defect.qa_status_at = now


def _save(
    defect: Defect, actor, before: dict, action: str = "defect.status_changed", **extra
) -> None:
    defect.save()
    audit.record(
        action,
        "defect",
        defect.pk,
        actor=actor,
        before=before,
        after={**_snapshot(defect), **extra},
    )


def create_defect(
    project: Project,
    actor,
    *,
    title: str,
    steps: str = "",
    expected: str = "",
    actual: str = "",
    severity: str = Priority.MEDIUM,
    owner=None,
    release: Release | None = None,
    found_in_result: CaseResult | None = None,
    evidence_file_ids: Iterable[UUID] = (),
) -> Defect:
    if not title.strip():
        raise ServiceError("Give the defect a title.")
    if severity not in Priority.values:
        raise ServiceError("Choose a severity: Critical, High, Medium or Low.")
    if found_in_result is not None:
        if found_in_result.run.project_id != project.pk:
            raise ServiceError("That result belongs to another project.")
        # A defect found in a run belongs to that run's release unless told otherwise.
        release = release or found_in_result.run.release
    if release is not None and release.project_id != project.pk:
        raise ServiceError("The release belongs to another project.")
    file_ids = list(evidence_file_ids)
    with transaction.atomic():
        defect = Defect.objects.create(
            org_id=project.org_id,
            project=project,
            release=release,
            display_no=next_number(project.pk, project.org_id, CounterKind.DEFECT),
            title=title,
            steps=steps,
            expected=expected,
            actual=actual,
            severity=severity,
            owner=owner,
            found_in_result=found_in_result,
            created_by=actor,
        )
        if file_ids:
            attach_evidence(project, actor, file_ids, [(EvidenceTarget.DEFECT, defect.pk)])
        if found_in_result is not None:
            # FR-RUN-04: the evidence already on the failed result supports the defect too.
            for link in EvidenceLink.objects.filter(
                target_type=EvidenceTarget.CASE_RESULT, target_id=found_in_result.pk
            ):
                EvidenceLink.objects.get_or_create(
                    evidence_id=link.evidence_id,
                    target_type=EvidenceTarget.DEFECT,
                    target_id=defect.pk,
                    defaults={"org_id": project.org_id},
                )
        audit.record(
            "defect.created",
            "defect",
            defect.pk,
            actor=actor,
            after={"display_no": defect.display_no, "severity": severity, **_snapshot(defect)},
        )
    return defect


def set_tracker_status(defect: Defect, actor, status: str) -> Defect:
    if status not in TrackerStatus.values:
        raise ServiceError("Choose Open, In progress, Fixed or Closed.")
    if status == defect.tracker_status:
        return defect
    now = timezone.now()
    with transaction.atomic():
        defect = Defect.objects.select_for_update().get(pk=defect.pk)
        before = _snapshot(defect)
        previous = defect.tracker_status
        reopened = False
        defect.tracker_status = status
        if status == TrackerStatus.FIXED:  # rule 1
            defect.fixed_at = now
            defect.fixed_by = actor
            if defect.qa_status == QaStatus.RETEST_FAILED:
                _set_qa(defect, QaStatus.NOT_RETESTED, now)
        elif status == TrackerStatus.CLOSED:
            defect.closed_at = now
        if status in OPEN_STATES and previous in FIXED_OR_CLOSED:  # rule 3
            reopened = defect.qa_status == QaStatus.VERIFIED
            _set_qa(defect, QaStatus.NOT_RETESTED, now)
        # A verified defect coming back is a reopen, counted for the reopen-rate guardrail.
        _save(
            defect, actor, before, action="defect.reopened" if reopened else "defect.status_changed"
        )
    return defect


def record_retest(
    defect: Defect,
    actor,
    *,
    outcome: str,
    evidence_file_ids: Iterable[UUID],
    build: str = "",
    environment: str = "",
) -> Retest:
    """Rule 2. Evidence is required for a pass and for a fail."""
    if outcome not in RetestOutcome.values:
        raise ServiceError("Choose Passed or Failed.")
    file_ids = list(evidence_file_ids)
    if not file_ids:
        raise ServiceError("Attach evidence: a screenshot, recording or log.", code="evidence")
    now = timezone.now()
    with transaction.atomic():
        # Check the status on the locked row, not on the copy the caller holds.
        defect = Defect.objects.select_for_update().select_related("project").get(pk=defect.pk)
        if defect.tracker_status not in FIXED_OR_CLOSED:
            raise ServiceError(
                "This defect hasn't been marked fixed, so there is nothing to retest yet."
            )
        if (
            outcome == RetestOutcome.PASSED
            and project_settings(defect.project)["fixer_cannot_verify"]
            and defect.fixed_by_id == getattr(actor, "pk", None)
        ):
            raise ServiceError(
                "You marked this fixed, so someone else needs to verify it.", code="fixer"
            )
        before = _snapshot(defect)
        retest = Retest.objects.create(
            org_id=defect.org_id,
            defect=defect,
            outcome=outcome,
            tested_by=actor,
            tested_at=now,
            build=build,
            environment=environment,
            created_by=actor,
        )
        attach_evidence(
            defect.project,
            actor,
            file_ids,
            [(EvidenceTarget.RETEST, retest.pk), (EvidenceTarget.DEFECT, defect.pk)],
            environment=environment,
        )
        if outcome == RetestOutcome.PASSED:
            _set_qa(defect, QaStatus.VERIFIED, now)
        else:
            _set_qa(defect, QaStatus.RETEST_FAILED, now)
            defect.tracker_status = TrackerStatus.OPEN  # v1 only
        _save(defect, actor, before, action="defect.retested", retest=str(retest.pk))
    return retest


def decide(defect: Defect, actor, decision: str, reason: str) -> Defect:
    """Rule 4: Won't fix or Deferred, with a reason. The caller checks the approver's role."""
    if decision not in (QaStatus.WONT_FIX, QaStatus.DEFERRED):
        raise ServiceError("Choose Won't fix or Deferred.")
    if not reason.strip():
        raise ServiceError("Give a reason. It stays on the record.")
    with transaction.atomic():
        defect = Defect.objects.select_for_update().get(pk=defect.pk)
        before = _snapshot(defect)
        _set_qa(defect, decision, timezone.now())
        defect.decision_reason = reason.strip()
        defect.decided_by = actor
        _save(defect, actor, before, action="defect.decided")
    return defect


EDITABLE = ("title", "steps", "expected", "actual", "severity", "owner", "release")


def update_defect(defect: Defect, actor, **changes) -> Defect:
    """Edit a defect's own fields (never its two statuses). The audit entry names the fields
    that changed and, for the short ones, their values; it never copies the long text."""
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ServiceError(f"Cannot change: {', '.join(sorted(unknown))}.")
    if "title" in changes and not str(changes["title"]).strip():
        raise ServiceError("Give the defect a title.")
    if "severity" in changes and changes["severity"] not in Priority.values:
        raise ServiceError("Choose a severity: Critical, High, Medium or Low.")
    release = changes.get("release")
    if release is not None and release.project_id != defect.project_id:
        raise ServiceError("The release belongs to another project.")
    changed = [name for name, value in changes.items() if getattr(defect, name) != value]
    if not changed:
        return defect

    def short(d: Defect) -> dict:
        return {
            "severity": d.severity,
            "owner": str(d.owner_id) if d.owner_id else None,
            "release": str(d.release_id) if d.release_id else None,
        }

    with transaction.atomic():
        before = short(defect)
        for name in changed:
            setattr(defect, name, changes[name])
        defect.save()
        audit.record(
            "defect.edited",
            "defect",
            defect.pk,
            actor=actor,
            before=before,
            after={**short(defect), "fields": sorted(changed)},
        )
    return defect


def chip(defect: Defect) -> str:
    """The status chip the web app draws for this defect (its mark and word)."""
    t, q = defect.tracker_status, defect.qa_status
    if q in (QaStatus.WONT_FIX, QaStatus.DEFERRED, QaStatus.VERIFIED):
        return str(q)
    if q == QaStatus.RETEST_FAILED:
        return "retest_failed"
    return "needs_retest" if t in FIXED_OR_CLOSED else "open"


def latest_retest(defect: Defect) -> Retest | None:
    return defect.retests.order_by("-tested_at", "-created_at").first()


def shown_as(defect: Defect) -> str:
    """The label from the DATA §7 table."""
    t, q = defect.tracker_status, defect.qa_status
    if q == QaStatus.WONT_FIX:
        return "Won't fix"
    if q == QaStatus.DEFERRED:
        return "Deferred"
    if q == QaStatus.VERIFIED:
        return "Verified"
    if q == QaStatus.RETEST_FAILED:
        if t == TrackerStatus.CLOSED:
            return "Closed, retest failed"
        return "Retest failed" if t == TrackerStatus.FIXED else "Reopened"
    if t == TrackerStatus.FIXED:
        return "Needs retest"
    if t == TrackerStatus.CLOSED:
        return "Closed, unverified"
    return "Open"
