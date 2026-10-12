"""Share links for signed reports (M8-08, FR-RPT-04, SEC §4).

A link shows the signed version only: the frozen report and the sign-off record, never live
data. It can be revoked and it expires (30 days by default). The token is shown once, when
the link is made; only its hash is stored. Every view and download through a link is audited.
"""

import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import Organisation
from apps.core.services import ServiceError, hash_token
from apps.core.tenancy import org_scope, scoped
from apps.reports.models import Report, ShareLink, SignOff
from apps.reports.services import signed_report
from apps.runs.models import Release

DEFAULT_DAYS = 30
MAX_DAYS = 365
NOT_FOUND = ServiceError("Not found.", code="not_found")


def create_link(release: Release, actor, days: int = DEFAULT_DAYS) -> tuple[ShareLink, str]:
    """Make a link to the release's signed report. Returns the link and its token; the token
    cannot be shown again."""
    report = signed_report(release)
    if report is None:
        raise ServiceError("Sign off the release first: only a signed report can be shared.")
    if not 1 <= days <= MAX_DAYS:
        raise ServiceError(f"A link can last from 1 to {MAX_DAYS} days.")
    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        link = ShareLink.objects.create(
            org_id=release.org_id,
            report=report,
            token_hash=hash_token(token),
            expires_at=timezone.now() + timedelta(days=days),
            created_by=actor,
        )
        audit.record(
            "share_link.created",
            "share_link",
            link.pk,
            actor=actor,
            after={"report": str(report.pk), "expires_at": link.expires_at.isoformat()},
        )
    return link, token


def links_for(release: Release):
    return (
        ShareLink.objects.filter(report__release=release)
        .select_related("created_by")
        .order_by("-created_at")
    )


def state_of(link: ShareLink) -> str:
    if link.revoked_at is not None:
        return "revoked"
    return "expired" if link.expires_at <= timezone.now() else "active"


def revoke(link: ShareLink, actor) -> ShareLink:
    if link.revoked_at is None:
        with transaction.atomic():
            link.revoked_at = timezone.now()
            link.save(update_fields=["revoked_at", "updated_at"])
            audit.record("share_link.revoked", "share_link", link.pk, actor=actor)
    return link


@dataclass
class Shared:
    """What a valid link shows. Everything here was fixed at sign-off."""

    link: ShareLink
    report: Report
    release: Release
    sign_off: SignOff
    project_name: str
    organisation_name: str


def open_link(token: str, action: str) -> Shared:
    """Resolve a token to the signed report it shares, and record the access. An unknown,
    expired or revoked token gives the same answer: not found."""
    token_hash = hash_token(token)
    # First find the link by the hash alone: no organisation is known yet (see the table's
    # row-level policy). Then continue inside that link's organisation, like a job does.
    with scoped(None, None, token_hash):
        link = ShareLink.objects.filter(token_hash=token_hash).first()
    if link is None or state_of(link) != "active":
        raise NOT_FOUND
    with org_scope(link.org_id):
        report = Report.objects.select_related("release__project").get(pk=link.report_id)
        release = report.release
        record = (
            SignOff.objects.filter(report=report)
            .select_related("signed_by")
            .order_by("-signed_at")
            .first()
        )
        if record is None:
            raise NOT_FOUND
        organisation = Organisation.objects.get(pk=link.org_id)
        audit.record(action, "share_link", link.pk, after={"report": str(report.pk)})
        return Shared(link, report, release, record, release.project.name, organisation.name)
