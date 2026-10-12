"""Organisations, invitations, members and projects (M1-08, M1-09, M1-19)."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core import services
from apps.core.models import Membership, MembershipStatus, Project, ProjectMember, Role
from apps.core.policy import Action, AuthenticatedOnly, project_or_404, requires, visible_projects
from apps.core.project_settings import project_settings


def _run(fn, *args, **kwargs):
    """Call a service function, turning a broken rule into the matching HTTP answer."""
    try:
        return fn(*args, **kwargs)
    except services.ServiceError as error:
        if error.code == "not_found":
            raise NotFound() from error
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
    invited_by = serializers.EmailField(source="invited_by.email")


@extend_schema(
    request=InviteSerializer,
    responses={200: InvitationSerializer(many=True), 201: InvitationSerializer},
)
@api_view(["GET", "POST"])
@permission_classes(requires(Action.MANAGE_MEMBERS))
def invite(request):
    """GET: pending invitations. POST: email an invitation with a chosen role."""
    if request.method == "GET":
        rows = services.pending_invitations().select_related("invited_by")
        return Response(InvitationSerializer(rows, many=True).data)
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


@extend_schema(request=None, responses={204: None})
@api_view(["DELETE"])
@permission_classes(requires(Action.MANAGE_MEMBERS))
def invite_detail(request, invite_id: UUID):
    """Revoke a pending invitation; its link stops working."""
    _run(services.revoke_invitation, request._request.membership, invite_id)
    return Response(status=status.HTTP_204_NO_CONTENT)


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


class RoleChangeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)


@extend_schema(responses=MemberSerializer(many=True))
@api_view(["GET"])
@permission_classes(requires(Action.VIEW))
def members(request):
    """People in this organisation. Removed members are not listed."""
    rows = (
        Membership.objects.filter(status__in=[MembershipStatus.ACTIVE, MembershipStatus.INVITED])
        .select_related("user")
        .order_by("created_at")
    )
    return Response(MemberSerializer(rows, many=True).data)


@extend_schema(request=RoleChangeSerializer, responses={200: MemberSerializer, 204: None})
@api_view(["PATCH", "DELETE"])
@permission_classes(requires(Action.MANAGE_MEMBERS))
def member_detail(request, user_id: UUID):
    """PATCH: change someone's role. DELETE: remove them from the organisation."""
    actor = request._request.membership
    if request.method == "DELETE":
        _run(services.remove_member, actor, user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    body = RoleChangeSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    changed = _run(services.change_role, actor, user_id, body.validated_data["role"])
    return Response(MemberSerializer(changed).data)


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


class ProjectDetailSerializer(ProjectSerializer):
    settings = serializers.SerializerMethodField()

    def get_settings(self, project) -> dict:
        return project_settings(project)


class ProjectUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    client_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    settings = serializers.DictField(required=False)


class ProjectMemberSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    email = serializers.EmailField(source="user.email")
    name = serializers.CharField(source="user.name")


class ProjectMemberAddSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()


_project = project_or_404


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


@extend_schema(request=ProjectUpdateSerializer, responses=ProjectDetailSerializer)
@api_view(["GET", "PATCH"])
@permission_classes(requires({"GET": Action.VIEW, "PATCH": Action.CREATE_PROJECT}))
def project_detail(request, key: str):
    """GET: one project with its settings. PATCH: rename it, or change client or settings."""
    project = _project(request, key)
    if request.method == "PATCH":
        body = ProjectUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        project = _run(
            services.update_project,
            request._request.membership,
            project,
            name=data.get("name"),
            client_name=data.get("client_name"),
            settings_changes=data.get("settings"),
        )
    return Response(ProjectDetailSerializer(project).data)


@extend_schema(
    request=ProjectMemberAddSerializer,
    responses={200: ProjectMemberSerializer(many=True), 204: None},
)
@api_view(["GET", "POST"])
@permission_classes(requires({"GET": Action.VIEW, "POST": Action.CREATE_PROJECT}))
def project_members(request, key: str):
    """GET: who is on the project. POST: add an organisation member to it."""
    project = _project(request, key)
    if request.method == "GET":
        rows = ProjectMember.objects.filter(project=project).select_related("user")
        return Response(ProjectMemberSerializer(rows, many=True).data)
    body = ProjectMemberAddSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    _run(
        services.add_project_member,
        request._request.membership,
        project,
        body.validated_data["user_id"],
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(request=None, responses={204: None})
@api_view(["DELETE"])
@permission_classes(requires(Action.CREATE_PROJECT))
def project_member_detail(request, key: str, user_id: UUID):
    """Take someone off the project. They stay in the organisation."""
    _run(
        services.remove_project_member, request._request.membership, _project(request, key), user_id
    )
    return Response(status=status.HTTP_204_NO_CONTENT)
