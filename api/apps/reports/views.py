from datetime import datetime

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.flags import flag_required
from apps.core.models import CounterKind
from apps.core.numbering import format_display_id
from apps.core.policy import Action, TokenAccess, project_or_404, requires
from apps.core.services import ServiceError
from apps.core.views_orgs import _run
from apps.reports import services, sharing
from apps.reports.facts import build_facts
from apps.reports.models import SignOff
from apps.reports.pdf import render_report
from apps.reports.summary import project_summary
from apps.runs.models import Release

# --- response shapes (also what `pnpm gen:api` turns into the web app's types) -------------


class CoverageSerializer(serializers.Serializer):
    verified_pct = serializers.IntegerField()
    verified = serializers.IntegerField()
    on_hold = serializers.IntegerField()
    failed = serializers.IntegerField()
    not_run = serializers.IntegerField()
    total_requirements = serializers.IntegerField()


class ReleaseBriefSerializer(serializers.Serializer):
    version = serializers.CharField()
    name = serializers.CharField()
    due = serializers.DateField(allow_null=True)
    readiness = serializers.ChoiceField(choices=("ready", "not_ready"))
    blockers = serializers.IntegerField()


class OpenWorkSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=(
            "needs_retest",
            "retest_failed",
            "stale",
            "uncovered",
            "missing_evidence",
            "unfiled_failures",
        )
    )
    count = serializers.IntegerField()
    oldest_days = serializers.IntegerField(allow_null=True)


class ActivitySerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    actor = serializers.CharField()
    text = serializers.CharField()
    refs = serializers.ListField(child=serializers.CharField())


class CountsSerializer(serializers.Serializer):
    requirements = serializers.IntegerField()
    cases = serializers.IntegerField()
    runs = serializers.IntegerField()
    open_defects = serializers.IntegerField()


class ProjectSummarySerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    client_name = serializers.CharField()
    is_new = serializers.BooleanField()
    release = ReleaseBriefSerializer(allow_null=True)
    coverage = CoverageSerializer(allow_null=True)
    open_work = OpenWorkSerializer(many=True)
    activity = ActivitySerializer(many=True)
    counts = CountsSerializer()


class BlockerSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=(
            "needs_retest",
            "open_critical",
            "closed_failed_retest",
            "uncovered_critical",
            "unfiled_failure",
        )
    )
    display_id = serializers.CharField()
    title = serializers.CharField()
    age_days = serializers.IntegerField()
    owner_name = serializers.CharField(allow_null=True)


class ReportLineSerializer(serializers.Serializer):
    text = serializers.CharField()
    refs = serializers.ListField(child=serializers.CharField())


class ReportSectionSerializer(serializers.Serializer):
    heading = serializers.CharField()
    lines = ReportLineSerializer(many=True)


class ReportSerializer(serializers.Serializer):
    display_id = serializers.CharField(allow_null=True)  # drafts are not stored, so have none
    state = serializers.ChoiceField(choices=("draft", "signed"))
    summary = serializers.CharField()
    sections = ReportSectionSerializer(many=True)


class SignOffSerializer(serializers.Serializer):
    by = serializers.CharField()
    at = serializers.DateTimeField()
    readiness = serializers.ChoiceField(choices=("ready", "not_ready"))
    reason = serializers.CharField(allow_null=True)


class ReleaseDetailSerializer(serializers.Serializer):
    project_key = serializers.CharField()
    version = serializers.CharField()
    name = serializers.CharField()
    due = serializers.DateField(allow_null=True)
    readiness = serializers.ChoiceField(choices=("ready", "not_ready"))
    blockers = BlockerSerializer(many=True)
    coverage = CoverageSerializer()
    report = ReportSerializer()
    sign_off = SignOffSerializer(allow_null=True)


class SignOffRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=2000, allow_blank=True, allow_null=True, required=False
    )


# --- views ---------------------------------------------------------------------------------


def _release(request, key: str, version: str) -> Release:
    project = project_or_404(request, key)
    release = (
        Release.objects.filter(project=project, name=version).select_related("project").first()
    )
    if release is None:
        raise NotFound()
    return release


def _age(since: str, now: datetime) -> int:
    return max((now - datetime.fromisoformat(since)).days, 0)


