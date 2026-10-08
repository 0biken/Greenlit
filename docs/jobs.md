# Background jobs

Anything slow runs in the background, one organisation at a time (TASKS M1-17, ARCH §6). Code: `api/apps/core/jobs.py`. Tests: `api/apps/core/tests/test_jobs.py`.

## Writing a job

```python
from apps.core.jobs import JobFailure, enqueue, job_handler


@job_handler("scan_file", max_retries=3)
def scan_file(job, file_id):
    job.set_progress(1, 3, "Scanning")  # visible to the browser straight away
    if not supported(file_id):
        raise JobFailure("This file type is not supported.")  # no retry; shown to people
    ...


# In a request or a service, inside the organisation's scope:
enqueue("scan_file", org_id=org.id, user=request.user, file_id=str(f.id))
```

- `args` must be JSON values and IDs only. Never put document text in them.
- The job is sent when the surrounding transaction commits, so it never runs against data that was rolled back.
- The handler runs inside the organisation's scope; the database refuses anything else.
- The handler is not wrapped in one transaction. Use `transaction.atomic()` around steps that must succeed or fail together.

## What happens on failure

| Raised | Result |
| --- | --- |
| `JobFailure("message")` | Stops at once, state `dead`, the message is shown to people |
| Any other exception | Reported to Sentry (scrubbed), state `failed`, retried after 10 s, 20 s, 40 s... up to 10 minutes; after `max_retries` it is `dead` and `error` holds only the exception's class name |

A job delivered twice is run once. A job marked `running` whose worker has not reported for 30 minutes is taken over, so a crashed worker does not strand it.

## API

| Call | Who | Purpose |
| --- | --- | --- |
| `GET /api/jobs/` (`?state=dead`) | Every member | The newest 100 jobs; `args` are never shown |
| `GET /api/jobs/{id}/` | Every member | Poll progress (decision 010: polling for now) |
| `POST /api/jobs/{id}/rerun/` | Owners and admins | Start a failed or dead job again; audited |

## Schedules

`for_each_org(kind)` queues one `kind` job per organisation, reading `org_registry`, a table of organisation IDs only that a database trigger fills. Point Celery beat at it for reminders and digests (M6).

## Running locally

`CELERY_TASK_ALWAYS_EAGER` is on in local settings, so jobs run inline when the request commits and no Redis or worker is needed. Retries then also run straight away, without the wait.
