"""Source documents and requirement review (M2-01, M2-03, M2-08)."""

from uuid import UUID

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core import audit
from apps.core.models import Project
from apps.core.policy import (
    Action,
    project_or_404,
    requires,
    visible_projects,
)
from apps.core.views_orgs import _run
from apps.requirements import services
from apps.requirements.models import Requirement, SourceDocument


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceDocument
        fields = ["id", "kind", "title", "content_text", "page_count", "created_at"]
        read_only_fields = ["id", "created_at"]


class SourceCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    kind = serializers.ChoiceField(choices=SourceDocument.Kind.choices, default="prd")
    content_text = serializers.CharField(max_length=1_000_000, trim_whitespace=True)

    def validate_content_text(self, value):
        if not value.strip():
            raise serializers.ValidationError("Paste the source text first.")
        if len(value.encode("utf-8")) > 1_000_000:
            raise serializers.ValidationError("Source text must be at most 1 MB.")
        return value


class RequirementSerializer(serializers.ModelSerializer):
    source_document_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Requirement
        fields = [
            "id",
            "display_no",
            "title",
            "text",
            "priority",
            "revision",
            "source_document_id",
            "source_locator",
            "review_state",
            "origin",
            "created_at",
        ]


class RequirementCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    text = serializers.CharField(trim_whitespace=True)
    priority = serializers.ChoiceField(choices=Requirement._meta.get_field("priority").choices)
    source_document_id = serializers.UUIDField(required=False, allow_null=True)
    source_locator = serializers.JSONField(required=False, default=dict)
    review_state = serializers.ChoiceField(choices=("draft", "accepted"), default="accepted")

    def validate_text(self, value):
        if not value.strip():
            raise serializers.ValidationError("Requirement text is required.")
        return value

    def validate_source_locator(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Source location must be an object.")
        return value


class RequirementUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    text = serializers.CharField(trim_whitespace=True)
    priority = serializers.ChoiceField(choices=Requirement._meta.get_field("priority").choices)

    def validate_text(self, value):
        if not value.strip():
            raise serializers.ValidationError("Requirement text is required.")
        return value


class ReviewSerializer(serializers.Serializer):
    review_state = serializers.ChoiceField(choices=("accepted", "rejected", "draft"))


def _visible_requirement(request, requirement_id: UUID) -> Requirement:
    visible = visible_projects(Project.objects.all(), request._request.membership)
    requirement = (
        Requirement.objects.filter(pk=requirement_id, project__in=visible)
        .select_related("source_document")
        .first()
    )
    if requirement is None:
        raise NotFound()
    return requirement


def _source_for_project(source_id: UUID | None, project: Project) -> SourceDocument | None:
    if source_id is None:
        return None
    source = SourceDocument.objects.filter(pk=source_id, project=project).first()
    if source is None:
        raise serializers.ValidationError(
            {"source_document_id": "Source not found in this project."}
        )
    return source


def _validate_locator(locator: dict, source: SourceDocument | None) -> dict:
    if source is None:
        if locator:
            raise serializers.ValidationError({"source_locator": "Choose a source document first."})
        return {}
    quote = locator.get("quote")
    if not isinstance(quote, str) or not quote.strip() or quote not in source.content_text:
        raise serializers.ValidationError(
            {"source_locator": {"quote": "The quoted passage must appear exactly in the source."}}
        )
    line = source.content_text.count("\n", 0, source.content_text.index(quote)) + 1
    return {"quote": quote, "start_line": line}


@extend_schema(methods=["GET"], responses=SourceSerializer(many=True))
@extend_schema(methods=["POST"], request=SourceCreateSerializer, responses={201: SourceSerializer})
@api_view(["GET", "POST"])
@permission_classes(requires({"GET": Action.VIEW, "POST": Action.WRITE_TESTING}))
def sources(request, key: str):
    project = project_or_404(request, key)
    if request.method == "GET":
        rows = SourceDocument.objects.filter(project=project).order_by("-created_at")
        return Response(SourceSerializer(rows, many=True).data)
    body = SourceCreateSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    with transaction.atomic():
        source = SourceDocument.objects.create(
            org_id=project.org_id,
            project=project,
            kind=body.validated_data["kind"],
            title=body.validated_data["title"].strip(),
            content_text=body.validated_data["content_text"],
            created_by=request.user,
        )
        audit.record(
            "source_document.created",
            "source_document",
            source.pk,
            actor=request.user,
            after={"project_id": str(project.pk), "kind": source.kind},
        )
    return Response(SourceSerializer(source).data, status=status.HTTP_201_CREATED)


@extend_schema(methods=["GET"], responses=RequirementSerializer(many=True))
@extend_schema(
    methods=["POST"], request=RequirementCreateSerializer, responses={201: RequirementSerializer}
)
@api_view(["GET", "POST"])
@permission_classes(requires({"GET": Action.VIEW, "POST": Action.WRITE_TESTING}))
def requirements(request, key: str):
    project = project_or_404(request, key)
    if request.method == "GET":
        rows = Requirement.objects.filter(project=project).select_related("source_document")
        state = request.query_params.get("state")
        query = request.query_params.get("q", "").strip()
        if state in {"draft", "accepted", "rejected"}:
            rows = rows.filter(review_state=state)
        if query:
            rows = rows.filter(title__icontains=query) | rows.filter(text__icontains=query)
        return Response(RequirementSerializer(rows.order_by("display_no"), many=True).data)

    body = RequirementCreateSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    source = _source_for_project(data.get("source_document_id"), project)
    locator = _validate_locator(data.get("source_locator", {}), source)
    requirement = _run(
        services.create_requirement,
        project,
        request.user,
        title=data["title"].strip(),
        text=data["text"],
        priority=data["priority"],
        review_state=data["review_state"],
        source_document=source,
        source_locator=locator,
    )
    return Response(RequirementSerializer(requirement).data, status=status.HTTP_201_CREATED)


@extend_schema(methods=["GET"], responses=RequirementSerializer)
@extend_schema(
    methods=["PATCH"], request=RequirementUpdateSerializer, responses=RequirementSerializer
)
@extend_schema(methods=["DELETE"], request=None, responses={204: None})
@api_view(["GET", "PATCH", "DELETE"])
@permission_classes(
    requires(
        {
            "GET": Action.VIEW,
            "PATCH": Action.WRITE_TESTING,
            "DELETE": Action.WRITE_TESTING,
        }
    )
)
def requirement_detail(request, requirement_id: UUID):
    requirement = _visible_requirement(request, requirement_id)
    if request.method == "GET":
        return Response(RequirementSerializer(requirement).data)
    if request.method == "DELETE":
        with transaction.atomic():
            requirement.delete()
            audit.record(
                "requirement.deleted",
                "requirement",
                requirement.pk,
                actor=request.user,
                after={"display_no": requirement.display_no},
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
    body = RequirementUpdateSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    return Response(
        RequirementSerializer(
            _run(services.update_requirement, requirement, request.user, **body.validated_data)
        ).data
    )


@extend_schema(request=ReviewSerializer, responses=RequirementSerializer)
@api_view(["POST"])
@permission_classes(requires(Action.WRITE_TESTING))
def review_requirement(request, requirement_id: UUID):
    requirement = _visible_requirement(request, requirement_id)
    body = ReviewSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    return Response(
        RequirementSerializer(
            services.set_review_state(
                requirement, request.user, body.validated_data["review_state"]
            )
        ).data
    )
