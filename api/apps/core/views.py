from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from apps.core.flags import enabled_flags
from apps.core.models import Membership, Organisation
from apps.core.policy import Action, AuthenticatedOnly, Public, requires


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()


@extend_schema(responses=HealthSerializer)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([Public])
def health(request):
    """Uptime check target (ARCH §8). No data access, so it works before org scope exists."""
    return Response(HealthSerializer({"status": "ok"}).data)


class FlagsSerializer(serializers.Serializer):
    enabled = serializers.ListField(child=serializers.CharField())


@extend_schema(responses=FlagsSerializer)
@api_view(["GET"])
@permission_classes([AuthenticatedOnly])
def flags(request):
    """Which modules are on in this deployment, so the app can hide the rest."""
    return Response(FlagsSerializer({"enabled": sorted(enabled_flags())}).data)


class OrganisationSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    slug = serializers.CharField()
    name = serializers.CharField()


class MembershipSummarySerializer(serializers.Serializer):
    organisation = OrganisationSummarySerializer()
    role = serializers.CharField()
    status = serializers.CharField()


class MeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    name = serializers.CharField()
    memberships = MembershipSummarySerializer(many=True)


@extend_schema(responses=MeSerializer)
@api_view(["GET"])
@permission_classes([AuthenticatedOnly])
def me(request):
    """The signed-in user and their own memberships. Works before an organisation is chosen."""
    memberships = list(Membership.objects.filter(user_id=request.user.pk).order_by("created_at"))
    orgs = {o.pk: o for o in Organisation.objects.filter(id__in=[m.org_id for m in memberships])}
    data = {
        "id": request.user.pk,
        "email": request.user.email,
        "name": request.user.name,
        "memberships": [
            {"organisation": orgs[m.org_id], "role": m.role, "status": m.status}
            for m in memberships
            if m.org_id in orgs
        ],
    }
    return Response(MeSerializer(data).data)


class CurrentOrganisationSerializer(OrganisationSummarySerializer):
    role = serializers.CharField()


@extend_schema(responses=CurrentOrganisationSerializer)
@api_view(["GET"])
@permission_classes(requires(Action.VIEW))
def current_organisation(request):
    """The organisation named by the X-Org header, with the caller's role in it."""
    org, membership = request._request.org, request._request.membership
    return Response(
        CurrentOrganisationSerializer(
            {"id": org.pk, "slug": org.slug, "name": org.name, "role": membership.role}
        ).data
    )


class PublicSchemaView(SpectacularAPIView):
    """The API schema is public: it describes endpoints and carries no data."""

    authentication_classes: list = []
    permission_classes = [Public]
