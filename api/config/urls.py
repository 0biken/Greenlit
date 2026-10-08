from django.contrib import admin
from django.urls import include, path

from apps.core import views_jobs, views_orgs
from apps.core.views import (
    PublicSchemaView,
    csrf,
    current_organisation,
    end_all_sessions,
    flags,
    health,
    me,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    # Sign-in for the single-page app (decision 012). `accounts/` stays only for the
    # social provider callbacks; allauth's own pages are switched off (HEADLESS_ONLY).
    path("_allauth/", include("allauth.headless.urls")),
    path("accounts/", include("allauth.urls")),
    path("api/health/", health, name="health"),
    path("api/csrf/", csrf, name="csrf"),
    path("api/flags/", flags, name="flags"),
    path("api/me/", me, name="me"),
    path("api/sessions/end-all/", end_all_sessions, name="end-all-sessions"),
    path("api/org/", current_organisation, name="current-organisation"),
    path("api/orgs/", views_orgs.create_organisation, name="create-organisation"),
    path("api/invites/", views_orgs.invite, name="invite"),
    path("api/invites/accept/", views_orgs.accept_invite, name="accept-invite"),
    path("api/members/", views_orgs.members, name="members"),
    path("api/projects/", views_orgs.projects, name="projects"),
    path("api/projects/<str:key>/", views_orgs.project_detail, name="project-detail"),
    path("api/jobs/", views_jobs.job_list, name="jobs"),
    path("api/jobs/<uuid:job_id>/", views_jobs.job_detail, name="job-detail"),
    path("api/jobs/<uuid:job_id>/rerun/", views_jobs.job_rerun, name="job-rerun"),
    path("api/schema/", PublicSchemaView.as_view(), name="schema"),
]
