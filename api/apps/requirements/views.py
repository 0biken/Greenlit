from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.choices import Origin, Priority, ReviewState
from apps.core.flags import flag_required
from apps.core.models import CounterKind, Project
from apps.core.numbering import parse_display_id
from apps.core.policy import Action, project_or_404, requires
from apps.core.views_orgs import _run
from apps.requirements import queries, services
from apps.requirements.models import Requirement

# --- shapes ----------------------------------------------------------------------------------


class RequirementRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_id = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    priority = serializers.ChoiceField(choices=Priority.choices)
    revision = serializers.IntegerField()
    review_state = serializers.ChoiceField(choices=ReviewState.choices)
    origin = serializers.ChoiceField(choices=Origin.choices)
    covered = serializers.BooleanField()
    cases = serializers.IntegerField()
    stale_cases = serializers.IntegerField()
    updated_at = serializers.DateTimeField()


class LinkedCaseSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    plan = serializers.CharField()
    plan_no = serializers.IntegerField()
    stale = serializers.BooleanField(help_text="Written against an older text of the requirement")


class RequirementTextSerializer(serializers.Serializer):
    revision = serializers.IntegerField()
    text = serializers.CharField()
    at = serializers.DateTimeField()
    by = serializers.CharField(allow_null=True)


class RequirementHistorySerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    actor = serializers.CharField()
    text = serializers.CharField()


class RequirementActionsSerializer(serializers.Serializer):
    edit = serializers.BooleanField()


class RequirementSourceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    page = serializers.IntegerField(allow_null=True)


class RequirementDetailSerializer(RequirementRowSerializer):
    text = serializers.CharField()
    stated_in = RequirementSourceSerializer(allow_null=True)
    created_by = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    linked_cases = LinkedCaseSerializer(many=True)
    revisions = RequirementTextSerializer(many=True)
    history = RequirementHistorySerializer(many=True)
    actions = RequirementActionsSerializer()


class RequirementEditSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    text = serializers.CharField(max_length=20000, required=False)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)


class RequirementWriteSerializer(RequirementEditSerializer):
    title = serializers.CharField(max_length=200)
    text = serializers.CharField(max_length=20000)


# --- lookups ---------------------------------------------------------------------------------


def requirement_or_404(project: Project, ident: str) -> Requirement:
    """The requirement by its uuid, number or REQ-n (DATA §4 rule 5)."""
    rows = Requirement.objects.filter(project=project).select_related(
        "project", "created_by", "source_document"
    )
    try:
        return rows.get(pk=UUID(ident))
    except (ValueError, Requirement.DoesNotExist):
        pass
    parsed = parse_display_id(ident)
    number = parsed.number if parsed and parsed.kind == CounterKind.REQUIREMENT else None
    if number is None and ident.isdigit():
        number = int(ident)
    requirement = rows.filter(display_no=number).first() if number else None
    if requirement is None:
        raise NotFound()
    return requirement


def _detail(request, requirement: Requirement) -> Response:
    data = queries.detail(requirement, request._request.membership)
    return Response(RequirementDetailSerializer(data).data)


# --- views -----------------------------------------------------------------------------------


@extend_schema(
    parameters=[
        OpenApiParameter("q", str, description="Part of the title or text, or a REQ number"),
        OpenApiParameter("priority", str, enum=Priority.values),
        OpenApiParameter("coverage", str, enum=["covered", "uncovered"]),
        OpenApiParameter(
            "state", str, enum=ReviewState.values, description="Default: not rejected"
        ),
    ],
    request=RequirementWriteSerializer,
    responses={200: RequirementRowSerializer(many=True), 201: RequirementDetailSerializer},
)
@api_view(["GET", "POST"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "POST": Action.WRITE_TESTING}), flag_required("plan")]
)
def requirements(request, key: str):
    """GET: the project's requirements with their coverage. POST: add one by hand (M2-08)."""
    project = project_or_404(request, key)
    if request.method == "GET":
        params = request.query_params
        rows = queries.requirement_list(
            project,
            q=params.get("q", ""),
            priority=params.get("priority", ""),
            coverage=params.get("coverage", ""),
            state=params.get("state", ""),
        )
        return Response(RequirementRowSerializer(rows, many=True).data)
    body = RequirementWriteSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    made = _run(
        services.create_requirement,
        project,
        request.user,
        title=data["title"],
        text=data["text"],
        priority=data.get("priority", Priority.MEDIUM),
    )
    response = _detail(request, requirement_or_404(project, str(made.pk)))
    response.status_code = 201
    return response


@extend_schema(request=RequirementEditSerializer, responses=RequirementDetailSerializer)
@api_view(["GET", "PATCH"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "PATCH": Action.WRITE_TESTING}), flag_required("plan")]
)
def requirement_detail(request, key: str, requirement_id: str):
    """GET: one requirement with the cases that cover it and its past texts. PATCH: edit it;
    changing the text raises its revision, which marks those cases Stale (FR-TC-05)."""
    project = project_or_404(request, key)
    requirement = requirement_or_404(project, requirement_id)
    if request.method == "PATCH":
        body = RequirementEditSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        _run(services.update_requirement, requirement, request.user, **body.validated_data)
    return _detail(request, requirement)
