from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.flags import flag_required
from apps.core.models import CounterKind, Project
from apps.core.numbering import format_display_id, parse_display_id
from apps.core.policy import Action, project_or_404, requires
from apps.core.views_orgs import _run
from apps.defects import status
from apps.defects.models import Defect, RetestOutcome, TrackerStatus


class DefectStateSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    tracker_status = serializers.CharField()
    qa_status = serializers.CharField()
    shown_as = serializers.CharField()


class RetestSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=RetestOutcome.choices)
    evidence_file_ids = serializers.ListField(child=serializers.UUIDField(), max_length=20)
    build = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    environment = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )


def defect_or_404(project: Project, ident: str) -> Defect:
    """APIs accept the uuid, the number, or the display ID (DATA §4 rule 5)."""
    rows = Defect.objects.filter(project=project)
    try:
        return rows.get(pk=UUID(ident))
    except (ValueError, Defect.DoesNotExist):
        pass
    parsed = parse_display_id(ident)
    number = parsed.number if parsed and parsed.kind == CounterKind.DEFECT else None
    if number is None and ident.isdigit():
        number = int(ident)
    defect = rows.filter(display_no=number).first() if number else None
    if defect is None:
        raise NotFound()
    return defect


def _state(defect: Defect) -> dict:
    return {
        "display_id": format_display_id(CounterKind.DEFECT, defect.display_no),
        "tracker_status": defect.tracker_status,
        "qa_status": defect.qa_status,
        "shown_as": status.shown_as(defect),
    }


@extend_schema(request=None, responses=DefectStateSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.SET_FIXED), flag_required("def")])
def mark_fixed(request, key: str, defect_id: str):
    """Set the defect to Fixed (FR-DEF-02). It moves to Needs retest."""
    defect = defect_or_404(project_or_404(request, key), defect_id)
    defect = _run(status.set_tracker_status, defect, request.user, TrackerStatus.FIXED)
    return Response(_state(defect))


@extend_schema(request=RetestSerializer, responses={201: DefectStateSerializer})
@api_view(["POST"])
@permission_classes([*requires(Action.MARK_VERIFIED), flag_required("def")])
def retests(request, key: str, defect_id: str):
    """Record a retest with evidence (FR-DEF-03). Passed: Verified. Failed: Retest failed,
    and the tracker status goes back to Open."""
    defect = defect_or_404(project_or_404(request, key), defect_id)
    body = RetestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    _run(
        status.record_retest,
        defect,
        request.user,
        outcome=data["outcome"],
        evidence_file_ids=data["evidence_file_ids"],
        build=data["build"],
        environment=data["environment"],
    )
    defect.refresh_from_db()
    return Response(_state(defect), status=201)
