"""Background jobs (M1-17, ARCH §6). Jobs run inline here (CELERY_TASK_ALWAYS_EAGER), so
`django_capture_on_commit_callbacks(execute=True)` stands in for the worker picking them up."""

import threading
import uuid
from datetime import timedelta

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.utils import timezone

from apps.core import jobs
from apps.core.jobs import JobFailure, backoff_seconds, enqueue, job_handler, run_job
from apps.core.models import (
    AuditEvent,
    Job,
    JobState,
    Membership,
    MembershipStatus,
    Organisation,
    OrgRegistry,
    Project,
    Role,
    User,
)
from apps.core.tenancy import get_scope, org_scope

CALLS: list[dict] = []
FLAKY = {"failures_left": 0}


@job_handler("test.record", max_retries=0)
def record(job, **args):
    CALLS.append(
        {
            "job": job.pk,
            "args": args,
            "projects": sorted(Project.objects.values_list("key", flat=True)),
        }
    )
    job.set_progress(1, 1, "Done")


@job_handler("test.flaky", max_retries=3)
def flaky(job):
    if FLAKY["failures_left"] > 0:
        FLAKY["failures_left"] -= 1
        raise RuntimeError("the PRD says something confidential")


@job_handler("test.broken", max_retries=2)
def broken(job):
    raise RuntimeError("the PRD says something confidential")


@job_handler("test.refuse", max_retries=3)
def refuse(job):
    raise JobFailure("This file type is not supported.")


@pytest.fixture(autouse=True)
def reset_recorders():
    CALLS.clear()
    FLAKY["failures_left"] = 0


def make_org(slug: str) -> Organisation:
    org_id = uuid.uuid4()
    with org_scope(org_id):
        org = Organisation.objects.create(id=org_id, name=slug.title(), slug=slug)
        Project.objects.create(org_id=org.id, name=f"{slug} app", key=slug[:4].upper())
    return org


def as_app_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


def job(queued: Job) -> Job:
    """The job as stored now, read in its own organisation's scope."""
    with org_scope(queued.org_id):
        return Job.objects.get(pk=queued.pk)


# --- Running --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_job_runs_inside_its_organisations_scope_only(django_capture_on_commit_callbacks):
    make_org("bravo")
    alpha = make_org("alpha")
    as_app_role()
    with django_capture_on_commit_callbacks(execute=True):
        queued = enqueue("test.record", org_id=alpha.id, file_id="F-1")
    done = job(queued)
    assert (done.state, done.attempts, done.error) == (JobState.SUCCEEDED, 1, "")
    assert done.progress == {"done": 1, "total": 1, "label": "Done"}
    assert done.started_at and done.finished_at
    # The handler saw its own organisation's project and nothing of Bravo's.
    assert CALLS == [{"job": queued.pk, "args": {"file_id": "F-1"}, "projects": ["ALPH"]}]


@pytest.mark.django_db
def test_the_scope_is_cleared_after_a_job_whatever_happened(django_capture_on_commit_callbacks):
    org = make_org("clean")
    as_app_role()
    before = get_scope()
    with django_capture_on_commit_callbacks(execute=True):
        enqueue("test.record", org_id=org.id)
        enqueue("test.broken", org_id=org.id)
    assert get_scope() == before


@pytest.mark.django_db
def test_failed_attempts_are_retried_until_one_succeeds(django_capture_on_commit_callbacks):
    org = make_org("retry")
    FLAKY["failures_left"] = 2
    as_app_role()
    with django_capture_on_commit_callbacks(execute=True):
        queued = enqueue("test.flaky", org_id=org.id)
    done = job(queued)
    assert (done.state, done.attempts, done.error) == (JobState.SUCCEEDED, 3, "")


@pytest.mark.django_db
def test_a_job_gives_up_after_its_retries_and_records_only_the_error_class(
    django_capture_on_commit_callbacks,
):
    org = make_org("dead")
    as_app_role()
    with django_capture_on_commit_callbacks(execute=True):
        queued = enqueue("test.broken", org_id=org.id)
    done = job(queued)
    assert (done.state, done.attempts) == (JobState.DEAD, 3)  # first try plus 2 retries
    assert done.error == "RuntimeError"  # never the message, which could quote a document
    assert done.finished_at is not None


