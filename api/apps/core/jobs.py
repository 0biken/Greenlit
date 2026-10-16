"""Background jobs, one organisation at a time (M1-17, ARCH §6, SEC §5).

    @job_handler("scan_file", max_retries=3)
    def scan_file(job, file_id):
        job.set_progress(1, 3, "Scanning")
        ...

    enqueue("scan_file", org_id=org.id, user=request.user, file_id=str(f.id))

Every job:
- carries one `org_id` and runs inside that organisation's scope, so it cannot read another
  tenant's rows (the database refuses);
- is safe to run twice: a job that already succeeded or gave up is skipped;
- retries with growing delays, then ends `dead`, where an admin can re-run it;
- records an error class, or a message written for people (`JobFailure`), never content;
- reports progress the browser can poll while it runs.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import sentry_sdk
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.core.models import Job, JobState, OrgRegistry
from apps.core.tenancy import org_scope, worker_scope

log = logging.getLogger("greenlit.jobs")

MAX_BACKOFF_SECONDS = 600
# A running job that has not reported for this long is taken to belong to a dead worker.
STALE_RUNNING_AFTER = timedelta(minutes=30)


class JobFailure(Exception):
    """A failure that retrying will not fix. Its message is shown to people, so it must not
    contain document text."""

    def __init__(self, safe_message: str):
        super().__init__(safe_message)
        self.safe_message = safe_message[:300]


@dataclass(frozen=True)
class Handler:
    fn: Callable[..., None]
    max_retries: int


HANDLERS: dict[str, Handler] = {}


def job_handler(kind: str, max_retries: int = 3):
    def register(fn: Callable[..., None]) -> Callable[..., None]:
        if kind in HANDLERS:
            raise ValueError(f"Job kind {kind!r} is already registered")
        HANDLERS[kind] = Handler(fn, max_retries)
        return fn

    return register


def backoff_seconds(attempt: int) -> int:
    """10 s, 20 s, 40 s ... capped at 10 minutes."""
    return min(10 * 2 ** max(attempt - 1, 0), MAX_BACKOFF_SECONDS)


def enqueue(kind: str, *, org_id: UUID | str, user=None, **args) -> Job:
    """Record a job and send it once the surrounding transaction commits.

    `args` must be JSON values and IDs only.
    """
    if kind not in HANDLERS:
        raise ValueError(f"Unknown job kind {kind!r}")
    with org_scope(org_id):
        job = Job.objects.create(
            org_id=org_id,
            kind=kind,
            args=args,
            created_by=user if getattr(user, "pk", None) else None,
        )
    job_id, org = str(job.pk), str(org_id)
    transaction.on_commit(lambda: run_job.delay(job_id, org))
    return job


def set_progress(job: Job, done: int, total: int, label: str = "") -> None:
    """Saved straight away, so the browser sees it while the job is still running."""
    job.progress = {"done": done, "total": total, "label": label[:120]}
    Job.objects.filter(pk=job.pk).update(progress=job.progress, updated_at=timezone.now())


Job.set_progress = set_progress  # type: ignore[attr-defined]


@shared_task(name="greenlit.run_job")
def run_job(job_id: str, org_id: str) -> None:
    with worker_scope(org_id):
        with transaction.atomic():
            job = Job.objects.select_for_update().filter(pk=job_id).first()
            if job is None:
                # Wrong organisation, or deleted: either way there is nothing to run here.
                log.warning("job not found in scope", extra={"job_id": job_id, "org_id": org_id})
                return
            if job.state in (JobState.SUCCEEDED, JobState.DEAD):
                return  # delivered twice, or already finished
            if (
                job.state == JobState.RUNNING
                and job.updated_at > timezone.now() - STALE_RUNNING_AFTER
            ):
                return  # another worker has it
            handler = HANDLERS.get(job.kind)
            job.state, job.attempts = JobState.RUNNING, job.attempts + 1
            job.started_at = job.started_at or timezone.now()
            job.save(update_fields=["state", "attempts", "started_at", "updated_at"])

        try:
            if handler is None:
                raise JobFailure(f"No handler for job kind {job.kind!r}")
            handler.fn(job, **job.args)
        except JobFailure as failure:
            _finish(job, JobState.DEAD, failure.safe_message)
            return
        except Exception as exc:  # noqa: BLE001 (any failure is recorded, then retried)
            sentry_sdk.capture_exception(exc)
            error = type(exc).__name__
            if job.attempts <= handler.max_retries:  # type: ignore[union-attr]
                _finish(job, JobState.FAILED, error, finished=False)
                retry = backoff_seconds(job.attempts)
                log.info("job retry", extra={"job_id": job_id, "in_seconds": retry})
                run_job.apply_async((job_id, org_id), countdown=retry)
            else:
                _finish(job, JobState.DEAD, error)
            return
        _finish(job, JobState.SUCCEEDED, "")


def _finish(job: Job, state: str, error: str, finished: bool = True) -> None:
    job.state, job.error = state, error
    job.finished_at = timezone.now() if finished else None
    Job.objects.filter(pk=job.pk).update(
        state=state, error=error, finished_at=job.finished_at, updated_at=timezone.now()
    )


def rerun(job: Job) -> bool:
    """Queue a failed or dead job again. Returns False if it is not in a state to re-run."""
    if job.state == JobState.QUEUED:
        return True  # already waiting
    if job.state not in (JobState.FAILED, JobState.DEAD):
        return False
    Job.objects.filter(pk=job.pk).update(
        state=JobState.QUEUED, attempts=0, error="", finished_at=None, updated_at=timezone.now()
    )
    job_id, org_id = str(job.pk), str(job.org_id)
    transaction.on_commit(lambda: run_job.delay(job_id, org_id))
    return True


@shared_task(name="greenlit.for_each_org")
def for_each_org(kind: str, **args) -> int:
    """Enqueue one `kind` job per organisation; for schedules such as reminders (ARCH §6)."""
    count = 0
    for org_id in OrgRegistry.objects.values_list("organisation_id", flat=True):
        with transaction.atomic():
            enqueue(kind, org_id=org_id, **args)
        count += 1
    return count


# A failed job is waiting to be tried again, so to a person it is still running.
IN_HAND = (JobState.QUEUED, JobState.RUNNING, JobState.FAILED)


def describe(job: Job | None) -> dict | None:
    """What a screen shows about a job it is waiting on. `error` is only ever a message written
    for people (`JobFailure`), from a job that gave up; never a retried error's class name."""
    if job is None:
        return None
    progress = job.progress or {}
    return {
        "id": job.pk,
        "kind": job.kind,
        "state": job.state,
        "running": job.state in IN_HAND,
        "progress": progress.get("label", ""),
        "done": progress.get("done", 0),
        "total": progress.get("total", 0),
        "error": job.error if job.state == JobState.DEAD else "",
    }
