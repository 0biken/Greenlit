"""Background jobs for the Inbox (ARCH §6). Each runs for one organisation, in its scope;
Celery beat queues them for every organisation with `for_each_org` (see CELERY_BEAT_SCHEDULE).
"""

from apps.core.jobs import job_handler
from apps.inbox import reminders


@job_handler("reminders", max_retries=3)
def reminders_job(job) -> None:
    """Every 15 minutes: escalate fixes left waiting, and alert on critical items at once."""
    told = reminders.run_reminders(job.org_id)
    job.set_progress(1, 1, f"{sum(told.values())} told")


@job_handler("digest", max_retries=3)
def digest_job(job) -> None:
    """Hourly: send the daily digest to whoever's local time has reached 07:00."""
    sent = reminders.run_digest(job.org_id)
    job.set_progress(1, 1, f"{sent} sent")
