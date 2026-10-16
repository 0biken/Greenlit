"""The nightly stale check and the case-level stale flag (M6-02; FR-TC-05)."""

import pytest
from tests.lab import Lab, days_ago

from apps.core.jobs import HANDLERS
from apps.inbox.stale_check import run_stale_check
from apps.plans import queries
from apps.plans.models import PlanVersion

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab():
    return Lab()


def check(lab):
    with lab.scope():
        return run_stale_check(lab.id)


def test_the_job_is_registered():
    assert "stale_check" in HANDLERS


def test_counts_stale_cases_per_project_and_clears_when_they_are_run(lab):
    _, version, _ = lab.plan(cases=[("Pays by card", []), ("Pays by wallet", [])])
    assert check(lab) == {lab.project.key: 2}
    lab.run(lab.release(), version, ["passed", "passed"])
    assert check(lab) == {}


def test_an_old_result_counts_as_stale(lab):
    _, version, _ = lab.plan(cases=[("Pays by card", [])])
    _, (result,) = lab.run(lab.release(), version, ["passed"])
    lab.backdate(result, recorded_at=days_ago(31))
    assert check(lab) == {lab.project.key: 1}


def test_the_check_sends_nothing_and_stores_nothing(lab):
    from django.core import mail

    from apps.inbox.models import Notification

    lab.plan(cases=[("Pays by card", [])])
    check(lab)
    with lab.scope():
        assert Notification.objects.count() == 0
    assert mail.outbox == []


def test_the_plan_version_marks_which_cases_are_stale(lab):
    _, version, _ = lab.plan(cases=[("Pays by card", []), ("Pays by wallet", [])])
    lab.run(lab.release(), version, ["passed", "not_run"])
    with lab.scope():
        detail = queries.version_detail(PlanVersion.objects.get(pk=version.pk))
    # The case with a passed result is fresh; the one never passed or failed is stale.
    assert sorted(c["stale"] for c in detail["cases"]) == [False, True]
