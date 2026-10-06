from django.contrib import admin
from django.urls import include, path

from apps.core import views_orgs
from apps.core.views import PublicSchemaView, current_organisation, flags, health, me

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("api/health/", health, name="health"),
    path("api/flags/", flags, name="flags"),
    path("api/me/", me, name="me"),
    path("api/org/", current_organisation, name="current-organisation"),
    path("api/orgs/", views_orgs.create_organisation, name="create-organisation"),
    path("api/invites/", views_orgs.invite, name="invite"),
    path("api/invites/accept/", views_orgs.accept_invite, name="accept-invite"),
    path("api/members/", views_orgs.members, name="members"),
    path("api/projects/", views_orgs.projects, name="projects"),
    path("api/projects/<str:key>/", views_orgs.project_detail, name="project-detail"),
    path("api/schema/", PublicSchemaView.as_view(), name="schema"),
]