@pytest.mark.django_db
def test_a_failure_retrying_cannot_fix_stops_at_once_with_its_message(
    django_capture_on_commit_callbacks,
):
    org = make_org("refused")
    as_app_role()
    with django_capture_on_commit_callbacks(execute=True):
        queued = enqueue("test.refuse", org_id=org.id)
    done = job(queued)
    assert (done.state, done.attempts, done.error) == (
        JobState.DEAD,
        1,
        "This file type is not supported.",
    )


@pytest.mark.django_db
def test_running_a_job_twice_does_the_work_once(django_capture_on_commit_callbacks):
    org = make_org("twice")
    as_app_role()
    with django_capture_on_commit_callbacks(execute=True):
        queued = enqueue("test.record", org_id=org.id)
    run_job(str(queued.pk), str(org.id))  # the queue delivers it again
    assert len(CALLS) == 1


@pytest.mark.django_db
def test_a_job_cannot_be_run_under_another_organisation():
    alpha, bravo = make_org("owner"), make_org("thief")
    as_app_role()
    queued = enqueue("test.record", org_id=alpha.id)  # not dispatched: no commit here
    run_job(str(queued.pk), str(bravo.id))
    assert CALLS == [] and job(queued).state == JobState.QUEUED
    run_job(str(queued.pk), str(alpha.id))
    assert len(CALLS) == 1


@pytest.mark.django_db
def test_a_running_job_is_left_alone_unless_its_worker_has_gone_quiet_for_30_minutes():
    org = make_org("stale")
    as_app_role()
    queued = enqueue("test.record", org_id=org.id)

    def last_heard(minutes_ago: int) -> None:
        with org_scope(org.id):
            Job.objects.filter(pk=queued.pk).update(
                state=JobState.RUNNING, updated_at=timezone.now() - timedelta(minutes=minutes_ago)
            )

    last_heard(29)
    run_job(str(queued.pk), str(org.id))
    assert CALLS == []  # another worker still has it

    last_heard(31)
    run_job(str(queued.pk), str(org.id))
    assert len(CALLS) == 1 and job(queued).state == JobState.SUCCEEDED


@pytest.mark.django_db
def test_only_registered_kinds_can_be_queued():
    org = make_org("kinds")
    with pytest.raises(ValueError, match="Unknown job kind"):
        enqueue("no.such.kind", org_id=org.id)


def test_retries_wait_longer_each_time_up_to_ten_minutes():
    assert [backoff_seconds(n) for n in range(1, 9)] == [10, 20, 40, 80, 160, 320, 600, 600]


def test_a_kind_cannot_be_registered_twice():
    with pytest.raises(ValueError, match="already registered"):
        job_handler("test.record")(lambda job: None)


# --- Progress is visible while the job runs ----------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_progress_can_be_read_from_another_connection_while_the_job_runs():
    org = make_org("live")
    seen: dict = {}

    @job_handler(f"test.watch.{uuid.uuid4().hex}", max_retries=0)
    def watched(job):
        job.set_progress(2, 5, "Reading pages 1 to 12")

        def poll():  # what the browser's polling request would see, on its own connection
            try:
                with org_scope(org.id):
                    seen["progress"] = Job.objects.get(pk=job.pk).progress
            finally:
                connection.close()

        thread = threading.Thread(target=poll)
        thread.start()
        thread.join()
        raise JobFailure("Stopped on purpose.")

    kind = next(k for k, h in jobs.HANDLERS.items() if h.fn is watched)
    with transaction.atomic():
        queued = enqueue(kind, org_id=org.id)
    assert seen["progress"] == {"done": 2, "total": 5, "label": "Reading pages 1 to 12"}
    assert job(queued).progress["done"] == 2  # kept although the job then failed


# --- Per-organisation schedules ---------------------------------------------------------------


@pytest.mark.django_db
def test_every_new_organisation_is_registered_for_schedules():
    org = make_org("registered")
    assert OrgRegistry.objects.filter(organisation_id=org.id).exists()


@pytest.mark.django_db
def test_the_app_can_read_the_registry_but_never_change_it():
    make_org("readonly")
    as_app_role()
    assert OrgRegistry.objects.count() >= 1
    with pytest.raises(DatabaseError, match="permission denied"), transaction.atomic():
        OrgRegistry.objects.create(organisation_id=uuid.uuid4())
    with pytest.raises(DatabaseError, match="permission denied"), transaction.atomic():
        OrgRegistry.objects.all().delete()


