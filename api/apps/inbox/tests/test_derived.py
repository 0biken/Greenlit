"""Derived states (M6-01, M6-02, DATA §9): each appears exactly when its condition holds."""

import pytest
from django.utils import timezone
from tests.lab import Lab, days_ago

from apps.core.models import Project
from apps.defects import status
from apps.inbox import derived
from apps.plans.models import CaseRevision, TestCase
from apps.requirements.services import change_text
from apps.runs.services import attach_evidence

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab():
    return Lab()


def ids(lab, fn, *args):
    with lab.scope():
        return [i.display_id for i in fn(Project.objects.filter(pk=lab.project.pk), *args)]


def now():
    return timezone.now()


# --- Needs retest ------------------------------------------------------------------------------


def test_needs_retest_is_a_fixed_or_closed_defect_nobody_has_retested(lab):
    d = lab.defect()
    assert ids(lab, derived.needs_retest) == []
    d = lab.set(d, "fixed")
    assert ids(lab, derived.needs_retest) == ["BUG-1"]
    lab.set(d, "closed")
    assert ids(lab, derived.needs_retest) == ["BUG-1"]


def test_a_retest_either_way_takes_it_out_of_needs_retest(lab):
    passed = lab.retest(lab.set(lab.defect(), "fixed"), "passed")
    failed = lab.retest(lab.set(lab.defect("Other"), "fixed"), "failed")
    assert ids(lab, derived.needs_retest) == []
    assert (passed.qa_status, failed.qa_status) == ("verified", "retest_failed")


def test_needs_retest_counts_its_age_from_when_it_was_fixed(lab):
    d = lab.backdate(lab.set(lab.defect(), "fixed"), fixed_at=days_ago(4.2))
    with lab.scope():
        (item,) = derived.needs_retest(Project.objects.filter(pk=lab.project.pk))
    assert (item.age_days(now()), item.next_action, item.owner_id) == (4, "retest", str(d.owner_id))


# --- Closed with a failed retest -----------------------------------------------------------------


def test_closed_with_a_failed_retest_is_critical(lab):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "failed")
    assert ids(lab, derived.closed_failed_retest) == []  # reopened in the tracker, not closed
    lab.set(d, "closed")
    with lab.scope():
        (item,) = derived.closed_failed_retest(Project.objects.filter(pk=lab.project.pk))
    assert (item.display_id, item.critical, item.status) == ("BUG-1", True, "retest_failed")
    assert ids(lab, derived.needs_retest) == []


# --- Aging -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "severity,age,expected",
    [
        ("critical", 3, True),
        ("critical", 1, False),
        ("high", 8, True),
        ("high", 6, False),
        ("low", 31, True),
        ("low", 29, False),
    ],
)
def test_an_open_defect_ages_past_its_severity_limit(lab, severity, age, expected):
    lab.backdate(lab.defect(severity=severity), created_at=days_ago(age))
    assert bool(ids(lab, derived.aging, now())) is expected


def test_aging_limits_come_from_the_project_settings(lab):
    lab.backdate(lab.defect(severity="high"), created_at=days_ago(4))
    assert ids(lab, derived.aging, now()) == []
    with lab.scope():
        lab.project.settings = {"aging_days": {"critical": 2, "high": 3, "medium": 14, "low": 30}}
        lab.project.save()
    assert ids(lab, derived.aging, now()) == ["BUG-1"]


def test_fixed_verified_and_wont_fix_defects_do_not_age(lab):
    fixed = lab.set(lab.defect("Fixed"), "fixed")
    verified = lab.set(
        lab.retest(lab.set(lab.defect("Verified"), "fixed"), "passed", actor=lab.lead), "open"
    )
    decided = lab.defect("Decided")
    with lab.scope():
        status.decide(decided, lab.lead, "wont_fix", "Accepted")
    for d in (fixed, verified, decided):
        lab.backdate(d, created_at=days_ago(90))
    # The reopened one is open and not verified any more, so it does age.
    assert ids(lab, derived.aging, now()) == ["BUG-2"]


# --- Failed results: unfiled, and missing evidence ------------------------------------------------


def a_failed_result(lab):
    _, version, _ = lab.plan(cases=[("Pays by card", []), ("Pays by transfer", [])])
    _, results = lab.run(lab.release(), version, ["failed", "passed"])
    return results[0]


def test_a_failed_result_with_no_defect_is_an_unfiled_failure(lab):
    result = a_failed_result(lab)
    with lab.scope():
        (item,) = derived.unfiled_failures(Project.objects.filter(pk=lab.project.pk))
    assert (item.display_id, item.title, item.owner_id) == (
        "TC-0001",
        "Pays by card",
        str(lab.tester.pk),
    )
    assert item.next_action == "file_defect"
    lab.defect(result=result)
    assert ids(lab, derived.unfiled_failures) == []


