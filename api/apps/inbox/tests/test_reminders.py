"""Reminders, critical alerts and the daily digest (M6-05, M6-06, M6-07, M5-07)."""

from datetime import UTC, datetime, timedelta

import pytest
from django.core import mail
from django.utils import timezone
from tests.lab import Lab, days_ago

from apps.core.jobs import HANDLERS, enqueue
from apps.core.models import Job, User
from apps.inbox.models import Notification
from apps.inbox.reminders import run_digest, run_reminders

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab():
    return Lab()


def told(lab):
    with lab.scope():
        return sorted((n.user.name, n.level) for n in Notification.objects.select_related("user"))


def remind(lab, now=None):
    with lab.scope():
        return run_reminders(lab.id, now)


def waiting(lab, days: float):
    return lab.backdate(lab.set(lab.defect(), "fixed"), fixed_at=days_ago(days))


LEADS = [("admin", "96h"), ("owner", "96h"), ("qa_lead", "96h")]


# --- Fixes left waiting (FR-INB-02) -


def test_nobody_is_told_before_48_hours(lab):
    waiting(lab, 1.9)
    assert remind(lab) == {"48h": 0, "96h": 0, "critical": 0}
    assert told(lab) == []


def test_after_48_hours_the_owner_is_reminded_and_it_tops_their_inbox(lab):
    waiting(lab, 2.1)
    assert remind(lab)["48h"] == 1
    assert told(lab) == [("qa_engineer", "48h")]
    item = lab.call(lab.tester, "get", "/api/inbox/").json()["items"][0]
    assert (item["display_id"], item["escalated"]) == ("BUG-1", True)
    assert len(mail.outbox) == 0  # the digest carries it; only critical items email at once


def test_after_96_hours_the_leads_are_told_as_well(lab):
    waiting(lab, 4.1)
    assert remind(lab) == {"48h": 1, "96h": 3, "critical": 0}
    assert told(lab) == sorted([*LEADS, ("qa_engineer", "48h")])


def test_each_level_is_told_once_however_often_the_job_runs(lab):
    waiting(lab, 4.1)
    remind(lab)
    assert remind(lab) == {"48h": 0, "96h": 0, "critical": 0}
    assert remind(lab) == {"48h": 0, "96h": 0, "critical": 0}
    assert len(told(lab)) == 4


def test_a_defect_fixed_again_later_is_reminded_again(lab):
    d = waiting(lab, 2.1)
    remind(lab)
    d = lab.retest(d, "failed")
    lab.backdate(lab.set(d, "fixed"), fixed_at=timezone.now() - timedelta(hours=50))
    assert remind(lab)["48h"] == 1
    assert told(lab).count(("qa_engineer", "48h")) == 2


def test_the_times_come_from_the_project_settings(lab):
    with lab.scope():
        lab.project.settings = {"retest_escalation_hours": [12, 20]}
        lab.project.save()
    waiting(lab, 1)
    assert remind(lab) == {"48h": 1, "96h": 3, "critical": 0}


def test_a_retested_defect_stops_being_reminded(lab):
    lab.retest(waiting(lab, 5), "passed")
    assert remind(lab) == {"48h": 0, "96h": 0, "critical": 0}


def test_leads_who_cannot_see_the_project_are_not_told(lab):
    from apps.core.models import ProjectMember

    with lab.scope():
        ProjectMember.objects.filter(user=lab.lead).delete()
    waiting(lab, 4.1)
    remind(lab)
    # Owners and admins see every project; the QA lead is no longer on this one.
    assert told(lab) == [("admin", "96h"), ("owner", "96h"), ("qa_engineer", "48h")]


# --- Closed with a failed retest (FR-DEF-05, FR-INB-03) -


def test_closing_a_defect_whose_retest_failed_alerts_people_at_once(
    lab, django_capture_on_commit_callbacks
):
    d = lab.retest(lab.set(lab.defect("Cart total ignores discount"), "fixed"), "failed")
    with django_capture_on_commit_callbacks(execute=True):
        lab.set(d, "closed")  # queues the reminders job, which runs inline in tests
    assert told(lab) == [
        ("admin", "critical"),
        ("owner", "critical"),
        ("qa_engineer", "critical"),
        ("qa_lead", "critical"),
    ]
    assert len(mail.outbox) == 4
    message = next(m for m in mail.outbox if m.to == [lab.tester.email])
    assert message.subject == "LAB-BUG-1 was closed, but its retest failed"
    assert "Cart total ignores discount" in message.body
    assert "/lab/bugs/1" in message.body
    with lab.scope():
        assert Job.objects.filter(kind="reminders", state="succeeded").count() == 1


def test_the_critical_alert_is_sent_once(lab, django_capture_on_commit_callbacks):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "failed")
    lab.set(d, "closed")
    with django_capture_on_commit_callbacks(execute=True):
        assert remind(lab)["critical"] == 4
        assert remind(lab)["critical"] == 0
    assert len(mail.outbox) == 4


