from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.ai.models import RejectReason
from apps.core.choices import Origin, Priority, ReviewState
from apps.core.flags import flag_required
from apps.core.models import Project
from apps.core.policy import Action, project_or_404, requires
from apps.core.views_orgs import _run
from apps.requirements.views import requirement_or_404
from apps.sources import queries, services
from apps.sources.models import SourceDocument, SourceKind, SourceState

# --- shapes ----------------------------------------------------------------------------------


class SourceJobSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    state = serializers.CharField()
    running = serializers.BooleanField()
    progress = serializers.CharField(allow_blank=True)
    done = serializers.IntegerField()
    total = serializers.IntegerField()
    error = serializers.CharField(allow_blank=True)


class SourceRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    kind = serializers.ChoiceField(choices=SourceKind.choices)
    state = serializers.ChoiceField(choices=SourceState.choices)
    failure = serializers.CharField(allow_blank=True)
    pages = serializers.IntegerField()
    pasted = serializers.BooleanField()
    file_name = serializers.CharField(allow_null=True)
    added_by = serializers.CharField(allow_null=True)
    added_at = serializers.DateTimeField()
    drafts = serializers.IntegerField()
    accepted = serializers.IntegerField()
    rejected = serializers.IntegerField()
    job = SourceJobSerializer(allow_null=True)


class SourcePageSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    start = serializers.IntegerField(help_text="Where this page starts in the whole text")
    text = serializers.CharField(allow_blank=True)


class SourceItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.IntegerField()
    display_id = serializers.CharField()
    title = serializers.CharField()
    text = serializers.CharField()
    priority = serializers.ChoiceField(choices=Priority.choices)
    review_state = serializers.ChoiceField(choices=ReviewState.choices)
    origin = serializers.ChoiceField(choices=Origin.choices)
    page = serializers.IntegerField(allow_null=True)
    start = serializers.IntegerField(allow_null=True)
    end = serializers.IntegerField(allow_null=True)
    vague = serializers.BooleanField()
    possible_duplicate_of = serializers.CharField(allow_null=True)
    assumptions = serializers.ListField(child=serializers.CharField())


class SourceActionsSerializer(serializers.Serializer):
    review = serializers.BooleanField()


class SourceDetailSerializer(SourceRowSerializer):
    text_pages = SourcePageSerializer(many=True)
    items = SourceItemSerializer(many=True)
    gaps = serializers.ListField(child=serializers.CharField())
    left_out = serializers.IntegerField(help_text="Drafts dropped because a check failed")
    allowance_message = serializers.CharField(allow_blank=True)
    fast_accepts = serializers.IntegerField(allow_null=True)
    actions = SourceActionsSerializer()


class SourceCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    file_id = serializers.UUIDField(required=False, help_text="A file uploaded with kind prd")
    text = serializers.CharField(
        max_length=services.MAX_PASTED_CHARS, required=False, help_text="Or the PRD pasted as text"
    )


class ReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=(ReviewState.ACCEPTED, ReviewState.REJECTED))
    reason = serializers.ChoiceField(
        choices=RejectReason.choices, required=False, allow_blank=True, default=""
    )
    viewed_ms = serializers.IntegerField(
        min_value=0, required=False, help_text="How long the draft was on screen before deciding"
    )


class AcceptManySerializer(serializers.Serializer):
    numbers = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=20
    )
    viewed_ms = serializers.IntegerField(min_value=0, required=False)


# --- lookups ---------------------------------------------------------------------------------


def source_or_404(project: Project, source_id: UUID) -> SourceDocument:
    document = (
        SourceDocument.objects.filter(project=project, pk=source_id)
        .select_related("file", "created_by", "project")
        .first()
    )
    if document is None:
        raise NotFound()
    return document


def _detail(request, document: SourceDocument) -> Response:
    data = queries.detail(document, request._request.membership)
    return Response(SourceDetailSerializer(data).data)


# --- views -----------------------------------------------------------------------------------


@extend_schema(
    request=SourceCreateSerializer,
    responses={200: SourceRowSerializer(many=True), 201: SourceDetailSerializer},
)
@api_view(["GET", "POST"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "POST": Action.WRITE_TESTING}), flag_required("plan")]
)
def sources(request, key: str):
    """GET: the project's source documents. POST: add a PRD, either a file already uploaded
    with kind `prd` (`file_id`) or pasted `text` (FR-PLAN-01)."""
    project = project_or_404(request, key)
    if request.method == "GET":
        return Response(SourceRowSerializer(queries.source_list(project), many=True).data)
    body = SourceCreateSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    if bool(data.get("file_id")) == bool(data.get("text")):
        raise ValidationError({"detail": "Send an uploaded file or pasted text, one of the two."})
    if data.get("file_id"):
        made = _run(
            services.create_from_file,
            project,
            request.user,
            file_id=data["file_id"],
            title=data.get("title", ""),
        )
    else:
        made = _run(
            services.create_from_text,
            project,
            request.user,
            title=data.get("title", ""),
            text=data["text"],
        )
    response = _detail(request, source_or_404(project, made.pk))
    response.status_code = status.HTTP_201_CREATED
    return response


@extend_schema(responses=SourceDetailSerializer)
@api_view(["GET"])
@permission_classes([*requires(Action.VIEW), flag_required("plan")])
def source_detail(request, key: str, source_id: UUID):
    """One source: its text by page, the requirements drafted from it with where each is stated,
    the questions the AI could not answer, and the progress of any job still running."""
    return _detail(request, source_or_404(project_or_404(request, key), source_id))


@extend_schema(request=None, responses=SourceDetailSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("plan")])
def draft(request, key: str, source_id: UUID):
    """Draft requirements from this source again. Passages that already have a draft are
    skipped, and unchanged text costs nothing."""
    document = source_or_404(project_or_404(request, key), source_id)
    _run(services.queue_drafting, document, request.user)
    return _detail(request, document)


@extend_schema(request=AcceptManySerializer, responses=SourceDetailSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("plan")])
def accept(request, key: str, source_id: UUID):
    """Accept up to 20 of this source's drafts at once (AI §6)."""
    document = source_or_404(project_or_404(request, key), source_id)
    body = AcceptManySerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    _run(services.accept_many, document, request.user, data["numbers"], data.get("viewed_ms"))
    return _detail(request, document)


@extend_schema(request=ReviewSerializer, responses={204: None})
@api_view(["POST"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("plan")])
def review(request, key: str, requirement_id: str):
    """Accept or reject a drafted requirement (FR-PLAN-04). Only accepted requirements count
    towards coverage, readiness and reports."""
    project = project_or_404(request, key)
    requirement = requirement_or_404(project, requirement_id)
    body = ReviewSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    _run(
        services.decide,
        project,
        requirement,
        request.user,
        data["decision"],
        reason=data["reason"],
        viewed_ms=data.get("viewed_ms"),
    )
    return Response(status=status.HTTP_204_NO_CONTENT)
