"""Plan versions (M3-01, M3-03): one draft per plan, and published versions never change."""

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.utils import DatabaseError
from tests.lab import Lab

from apps.core.services import ServiceError
from apps.plans import services as plans
from apps.plans.models import CaseRevision, PlanVersion, PlanVersionCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab():
    return Lab()


def refused(fn):
    """The database refuses `fn` (a trigger or constraint), leaving the transaction usable."""
    with pytest.raises(DatabaseError), transaction.atomic():
        fn()


def _sql(statement: str, *params) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, list(params))


def test_a_new_plan_starts_with_one_empty_draft(lab):
    plan, draft, _ = lab.plan(approve=False)
    assert (draft.state, draft.number, plan.current_version_id) == ("draft", "", None)


def test_a_plan_cannot_have_two_drafts(lab):
    plan, _, _ = lab.plan(approve=False)
    with lab.scope(), pytest.raises(IntegrityError), transaction.atomic():
        PlanVersion.objects.create(org_id=lab.id, plan=plan)


def test_approving_numbers_the_version_and_supersedes_the_previous_one(lab):
    plan, v1, _ = lab.plan(cases=[("Pays by card", [])])
    assert (v1.number, v1.state, v1.approved_by_id) == ("1.0", "published", lab.lead.pk)
    with lab.scope():
        PlanVersion.objects.create(org_id=lab.id, plan=plan)
        v2 = plans.approve(plans.draft_of(plan), lab.lead)
        PlanVersion.objects.create(org_id=lab.id, plan=plan)
        v3 = plans.approve(plans.draft_of(plan), lab.lead, major=True)
        plan.refresh_from_db()
        v1.refresh_from_db()
        v2.refresh_from_db()
    assert (v2.number, v3.number) == ("1.1", "2.0")
    assert (v1.state, v2.state, v3.state) == ("superseded", "superseded", "published")
    assert plan.current_version_id == v3.pk


def test_only_a_draft_can_be_approved_or_given_cases(lab):
    _, version, _ = lab.plan(cases=[("Pays by card", [])])
    with lab.scope():
        with pytest.raises(ServiceError):
            plans.approve(version, lab.lead)
        with pytest.raises(ServiceError):
            plans.add_case(version, lab.lead, title="Late", steps=["x"], expected="y")


def test_a_case_needs_a_title_a_step_and_an_expected_result(lab):
    _, draft, _ = lab.plan(approve=False)
    with lab.scope(), pytest.raises(ServiceError):
        plans.add_case(draft, lab.lead, title="No steps", steps=[], expected="y")


def test_a_case_records_which_requirement_text_it_was_written_against(lab):
    requirement = lab.requirement()
    _, _, (revision,) = lab.plan(cases=[("Pays by card", [requirement])])
    with lab.scope():
        link = revision.requirement_links.get()
    assert (link.requirement_id, link.req_revision_seen) == (requirement.pk, 1)


def test_the_database_refuses_changes_to_a_published_version(lab):
    _, version, (revision,) = lab.plan(cases=[("Pays by card", [])])
    with lab.scope():
        refused(lambda: PlanVersion.objects.filter(pk=version.pk).update(number="9.9"))
        refused(lambda: PlanVersion.objects.filter(pk=version.pk).update(state="draft"))
        refused(lambda: _sql("DELETE FROM plans_planversion WHERE id = %s", version.pk))
        # Its list of cases is frozen too: nothing added, moved or removed.
        pointer = PlanVersionCase.objects.get(plan_version=version)
        refused(lambda: PlanVersionCase.objects.filter(pk=pointer.pk).update(position=5))
        refused(
            lambda: PlanVersionCase.objects.create(
                org_id=lab.id, plan_version=version, case_revision=revision, position=2
            )
        )
        # And so is the content of every case revision it uses.
        refused(lambda: CaseRevision.objects.filter(pk=revision.pk).update(title="Edited later"))
        revision.refresh_from_db()
    assert revision.title == "Pays by card"


def test_a_superseded_version_is_frozen_as_well(lab):
    plan, v1, _ = lab.plan(cases=[("Pays by card", [])])
    with lab.scope():
        PlanVersion.objects.create(org_id=lab.id, plan=plan)
        plans.approve(plans.draft_of(plan), lab.lead)
        refused(lambda: PlanVersion.objects.filter(pk=v1.pk).update(state="published"))


def test_a_draft_and_its_cases_can_still_change(lab):
    _, draft, (revision,) = lab.plan(cases=[("Pays by card", [])], approve=False)
    with lab.scope():
        CaseRevision.objects.filter(pk=revision.pk).update(title="Pays by saved card")
        PlanVersionCase.objects.filter(plan_version=draft).update(position=3)
        revision.refresh_from_db()
    assert revision.title == "Pays by saved card"