@pytest.mark.django_db
def test_a_schedule_fans_out_one_job_per_organisation_each_in_its_own_scope(
    django_capture_on_commit_callbacks,
):
    first, second = make_org("first"), make_org("second")
    as_app_role()
    with django_capture_on_commit_callbacks(execute=True):
        count = jobs.for_each_org("test.record")
    assert count == OrgRegistry.objects.count() >= 2
    seen = sorted(tuple(call["projects"]) for call in CALLS)
    assert ("FIRS",) in seen and ("SECO",) in seen
    assert all(len(projects) == 1 for projects in seen)  # nobody saw another tenant's project
    for org in (first, second):
        with org_scope(org.id):
            assert Job.objects.filter(kind="test.record", state=JobState.SUCCEEDED).count() == 1


# --- The API ----------------------------------------------------------------------------------


def member(org: Organisation, role: str) -> Client:
    user = User.objects.create_user(f"{role}-{org.slug}@example.com", "x" * 14)
    with org_scope(org.id):
        Membership.objects.create(
            org_id=org.id, user=user, role=role, status=MembershipStatus.ACTIVE
        )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def dead_job(django_capture_on_commit_callbacks):
    org = make_org("jobsapi")
    with django_capture_on_commit_callbacks(execute=True):
        queued = enqueue("test.broken", org_id=org.id)
    return org, queued


@pytest.mark.django_db
def test_members_can_follow_jobs_without_seeing_their_arguments(dead_job):
    org, queued = dead_job
    as_app_role()
    viewer = member(org, Role.VIEWER)
    listed = viewer.get("/api/jobs/", headers={"X-Org": org.slug}).json()
    assert [j["id"] for j in listed] == [str(queued.pk)]
    detail = viewer.get(f"/api/jobs/{queued.pk}/", headers={"X-Org": org.slug}).json()
    assert detail["state"] == "dead" and "args" not in detail
    dead = viewer.get("/api/jobs/?state=dead", headers={"X-Org": org.slug}).json()
    assert len(dead) == 1
    assert viewer.get("/api/jobs/?state=nonsense", headers={"X-Org": org.slug}).status_code == 400


@pytest.mark.django_db
def test_an_admin_reruns_a_dead_job_and_it_is_audited(dead_job, django_capture_on_commit_callbacks):
    org, queued = dead_job
    FLAKY["failures_left"] = 0
    as_app_role()
    admin = member(org, Role.ADMIN)
    with org_scope(org.id):  # make it a job that will now succeed
        Job.objects.filter(pk=queued.pk).update(kind="test.flaky")
    with django_capture_on_commit_callbacks(execute=True):
        response = admin.post(f"/api/jobs/{queued.pk}/rerun/", headers={"X-Org": org.slug})
    assert response.status_code == 202
    assert job(queued).state == JobState.SUCCEEDED
    with org_scope(org.id):
        event = AuditEvent.objects.get(action="job.rerun")
    assert event.before == {"state": "dead"} and event.after == {"state": "queued"}


@pytest.mark.django_db
def test_a_job_that_succeeded_cannot_be_rerun(django_capture_on_commit_callbacks):
    org = make_org("finished")
    with django_capture_on_commit_callbacks(execute=True):
        queued = enqueue("test.record", org_id=org.id)
    as_app_role()
    response = member(org, Role.OWNER).post(
        f"/api/jobs/{queued.pk}/rerun/", headers={"X-Org": org.slug}
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_only_owners_and_admins_can_rerun(dead_job):
    org, queued = dead_job
    as_app_role()
    lead = member(org, Role.QA_LEAD)
    assert (
        lead.post(f"/api/jobs/{queued.pk}/rerun/", headers={"X-Org": org.slug}).status_code == 403
    )


@pytest.mark.django_db
def test_another_organisations_job_is_not_found(dead_job):
    org, queued = dead_job
    other = make_org("elsewhere")
    as_app_role()
    outsider = member(other, Role.OWNER)
    headers = {"X-Org": other.slug}
    assert outsider.get(f"/api/jobs/{queued.pk}/", headers=headers).status_code == 404
    assert outsider.post(f"/api/jobs/{queued.pk}/rerun/", headers=headers).status_code == 404
