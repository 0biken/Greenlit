from celery import shared_task


@shared_task
def ping() -> str:
    """Smoke-test job: proves the queue and workers are wired up (M0-05)."""
    return "pong"
