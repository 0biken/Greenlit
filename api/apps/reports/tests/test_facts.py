"""The facts builder (M8-01, M8-02, M8-03): readiness blockers and verified coverage, and the
dashboard and release endpoints that read from it."""

import pytest
from tests.lab import Lab, days_ago

from apps.core.models import Project
from apps.defects import status
from apps.plans.models import CaseRevision
from apps.reports.facts import build_facts
from apps.reports.services import report_body
from apps.reports.summary import project_summary

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab():
    return Lab()


def facts(lab, release):
    with lab.scope():
        return build_facts(release)


def blocker_types(lab, release):
    return [b.type for b in facts(lab, release).blockers]


# --- Readiness: each blocker on its own ----------------------------------------------------------


def test_an_empty_release_is_ready(lab):
    f = facts(lab, lab.release())
    assert (f.readiness, f.blockers, f.coverage.total_requirements, f.coverage.verified_pct) == (
        "ready",
        [],
        0,
        0,
    )


def test_a_fix_waiting_for_its_retest_blocks_the_release(lab):
    release = lab.release()
    d = lab.set(lab.defect(release=release), "fixed")
    assert blocker_types(lab, release) == ["needs_retest"]
    lab.retest(d, "passed")
    assert facts(lab, release).readiness == "ready"


def test_a_defect_closed_with_a_failed_retest_blocks_the_release(lab):
    release = lab.release()
    lab.set(lab.retest(lab.set(lab.defect(release=release), "fixed"), "failed"), "closed")
    assert blocker_types(lab, release) == ["closed_failed_retest"]


def test_an_open_critical_defect_blocks_and_an_open_high_one_does_not(lab):
    release = lab.release()
    lab.defect("High", severity="high", release=release)
    assert facts(lab, release).readiness == "ready"
    critical = lab.defect("Critical", severity="critical", release=release)
    assert blocker_types(lab, release) == ["open_critical"]
    with lab.scope():
        status.decide(critical, lab.lead, "deferred", "Moved to 2.5")
    assert facts(lab, release).readiness == "ready"


def test_a_failure_nobody_filed_blocks_the_release(lab):
    release = lab.release()
    _, version, _ = lab.plan(cases=[("Pays by card", [])])
    _, (result,) = lab.run(release, version, ["failed"])
    (blocker,) = facts(lab, release).blockers
    assert (blocker.type, blocker.display_id) == ("unfiled_failure", "TC-0001")
    lab.defect(severity="low", result=result)
    assert (
        facts(lab, release).readiness == "ready"
    )  # filed, low severity, still open: not a blocker


def test_an_uncovered_critical_requirement_blocks_and_a_medium_one_is_only_a_risk(lab):
    release = lab.release()
    lab.requirement("Medium, no tests")
    f = facts(lab, release)
    assert f.readiness == "ready" and [r["display_id"] for r in f.risks] == ["REQ-1"]
    lab.requirement("Critical, no tests", priority="critical")
    assert blocker_types(lab, release) == ["uncovered_critical"]


def test_blockers_are_listed_by_type_in_a_fixed_order(lab):
    release = lab.release()
    lab.requirement("Critical, no tests", priority="critical")
    lab.set(lab.defect("Waiting", release=release), "fixed")
    lab.set(lab.retest(lab.set(lab.defect("Broken", release=release), "fixed"), "failed"), "closed")
    lab.defect("Critical open", severity="critical", release=release)
    assert blocker_types(lab, release) == [
        "closed_failed_retest",
        "open_critical",
        "needs_retest",
        "uncovered_critical",
    ]


def test_defects_of_another_release_do_not_block_this_one(lab):
    mine, other = lab.release("1.0"), lab.release("2.0")
    lab.set(lab.defect(release=other), "fixed")
    assert facts(lab, mine).readiness == "ready"
    assert facts(lab, other).readiness == "not_ready"


def test_a_defect_found_in_the_releases_run_counts_even_without_a_release_set(lab):
    release = lab.release()
    _, version, _ = lab.plan(cases=[("Pays by card", [])])
    _, (result,) = lab.run(release, version, ["failed"])
    lab.set(lab.defect(result=result), "fixed")
    assert blocker_types(lab, release) == ["needs_retest"]


def test_draft_defects_do_not_count(lab):
    release = lab.release()
    d = lab.set(lab.defect(release=release), "fixed")
    with lab.scope():
        type(d).objects.filter(pk=d.pk).update(review_state="draft")
    assert facts(lab, release).readiness == "ready"


# --- Verified coverage (DATA §9) -


def a_release_with_four_requirements(lab):
    """REQ-1 passes; REQ-2 fails with a defect; REQ-3 is blocked; REQ-4 has no tests."""
    release = lab.release()
    r1, r2, r3 = lab.requirement("One"), lab.requirement("Two"), lab.requirement("Three")
    lab.requirement("Four")
    _, version, _ = lab.plan(cases=[("Case one", [r1]), ("Case two", [r2]), ("Case three", [r3])])
    _, results = lab.run(release, version, ["passed", "failed", "blocked"])
    return release, version, results


def test_coverage_counts_requirements_whose_every_case_passed(lab):
    release, _, _ = a_release_with_four_requirements(lab)
    c = facts(lab, release).coverage
    assert (c.verified, c.failed, c.on_hold, c.not_run, c.total_requirements) == (1, 1, 1, 1, 4)
    assert c.verified_pct == 25


def test_a_requirement_is_not_verified_while_a_defect_against_its_case_is_open(lab):
    release = lab.release()
    r1 = lab.requirement("One")
    _, version, _ = lab.plan(cases=[("Case one", [r1])])
    _, (result,) = lab.run(release, version, ["failed"])
    defect = lab.set(lab.defect(result=result), "fixed")
    # A second run passes, but the defect has not been retested yet.
    lab.run(release, version, ["passed"])
    c = facts(lab, release).coverage
    assert (c.verified, c.on_hold) == (0, 1)
    lab.retest(defect, "passed")
    assert facts(lab, release).coverage.verified == 1