def release_detail_data(release: Release) -> dict:
    """Readiness and blockers are always live; the report is the signed copy once there is one."""
    now = timezone.now()
    facts = build_facts(release)
    signed = services.signed_report(release)
    report: dict[str, object]
    if signed is not None:
        body = signed.body
        report = {
            "display_id": format_display_id(CounterKind.REPORT, signed.display_no),
            "state": "signed",
        }
    else:
        body = services.report_body(facts)
        report = {"display_id": None, "state": "draft"}
    report.update(summary=body["summary"], sections=body["sections"])
    record = (
        SignOff.objects.filter(release=release)
        .select_related("signed_by")
        .order_by("-signed_at")
        .first()
    )
    data = facts.as_dict()
    return {
        "project_key": release.project.key,
        "version": release.name,
        "name": f"Release {release.name}",
        "due": release.target_date,
        "readiness": facts.readiness,
        "blockers": [{**b, "age_days": _age(b["since"], now)} for b in data["blockers"]],
        "coverage": data["coverage"],
        "report": report,
        "sign_off": (
            {
                "by": record.signed_by.name or record.signed_by.email,
                "at": record.signed_at,
                "readiness": record.readiness_at_signing,
                "reason": record.override_reason or None,
            }
            if record
            else None
        ),
    }


@extend_schema(responses=ProjectSummarySerializer)
@api_view(["GET"])
@permission_classes(requires(Action.VIEW))
def summary(request, key: str):
    """The project dashboard: next release, verified coverage, open work, recent activity."""
    project = project_or_404(request, key)
    return Response(ProjectSummarySerializer(project_summary(project)).data)


@extend_schema(responses=ReleaseDetailSerializer)
@api_view(["GET"])
@permission_classes([*requires(Action.VIEW), flag_required("rpt")])
def release_detail(request, key: str, version: str):
    """Readiness with blockers by type, verified coverage, the report and any sign-off."""
    return Response(
        ReleaseDetailSerializer(release_detail_data(_release(request, key, version))).data
    )


@extend_schema(request=SignOffRequestSerializer, responses=ReleaseDetailSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.SIGN_OFF), flag_required("rpt")])
def sign_off(request, key: str, version: str):
    """Sign off the release (M8-06). Not ready yet needs a written reason, kept on the record."""
    release = _release(request, key, version)
    body = SignOffRequestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    _run(services.sign_off, release, request._request.membership, body.validated_data.get("reason"))
    release.refresh_from_db()
    return Response(ReleaseDetailSerializer(release_detail_data(release)).data)


# --- PDF and share links (M8-07, M8-08) -------------------------------------------------------


class ShareLinkSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    state = serializers.ChoiceField(choices=("active", "expired", "revoked"))
    created_by = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()


class ShareLinkCreatedSerializer(ShareLinkSerializer):
    token = serializers.CharField(help_text="Shown once. Only its hash is stored.")


class ShareLinkRequestSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=sharing.MAX_DAYS, required=False)


class SharedReportSerializer(serializers.Serializer):
    organisation = serializers.CharField()
    project = serializers.CharField()
    version = serializers.CharField()
    report = ReportSerializer()
    sign_off = SignOffSerializer()
    blockers = BlockerSerializer(many=True)
    coverage = CoverageSerializer()
    expires_at = serializers.DateTimeField()


def _link_row(link) -> dict:
    return {
        "id": link.pk,
        "state": sharing.state_of(link),
        "created_by": (link.created_by.name or link.created_by.email) if link.created_by else None,
        "created_at": link.created_at,
        "expires_at": link.expires_at,
    }


