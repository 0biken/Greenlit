from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.choices import Priority
from apps.core.flags import flag_required
from apps.core.models import CounterKind, Membership, MembershipStatus, Project
from apps.core.numbering import parse_display_id
from apps.core.policy import Action, project_or_404, requires, visible_projects
from apps.core.services import ServiceError
from apps.core.views_orgs import _run
from apps.defects import queries, status
from apps.defects.models import Defect, QaStatus, RetestOutcome, TrackerStatus
from apps.runs.models import CaseResult, Release

# --- shapes ----------------------------------------------------------------------------------


class DefectStateSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    tracker_status = serializers.CharField()
    qa_status = serializers.CharField()
    shown_as = serializers.CharField()


class DefectRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_id = serializers.CharField()
    title = serializers.CharField()
    severity = serializers.ChoiceField(choices=Priority.choices)
    tracker_status = serializers.ChoiceField(choices=TrackerStatus.choices)
    qa_status = serializers.ChoiceField(choices=QaStatus.choices)
    shown_as = serializers.CharField()
    chip = serializers.CharField()
    owner_name = serializers.CharField(allow_null=True)
    release = serializers.CharField(allow_null=True)
    age_days = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class EvidenceSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    file_id = serializers.UUIDField()
    name = serializers.CharField()
    mime = serializers.CharField()
    state = serializers.CharField()


class RetestRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=RetestOutcome.choices)
    by = serializers.CharField(allow_null=True)
    at = serializers.DateTimeField()
    build = serializers.CharField()
    environment = serializers.CharField()
    evidence = EvidenceSerializer(many=True)


class FoundInSerializer(serializers.Serializer):
    run = serializers.CharField()
    run_no = serializers.IntegerField()
    case = serializers.CharField()
    case_title = serializers.CharField()
    result_id = serializers.UUIDField()


class RequirementRefSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    title = serializers.CharField()


class DecisionSerializer(serializers.Serializer):
    decision = serializers.CharField()
    reason = serializers.CharField()
    by = serializers.CharField(allow_null=True)


class HistoryLineSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    actor = serializers.CharField()
    text = serializers.CharField()


class DefectActionsSerializer(serializers.Serializer):
    edit = serializers.BooleanField()
    set_status = serializers.ListField(child=serializers.ChoiceField(choices=TrackerStatus.choices))
    retest = serializers.BooleanField()
    decide = serializers.BooleanField()


class DefectDetailSerializer(DefectRowSerializer):
    steps = serializers.CharField(allow_blank=True)
    expected = serializers.CharField(allow_blank=True)
    actual = serializers.CharField(allow_blank=True)
    owner_id = serializers.UUIDField(allow_null=True)
    created_by = serializers.CharField(allow_null=True)
    fixed_at = serializers.DateTimeField(allow_null=True)
    fixed_by = serializers.CharField(allow_null=True)
    decision = DecisionSerializer(allow_null=True)
    found_in = FoundInSerializer(allow_null=True)
    requirements = RequirementRefSerializer(many=True)
    evidence = EvidenceSerializer(many=True)
    retests = RetestRowSerializer(many=True)
    history = HistoryLineSerializer(many=True)
    actions = DefectActionsSerializer()


class DefectEditSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    steps = serializers.CharField(max_length=10000, required=False, allow_blank=True)
    expected = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    actual = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    severity = serializers.ChoiceField(choices=Priority.choices, required=False)
    owner_id = serializers.UUIDField(required=False, allow_null=True)
    release = serializers.CharField(
        max_length=60, required=False, allow_null=True, allow_blank=True
    )


class DefectWriteSerializer(DefectEditSerializer):
    title = serializers.CharField(max_length=200)
    # Where it was found is set once, when the defect is filed.
    found_in_result = serializers.UUIDField(required=False, allow_null=True)
    evidence_file_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=20, required=False
    )


class StatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TrackerStatus.choices)


class DecisionRequestSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=(QaStatus.WONT_FIX, QaStatus.DEFERRED))
    reason = serializers.CharField(max_length=2000, allow_blank=True)


class RetestSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=RetestOutcome.choices)
    evidence_file_ids = serializers.ListField(child=serializers.UUIDField(), max_length=20)
    build = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    environment = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )


# --- lookups ---------------------------------------------------------------------------------


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
        "display_id": queries.bug_id(defect),
        "tracker_status": defect.tracker_status,
        "qa_status": defect.qa_status,
        "shown_as": status.shown_as(defect),
    }


