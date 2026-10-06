"""Proof that the database itself isolates tenants (DATA §8, SEC §5).

Tests run as the owner role (it creates the test database) and switch to the restricted
`greenlit_app` role with SET LOCAL ROLE, the role the running app uses. Run with
DATABASE_URL set to the owner URL (see docs/local-setup-no-docker.md).
"""

import uuid

import pytest
from django.db import DatabaseError, connection, transaction

from apps.core.models import (
    Membership,
    MembershipStatus,
    Organisation,
    Project,
    ProjectMember,
    Role,
    User,
)
from apps.core.tenancy import org_scope, set_scope

pytestmark = pytest.mark.django_db


def as_app_role() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


def as_owner_role() -> None:
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")


def make_org(name: str, project_key: str) -> tuple[Organisation, Project]:
    org_id = uuid.uuid4()
    with org_scope(org_id):
        org = Organisation.objects.create(id=org_id, name=name, slug=name.lower())
        project = Project.objects.create(org_id=org.id, name=f"{name} app", key=project_key)
    return org, project


@pytest.fixture
def two_orgs():
    org_a, project_a = make_org("Alpha", "ALP")
    org_b, project_b = make_org("Beta", "BET")
    return org_a, project_a, org_b, project_b


def test_app_role_cannot_bypass_rls():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'greenlit_app'")
        assert cursor.fetchone() == (False, False)


def test_every_tenant_table_has_forced_rls():
    """A new tenant table without row-level security fails the build (M1-03)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND EXISTS (SELECT 1 FROM pg_attribute a
                          WHERE a.attrelid = c.oid AND a.attname = 'org_id' AND NOT a.attisdropped)
            """
        )
        tables = cursor.fetchall()
    assert tables, "expected at least one tenant table"
    missing = [name for name, enabled, forced in tables if not (enabled and forced)]
    assert missing == []


def test_query_without_scope_fails(two_orgs):
    as_app_role()
    set_scope(None)
    with pytest.raises(DatabaseError, match="no organisation scope"), transaction.atomic():
        list(Project.objects.all())


def test_scope_limits_reads_to_one_organisation(two_orgs):
    org_a, project_a, org_b, project_b = two_orgs
    as_app_role()
    set_scope(org_a.id)
    assert list(Project.objects.values_list("id", flat=True)) == [project_a.id]
    set_scope(org_b.id)
    assert list(Project.objects.values_list("id", flat=True)) == [project_b.id]


def test_cannot_look_up_another_organisations_row_by_id(two_orgs):
    org_a, _, _, project_b = two_orgs
    as_app_role()
    set_scope(org_a.id)
    assert not Project.objects.filter(id=project_b.id).exists()


def test_cannot_write_into_another_organisation(two_orgs):
    org_a, _, org_b, _ = two_orgs
    as_app_role()
    set_scope(org_a.id)
    with pytest.raises(DatabaseError), transaction.atomic():
        Project.objects.create(org_id=org_b.id, name="Smuggled", key="SMG")


def test_cannot_update_another_organisations_row(two_orgs):
    org_a, _, _, project_b = two_orgs
    as_app_role()
    set_scope(org_a.id)
    assert Project.objects.filter(id=project_b.id).update(name="Hijacked") == 0
    as_owner_role()
    with org_scope(project_b.org_id):
        assert Project.objects.get(id=project_b.id).name == "Beta app"


def test_foreign_key_cannot_point_into_another_organisation(two_orgs):
    org_a, _, _, project_b = two_orgs
    user = User.objects.create_user("tester@example.com", "x" * 14)
    as_app_role()
    set_scope(org_a.id)
    with pytest.raises(DatabaseError, match="cross-organisation"), transaction.atomic():
        ProjectMember.objects.create(org_id=org_a.id, project_id=project_b.id, user=user)


def test_foreign_key_trigger_also_holds_for_the_owner_role(two_orgs):
    """The same-organisation rule is a trigger, not only a policy, so it survives role changes."""
    org_a, project_a, _, project_b = two_orgs
    user = User.objects.create_user("tester2@example.com", "x" * 14)
    with org_scope(org_a.id):
        ProjectMember.objects.create(org_id=org_a.id, project_id=project_a.id, user=user)
    with org_scope(org_a.id):
        with pytest.raises(DatabaseError, match="cross-organisation"), transaction.atomic():
            ProjectMember.objects.create(org_id=org_a.id, project_id=project_b.id, user=user)


def test_user_sees_own_memberships_before_choosing_an_organisation(two_orgs):
    org_a, _, org_b, _ = two_orgs
    me = User.objects.create_user("me@example.com", "x" * 14)
    other = User.objects.create_user("other@example.com", "x" * 14)
    for org, user in [(org_a, me), (org_b, me), (org_a, other)]:
        with org_scope(org.id):
            Membership.objects.create(
                org_id=org.id, user=user, role=Role.QA_LEAD, status=MembershipStatus.ACTIVE
            )
    as_app_role()
    set_scope(None, me.id)
    assert Membership.objects.filter(user=me).count() == 2
    assert Membership.objects.filter(user=other).count() == 0
    assert set(Organisation.objects.values_list("id", flat=True)) == {org_a.id, org_b.id}


def test_user_scope_alone_does_not_allow_writing_memberships(two_orgs):
    _, _, org_b, _ = two_orgs
    me = User.objects.create_user("me2@example.com", "x" * 14)
    as_app_role()
    set_scope(None, me.id)
    with pytest.raises(DatabaseError), transaction.atomic():
        Membership.objects.create(org_id=org_b.id, user=me, role=Role.OWNER)


def test_soft_delete_hides_rows_and_keeps_them(two_orgs):
    org_a, project_a, _, _ = two_orgs
    with org_scope(org_a.id):
        Project.objects.get(id=project_a.id).delete()
        assert not Project.objects.filter(id=project_a.id).exists()
        assert Project.all_objects.filter(id=project_a.id, deleted_at__isnull=False).exists()
