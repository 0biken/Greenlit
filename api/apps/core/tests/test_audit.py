"""The append-only audit log (M1-12, DATA §10)."""

import datetime
import uuid

import pytest
from django.db import DatabaseError, connection, transaction

from apps.core.audit import changed_fields, record
from apps.core.models import AuditEvent, Organisation, User
from apps.core.tenancy import org_scope, set_scope

pytestmark = pytest.mark.django_db


def make_org(name: str) -> Organisation:
    org_id = uuid.uuid4()
    with org_scope(org_id):
        return Organisation.objects.create(id=org_id, name=name, slug=name.lower())


def as_app_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


def test_changed_fields_keeps_only_what_changed():
    before = {"qa_status": "not_retested", "title": "Same", "severity": "high"}
    after = {"qa_status": "verified", "title": "Same", "severity": "high"}
    assert changed_fields(before, after) == (
        {"qa_status": "not_retested"},
        {"qa_status": "verified"},
    )


def test_changed_fields_handles_added_and_removed_keys():
    assert changed_fields({"a": 1}, {"b": 2}) == ({"a": 1}, {"b": 2})
    assert changed_fields({}, {}) == ({}, {})


def test_record_writes_an_event_in_the_current_organisation():
    org = make_org("Audit")
    user = User.objects.create_user("auditor@example.com", "x" * 14)
    with org_scope(org.id):
        event = record(
            "defect.qa_status_changed",
            "defect",
            "BUG-1042",
            actor=user,
            before={"qa_status": "not_retested", "title": "T"},
            after={"qa_status": "verified", "title": "T"},
        )
        stored = AuditEvent.objects.get(id=event.id)
    assert stored.org_id == org.id
    assert stored.actor_id == user.id
    assert (stored.action, stored.target_type, stored.target_id) == (
        "defect.qa_status_changed",
        "defect",
        "BUG-1042",
    )
    assert stored.before == {"qa_status": "not_retested"}
    assert stored.after == {"qa_status": "verified"}


def test_record_refuses_to_run_without_an_organisation_scope():
    with pytest.raises(RuntimeError, match="organisation scope"):
        record("x", "y", "z")


def test_values_like_uuids_and_datetimes_are_stored_as_json():
    org = make_org("Audit2")
    when = datetime.datetime(2026, 10, 5, 12, 0, tzinfo=datetime.UTC)
    with org_scope(org.id):
        event = record("plan.approved", "plan", "TP-3", after={"by": uuid.uuid4(), "at": when})
        stored = AuditEvent.objects.get(id=event.id)
    assert stored.after["at"].startswith("2026-10-05T12:00:00")


def test_the_app_role_can_append_and_read_but_not_change_or_delete():
    org = make_org("Audit3")
    with org_scope(org.id):
        event = record("a", "t", "1", after={"k": "v"})
    as_app_role()
    set_scope(org.id)
    assert AuditEvent.objects.filter(id=event.id).exists()
    record("b", "t", "2")  # appending still works
    with pytest.raises(DatabaseError, match="permission denied"), transaction.atomic():
        AuditEvent.objects.filter(id=event.id).update(action="tampered")
    with pytest.raises(DatabaseError, match="permission denied"), transaction.atomic():
        AuditEvent.objects.filter(id=event.id).delete()


def test_even_the_owner_role_cannot_change_or_delete_events():
    """A trigger refuses UPDATE and DELETE for every role, not only the restricted one."""
    org = make_org("Audit4")
    with org_scope(org.id):
        event = record("a", "t", "1")
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
            AuditEvent.objects.filter(id=event.id).update(action="tampered")
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
            AuditEvent.objects.filter(id=event.id).delete()
        assert AuditEvent.objects.get(id=event.id).action == "a"


def test_events_of_other_organisations_are_invisible():
    mine, theirs = make_org("Mine"), make_org("Theirs")
    with org_scope(theirs.id):
        record("secret", "t", "1")
    with org_scope(mine.id):
        record("ordinary", "t", "2")
    as_app_role()
    set_scope(mine.id)
    assert list(AuditEvent.objects.values_list("action", flat=True)) == ["ordinary"]
