"""Release, run, result and evidence rules (M4-01, M4-02, M4-03, M4-05 core).

The run screen and its API arrive with the rest of M4; retests and sign-off use these.
"""

from collections.abc import Iterable
from datetime import date
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.core import audit
from apps.core.models import CounterKind, Project
from apps.core.numbering import next_number
from apps.core.services import ServiceError
from apps.files.models import FileState, StoredFile
from apps.plans.models import PlanVersion, PlanVersionCase, VersionState
from apps.runs.models import (
    CaseResult,
    Evidence,
    EvidenceLink,
    EvidenceTarget,
    Outcome,
    Release,
    ReleaseState,
    RunState,
    TestRun,
)


def create_release(
    project: Project, actor, *, name: str, target_date: date | None = None
) -> Release:
    name = name.strip()
    if not name:
        raise ServiceError("Give the release a name, such as 2.4.1.")
    if Release.objects.filter(project=project, name=name).exists():
        raise ServiceError(f"Release {name} already exists in this project.")
    with transaction.atomic():
        release = Release.objects.create(
            org_id=project.org_id,
            project=project,
            name=name,
            target_date=target_date,
            created_by=actor,
        )
        audit.record("release.created", "release", release.pk, actor=actor, after={"name": name})
    return release


def start_run(
    release: Release, plan_version: PlanVersion, actor, *, build: str = "", environment: str = ""
) -> TestRun:
    """A run is fixed to one published plan version for life; every case starts Not run."""
    if plan_version.state == VersionState.DRAFT:
        raise ServiceError("Runs use a published plan version, not a draft.")
    if plan_version.plan.project_id != release.project_id:
        raise ServiceError("The plan and the release belong to different projects.")
    if release.state != ReleaseState.OPEN:
        raise ServiceError(f"Release {release.name} is not open, so it takes no new runs.")
    with transaction.atomic():
        run = TestRun.objects.create(
            org_id=release.org_id,
            project_id=release.project_id,
            display_no=next_number(release.project_id, release.org_id, CounterKind.TEST_RUN),
            release=release,
            plan_version=plan_version,
            build=build,
            environment=environment,
            created_by=actor,
        )
        for pointer in PlanVersionCase.objects.filter(plan_version=plan_version).order_by(
            "position"
        ):
            CaseResult.objects.create(
                org_id=release.org_id, run=run, case_revision_id=pointer.case_revision_id
            )
        audit.record(
            "run.started", "test_run", run.pk, actor=actor, after={"release": release.name}
        )
    return run


def record_result(result: CaseResult, actor, outcome: str, note: str = "") -> CaseResult:
    """Save a result at once; latest write wins and the old outcome goes to the audit log."""
    if outcome not in Outcome.values:
        raise ServiceError("Choose Passed, Failed, Blocked or Not run.")
    if result.run.state == RunState.COMPLETE:
        raise ServiceError(
            "This run is complete, so its results can no longer change.", code="complete"
        )
    if result.outcome == outcome and result.note == note:
        return result  # a retried save: nothing to do, nothing to audit
    with transaction.atomic():
        before = result.outcome
        result.outcome = outcome
        result.note = note
        result.recorded_by = actor
        result.recorded_at = timezone.now()
        result.save(update_fields=["outcome", "note", "recorded_by", "recorded_at", "updated_at"])
        audit.record(
            "result.recorded",
            "case_result",
            result.pk,
            actor=actor,
            before={"outcome": before},
            after={"outcome": outcome},
        )
    return result


# Files still being scanned can be linked; files found unsafe or of the wrong type cannot.
LINKABLE_FILE_STATES = (FileState.PENDING, FileState.SCANNING, FileState.AVAILABLE)


def attach_evidence(
    project: Project,
    actor,
    file_ids: Iterable[UUID],
    targets: Iterable[tuple[str, UUID]],
    *,
    environment: str = "",
) -> list[Evidence]:
    """Turn uploaded files into evidence (EV-nnnn) and link each to every target."""
    file_ids = list(dict.fromkeys(file_ids))
    files = {f.pk: f for f in StoredFile.objects.filter(project=project, pk__in=file_ids)}
    if not file_ids or len(files) != len(file_ids):
        raise ServiceError("Attach evidence: a screenshot, recording or log.", code="evidence")
    if any(f.state not in LINKABLE_FILE_STATES for f in files.values()):
        raise ServiceError("One of the files was refused. Upload it again or choose another.")
    targets = list(targets)
    if any(kind not in EvidenceTarget.values for kind, _ in targets):
        raise ServiceError("Evidence can support results, runs, defects and retests.")
    created: list[Evidence] = []
    with transaction.atomic():
        for file_id in file_ids:
            stored = files[file_id]
            evidence = Evidence.objects.create(
                org_id=project.org_id,
                project=project,
                display_no=next_number(project.pk, project.org_id, CounterKind.EVIDENCE),
                file=stored,
                mime=stored.declared_mime,
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
                environment=environment,
                created_by=actor,
            )
            for kind, target_id in targets:
                EvidenceLink.objects.create(
                    org_id=project.org_id, evidence=evidence, target_type=kind, target_id=target_id
                )
            audit.record(
                "evidence.attached",
                "evidence",
                evidence.pk,
                actor=actor,
                after={"targets": [f"{k}:{t}" for k, t in targets]},
            )
            created.append(evidence)
    return created


def cancel_release(release: Release, actor) -> Release:
    if release.state == ReleaseState.SIGNED_OFF:
        raise ServiceError("A signed-off release cannot be cancelled.", code="conflict")
    if release.state == ReleaseState.CANCELLED:
        return release
    with transaction.atomic():
        release.state = ReleaseState.CANCELLED
        release.save(update_fields=["state", "updated_at"])
        audit.record(
            "release.cancelled",
            "release",
            release.pk,
            actor=actor,
            before={"state": ReleaseState.OPEN},
            after={"state": ReleaseState.CANCELLED},
        )
    return release


def failures_missing_evidence(run: TestRun) -> list[CaseResult]:
    """Failed results of this run with no evidence attached (FR-RUN-05)."""
    linked = EvidenceLink.objects.filter(
        target_type=EvidenceTarget.CASE_RESULT, target_id=OuterRef("pk")
    )
    return list(
        CaseResult.objects.filter(run=run, outcome=Outcome.FAILED)
        .filter(~Exists(linked))
        .select_related("case_revision__test_case")
        .order_by("created_at")
    )


class RunIncomplete(ServiceError):
    """The run cannot be completed yet; `missing` are the failed results without evidence."""

    def __init__(self, missing: list[CaseResult]):
        n = len(missing)
        super().__init__(
            f"{n} failed {'result has' if n == 1 else 'results have'} no evidence. "
            "Attach evidence to each before completing the run.",
            code="evidence",
        )
        self.missing = missing


def complete_run(run: TestRun, actor) -> TestRun:
    """A run cannot be marked complete while failed cases have no evidence (FR-RUN-05)."""
    if run.state == RunState.COMPLETE:
        return run
    missing = failures_missing_evidence(run)
    if missing:
        raise RunIncomplete(missing)
    with transaction.atomic():
        run.state = RunState.COMPLETE
        run.save(update_fields=["state", "updated_at"])
        audit.record(
            "run.completed",
            "test_run",
            run.pk,
            actor=actor,
            before={"state": RunState.IN_PROGRESS},
            after={"state": RunState.COMPLETE},
        )
    return run
