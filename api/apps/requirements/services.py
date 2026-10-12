"""Requirement rules (M2-03, M2-08). Reading is in `queries.py`."""

from django.db import transaction

from apps.core import audit
from apps.core.choices import Origin, Priority, ReviewState
from apps.core.models import CounterKind, Project
from apps.core.numbering import next_number
from apps.core.services import ServiceError
from apps.requirements.models import Requirement, RequirementRevision

EDITABLE = ("title", "text", "priority")


def _check(title: str | None = None, text: str | None = None, priority: str | None = None) -> None:
    if title is not None and not title.strip():
        raise ServiceError("Give the requirement a title.")
    if title is not None and len(title) > 200:
        raise ServiceError("Keep the title to 200 characters.")
    if text is not None and not text.strip():
        raise ServiceError("Say what must be true: the requirement's text is empty.")
    if priority is not None and priority not in Priority.values:
        raise ServiceError("Choose a priority: Critical, High, Medium or Low.")


def keep_revision(requirement: Requirement, actor=None) -> RequirementRevision:
    """Make sure the requirement's current text is on record as its current revision."""
    row, _ = RequirementRevision.objects.get_or_create(
        requirement=requirement,
        revision=requirement.revision,
        defaults={
            "org_id": requirement.org_id,
            "text": requirement.text,
            "source_locator": requirement.source_locator,
            "created_by": actor if getattr(actor, "pk", None) else None,
        },
    )
    return row


def create_requirement(
    project: Project,
    actor,
    *,
    title: str,
    text: str,
    priority: str = Priority.MEDIUM,
    review_state: str = ReviewState.ACCEPTED,
    origin: str = Origin.HUMAN,
) -> Requirement:
    _check(title, text, priority)
    with transaction.atomic():
        requirement = Requirement.objects.create(
            org_id=project.org_id,
            project=project,
            display_no=next_number(project.pk, project.org_id, CounterKind.REQUIREMENT),
            title=title.strip(),
            text=text,
            priority=priority,
            review_state=review_state,
            origin=origin,
            created_by=actor,
        )
        keep_revision(requirement, actor)
        audit.record(
            "requirement.created",
            "requirement",
            requirement.pk,
            actor=actor,
            after={"display_no": requirement.display_no, "review_state": review_state},
        )
    return requirement


def change_text(requirement: Requirement, actor, text: str) -> Requirement:
    """A text change raises `revision`, which makes cases written against the old text Stale.
    The old text stays on record as the old revision (G-07)."""
    if text == requirement.text:
        return requirement
    _check(text=text)
    with transaction.atomic():
        before = requirement.revision
        keep_revision(requirement)  # for requirements made before revisions were kept
        requirement.text = text
        requirement.revision = before + 1
        requirement.save(update_fields=["text", "revision", "updated_at"])
        keep_revision(requirement, actor)
        audit.record(
            "requirement.text_changed",
            "requirement",
            requirement.pk,
            actor=actor,
            before={"revision": before},
            after={"revision": requirement.revision},
        )
    return requirement


def update_requirement(requirement: Requirement, actor, **changes) -> Requirement:
    """Edit a requirement's title, priority or text. The audit entry names what changed and
    never copies the text; the text's own history is in `requirement_revision`."""
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ServiceError(f"Cannot change: {', '.join(sorted(unknown))}.")
    _check(changes.get("title"), changes.get("text"), changes.get("priority"))
    if "title" in changes:
        changes["title"] = changes["title"].strip()
    with transaction.atomic():
        fields = [
            name
            for name in ("title", "priority")
            if name in changes and getattr(requirement, name) != changes[name]
        ]
        if fields:
            before = {"priority": requirement.priority}
            for name in fields:
                setattr(requirement, name, changes[name])
            requirement.save(update_fields=[*fields, "updated_at"])
            audit.record(
                "requirement.edited",
                "requirement",
                requirement.pk,
                actor=actor,
                before=before,
                after={"priority": requirement.priority, "fields": sorted(fields)},
            )
        if "text" in changes:
            change_text(requirement, actor, changes["text"])
    return requirement
