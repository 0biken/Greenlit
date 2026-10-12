"""Requirement rules (M2-03). The full screen and API arrive with M2-08."""

from django.db import transaction

from apps.core import audit
from apps.core.choices import Origin, Priority, ReviewState
from apps.core.models import CounterKind, Project
from apps.core.numbering import next_number
from apps.requirements.models import Requirement


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
    with transaction.atomic():
        requirement = Requirement.objects.create(
            org_id=project.org_id,
            project=project,
            display_no=next_number(project.pk, project.org_id, CounterKind.REQUIREMENT),
            title=title,
            text=text,
            priority=priority,
            review_state=review_state,
            origin=origin,
            created_by=actor,
        )
        audit.record(
            "requirement.created",
            "requirement",
            requirement.pk,
            actor=actor,
            after={"display_no": requirement.display_no, "review_state": review_state},
        )
    return requirement


def change_text(requirement: Requirement, actor, text: str) -> Requirement:
    """A text change raises `revision`, which makes cases written against the old text Stale."""
    if text == requirement.text:
        return requirement
    with transaction.atomic():
        before = requirement.revision
        requirement.text = text
        requirement.revision = before + 1
        requirement.save(update_fields=["text", "revision", "updated_at"])
        audit.record(
            "requirement.text_changed",
            "requirement",
            requirement.pk,
            actor=actor,
            before={"revision": before},
            after={"revision": requirement.revision},
        )
    return requirement