def _references(request, project: Project, data: dict) -> dict:
    """Turn the owner, release and result named in a request into records of this project.
    Anything that is not in the project is a plain validation error: it names nothing."""
    out: dict = {}
    if "owner_id" in data:
        owner = None
        if data["owner_id"] is not None:
            member = (
                Membership.objects.filter(user_id=data["owner_id"], status=MembershipStatus.ACTIVE)
                .select_related("user")
                .first()
            )
            on_project = (
                member is not None
                and visible_projects(Project.objects.filter(pk=project.pk), member).exists()
            )
            if not on_project:
                raise ServiceError("Choose an owner who is on this project.")
            owner = member.user
        out["owner"] = owner
    if "release" in data:
        release = None
        if data["release"]:
            release = Release.objects.filter(project=project, name=data["release"]).first()
            if release is None:
                raise ServiceError("That release is not in this project.")
        out["release"] = release
    if data.get("found_in_result") is not None:
        result = (
            CaseResult.objects.filter(pk=data["found_in_result"], run__project=project)
            .select_related("run__release")
            .first()
        )
        if result is None:
            raise ServiceError("That result is not in this project.")
        out["found_in_result"] = result
    return out


def _detail(request, defect: Defect) -> Response:
    defect = Defect.objects.select_related(
        "owner",
        "release",
        "created_by",
        "fixed_by",
        "decided_by",
        "found_in_result__run",
        "found_in_result__case_revision__test_case",
    ).get(pk=defect.pk)
    data = queries.detail(defect, request._request.membership)
    return Response(DefectDetailSerializer(data).data)


# --- views -----------------------------------------------------------------------------------


@extend_schema(
    parameters=[
        OpenApiParameter("state", str, enum=list(queries.STATES)),
        OpenApiParameter("severity", str, enum=Priority.values),
        OpenApiParameter("release", str),
        OpenApiParameter("q", str, description="Part of the title, or a BUG number"),
    ],
    request=DefectWriteSerializer,
    responses={200: DefectRowSerializer(many=True), 201: DefectDetailSerializer},
)
@api_view(["GET", "POST"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "POST": Action.WRITE_TESTING}), flag_required("def")]
)
def defects(request, key: str):
    """GET: the project's defects, open work first. POST: file a defect (FR-DEF-01)."""
    project = project_or_404(request, key)
    if request.method == "GET":
        params = request.query_params
        rows = queries.defect_list(
            project,
            state=params.get("state", ""),
            severity=params.get("severity", ""),
            release=params.get("release", ""),
            q=params.get("q", ""),
        )
        return Response(DefectRowSerializer([queries.list_row(d) for d in rows], many=True).data)
    body = DefectWriteSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data

    def create() -> Defect:
        refs = _references(request, project, data)
        return status.create_defect(
            project,
            request.user,
            title=data["title"],
            steps=data.get("steps", ""),
            expected=data.get("expected", ""),
            actual=data.get("actual", ""),
            severity=data.get("severity", Priority.MEDIUM),
            evidence_file_ids=data.get("evidence_file_ids", []),
            **refs,
        )

    response = _detail(request, _run(create))
    response.status_code = 201
    return response


@extend_schema(request=DefectEditSerializer, responses=DefectDetailSerializer)
@api_view(["GET", "PATCH"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "PATCH": Action.WRITE_TESTING}), flag_required("def")]
)
def defect_detail(request, key: str, defect_id: str):
    """GET: one defect with its retests, evidence and history. PATCH: edit its own fields."""
    project = project_or_404(request, key)
    defect = defect_or_404(project, defect_id)
    if request.method == "PATCH":
        body = DefectEditSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        def edit() -> Defect:
            changes = {
                k: v
                for k, v in data.items()
                if k in ("title", "steps", "expected", "actual", "severity")
            }
            changes.update(_references(request, project, data))
            return status.update_defect(defect, request.user, **changes)

        defect = _run(edit)
    return _detail(request, defect)


@extend_schema(request=StatusChangeSerializer, responses=DefectStateSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.SET_FIXED), flag_required("def")])
def set_status(request, key: str, defect_id: str):
    """Set the tracker status: open, in progress, fixed or closed (FR-DEF-02, FR-DEF-05)."""
    defect = defect_or_404(project_or_404(request, key), defect_id)
    body = StatusChangeSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    defect = _run(status.set_tracker_status, defect, request.user, body.validated_data["status"])
    return Response(_state(defect))


@extend_schema(request=None, responses=DefectStateSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.SET_FIXED), flag_required("def")])
def mark_fixed(request, key: str, defect_id: str):
    """Set the defect to Fixed (FR-DEF-02). It moves to Needs retest."""
    defect = defect_or_404(project_or_404(request, key), defect_id)
    defect = _run(status.set_tracker_status, defect, request.user, TrackerStatus.FIXED)
    return Response(_state(defect))


@extend_schema(request=DecisionRequestSerializer, responses=DefectStateSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.APPROVE_WONTFIX), flag_required("def")])
def decision(request, key: str, defect_id: str):
    """Won't fix or Deferred, with a reason; the approver is recorded (FR-DEF-04)."""
    defect = defect_or_404(project_or_404(request, key), defect_id)
    body = DecisionRequestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    defect = _run(status.decide, defect, request.user, data["decision"], data["reason"])
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
