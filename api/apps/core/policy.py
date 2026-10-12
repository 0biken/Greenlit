"""The one permission module (M1-10, SEC §4, PRD §9).

Every endpoint declares what it needs with `requires(Action.X)`; no endpoint writes its own
role logic. The checks run on the server in a fixed order, before any data is read:

1. Who are you?        a signed-in user (DRF `IsAuthenticated`);
2. Which organisation? an active membership, resolved by the tenancy middleware, else 404;
3. Two-step?           owners and admins must have set it up, else 403 `mfa_required`;
4. May you do this?    the role allows the action, else 403.

A record the user cannot see is "not found", never "forbidden". A 403 means the user can see
the thing but may not do that to it: their role forbids it, or two-step verification is missing.
"""

from enum import StrEnum

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.core.mfa import MfaRequired, needs_mfa_enrolment
from apps.core.models import Project, ProjectMember, Role


class Action(StrEnum):
    """One member per row of the role matrix in PRD v2, section 9."""

    MANAGE_MEMBERS = "manage_members"
    MANAGE_BILLING = "manage_billing"
    CREATE_PROJECT = "create_project"
    APPROVE_PLAN = "approve_plan"
    WRITE_TESTING = "write_testing"  # write cases, record runs, attach evidence
    SET_FIXED = "set_fixed"
    MARK_VERIFIED = "mark_verified"
    APPROVE_WONTFIX = "approve_wontfix"
    SIGN_OFF = "sign_off"
    VIEW = "view"
    MANAGE_JOBS = "manage_jobs"  # re-run failed background jobs (everyone can watch progress)


_OWNER = {Role.OWNER}
_OWNER_ADMIN = _OWNER | {Role.ADMIN}
_LEADS = _OWNER_ADMIN | {Role.QA_LEAD}
_TESTERS = _LEADS | {Role.QA_ENGINEER}
_FIXERS = _TESTERS | {Role.DEVELOPER}
_EVERYONE = _FIXERS | {Role.VIEWER}

MATRIX: dict[Action, frozenset[str]] = {
    Action.MANAGE_MEMBERS: frozenset(_OWNER_ADMIN),
    Action.MANAGE_BILLING: frozenset(_OWNER),
    Action.CREATE_PROJECT: frozenset(_OWNER_ADMIN),
    Action.APPROVE_PLAN: frozenset(_LEADS),
    Action.WRITE_TESTING: frozenset(_TESTERS),
    Action.SET_FIXED: frozenset(_FIXERS),
    Action.MARK_VERIFIED: frozenset(_TESTERS),
    Action.APPROVE_WONTFIX: frozenset(_LEADS),
    Action.SIGN_OFF: frozenset(_LEADS),
    Action.VIEW: frozenset(_EVERYONE),
    Action.MANAGE_JOBS: frozenset(_OWNER_ADMIN),
}


def can(role: str, action: Action) -> bool:
    return role in MATRIX[action]


def sees_every_project(role: str) -> bool:
    """Owners and admins see all projects; everyone else needs a project_member row."""
    return role in _OWNER_ADMIN


def visible_projects(queryset, membership):
    """Narrow a Project queryset to what this member may see (DATA §8 rule 3).

    Must be used for every project lookup, so an unseen project is simply not found.
    """
    if sees_every_project(membership.role):
        return queryset
    member_of = ProjectMember.objects.filter(user_id=membership.user_id).values("project_id")
    return queryset.filter(id__in=member_of)


def project_or_404(request, key: str) -> Project:
    """The project with this key, if the caller may see it; otherwise 404 (never 403)."""
    project = (
        visible_projects(Project.objects.all(), request._request.membership)
        .filter(key=key.upper())
        .first()
    )
    if project is None:
        raise NotFound()
    return project


class _Requires(BasePermission):
    """`actions` maps an HTTP method to the action it needs. HEAD and OPTIONS follow GET."""

    actions: dict[str, Action]

    def has_permission(self, request, view) -> bool:
        membership = getattr(request._request, "membership", None)
        if membership is None:
            raise NotFound()  # no organisation named, or not a member of it
        if needs_mfa_enrolment(request.user, membership.role):
            raise MfaRequired()
        method = request.method.upper()
        action = self.actions.get(method) or (
            self.actions.get("GET") if method in ("HEAD", "OPTIONS") else None
        )
        if action is None:
            return True  # a method the view does not handle; DRF answers 405
        return can(membership.role, action)


def requires(action: Action | dict[str, Action]) -> list[type[BasePermission]]:
    """The `permission_classes` for an endpoint that needs `action` in the current organisation.

    Pass one action for every method, or a dict such as
    `{"GET": Action.VIEW, "POST": Action.CREATE_PROJECT}`.
    """
    actions = action if isinstance(action, dict) else dict.fromkeys(_ALL_METHODS, action)
    name = "_".join(sorted({a.value for a in actions.values()}))
    cls = type(f"Requires_{name}", (_Requires,), {"actions": actions})
    return [IsAuthenticated, cls]


_ALL_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


class Public(BasePermission):
    """Marks an endpoint as deliberately open to anyone (health check, API schema)."""

    def has_permission(self, request, view) -> bool:
        return True


class AuthenticatedOnly(IsAuthenticated):
    """Marks an endpoint that needs a signed-in user but no organisation, such as `/api/me/`."""
