"""Business rules for organisations, invitations and projects (FR-ORG-01 to 03).

Views validate the shape of a request and call these functions; the rules live here so they
can be tested without HTTP. Each function does its writes and its audit entry in one transaction.
"""

import hashlib
import re
import secrets
import uuid
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import (
    Invitation,
    Membership,
    MembershipStatus,
    Organisation,
    Project,
    ProjectMember,
    Role,
    User,
)
from apps.core.tenancy import org_scope, scoped

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38})[a-z0-9]$")
PROJECT_KEY_RE = re.compile(r"^[A-Za-z]{2,6}$")
# Words that would collide with routes or look official.
RESERVED_SLUGS = frozenset(
    {"admin", "api", "accounts", "static", "www", "app", "help", "support", "new", "settings"}
)


class ServiceError(Exception):
    """A rule was broken. `message` is safe to show to the person who made the request."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.code = code


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def slugify_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]


# --- Organisations (FR-ORG-01) -------------------------------------------------------------


def create_organisation(user: User, name: str, slug: str | None = None) -> Organisation:
    """Create an organisation with `user` as its owner."""
    name = name.strip()
    if not name:
        raise ServiceError("Give the organisation a name.")
    explicit = bool(slug)
    base = slug if slug else slugify_name(name)
    candidates = [base]
    if not explicit:
        # The address came from the name, so a clash is resolved by adding a short suffix.
        candidates += [f"{base[:34]}-{secrets.token_hex(2)}" for _ in range(4)]

    for candidate in candidates:
        if not SLUG_RE.match(candidate or "") or candidate in RESERVED_SLUGS:
            raise ServiceError(
                "Use 3 to 40 lowercase letters, numbers and hyphens for the address."
                if explicit
                else "Choose an address for the organisation: letters, numbers and hyphens."
            )
        org_id = uuid.uuid4()
        try:
            with org_scope(org_id, user.pk):
                org = Organisation.objects.create(id=org_id, name=name, slug=candidate)
                Membership.objects.create(
                    org_id=org_id, user=user, role=Role.OWNER, status=MembershipStatus.ACTIVE
                )
                audit.record(
                    "organisation.created",
                    "organisation",
                    org_id,
                    actor=user,
                    after={"name": name, "slug": candidate},
                )
            return org
        except IntegrityError:
            continue  # the address is taken; try the next candidate
    raise ServiceError("That address is not available.", code="slug_taken")


# --- Invitations (FR-ORG-01) ---------------------------------------------------------------


def invite_member(inviter: Membership, org: Organisation, email: str, role: str) -> Invitation:
    """Invite `email` to `org` with `role`. Must run inside the organisation's scope."""
    email = email.strip().lower()
    if role not in Role.values:
        raise ServiceError("Choose a valid role.")
    if role == Role.OWNER and inviter.role != Role.OWNER:
        raise ServiceError("Only an owner can invite another owner.", code="forbidden")
    if Membership.objects.filter(
        user__email__iexact=email, status=MembershipStatus.ACTIVE
    ).exists():
        raise ServiceError("That person is already a member.")

    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        # A new invitation replaces any earlier pending one for the same address.
        Invitation.objects.filter(
            email=email, accepted_at__isnull=True, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
        invitation = Invitation.objects.create(
            org_id=org.pk,
            email=email,
            role=role,
            token_hash=hash_token(token),
            expires_at=timezone.now() + timedelta(days=settings.INVITE_TTL_DAYS),
            invited_by=inviter.user,
        )
        audit.record(
            "member.invited",
            "invitation",
            invitation.pk,
            actor=inviter.user,
            after={"email": email, "role": role},
        )
        link = f"{settings.FRONTEND_URL}/invite/{token}"
        # Titles and links only, never document content (SEC §10).
        subject = f"You're invited to {org.name} on Greenlit"
        body = (
            f"{inviter.user.name or inviter.user.email} invited you to join {org.name} on "
            f"Greenlit as {Role(role).label}.\n\nAccept the invitation: {link}\n\n"
            f"The link works for {settings.INVITE_TTL_DAYS} days."
        )
        transaction.on_commit(lambda: send_mail(subject, body, None, [email]))
    return invitation


def accept_invitation(user: User, token: str) -> Membership:
    """Join the organisation named by an invitation token (FR-ORG-01).

    Every way this can fail gives the same answer, so a guessed or stolen token learns nothing.
    """
    refusal = ServiceError("This invitation is not valid.", code="invalid_invitation")
    token_hash = hash_token(token)
    with scoped(None, user.pk, token_hash):
        invitation = Invitation.objects.filter(token_hash=token_hash).first()
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or invitation.expires_at < timezone.now()
            or invitation.email != user.email.lower()
            # The invitation went to this address, so the account must have proved it owns it.
            or not EmailAddress.objects.filter(
                user=user, email__iexact=invitation.email, verified=True
            ).exists()
        ):
            raise refusal
        org_id, role = invitation.org_id, invitation.role

    with org_scope(org_id, user.pk):
        invitation = Invitation.objects.get(token_hash=token_hash)
        membership = Membership.objects.filter(user=user).first()
        before = {"role": membership.role, "status": membership.status} if membership else {}
        if membership is None:
            membership = Membership.objects.create(
                org_id=org_id, user=user, role=role, status=MembershipStatus.ACTIVE
            )
        else:
            membership.role, membership.status = role, MembershipStatus.ACTIVE
            membership.save(update_fields=["role", "status", "updated_at"])
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at", "updated_at"])
        audit.record(
            "member.joined",
            "membership",
            membership.pk,
            actor=user,
            before=before,
            after={"role": role, "status": MembershipStatus.ACTIVE.value},
        )
    return membership


