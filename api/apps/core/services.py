"""Business rules for organisations, invitations and projects (FR-ORG-01 to 03).

Views validate the shape of a request and call these functions; the rules live here so they
can be tested without HTTP. Each function does its writes and its audit entry in one transaction.
"""

import hashlib
import re
import secrets
import uuid
from datetime import timedelta

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
