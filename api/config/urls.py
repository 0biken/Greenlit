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
from apps.defects import views as defect_views
from apps.files import views as file_views
from apps.inbox import views as inbox_views
from apps.reports import views as report_views
from apps.requirements import views as requirement_views

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
    path("api/invites/<uuid:invite_id>/", views_orgs.invite_detail, name="invite-detail"),
    path("api/members/", views_orgs.members, name="members"),
    path("api/members/<uuid:user_id>/", views_orgs.member_detail, name="member-detail"),
    path("api/projects/", views_orgs.projects, name="projects"),
    path("api/projects/<str:key>/", views_orgs.project_detail, name="project-detail"),
    path("api/projects/<str:key>/members/", views_orgs.project_members, name="project-members"),
    path(
        "api/projects/<str:key>/members/<uuid:user_id>/",
        views_orgs.project_member_detail,
        name="project-member-detail",
    ),
    path("api/jobs/", views_jobs.job_list, name="jobs"),
    path("api/jobs/<uuid:job_id>/", views_jobs.job_detail, name="job-detail"),
    path("api/jobs/<uuid:job_id>/rerun/", views_jobs.job_rerun, name="job-rerun"),
    path("api/projects/<str:key>/files/", file_views.start_upload, name="file-upload"),
    path("api/projects/<str:key>/sources/", requirement_views.sources, name="sources"),
    path(
        "api/projects/<str:key>/requirements/", requirement_views.requirements, name="requirements"
    ),
    path(
        "api/requirements/<uuid:requirement_id>/review/",
        requirement_views.review_requirement,
        name="requirement-review",
    ),
    path(
        "api/requirements/<uuid:requirement_id>/",
        requirement_views.requirement_detail,
        name="requirement-detail",
    ),
    path("api/files/<uuid:file_id>/", file_views.file_detail, name="file-detail"),
    path("api/files/<uuid:file_id>/complete/", file_views.complete_upload, name="file-complete"),
    path("api/files/<uuid:file_id>/download/", file_views.download, name="file-download"),
    # Development stand-ins for the storage bucket; answer 404 unless storage is "local".
    path("files/local/upload/<str:token>/", file_views.local_upload, name="file-local-upload"),
    path(
        "files/local/download/<str:token>/", file_views.local_download, name="file-local-download"
    ),
    path("api/inbox/", inbox_views.inbox, name="inbox"),
    path("api/inbox/<str:item_id>/snooze/", inbox_views.snooze, name="inbox-snooze"),
    path("api/inbox/<str:item_id>/unsnooze/", inbox_views.unsnooze, name="inbox-unsnooze"),
    path("api/projects/<str:key>/summary/", report_views.summary, name="project-summary"),
    path(
        "api/projects/<str:key>/releases/<str:version>/",
        report_views.release_detail,
        name="release-detail",
    ),
    path(
        "api/projects/<str:key>/releases/<str:version>/sign-off/",
        report_views.sign_off,
        name="release-sign-off",
    ),
    path(
        "api/projects/<str:key>/defects/<str:defect_id>/fixed/",
        defect_views.mark_fixed,
        name="defect-fixed",
    ),
    path(
        "api/projects/<str:key>/defects/<str:defect_id>/retests/",
        defect_views.retests,
        name="defect-retests",
    ),
    path("api/schema/", PublicSchemaView.as_view(), name="schema"),
]
