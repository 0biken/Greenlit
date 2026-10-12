from datetime import datetime

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.flags import flag_required
from apps.core.models import CounterKind
from apps.core.numbering import format_display_id
from apps.core.policy import Action, project_or_404, requires
from apps.core.views_orgs import _run
from apps.reports import services
from apps.reports.facts import build_facts
from apps.reports.models import SignOff
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
