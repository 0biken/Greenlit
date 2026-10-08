"""The role matrix, checked against an independent copy of PRD v2 section 9 (M1-10)."""

import uuid

import pytest

from apps.core.models import (
    Membership,
    MembershipStatus,
    Organisation,
    Project,
    ProjectMember,
    Role,
    User,
)
from apps.core.policy import MATRIX, Action, can, sees_every_project, visible_projects
from apps.core.tenancy import org_scope

ROLES = [r.value for r in Role]

# Copied by hand from the table in PRD v2, section 9. Columns: owner, admin, qa_lead,
# qa_engineer, developer, viewer. If the policy and this table disagree, one of them is wrong.
PRD_TABLE = {
    Action.MANAGE_MEMBERS: "YY....",  # admin: "members only"
    Action.MANAGE_BILLING: "Y.....",
    Action.CREATE_PROJECT: "YY....",
    Action.APPROVE_PLAN: "YYY...",
    Action.WRITE_TESTING: "YYYY..",
    Action.SET_FIXED: "YYYYY.",
    Action.MARK_VERIFIED: "YYYY..",
    Action.APPROVE_WONTFIX: "YYY...",
    Action.SIGN_OFF: "YYY...",
    Action.VIEW: "YYYYYY",
    Action.MANAGE_JOBS: "YY....",  # "Re-run failed background jobs"
}


def test_every_action_is_in_the_prd_table_and_the_policy():
    assert set(PRD_TABLE) == set(Action) == set(MATRIX)


@pytest.mark.parametrize("action", list(Action))
@pytest.mark.parametrize("role", ROLES)
def test_policy_matches_the_prd_table(role, action):
    expected = PRD_TABLE[action][ROLES.index(role)] == "Y"
    assert can(role, action) is expected


def test_nobody_below_qa_lead_can_sign_off_or_approve():
    for role in (Role.QA_ENGINEER, Role.DEVELOPER, Role.VIEWER):
        assert not can(role, Action.SIGN_OFF)
        assert not can(role, Action.APPROVE_PLAN)
        assert not can(role, Action.APPROVE_WONTFIX)


def test_a_developer_can_mark_fixed_but_never_verified():
    assert can(Role.DEVELOPER, Action.SET_FIXED)
    assert not can(Role.DEVELOPER, Action.MARK_VERIFIED)


def test_only_owners_and_admins_see_every_project():
    assert {r for r in ROLES if sees_every_project(r)} == {"owner", "admin"}


@pytest.mark.django_db
def test_project_visibility_follows_project_membership():
    org_id = uuid.uuid4()
    with org_scope(org_id):
        org = Organisation.objects.create(id=org_id, name="Gamma", slug="gamma")
        mine = Project.objects.create(org_id=org.id, name="Mine", key="MIN")
        theirs = Project.objects.create(org_id=org.id, name="Theirs", key="THE")
        user = User.objects.create_user("p@example.com", "x" * 14)
        ProjectMember.objects.create(org_id=org.id, project=mine, user=user)
        engineer = Membership.objects.create(
            org_id=org.id, user=user, role=Role.QA_ENGINEER, status=MembershipStatus.ACTIVE
        )
        seen = set(visible_projects(Project.objects.all(), engineer).values_list("id", flat=True))
        assert seen == {mine.id}

        engineer.role = Role.ADMIN
        seen = set(visible_projects(Project.objects.all(), engineer).values_list("id", flat=True))
        assert seen == {mine.id, theirs.id}