# --- Projects (FR-ORG-03) ------------------------------------------------------------------


def create_project(
    creator: Membership, name: str, key: str, client_name: str = "", member_ids=()
) -> Project:
    """Create a project in the current organisation. Must run inside its scope."""
    name, key = name.strip(), key.strip().upper()
    if not name:
        raise ServiceError("Give the project a name.")
    if not PROJECT_KEY_RE.match(key):
        raise ServiceError("The project key is 2 to 6 letters.")
    if Project.all_objects.filter(key=key).exists():
        raise ServiceError("That project key is already used in this organisation.")

    member_ids = list(dict.fromkeys(member_ids))
    members = list(
        Membership.objects.filter(user_id__in=member_ids, status=MembershipStatus.ACTIVE)
    )
    if len(members) != len(member_ids):
        raise ServiceError("Every project member must be an active member of the organisation.")

    with transaction.atomic():
        project = Project.objects.create(
            org_id=creator.org_id, name=name, client_name=client_name.strip(), key=key
        )
        for member in members:
            ProjectMember.objects.create(
                org_id=creator.org_id, project=project, user_id=member.user_id
            )
        audit.record(
            "project.created",
            "project",
            project.pk,
            actor=creator.user,
            after={
                "name": name,
                "key": key,
                "client_name": client_name.strip(),
                "members": [str(m.user_id) for m in members],
            },
        )
    return project


# --- Managing members (M1-19) ----------------------------------------------------------------

NOT_FOUND = "Not found."
LAST_OWNER = "An organisation needs at least one owner. Make someone else an owner first."
OWNERS_ONLY = "Only an owner can change an owner, or make someone an owner."


def _active_member(user_id) -> Membership:
    """An active member of the current organisation, or not found (never "forbidden")."""
    target = (
        Membership.objects.filter(user_id=user_id, status=MembershipStatus.ACTIVE)
        .select_related("user")
        .first()
    )
    if target is None:
        raise ServiceError(NOT_FOUND, code="not_found")
    return target


def _leaves_no_owner(target: Membership) -> bool:
    if target.role != Role.OWNER:
        return False
    return Membership.objects.filter(role=Role.OWNER, status=MembershipStatus.ACTIVE).count() <= 1


def change_role(actor: Membership, user_id, role: str) -> Membership:
    if role not in Role.values:
        raise ServiceError("Choose a valid role.")
    target = _active_member(user_id)
    if target.role == role:
        return target
    if Role.OWNER in (target.role, role) and actor.role != Role.OWNER:
        raise ServiceError(OWNERS_ONLY, code="forbidden")
    if role != Role.OWNER and _leaves_no_owner(target):
        raise ServiceError(LAST_OWNER, code="last_owner")

    before = target.role
    with transaction.atomic():
        target.role = role
        target.save(update_fields=["role", "updated_at"])
        audit.record(
            "member.role_changed",
            "membership",
            target.pk,
            actor=actor.user,
            before={"role": before},
            after={"role": role},
        )
    return target


