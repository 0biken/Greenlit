"""Organisation scope for the database (DATA §8 rule 2, ARCH §4: `core` owns tenancy).

Row-level security reads `app.org_id` and `app.user_id`. Both are set with `set_config(..., true)`,
so they last only for the current transaction. Requests run in one transaction
(`ATOMIC_REQUESTS`), and jobs must use `org_scope`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import connection, transaction


def set_scope(
    org_id: UUID | str | None,
    user_id: UUID | str | None = None,
    invite_hash: str | None = None,
) -> None:
    """Set the scope for the current transaction. Must be called inside one.

    `invite_hash` lets the holder of an invitation token read that one invitation before they
    belong to the organisation (see migration 0008).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.org_id', %s, true), set_config('app.user_id', %s, true), "
            "set_config('app.invite_hash', %s, true)",
            [str(org_id) if org_id else "", str(user_id) if user_id else "", invite_hash or ""],
        )


def get_scope() -> tuple[str, str, str]:
    """The current (org_id, user_id, invite_hash); empty strings where unset."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT coalesce(current_setting('app.org_id', true), ''), "
            "coalesce(current_setting('app.user_id', true), ''), "
            "coalesce(current_setting('app.invite_hash', true), '')"
        )
        org_id, user_id, invite_hash = cursor.fetchone()
    return org_id, user_id, invite_hash


def restore_scope(previous: tuple[str, str, str]) -> None:
    """Put back a scope saved by `get_scope`, unless the transaction is already failing.

    After an error the enclosing atomic block rolls back, and Postgres reverts local settings
    with it, so there is nothing to restore (and running a query would raise a second error).
    """
    if not connection.needs_rollback:
        set_scope(*previous)


@contextmanager
def org_scope(org_id: UUID | str, user_id: UUID | str | None = None) -> Iterator[None]:
    """Run a block (a job, a script) inside one organisation's scope.

    The previous scope is restored on exit, so blocks can nest.
    """
    with scoped(org_id, user_id):
        yield


@contextmanager
def scoped(
    org_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
    invite_hash: str | None = None,
) -> Iterator[None]:
    """Run a block with any part of the scope set or left unset. Restores on normal exit."""
    with transaction.atomic():
        previous = get_scope()
        set_scope(org_id, user_id, invite_hash)
        yield
        restore_scope(previous)


@contextmanager
def worker_scope(org_id: UUID | str) -> Iterator[None]:
    """Hold one organisation's scope on this connection for a whole background job.

    Unlike `org_scope` this is not one transaction: the job can commit as it goes, so its
    progress is visible while it runs. The scope is always cleared afterwards, so the next job
    on this worker starts with none. Only for job runners (apps/core/jobs.py).
    """
    previous = get_scope()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.org_id', %s, false), set_config('app.user_id', '', false), "
            "set_config('app.invite_hash', '', false)",
            [str(org_id)],
        )
    try:
        yield
    finally:
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.org_id', %s, false), "
                    "set_config('app.user_id', %s, false), "
                    "set_config('app.invite_hash', %s, false)",
                    list(previous),
                )