def test_closing_an_ordinary_defect_alerts_nobody(lab, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        lab.set(lab.set(lab.defect(), "fixed"), "closed")
    assert mail.outbox == [] and told(lab) == []


def test_the_jobs_are_registered_and_scheduled(lab, settings):
    assert {"reminders", "digest"} <= set(HANDLERS)
    schedule = settings.CELERY_BEAT_SCHEDULE
    assert schedule["reminders"]["schedule"] == 15 * 60
    assert schedule["reminders"]["args"] == ["reminders"] and schedule["digest"]["args"] == [
        "digest"
    ]
    with lab.scope():
        assert enqueue("digest", org_id=lab.id).kind == "digest"


# --- The daily digest (FR-INB-03) -


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 12, hour, minute, tzinfo=UTC)


def digest(lab, now, capture):
    with capture(execute=True), lab.scope():
        return run_digest(lab.id, now)


def set_zone(user: User, zone: str) -> None:
    User.objects.filter(pk=user.pk).update(time_zone=zone)


def test_the_digest_goes_at_seven_in_each_persons_own_time_zone(
    lab, django_capture_on_commit_callbacks
):
    lab.set(lab.defect("Payment times out"), "fixed")  # in the tester's Inbox only
    set_zone(lab.tester, "Africa/Lagos")  # UTC+1
    assert digest(lab, at(5, 30), django_capture_on_commit_callbacks) == 0  # 06:30 in Lagos
    assert digest(lab, at(6, 5), django_capture_on_commit_callbacks) == 1  # 07:05 in Lagos
    (message,) = mail.outbox
    assert message.to == [lab.tester.email]
    assert message.subject == "Greenlit: 1 item needs you"


def test_the_digest_is_sent_once_a_day(lab, django_capture_on_commit_callbacks):
    lab.set(lab.defect(), "fixed")
    assert digest(lab, at(7, 5), django_capture_on_commit_callbacks) == 1
    assert digest(lab, at(8, 5), django_capture_on_commit_callbacks) == 0
    assert digest(lab, at(7, 5) + timedelta(days=1), django_capture_on_commit_callbacks) == 1
    assert len(mail.outbox) == 2


def test_nobody_with_an_empty_inbox_gets_a_digest(lab, django_capture_on_commit_callbacks):
    assert digest(lab, at(7, 5), django_capture_on_commit_callbacks) == 0
    assert mail.outbox == []
    with lab.scope():
        assert not Notification.objects.exists()


def test_the_digest_is_not_sent_in_the_afternoon(lab, django_capture_on_commit_callbacks):
    lab.set(lab.defect(), "fixed")
    assert digest(lab, at(15), django_capture_on_commit_callbacks) == 0


def test_the_digest_lists_ids_titles_and_links_and_never_the_text(
    lab, django_capture_on_commit_callbacks
):
    requirement = lab.requirement("Refund to the original card")
    with lab.scope():
        type(requirement).objects.filter(pk=requirement.pk).update(text="SECRET-REQUIREMENT-TEXT")
        d = lab.defect("Payment times out")
        type(d).objects.filter(pk=d.pk).update(
            steps="SECRET-STEPS", actual="SECRET-ACTUAL", created_at=days_ago(9)
        )
    assert digest(lab, at(7, 5), django_capture_on_commit_callbacks) >= 1
    message = next(m for m in mail.outbox if m.to == [lab.lead.email])
    body = message.body
    assert (
        "Requirements without tests (1)" in body
        and "LAB-REQ-1  Refund to the original card" in body
    )
    assert "Ageing defects (1)" in body and "LAB-BUG-1  Payment times out  (9 days)" in body
    assert "/lab/requirements/1" in body and "/lab/bugs/1" in body and "/inbox" in body
    assert "SECRET" not in body and "SECRET" not in message.subject


def test_snoozed_items_stay_out_of_the_digest(lab, django_capture_on_commit_callbacks):
    d = lab.set(lab.defect(), "fixed")
    until = (timezone.now() + timedelta(days=2)).isoformat()
    body = {"reason": "Waiting for staging", "until": until}
    assert (
        lab.call(lab.tester, "post", f"/api/inbox/defect.{d.pk}/snooze/", body).status_code == 204
    )
    assert (
        digest(lab, timezone.now().replace(hour=7, minute=5), django_capture_on_commit_callbacks)
        == 0
    )


def test_an_unknown_time_zone_falls_back_to_utc(lab, django_capture_on_commit_callbacks):
    lab.set(lab.defect(), "fixed")
    set_zone(lab.tester, "Mars/Olympus")
    assert digest(lab, at(7, 5), django_capture_on_commit_callbacks) == 1