def _pdf_response(pdf_bytes: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _signed_pdf(project_name: str, release: Release, report, record: SignOff) -> HttpResponse:
    report_id = format_display_id(CounterKind.REPORT, report.display_no)
    pdf_bytes = render_report(
        project=project_name,
        release=release.name,
        report_id=report_id,
        body=report.body,
        signed_by=record.signed_by.name or record.signed_by.email,
        signed_at=record.signed_at,
        readiness=record.readiness_at_signing,
        reason=record.override_reason,
    )
    safe = "".join(ch if ch.isalnum() or ch in ".-" else "-" for ch in release.name)
    return _pdf_response(pdf_bytes, f"{release.project.key}-{safe}-{report_id}.pdf")


@extend_schema(responses={(200, "application/pdf"): bytes})
@api_view(["GET"])
@permission_classes([*requires(Action.VIEW), flag_required("rpt")])
def report_pdf(request, key: str, version: str):
    """The signed report as a PDF (FR-RPT-04). Not found until the release is signed off."""
    release = _release(request, key, version)
    report = services.signed_report(release)
    record = (
        SignOff.objects.filter(report=report).select_related("signed_by").first()
        if report
        else None
    )
    if report is None or record is None:
        raise NotFound()
    return _signed_pdf(release.project.name, release, report, record)


@extend_schema(
    request=ShareLinkRequestSerializer,
    responses={200: ShareLinkSerializer(many=True), 201: ShareLinkCreatedSerializer},
)
@api_view(["GET", "POST"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "POST": Action.SIGN_OFF}), flag_required("rpt")]
)
def share_links(request, key: str, version: str):
    """GET: the release's share links, for anyone on the project (never their tokens). POST:
    make one (owners, admins and QA leads); its token is in the answer once and cannot be
    fetched again."""
    release = _release(request, key, version)
    if request.method == "GET":
        return Response(
            ShareLinkSerializer(
                [_link_row(link) for link in sharing.links_for(release)], many=True
            ).data
        )
    body = ShareLinkRequestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    link, token = _run(
        sharing.create_link,
        release,
        request.user,
        body.validated_data.get("days", sharing.DEFAULT_DAYS),
    )
    return Response(
        ShareLinkCreatedSerializer({**_link_row(link), "token": token}).data, status=201
    )


@extend_schema(request=None, responses={204: None})
@api_view(["DELETE"])
@permission_classes([*requires(Action.SIGN_OFF), flag_required("rpt")])
def share_link_detail(request, key: str, version: str, link_id):
    """Revoke a share link. It stops working at once."""
    release = _release(request, key, version)
    link = sharing.links_for(release).filter(pk=link_id).first()
    if link is None:
        raise NotFound()
    sharing.revoke(link, request.user)
    return Response(status=204)


def _open(token: str, action: str) -> sharing.Shared:
    try:
        return sharing.open_link(token, action)
    except ServiceError as error:
        raise NotFound() from error


@extend_schema(responses=SharedReportSerializer)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([TokenAccess, flag_required("rpt")])
def shared_report(request, token: str):
    """What a share link shows: the signed report and its sign-off, as they were signed.
    Never live data. Unknown, expired and revoked links are all simply not found."""
    shared = _open(token, "share_link.viewed")
    facts = shared.report.body.get("facts", {})
    signed_at = shared.sign_off.signed_at
    data = {
        "organisation": shared.organisation_name,
        "project": shared.project_name,
        "version": shared.release.name,
        "report": {
            "display_id": format_display_id(CounterKind.REPORT, shared.report.display_no),
            "state": "signed",
            "summary": shared.report.body["summary"],
            "sections": shared.report.body["sections"],
        },
        "sign_off": {
            "by": shared.sign_off.signed_by.name or shared.sign_off.signed_by.email,
            "at": signed_at,
            "readiness": shared.sign_off.readiness_at_signing,
            "reason": shared.sign_off.override_reason or None,
        },
        # Ages are counted to the moment of signing, so the page reads the same every day.
        "blockers": [
            {**b, "age_days": _age(b["since"], signed_at)} for b in facts.get("blockers", [])
        ],
        "coverage": facts.get("coverage", {}),
        "expires_at": shared.link.expires_at,
    }
    return Response(SharedReportSerializer(data).data)


@extend_schema(responses={(200, "application/pdf"): bytes})
@api_view(["GET"])
@authentication_classes([])
@permission_classes([TokenAccess, flag_required("rpt")])
def shared_report_pdf(request, token: str):
    """The signed report as a PDF, through a share link. Each download is audited."""
    shared = _open(token, "share_link.downloaded")
    return _signed_pdf(shared.project_name, shared.release, shared.report, shared.sign_off)
