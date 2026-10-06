"""Writing to the append-only audit log (M1-12, DATA §10, FR-ORG-04).

Call `record(...)` in the same transaction as the change it describes, so the log and the data
cannot disagree. The organisation comes from the current database scope, never from the caller.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.core.models import AuditEvent
from apps.core.tenancy import get_scope


def changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[dict, dict]:
    """The (before, after) pair holding only fields whose value changed (DATA §10 rules)."""
    keys = [k for k in {*before, *after} if before.get(k) != after.get(k)]
    return (
        {k: before.get(k) for k in keys if k in before},
        {k: after.get(k) for k in keys if k in after},
    )


def record(
    action: str,
    target_type: str,
    target_id: Any,
    *,
    actor: Any = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
) -> AuditEvent:
    """Append one event. `before` and `after` are reduced to the changed fields.

    AI actions pass the model name and source record IDs in `after`, never prompt text.
    """
    org_id, *_ = get_scope()
    if not org_id:
        raise RuntimeError("Audit events need an organisation scope (use org_scope or a request)")
    old, new = changed_fields(before or {}, after or {})
    with transaction.atomic():
        return AuditEvent.objects.create(
            org_id=UUID(org_id),
            actor=actor if getattr(actor, "pk", None) else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            before=old,
            after=new,
        )
