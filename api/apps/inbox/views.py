from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.flags import flag_required
from apps.core.policy import Action, requires
from apps.core.views_orgs import _run
from apps.inbox import services
from apps.inbox.services import GROUPS


class InboxItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    group = serializers.ChoiceField(choices=GROUPS)
    critical = serializers.BooleanField()
    status = serializers.CharField()
    display_id = serializers.CharField()
    title = serializers.CharField()
    project_key = serializers.CharField()
    project_name = serializers.CharField()
    age_days = serializers.IntegerField()
    since = serializers.DateTimeField()
    next_action = serializers.ChoiceField(
        choices=("retest", "run", "add_case", "open", "file_defect", "attach_evidence")
    )
    owner_name = serializers.CharField(allow_null=True)
    escalated = serializers.BooleanField(help_text="Waiting past the first escalation time")
    snoozed_until = serializers.DateTimeField(allow_null=True)
    snooze_reason = serializers.CharField(allow_null=True)


class InboxCountsSerializer(serializers.Serializer):
    closed_failed_retest = serializers.IntegerField()
    needs_retest = serializers.IntegerField()
    aging_defects = serializers.IntegerField()
    unfiled_failures = serializers.IntegerField()
    missing_evidence = serializers.IntegerField()
    stale_tests = serializers.IntegerField()
    uncovered = serializers.IntegerField()


class NextReleaseSerializer(serializers.Serializer):
    project_key = serializers.CharField()
    version = serializers.CharField()
    due = serializers.DateField()


class InboxSerializer(serializers.Serializer):
    items = InboxItemSerializer(many=True)
    counts = InboxCountsSerializer()
    snoozed = serializers.IntegerField()
    next_release = NextReleaseSerializer(allow_null=True)


class SnoozeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)
    until = serializers.DateTimeField()


@extend_schema(
    parameters=[OpenApiParameter("snoozed", bool, description="Show only snoozed items")],
    responses=InboxSerializer,
)
@api_view(["GET"])
@permission_classes([*requires(Action.VIEW), flag_required("inb")])
def inbox(request):
    """Everything that needs you across your projects, grouped by urgency (FR-INB-01)."""
    snoozed = request.query_params.get("snoozed") in ("1", "true")
    data = services.inbox(request._request.membership, snoozed=snoozed)
    return Response(InboxSerializer(data).data)


@extend_schema(request=SnoozeSerializer, responses={204: None})
@api_view(["POST"])
@permission_classes([*requires(Action.VIEW), flag_required("inb")])
def snooze(request, item_id: str):
    """Hide an item from your Inbox until a date, with a reason (FR-INB-04)."""
    body = SnoozeSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    _run(services.snooze, request._request.membership, item_id, data["until"], data["reason"])
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(request=None, responses={204: None})
@api_view(["POST"])
@permission_classes([*requires(Action.VIEW), flag_required("inb")])
def unsnooze(request, item_id: str):
    _run(services.unsnooze, request._request.membership, item_id)
    return Response(status=status.HTTP_204_NO_CONTENT)
