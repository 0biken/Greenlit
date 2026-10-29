"""Requirement creation, editing, revision and review rules (M2-03, M2-08)."""

from django.db import transaction

from apps.core import audit
from apps.core.choices import Origin, Priority, ReviewState
from apps.core.models import CounterKind, Project
from apps.core.numbering import next_number
from apps.requirements.models import Requirement, SourceDocument


def create_requirement(
    project: Project,
    actor,
    *,
    title: str,
    text: str,
    priority: str = Priority.MEDIUM,
    review_state: str = ReviewState.ACCEPTED,
    origin: str = Origin.HUMAN,
    source_document: SourceDocument | None = None,
    source_locator: dict | None = None,
) -> Requirement:
    with transaction.atomic():
        requirement = Requirement.objects.create(
            org_id=project.org_id,
            project=project,
            source_document=source_document,
            display_no=next_number(project.pk, project.org_id, CounterKind.REQUIREMENT),
            title=title,
            text=text,
            priority=priority,
            review_state=review_state,
            origin=origin,
            source_locator=source_locator or {},
            created_by=actor,
        )
        audit.record(
            "requirement.created",
            "requirement",
            requirement.pk,
            actor=actor,
            after={
                "display_no": requirement.display_no,
                "review_state": review_state,
                "source_document_id": str(source_document.pk) if source_document else None,
            },
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


def update_requirement(
    requirement: Requirement,
    actor,
    *,
    title: str,
    text: str,
    priority: str,
) -> Requirement:
    """Edit a manual requirement; text changes increment revision for stale-case tracking."""
    before = {
        "priority": requirement.priority,
        "revision": requirement.revision,
        "title_changed": False,
        "text_changed": False,
    }
    title_changed = title != requirement.title
    text_changed = text != requirement.text
    fields = ["title", "priority"]
    requirement.title = title
    requirement.priority = priority
    if text_changed:
        requirement.text = text
        requirement.revision += 1
        fields.extend(["text", "revision"])
    if not title_changed and not text_changed and before["priority"] == priority:
        return requirement
    with transaction.atomic():
        requirement.save(update_fields=[*fields, "updated_at"])
        audit.record(
            "requirement.updated",
            "requirement",
            requirement.pk,
            actor=actor,
            before={
                "priority": before["priority"],
                "revision": before["revision"],
                "title_changed": False,
                "text_changed": False,
            },
            after={
                "priority": requirement.priority,
                "revision": requirement.revision,
                "title_changed": title_changed,
                "text_changed": text_changed,
            },
        )
    return requirement


def set_review_state(requirement: Requirement, actor, review_state: str) -> Requirement:
    if review_state == requirement.review_state:
        return requirement
    before = requirement.review_state
    with transaction.atomic():
        requirement.review_state = review_state
        requirement.save(update_fields=["review_state", "updated_at"])
        audit.record(
            f"requirement.{review_state}",
            "requirement",
            requirement.pk,
            actor=actor,
            before={"review_state": before},
            after={"review_state": review_state},
        )
    return requirement
