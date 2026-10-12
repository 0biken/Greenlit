from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.core.choices import Priority
from apps.core.flags import flag_required
from apps.core.models import CounterKind, Project
from apps.core.numbering import format_display_id, parse_display_id
from apps.core.policy import Action, project_or_404, requires
from apps.core.views_orgs import _run
from apps.plans.models import TestPlan
from apps.runs import queries, services
from apps.runs.models import (
    CaseResult,
    EvidenceTarget,
    Outcome,
    Release,
    ReleaseState,
    RunState,
    TestRun,
)

# --- shapes ----------------------------------------------------------------------------------


class ReleaseRowSerializer(serializers.Serializer):
    version = serializers.CharField()
    due = serializers.DateField(allow_null=True)
    state = serializers.ChoiceField(choices=ReleaseState.choices)
    runs = serializers.IntegerField()


class ReleaseCreateSerializer(serializers.Serializer):
    version = serializers.CharField(max_length=60)
    due = serializers.DateField(required=False, allow_null=True)


class RunRowSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    number = serializers.IntegerField()
    plan = serializers.CharField()
    plan_version = serializers.CharField()
    release = serializers.CharField()
    build = serializers.CharField(allow_blank=True)
    environment = serializers.CharField(allow_blank=True)
    state = serializers.ChoiceField(choices=RunState.choices)
    started_by = serializers.CharField(allow_null=True)
    started_at = serializers.DateTimeField()
    total = serializers.IntegerField()
    passed = serializers.IntegerField()
    failed = serializers.IntegerField()
    blocked = serializers.IntegerField()
    not_run = serializers.IntegerField()


class RunEvidenceSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    file_id = serializers.UUIDField()
    name = serializers.CharField()
    mime = serializers.CharField()
    state = serializers.CharField()


class RunDefectSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    number = serializers.IntegerField()
    shown_as = serializers.CharField()
    chip = serializers.CharField()


class RunCaseSerializer(serializers.Serializer):
    result_id = serializers.UUIDField()
    case = serializers.CharField()
    title = serializers.CharField()
    preconditions = serializers.CharField(allow_blank=True)
    steps = serializers.ListField(child=serializers.CharField())
    expected = serializers.CharField()
    priority = serializers.ChoiceField(choices=Priority.choices)
    outcome = serializers.ChoiceField(choices=Outcome.choices)
    note = serializers.CharField(allow_blank=True)
    recorded_by = serializers.CharField(allow_null=True)
    recorded_at = serializers.DateTimeField(allow_null=True)
    evidence = RunEvidenceSerializer(many=True)
    defects = RunDefectSerializer(many=True)


class RunDetailSerializer(RunRowSerializer):
    cases = RunCaseSerializer(many=True)


class RunCreateSerializer(serializers.Serializer):
    plan = serializers.IntegerField(min_value=1, help_text="The plan's number: 3 for TP-3")
    release = serializers.CharField(max_length=60)
    build = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    environment = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )


class ResultWriteSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=Outcome.choices)
    note = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")


class ResultSavedSerializer(serializers.Serializer):
    result_id = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=Outcome.choices)
    note = serializers.CharField(allow_blank=True)
    recorded_at = serializers.DateTimeField(allow_null=True)


class AttachEvidenceSerializer(serializers.Serializer):
    file_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=20)


# --- lookups ---------------------------------------------------------------------------------


def run_or_404(project: Project, ident: str) -> TestRun:
    """The run by its number, RUN-n, or uuid (DATA §4 rule 5)."""
    rows = TestRun.objects.filter(project=project).select_related(
        "plan_version__plan", "release", "created_by"
    )
    run = None
    parsed = parse_display_id(ident)
    if parsed and parsed.kind == CounterKind.TEST_RUN:
        run = rows.filter(display_no=parsed.number).first()
    elif ident.isdigit():
        run = rows.filter(display_no=int(ident)).first()
    else:
        try:
            run = rows.filter(pk=UUID(ident)).first()
        except ValueError:
            run = None
    if run is None:
        raise NotFound()
    return run


def _result(run: TestRun, result_id: UUID) -> CaseResult:
    result = CaseResult.objects.filter(run=run, pk=result_id).select_related("run").first()
    if result is None:
        raise NotFound()
    return result


def _detail(run: TestRun) -> Response:
    return Response(RunDetailSerializer(queries.run_detail(run)).data)


# --- releases --------------------------------------------------------------------------------