def remove_member(actor: Membership, user_id) -> None:
    """Take someone out of the organisation. Their account and other organisations remain."""
    target = _active_member(user_id)
    if target.role == Role.OWNER and actor.role != Role.OWNER:
        raise ServiceError(OWNERS_ONLY, code="forbidden")
    if _leaves_no_owner(target):
        raise ServiceError(LAST_OWNER, code="last_owner")
    with transaction.atomic():
        target.status = MembershipStatus.REMOVED
        target.save(update_fields=["status", "updated_at"])
        ProjectMember.objects.filter(user_id=target.user_id).delete()  # soft delete
        audit.record(
            "member.removed",
            "membership",
            target.pk,
            actor=actor.user,
            before={"status": MembershipStatus.ACTIVE.value, "role": target.role},
            after={"status": MembershipStatus.REMOVED.value},
        )


def pending_invitations():
    return Invitation.objects.filter(
        accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()
    ).order_by("-created_at")


def revoke_invitation(actor: Membership, invitation_id) -> None:
    invitation = pending_invitations().filter(pk=invitation_id).first()
    if invitation is None:
        raise ServiceError(NOT_FOUND, code="not_found")
    with transaction.atomic():
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["revoked_at", "updated_at"])
        audit.record(
            "invitation.revoked",
            "invitation",
            invitation.pk,
            actor=actor.user,
            before={"email": invitation.email, "state": "pending"},
            after={"state": "revoked"},
        )


# --- Changing projects (M1-19) ---------------------------------------------------------------


def update_project(
    actor: Membership,
    project: Project,
    name: str | None = None,
    client_name: str | None = None,
    settings_changes: dict | None = None,
) -> Project:
    from apps.core.project_settings import clean_settings

    before: dict = {}
    after: dict = {}
    if name is not None:
        name = name.strip()
        if not name:
            raise ServiceError("Give the project a name.")
        if name != project.name:
            before["name"], after["name"] = project.name, name
    if client_name is not None and client_name.strip() != project.client_name:
        before["client_name"], after["client_name"] = project.client_name, client_name.strip()
    new_settings = None
    if settings_changes is not None:
        new_settings = clean_settings(project.settings, settings_changes)
        if new_settings == project.settings:
            new_settings = None

    with transaction.atomic():
        if after:
            for field_name, value in after.items():
                setattr(project, field_name, value)
            project.save(update_fields=[*after, "updated_at"])
            audit.record(
                "project.updated",
                "project",
                project.pk,
                actor=actor.user,
                before=before,
                after=after,
            )
        if new_settings is not None:
            old = project.settings
            project.settings = new_settings
            project.save(update_fields=["settings", "updated_at"])
            audit.record(
                "project.settings_changed",
                "project",
                project.pk,
                actor=actor.user,
                before={"settings": old},
                after={"settings": new_settings},
            )
    return project


def add_project_member(actor: Membership, project: Project, user_id) -> None:
    target = _active_member(user_id)
    existing = ProjectMember.all_objects.filter(project=project, user_id=target.user_id).first()
    if existing is not None and existing.deleted_at is None:
        return  # already on the project
    with transaction.atomic():
        if existing is not None:
            # The unique (project, user) row survives a soft delete, so restore it.
            existing.deleted_at = None
            existing.save(update_fields=["deleted_at", "updated_at"])
        else:
            ProjectMember.objects.create(
                org_id=project.org_id, project=project, user_id=target.user_id
            )
        audit.record(
            "project.member_added",
            "project",
            project.pk,
            actor=actor.user,
            after={"user_id": str(target.user_id)},
        )


def remove_project_member(actor: Membership, project: Project, user_id) -> None:
    row = ProjectMember.objects.filter(project=project, user_id=user_id).first()
    if row is None:
        raise ServiceError(NOT_FOUND, code="not_found")
    with transaction.atomic():
        row.delete()  # soft delete
        audit.record(
            "project.member_removed",
            "project",
            project.pk,
            actor=actor.user,
            before={"user_id": str(user_id)},
        )
