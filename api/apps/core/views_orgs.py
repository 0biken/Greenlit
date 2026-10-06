"""Organisations, invitations, members and projects (M1-08, M1-09)."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core import services
from apps.core.models import Membership, MembershipStatus, Project, Role
from apps.core.policy import Action, AuthenticatedOnly, requires, visible_projects


def _run(fn, *args, **kwargs):
    """Call a service function, turning a broken rule into a 400 with its message."""
    try:
        return fn(*args, **kwargs)
    except services.ServiceError as error:
        if error.code == "forbidden":
            raise PermissionDenied(error.message) from error
        raise ValidationError({"detail": error.message, "code": error.code}) from error


# --- Create an organisation ----------------------------------------------------------------


class OrganisationCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    slug = serializers.CharField(max_length=40, required=False, allow_blank=True)


class OrganisationCreatedSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    slug = serializers.CharField()
    name = serializers.CharField()


@extend_schema(
    request=OrganisationCreateSerializer,
    responses={201: OrganisationCreatedSerializer},
)
@api_view(["POST"])
@permission_classes([AuthenticatedOnly])
def create_organisation(request):
    """Create an organisation. The caller becomes its owner."""
    body = OrganisationCreateSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    org = _run(
        services.create_organisation,
        request.user,
        body.validated_data["name"],
        body.validated_data.get("slug") or None,
    )
    return Response(
        OrganisationCreatedSerializer({"id": org.pk, "slug": org.slug, "name": org.name}).data,
        status=status.HTTP_201_CREATED,
    )


# --- Invitations ---------------------------------------------------------------------------


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=Role.choices)


class InvitationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()
    expires_at = serializers.DateTimeField()


@extend_schema(request=InviteSerializer, responses={201: InvitationSerializer})
@api_view(["POST"])
@permission_classes(requires(Action.MANAGE_MEMBERS))
def invite(request):
    """Email an invitation to join this organisation with a chosen role."""
    body = InviteSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    invitation = _run(
        services.invite_member,
        request._request.membership,
        request._request.org,
        body.validated_data["email"],
        body.validated_data["role"],
    )
    return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)


class AcceptInviteSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)


@extend_schema(request=AcceptInviteSerializer, responses={200: OrganisationCreatedSerializer})
@api_view(["POST"])
@permission_classes([AuthenticatedOnly])
def accept_invite(request):
    """Accept an invitation from the emailed link. Needs a signed-in user with the invited email."""
    body = AcceptInviteSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    membership = _run(services.accept_invitation, request.user, body.validated_data["token"])
    from apps.core.models import Organisation
    from apps.core.tenancy import org_scope

    with org_scope(membership.org_id, request.user.pk):
        org = Organisation.objects.get(pk=membership.org_id)
    return Response(
        OrganisationCreatedSerializer({"id": org.pk, "slug": org.slug, "name": org.name}).data
    )


# --- Members -------------------------------------------------------------------------------


class MemberSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    email = serializers.EmailField(source="user.email")
    name = serializers.CharField(source="user.name")
    role = serializers.CharField()
    status = serializers.CharField()


@extend_schema(responses=MemberSerializer(many=True))
@api_view(["GET"])
@permission_classes(requires(Action.VIEW))
def members(request):
    """People in this organisation."""
    rows = (
        Membership.objects.filter(status__in=[MembershipStatus.ACTIVE, MembershipStatus.INVITED])
        .select_related("user")
        .order_by("created_at")
    )
    return Response(MemberSerializer(rows, many=True).data)


# --- Projects ------------------------------------------------------------------------------


class ProjectCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    key = serializers.CharField(max_length=6)
    client_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    member_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


class ProjectSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    key = serializers.CharField()
    name = serializers.CharField()
    client_name = serializers.CharField()


@extend_schema(
    request=ProjectCreateSerializer,
    responses={200: ProjectSerializer(many=True), 201: ProjectSerializer},
)
@api_view(["GET", "POST"])
@permission_classes(requires({"GET": Action.VIEW, "POST": Action.CREATE_PROJECT}))
def projects(request):
    """GET: projects this member can see. POST: create a project."""
    membership = request._request.membership
    if request.method == "GET":
        rows = visible_projects(Project.objects.all(), membership).order_by("key")
        return Response(ProjectSerializer(rows, many=True).data)

    body = ProjectCreateSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    project = _run(
        services.create_project,
        membership,
        data["name"],
        data["key"],
        data.get("client_name", ""),
        data.get("member_ids", []),
    )
    return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


@extend_schema(responses=ProjectSerializer)
@api_view(["GET"])
@permission_classes(requires(Action.VIEW))
def project_detail(request, key: str):
    """One project, by key. A project the member cannot see is not found."""
    project = (
        visible_projects(Project.objects.all(), request._request.membership)
        .filter(key=key.upper())
        .first()
    )
    if project is None:
        raise NotFound()
    return Response(ProjectSerializer(project).data)