@extend_schema(
    request=ReleaseCreateSerializer,
    responses={200: ReleaseRowSerializer(many=True), 201: ReleaseRowSerializer},
)
@api_view(["GET", "POST"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "POST": Action.WRITE_TESTING}), flag_required("run")]
)
def releases(request, key: str):
    """GET: the project's releases, newest first. POST: create one (M4-01)."""
    project = project_or_404(request, key)
    if request.method == "POST":
        body = ReleaseCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        release = _run(
            services.create_release,
            project,
            request.user,
            name=data["version"],
            target_date=data.get("due"),
        )
        row = {
            "version": release.name,
            "due": release.target_date,
            "state": release.state,
            "runs": 0,
        }
        return Response(ReleaseRowSerializer(row).data, status=status.HTTP_201_CREATED)
    return Response(ReleaseRowSerializer(queries.releases(project), many=True).data)


@extend_schema(request=None, responses={204: None})
@api_view(["POST"])
@permission_classes([*requires(Action.SIGN_OFF), flag_required("run")])
def cancel_release(request, key: str, version: str):
    """Cancel an open release. Owners, admins and QA leads."""
    project = project_or_404(request, key)
    release = Release.objects.filter(project=project, name=version).first()
    if release is None:
        raise NotFound()
    _run(services.cancel_release, release, request.user)
    return Response(status=status.HTTP_204_NO_CONTENT)


# --- runs ------------------------------------------------------------------------------------


@extend_schema(
    request=RunCreateSerializer,
    responses={200: RunRowSerializer(many=True), 201: RunDetailSerializer},
)
@api_view(["GET", "POST"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "POST": Action.WRITE_TESTING}), flag_required("run")]
)
def runs(request, key: str):
    """GET: the project's runs, newest first. POST: start a run from a plan's current version
    (FR-RUN-01); the run is tied to that exact version for life."""
    project = project_or_404(request, key)
    if request.method == "GET":
        return Response(RunRowSerializer(queries.run_list(project), many=True).data)
    body = RunCreateSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    plan = (
        TestPlan.objects.filter(
            project=project, display_no=data["plan"], current_version__isnull=False
        )
        .select_related("current_version__plan")
        .first()
    )
    release = Release.objects.filter(project=project, name=data["release"]).first()
    if plan is None or release is None:
        raise ValidationError(
            {"detail": "Choose a plan with a published version and a release in this project."}
        )
    run = _run(
        services.start_run,
        release,
        plan.current_version,
        request.user,
        build=data["build"],
        environment=data["environment"],
    )
    response = _detail(run_or_404(project, str(run.pk)))
    response.status_code = status.HTTP_201_CREATED
    return response


@extend_schema(responses=RunDetailSerializer)
@api_view(["GET"])
@permission_classes([*requires(Action.VIEW), flag_required("run")])
def run_detail(request, key: str, run_id: str):
    """The run with every case: steps, expected result, outcome, evidence and defects."""
    return _detail(run_or_404(project_or_404(request, key), run_id))


@extend_schema(request=ResultWriteSerializer, responses=ResultSavedSerializer)
@api_view(["PUT"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("run")])
def result(request, key: str, run_id: str, result_id: UUID):
    """Record a case as passed, failed, blocked or not run (FR-RUN-02). Saved at once; sending
    the same result again changes nothing, so a retried save is harmless."""
    run = run_or_404(project_or_404(request, key), run_id)
    body = ResultWriteSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    saved = _run(
        services.record_result, _result(run, result_id), request.user, data["outcome"], data["note"]
    )
    return Response(
        ResultSavedSerializer(
            {
                "result_id": saved.pk,
                "outcome": saved.outcome,
                "note": saved.note,
                "recorded_at": saved.recorded_at,
            }
        ).data
    )


@extend_schema(request=AttachEvidenceSerializer, responses=RunEvidenceSerializer(many=True))
@api_view(["POST"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("run")])
def result_evidence(request, key: str, run_id: str, result_id: UUID):
    """Attach uploaded files to a result as evidence (FR-RUN-03)."""
    project = project_or_404(request, key)
    run = run_or_404(project, run_id)
    target = _result(run, result_id)
    body = AttachEvidenceSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    made = _run(
        services.attach_evidence,
        project,
        request.user,
        body.validated_data["file_ids"],
        [(EvidenceTarget.CASE_RESULT, target.pk)],
        environment=run.environment,
    )
    rows = [queries.evidence_row(e) for e in made]
    return Response(RunEvidenceSerializer(rows, many=True).data, status=status.HTTP_201_CREATED)


@extend_schema(request=None, responses=RunDetailSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("run")])
def complete(request, key: str, run_id: str):
    """Mark the run complete. Refused while failed results have no evidence; the answer lists
    them (FR-RUN-05)."""
    run = run_or_404(project_or_404(request, key), run_id)
    try:
        services.complete_run(run, request.user)
    except services.RunIncomplete as error:
        return Response(
            {
                "detail": error.message,
                "code": error.code,
                "missing": [
                    {
                        "result_id": str(r.pk),
                        "case": format_display_id(
                            CounterKind.TEST_CASE, r.case_revision.test_case.display_no
                        ),
                        "title": r.case_revision.title,
                    }
                    for r in error.missing
                ],
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return _detail(run)