def test_every_linked_case_must_pass(lab):
    release = lab.release()
    r1 = lab.requirement("One")
    _, version, _ = lab.plan(cases=[("Positive", [r1]), ("Negative", [r1])])
    lab.run(release, version, ["passed"])  # the second case is not run
    assert facts(lab, release).coverage.verified == 0
    lab.run(release, version, ["passed", "passed"])
    assert facts(lab, release).coverage.verified == 1


def test_the_latest_run_of_each_plan_is_the_one_that_counts(lab):
    release = lab.release()
    r1, r2 = lab.requirement("One"), lab.requirement("Two")
    _, checkout, _ = lab.plan(title="Checkout", cases=[("Case one", [r1])])
    _, cart, _ = lab.plan(title="Cart", cases=[("Case two", [r2])])
    lab.run(release, checkout, ["failed"])
    lab.run(release, cart, ["passed"])
    newest, _ = lab.run(release, checkout, ["passed"])
    f = facts(lab, release)
    assert f.coverage.verified == 2
    assert sorted(r.plan for r in f.runs) == ["Cart", "Checkout"]
    assert f"RUN-{newest.display_no:03d}" in [r.display_id for r in f.runs]


def test_only_accepted_requirements_and_cases_count(lab):
    release = lab.release()
    r1 = lab.requirement("Accepted")
    lab.requirement("Still a draft", review_state="draft")
    _, draft, (revision,) = lab.plan(cases=[("Unreviewed case", [r1])], approve=False)
    with lab.scope():
        CaseRevision.objects.filter(pk=revision.pk).update(review_state="draft")
        from apps.plans import services as plans

        version = plans.approve(draft, lab.lead)
    lab.run(release, version, ["passed"])
    c = facts(lab, release).coverage
    assert (c.total_requirements, c.verified, c.not_run) == (1, 0, 1)


# --- The report built from the facts -


def test_every_report_line_names_its_records_and_matches_the_facts(lab):
    release, _, results = a_release_with_four_requirements(lab)
    lab.defect("Case two fails", result=results[1], release=release)
    f = facts(lab, release)
    body = report_body(f)
    assert body["summary"].startswith("25% of requirements are verified with evidence (1 of 4).")
    assert "Not ready yet" not in body["summary"]  # nothing blocks: the failure was filed
    (line,) = body["sections"][0]["lines"]
    assert (
        line["text"]
        == "Checkout: 1 of 3 cases passed in RUN-001; 1 failed and was filed; 1 blocked."
    )
    assert line["refs"] == ["RUN-001", "BUG-1"]
    headings = [s["heading"] for s in body["sections"]]
    assert headings == ["Results by area", "Open defects", "Risks"]
    assert body["facts"]["readiness"] == f.readiness == "ready"


def test_the_report_never_says_ready_when_the_facts_say_otherwise(lab):
    release = lab.release()
    lab.set(lab.defect(release=release), "fixed")
    body = report_body(facts(lab, release))
    assert "Not ready yet. 1 blocker remains." in body["summary"]


# --- The endpoints -


def test_the_release_endpoint_gives_readiness_blockers_coverage_and_a_draft_report(lab):
    release, _, _ = a_release_with_four_requirements(lab)
    lab.backdate(lab.set(lab.defect("Waiting", release=release), "fixed"), fixed_at=days_ago(4))
    body = lab.call(lab.viewer, "get", "/api/projects/lab/releases/1.0/").json()
    assert (body["version"], body["readiness"], body["sign_off"]) == ("1.0", "not_ready", None)
    types = [b["type"] for b in body["blockers"]]
    assert types == ["needs_retest", "unfiled_failure"]
    assert (body["blockers"][0]["display_id"], body["blockers"][0]["age_days"]) == ("BUG-1", 4)
    assert body["coverage"]["verified_pct"] == 25
    assert body["report"]["state"] == "draft" and body["report"]["display_id"] is None


def test_an_unknown_release_is_not_found(lab):
    assert lab.call(lab.viewer, "get", "/api/projects/lab/releases/9.9/").status_code == 404
    assert lab.call(lab.viewer, "get", "/api/projects/nope/releases/1.0/").status_code == 404


def test_the_dashboard_agrees_with_the_release_and_the_inbox(lab):
    release, _, _ = a_release_with_four_requirements(lab)
    lab.backdate(lab.set(lab.defect("Waiting", release=release), "fixed"), fixed_at=days_ago(4))
    body = lab.call(lab.viewer, "get", "/api/projects/lab/summary/").json()
    assert body["is_new"] is False
    assert body["release"] == {
        "version": "1.0",
        "name": "Release 1.0",
        "due": body["release"]["due"],
        "readiness": "not_ready",
        "blockers": 2,
    }
    assert body["coverage"]["verified_pct"] == 25
    work = {w["kind"]: (w["count"], w["oldest_days"]) for w in body["open_work"]}
    assert work["needs_retest"] == (1, 4)
    assert work["unfiled_failures"] == (1, 0) and work["uncovered"] == (1, 0)
    assert work["retest_failed"] == (0, None)
    assert body["counts"] == {"requirements": 4, "cases": 3, "runs": 1, "open_defects": 1}
    assert any("BUG-1" in line["refs"] for line in body["activity"])


def test_a_project_with_nothing_in_it_is_new(lab):
    with lab.scope():
        summary = project_summary(Project.objects.get(pk=lab.project.pk))
    assert summary["is_new"] is True and summary["release"] is None and summary["coverage"] is None