def test_a_failed_result_with_no_evidence_is_missing_evidence(lab):
    result = a_failed_result(lab)
    assert ids(lab, derived.missing_evidence) == ["TC-0001"]
    with lab.scope():
        attach_evidence(lab.project, lab.tester, [lab.file().pk], [("case_result", result.pk)])
    assert ids(lab, derived.missing_evidence) == []


def test_passed_blocked_and_not_run_results_are_neither(lab):
    _, version, _ = lab.plan(cases=[("A", []), ("B", []), ("C", [])])
    lab.run(lab.release(), version, ["passed", "blocked"])
    assert ids(lab, derived.unfiled_failures) == ids(lab, derived.missing_evidence) == []


# --- Stale -------------------------------------------------------------------------------------


def test_a_case_never_run_is_stale_until_it_has_a_result(lab):
    _, version, _ = lab.plan(cases=[("Pays by card", [])])
    assert ids(lab, derived.stale, now()) == ["TC-0001"]
    lab.run(lab.release(), version, ["passed"])
    assert ids(lab, derived.stale, now()) == []


def test_a_case_goes_stale_when_its_last_result_is_older_than_the_project_allows(lab):
    _, version, _ = lab.plan(cases=[("Pays by card", [])])
    _, (result,) = lab.run(lab.release(), version, ["failed"])
    lab.backdate(result, recorded_at=days_ago(31))
    with lab.scope():
        (item,) = derived.stale(Project.objects.filter(pk=lab.project.pk), now())
    assert (item.display_id, item.age_days(now()), item.next_action) == ("TC-0001", 31, "run")
    with lab.scope():
        lab.project.settings = {"stale_after_days": 60}
        lab.project.save()
    assert ids(lab, derived.stale, now()) == []


def test_blocked_and_not_run_do_not_count_as_running_the_case(lab):
    _, version, _ = lab.plan(cases=[("Pays by card", [])])
    lab.run(lab.release(), version, ["blocked"])
    assert ids(lab, derived.stale, now()) == ["TC-0001"]


def test_a_case_goes_stale_when_its_requirement_changes(lab):
    requirement = lab.requirement()
    _, version, _ = lab.plan(cases=[("Pays by card", [requirement])])
    lab.run(lab.release(), version, ["passed"])
    assert ids(lab, derived.stale, now()) == []
    with lab.scope():
        change_text(requirement, lab.lead, "Customers can pay by card or wallet.")
        (item,) = derived.stale(Project.objects.filter(pk=lab.project.pk), now())
    assert item.display_id == "TC-0001" and item.extra["requirement_changed"] is True


def test_cases_in_an_unapproved_draft_or_retired_are_not_stale(lab):
    lab.plan(title="Draft only", cases=[("Not approved yet", [])], approve=False)
    assert ids(lab, derived.stale, now()) == []
    _, _, (revision,) = lab.plan(title="Approved", cases=[("Old case", [])])
    assert ids(lab, derived.stale, now()) == ["TC-0002"]
    with lab.scope():
        TestCase.objects.filter(pk=revision.test_case_id).update(retired_at=now())
    assert ids(lab, derived.stale, now()) == []


# --- Uncovered -----------------------------------------------------------------------------------


def test_an_accepted_requirement_with_no_case_in_a_current_version_is_uncovered(lab):
    covered = lab.requirement("Pay by card")
    lab.requirement("Refund to the original card", priority="critical")
    lab.plan(cases=[("Pays by card", [covered])])
    with lab.scope():
        (item,) = derived.uncovered(Project.objects.filter(pk=lab.project.pk))
    assert (item.display_id, item.severity, item.next_action) == ("REQ-2", "critical", "add_case")


def test_draft_requirements_do_not_count_and_draft_plans_do_not_cover(lab):
    lab.requirement("Still a draft", review_state="draft")
    waiting = lab.requirement("Covered only in a draft plan")
    lab.plan(cases=[("Case in a draft", [waiting])], approve=False)
    assert ids(lab, derived.uncovered) == ["REQ-2"]


def test_a_case_that_is_not_accepted_does_not_cover(lab):
    requirement = lab.requirement()
    _, draft, (revision,) = lab.plan(cases=[("AI draft case", [requirement])], approve=False)
    with lab.scope():
        CaseRevision.objects.filter(pk=revision.pk).update(review_state="draft")
        from apps.plans import services as plans

        plans.approve(draft, lab.lead)
    assert ids(lab, derived.uncovered) == ["REQ-1"]


def test_all_items_puts_the_states_together(lab):
    lab.requirement("Uncovered")
    lab.set(lab.defect(), "fixed")
    with lab.scope():
        groups = [
            i.group for i in derived.all_items(Project.objects.filter(pk=lab.project.pk), now())
        ]
    assert groups == ["needs_retest", "uncovered"]
