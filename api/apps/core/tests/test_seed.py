"""The seed command (M1-20): it must work on an empty database, be safe to run again, and
produce the records the local screens are meant to show."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

from apps.core.models import Membership, Project, ProjectMember, Role, User
from apps.core.tenancy import org_scope
from apps.defects.models import Defect
from apps.inbox.services import inbox
from apps.reports.facts import build_facts
from apps.reports.models import Report, ShareLink, SignOff
from apps.runs.models import Release, TestRun

pytestmark = pytest.mark.django_db


def seed() -> str:
    out = StringIO()
    call_command("seed", stdout=out)
    return out.getvalue()


def karma_id():
    owner = User.objects.get(email="owner@karmagroups.example")
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.user_id', %s, true)", [str(owner.pk)])
        cursor.execute("SELECT id FROM core_organisation WHERE slug = 'karma-groups'")
        org_id = cursor.fetchone()[0]
        cursor.execute("SELECT set_config('app.user_id', '', true)")
    return org_id


def test_the_seed_builds_karma_groups_with_every_role_on_every_project():
    seed()
    with org_scope(karma_id()):
        assert sorted(Membership.objects.values_list("role", flat=True)) == sorted(Role.values)
        assert sorted(Project.objects.values_list("key", flat=True)) == ["HUBE", "KOLA", "MARA"]
        assert ProjectMember.objects.count() == 6 * 3


def test_the_seeded_release_is_not_ready_for_the_reasons_the_screens_show():
    seed()
    with org_scope(karma_id()):
        release = Release.objects.select_related("project").get(name="2.4.1")
        facts = build_facts(release)
        assert facts.readiness == "not_ready"
        assert sorted(b.type for b in facts.blockers) == [
            "closed_failed_retest",
            "needs_retest",
            "needs_retest",
            "uncovered_critical",
            "unfiled_failure",
        ]
        tester = Membership.objects.select_related("user").get(user__email="qa@karmagroups.example")
        groups = {i["group"] for i in inbox(tester)["items"]}
        assert groups == {
            "closed_failed_retest",
            "needs_retest",
            "unfiled_failures",
            "missing_evidence",
            "stale_tests",
        }
        # MARA is left empty on purpose, to show a project's first visit.
        assert not Release.objects.filter(project__key="MARA").exists()


def test_the_seed_signs_off_one_release_and_prints_its_share_link_once():
    first = seed()
    assert "/shared/" in first
    with org_scope(karma_id()):
        signed = Release.objects.get(project__key="KOLA", name="5.0.0")
        assert signed.state == "signed_off"
        assert SignOff.objects.get().readiness_at_signing == "not_ready"
        assert Report.objects.get().state == "signed"
        assert ShareLink.objects.count() == 1
        token = first.split("/shared/")[1].split()[0]
        assert token not in str(list(ShareLink.objects.values()))  # only its hash is stored
        in_progress = TestRun.objects.get(release__name="5.1.0")
        assert in_progress.state == "in_progress"


def test_running_the_seed_again_adds_nothing():
    seed()
    org_id = karma_id()

    def counts():
        with org_scope(org_id):
            return (
                Defect.objects.count(),
                Release.objects.count(),
                TestRun.objects.count(),
                ShareLink.objects.count(),
                Membership.objects.count(),
                ProjectMember.objects.count(),
            )

    before = counts()
    again = seed()
    assert counts() == before
    assert "/shared/" not in again and "Added sample records" not in again


def test_the_seed_leaves_a_plan_with_history_and_a_draft_awaiting_approval():
    from apps.plans.diff import diff_versions
    from apps.plans.models import PlanVersion, TestPlan

    seed()
    with org_scope(karma_id()):
        plan = TestPlan.objects.select_related("current_version").get(title="Sign-in")
        versions = {v.number: v for v in PlanVersion.objects.filter(plan=plan)}
        assert plan.current_version.number == "1.1"
        assert sorted(versions) == ["", "1.0", "1.1"]
        assert versions[""].submitted_at is not None
        assert (versions["1.0"].state, versions["1.1"].state) == ("superseded", "published")
        diff = diff_versions(versions["1.0"], versions["1.1"])
        assert (len(diff["added"]), len(diff["removed"]), len(diff["changed"])) == (1, 0, 1)
        assert "moved" in {step["op"] for step in diff["changed"][0]["steps"]}


def test_the_seed_leaves_drafted_requirements_waiting_for_review(
    django_capture_on_commit_callbacks,
):
    from apps.requirements.models import Requirement
    from apps.sources.models import SourceDocument

    with django_capture_on_commit_callbacks(execute=True):  # the drafting job runs on commit
        seed()
    with org_scope(karma_id()):
        document = SourceDocument.objects.get(title="Scheduled transfers PRD")
        drafts = Requirement.objects.filter(source_document=document)
        assert document.state == "ready" and drafts.count() == 5
        assert set(drafts.values_list("review_state", "origin")) == {("draft", "ai")}


def test_the_seed_leaves_drafted_cases_waiting_for_review(django_capture_on_commit_callbacks):
    from apps.plans import drafting
    from apps.plans.models import CaseRevision, TestPlan

    with django_capture_on_commit_callbacks(execute=True):
        seed()
    with org_scope(karma_id()):
        plan = TestPlan.objects.get(title="Transfers")
        waiting = CaseRevision.objects.filter(pk__in=drafting.undecided(plan).values("target_id"))
        assert sorted(waiting.values_list("case_type", "review_state")) == [
            ("negative", "draft"),
            ("positive", "draft"),
        ]
