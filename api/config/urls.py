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
from apps.plans import views as plan_views
from apps.reports import views as report_views
from apps.requirements import views as requirement_views
from apps.runs import views as run_views
from apps.sources import views as source_views

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
        "api/projects/<str:key>/requirements/", requirement_views.requirements, name="requirements"
    ),
    path(
        "api/projects/<str:key>/requirements/<str:requirement_id>/",
        requirement_views.requirement_detail,
        name="requirement-detail",
    ),
    path(
        "api/projects/<str:key>/requirements/<str:requirement_id>/review/",
        source_views.review,
        name="requirement-review",
    ),
    path("api/projects/<str:key>/sources/", source_views.sources, name="sources"),
    path(
        "api/projects/<str:key>/sources/<uuid:source_id>/",
        source_views.source_detail,
        name="source-detail",
    ),
    path(
        "api/projects/<str:key>/sources/<uuid:source_id>/draft/",
        source_views.draft,
        name="source-draft",
    ),
    path(
        "api/projects/<str:key>/sources/<uuid:source_id>/accept/",
        source_views.accept,
        name="source-accept",
    ),
    path("api/projects/<str:key>/plans/", plan_views.plans, name="plans"),
    path("api/projects/<str:key>/plans/<str:plan_id>/", plan_views.plan_detail, name="plan-detail"),
    path("api/projects/<str:key>/plans/<str:plan_id>/draft/", plan_views.draft, name="plan-draft"),
    path(
        "api/projects/<str:key>/plans/<str:plan_id>/draft/cases/",
        plan_views.draft_cases,
        name="plan-draft-cases",
    ),
    path(
        "api/projects/<str:key>/plans/<str:plan_id>/draft/cases/<str:case_id>/",
        plan_views.draft_case,
        name="plan-draft-case",
    ),
    path(
        "api/projects/<str:key>/plans/<str:plan_id>/draft/submit/",
        plan_views.submit,
        name="plan-submit",
    ),
    path(
        "api/projects/<str:key>/plans/<str:plan_id>/draft/approve/",
        plan_views.approve,
        name="plan-approve",
    ),
    path("api/projects/<str:key>/plans/<str:plan_id>/diff/", plan_views.diff, name="plan-diff"),
    path(
        "api/projects/<str:key>/plans/<str:plan_id>/versions/<str:version>/",
        plan_views.version_detail,
        name="plan-version",
    ),
    path(
        "api/projects/<str:key>/plans/<str:plan_id>/versions/<str:version>/roll-back/",
        plan_views.roll_back,
        name="plan-roll-back",
    ),
    path("api/projects/<str:key>/cases/<str:case_id>/", plan_views.case_detail, name="case-detail"),
    path("api/projects/<str:key>/releases/", run_views.releases, name="releases"),
    path(
        "api/projects/<str:key>/releases/<str:version>/cancel/",
        run_views.cancel_release,
        name="release-cancel",
    ),
    path("api/projects/<str:key>/runs/", run_views.runs, name="runs"),
    path("api/projects/<str:key>/runs/<str:run_id>/", run_views.run_detail, name="run-detail"),
    path(
        "api/projects/<str:key>/runs/<str:run_id>/complete/",
        run_views.complete,
        name="run-complete",
    ),
    path(
        "api/projects/<str:key>/runs/<str:run_id>/results/<uuid:result_id>/",
        run_views.result,
        name="run-result",
    ),
    path(
        "api/projects/<str:key>/runs/<str:run_id>/results/<uuid:result_id>/evidence/",
        run_views.result_evidence,
        name="run-result-evidence",
    ),
    path(
        "api/projects/<str:key>/releases/<str:version>/",
        report_views.release_detail,
        name="release-detail",
    ),
    path(
        "api/projects/<str:key>/releases/<str:version>/report.pdf",
        report_views.report_pdf,
        name="release-report-pdf",
    ),
    path(
        "api/projects/<str:key>/releases/<str:version>/share-links/",
        report_views.share_links,
        name="release-share-links",
    ),
    path(
        "api/projects/<str:key>/releases/<str:version>/share-links/<uuid:link_id>/",
        report_views.share_link_detail,
        name="release-share-link",
    ),
    path("api/shared/<str:token>/", report_views.shared_report, name="shared-report"),
    path("api/shared/<str:token>/report.pdf", report_views.shared_report_pdf, name="shared-pdf"),
    path(
        "api/projects/<str:key>/releases/<str:version>/sign-off/",
        report_views.sign_off,
        name="release-sign-off",
    ),
    path("api/projects/<str:key>/defects/", defect_views.defects, name="defects"),
    path(
        "api/projects/<str:key>/defects/<str:defect_id>/",
        defect_views.defect_detail,
        name="defect-detail",
    ),
    path(
        "api/projects/<str:key>/defects/<str:defect_id>/status/",
        defect_views.set_status,
        name="defect-status",
    ),
    path(
        "api/projects/<str:key>/defects/<str:defect_id>/decision/",
        defect_views.decision,
        name="defect-decision",
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
