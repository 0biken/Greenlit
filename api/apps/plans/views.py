from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.ai.serializers import AcceptManySerializer, ReviewSerializer
from apps.core.choices import Priority, ReviewState
from apps.core.flags import flag_required
from apps.core.models import CounterKind, Project
from apps.core.numbering import parse_display_id
from apps.core.policy import Action, project_or_404, requires
from apps.core.services import ServiceError
from apps.core.views_jobs import JobProgressSerializer
from apps.core.views_orgs import _run
from apps.plans import drafting, queries, services
from apps.plans.diff import diff_versions
from apps.plans.models import (
    CaseRevision,
    CaseType,
    PlanVersion,
    PlanVersionCase,
    TestCase,
    TestPlan,
    VersionState,
)
from apps.requirements.models import Requirement

# --- shapes ----------------------------------------------------------------------------------


class PlanRowSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    version = serializers.CharField(
        allow_null=True, help_text="The current published version; none until first approved"
    )
    cases = serializers.IntegerField()
    has_draft = serializers.BooleanField()
    draft_submitted = serializers.BooleanField()
    case_drafts = serializers.IntegerField(help_text="AI-drafted cases waiting for review")


class PlanVersionRowSerializer(serializers.Serializer):
    number = serializers.CharField()
    state = serializers.ChoiceField(choices=VersionState.choices)
    cases = serializers.IntegerField()
    approved_by = serializers.CharField(allow_null=True)
    approved_at = serializers.DateTimeField(allow_null=True)


class PlanDraftSerializer(serializers.Serializer):
    cases = serializers.IntegerField()
    submitted_by = serializers.CharField(allow_null=True)
    submitted_at = serializers.DateTimeField(allow_null=True)


class UncoveredSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    title = serializers.CharField()
    priority = serializers.ChoiceField(choices=Priority.choices)


class PlanActionsSerializer(serializers.Serializer):
    edit = serializers.BooleanField()
    approve = serializers.BooleanField()


class PlanDetailSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    scope = serializers.CharField(allow_blank=True)
    case_drafts = serializers.IntegerField()
    version = serializers.CharField(allow_null=True)
    versions = PlanVersionRowSerializer(many=True)
    draft = PlanDraftSerializer(allow_null=True)
    uncovered = UncoveredSerializer(many=True)
    actions = PlanActionsSerializer()


class CaseRequirementSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    stale = serializers.BooleanField(help_text="The requirement's text changed after this case")


class PlanCaseSerializer(serializers.Serializer):
    case = serializers.CharField()
    number = serializers.IntegerField()
    revision = serializers.IntegerField()
    title = serializers.CharField()
    preconditions = serializers.CharField(allow_blank=True)
    steps = serializers.ListField(child=serializers.CharField())
    expected = serializers.CharField()
    priority = serializers.ChoiceField(choices=Priority.choices)
    requirements = CaseRequirementSerializer(many=True)
    stale = serializers.BooleanField(
        help_text="No passed or failed result within the project's stale window, or a linked "
        "requirement changed since the case was written"
    )


class PlanVersionDetailSerializer(serializers.Serializer):
    number = serializers.CharField(allow_blank=True)
    state = serializers.ChoiceField(choices=VersionState.choices)
    cases = PlanCaseSerializer(many=True)


class PlanCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    scope = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")


class CaseEditSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    preconditions = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    steps = serializers.ListField(
        child=serializers.CharField(max_length=2000, allow_blank=True),
        max_length=services.MAX_STEPS,
        required=False,
    )
    expected = serializers.CharField(max_length=5000, required=False)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    requirements = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        help_text="Requirement numbers: 12 for REQ-12",
    )
    position = serializers.IntegerField(min_value=1, required=False, help_text="1 is first")


class CaseWriteSerializer(CaseEditSerializer):
    title = serializers.CharField(max_length=200)
    steps = serializers.ListField(
        child=serializers.CharField(max_length=2000, allow_blank=True),
        max_length=services.MAX_STEPS,
    )
    expected = serializers.CharField(max_length=5000)


class ApproveSerializer(serializers.Serializer):
    major = serializers.BooleanField(required=False, default=False)


class DiffCaseSerializer(serializers.Serializer):
    case = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()


class DiffFieldSerializer(serializers.Serializer):
    field = serializers.ChoiceField(choices=("title", "preconditions", "expected", "priority"))
    before = serializers.CharField(allow_blank=True)
    after = serializers.CharField(allow_blank=True)


class DiffStepSerializer(serializers.Serializer):
    op = serializers.ChoiceField(choices=("same", "added", "removed", "moved"))
    text = serializers.CharField()
    before = serializers.IntegerField(allow_null=True)
    after = serializers.IntegerField(allow_null=True)


class DiffChangedSerializer(DiffCaseSerializer):
    changes = DiffFieldSerializer(many=True)
    steps = DiffStepSerializer(many=True)


class PlanDiffSerializer(serializers.Serializer):
    added = DiffCaseSerializer(many=True)
    removed = DiffCaseSerializer(many=True)
    changed = DiffChangedSerializer(many=True)
    unchanged_count = serializers.IntegerField()
    unchanged = DiffCaseSerializer(many=True)


class CasePlanSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    version = serializers.CharField(allow_null=True, help_text="None while it is in a draft")
    revision = serializers.IntegerField()


class CaseRevisionRowSerializer(serializers.Serializer):
    revision = serializers.IntegerField()
    title = serializers.CharField()
    at = serializers.DateTimeField()
    by = serializers.CharField(allow_null=True)


class CaseResultRowSerializer(serializers.Serializer):
    run = serializers.CharField()
    run_no = serializers.IntegerField()
    outcome = serializers.CharField()
    at = serializers.DateTimeField()
    revision = serializers.IntegerField()


class CaseDetailSerializer(PlanCaseSerializer):
    retired = serializers.BooleanField()
    plans = CasePlanSerializer(many=True)
    revisions = CaseRevisionRowSerializer(many=True)
    results = CaseResultRowSerializer(many=True)


# --- lookups ---------------------------------------------------------------------------------


def _by_number(rows, ident: str, kind: CounterKind):
    try:
        return rows.filter(pk=UUID(ident)).first()
    except ValueError:
        pass
    parsed = parse_display_id(ident)
    number = parsed.number if parsed and parsed.kind == kind else None
    if number is None and ident.isdigit():
        number = int(ident)
    return rows.filter(display_no=number).first() if number else None


def plan_or_404(project: Project, ident: str) -> TestPlan:
    """The plan by its uuid, number or TP-n (DATA §4 rule 5)."""
    rows = TestPlan.objects.filter(project=project).select_related("current_version")
    plan = _by_number(rows, ident, CounterKind.TEST_PLAN)
    if plan is None:
        raise NotFound()
    return plan


def case_or_404(project: Project, ident: str) -> TestCase:
    case = _by_number(TestCase.objects.filter(project=project), ident, CounterKind.TEST_CASE)
    if case is None:
        raise NotFound()
    return case


def version_or_404(plan: TestPlan, ident: str) -> PlanVersion:
    """A version by its number ("1.2"), or the word "draft"."""
    rows = PlanVersion.objects.filter(plan=plan)
    version = (
        rows.filter(state=VersionState.DRAFT).first()
        if ident == "draft"
        else rows.exclude(number="").filter(number=ident).first()
    )
    if version is None:
        raise NotFound()
    return version


def _draft(plan: TestPlan) -> PlanVersion:
    draft = PlanVersion.objects.filter(plan=plan, state=VersionState.DRAFT).first()
    if draft is None:
        raise NotFound()
    draft.plan = plan
    return draft


def _linked(project: Project, numbers: list[int]) -> list[Requirement]:
    """The requirements with these numbers. A number that is not in the project names nothing."""
    found = list(Requirement.objects.filter(project=project, display_no__in=set(numbers)))
    if len(found) != len(set(numbers)):
        raise ServiceError("One of the linked requirements is not in this project.")
    return found


def _plan(request, plan: TestPlan) -> Response:
    plan = TestPlan.objects.select_related("current_version").get(pk=plan.pk)
    data = queries.plan_detail(plan, request._request.membership)
    return Response(PlanDetailSerializer(data).data)


def _version(version: PlanVersion) -> Response:
    return Response(PlanVersionDetailSerializer(queries.version_detail(version)).data)


# --- plans -----------------------------------------------------------------------------------


@extend_schema(
    request=PlanCreateSerializer,
    responses={200: PlanRowSerializer(many=True), 201: PlanDetailSerializer},
)
@api_view(["GET", "POST"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "POST": Action.WRITE_TESTING}), flag_required("plan")]
)
def plans(request, key: str):
    """GET: the project's plans. POST: a new plan, which starts as an empty draft."""
    project = project_or_404(request, key)
    if request.method == "GET":
        return Response(PlanRowSerializer(queries.plan_list(project), many=True).data)
    body = PlanCreateSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    plan = _run(services.create_plan, project, request.user, **body.validated_data)
    response = _plan(request, plan)
    response.status_code = status.HTTP_201_CREATED
    return response


@extend_schema(responses=PlanDetailSerializer)
@api_view(["GET"])
@permission_classes([*requires(Action.VIEW), flag_required("plan")])
def plan_detail(request, key: str, plan_id: str):
    """The plan: its versions, its draft if it has one, and the requirements nothing covers."""
    return _plan(request, plan_or_404(project_or_404(request, key), plan_id))


@extend_schema(responses=PlanVersionDetailSerializer)
@api_view(["GET"])
@permission_classes([*requires(Action.VIEW), flag_required("plan")])
def version_detail(request, key: str, plan_id: str, version: str):
    """The cases of one version, in order. `version` is a number such as 1.2, or `draft`."""
    plan = plan_or_404(project_or_404(request, key), plan_id)
    return _version(version_or_404(plan, version))


# --- the draft -------------------------------------------------------------------------------


@extend_schema(request=None, responses={201: PlanDetailSerializer, 200: PlanDetailSerializer})
@api_view(["POST", "DELETE"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("tc")])
def draft(request, key: str, plan_id: str):
    """POST: open a draft of a published plan to edit it (FR-TC-02); if someone already
    opened one, that draft is the answer. DELETE: discard the draft; the published version is
    untouched."""
    plan = plan_or_404(project_or_404(request, key), plan_id)
    if request.method == "POST":
        if PlanVersion.objects.filter(plan=plan, state=VersionState.DRAFT).exists():
            return _plan(request, plan)
        _run(services.open_draft, plan, request.user)
        response = _plan(request, plan)
        response.status_code = status.HTTP_201_CREATED
        return response
    _run(services.discard_draft, _draft(plan), request.user)
    return _plan(request, plan)


@extend_schema(request=CaseWriteSerializer, responses={201: PlanVersionDetailSerializer})
@api_view(["POST"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("tc")])
def draft_cases(request, key: str, plan_id: str):
    """Add a case to the draft (FR-TC-01). The answer is the whole draft, in order."""
    project = project_or_404(request, key)
    version = _draft(plan_or_404(project, plan_id))
    body = CaseWriteSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data

    def add() -> None:
        services.add_case(
            version,
            request.user,
            title=data["title"],
            steps=data["steps"],
            expected=data["expected"],
            preconditions=data.get("preconditions", ""),
            priority=data.get("priority", Priority.MEDIUM),
            requirements=_linked(project, data.get("requirements", [])),
        )

    _run(add)
    response = _version(version)
    response.status_code = status.HTTP_201_CREATED
    return response


@extend_schema(request=CaseEditSerializer, responses=PlanVersionDetailSerializer)
@api_view(["PATCH", "DELETE"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("tc")])
def draft_case(request, key: str, plan_id: str, case_id: str):
    """PATCH: edit the case in the draft, or move it with `position`. DELETE: take it out of
    the draft (the case and its history remain). The answer is the whole draft, in order."""
    project = project_or_404(request, key)
    version = _draft(plan_or_404(project, plan_id))
    case = case_or_404(project, case_id)
    if not PlanVersionCase.objects.filter(
        plan_version=version, case_revision__test_case=case
    ).exists():
        raise NotFound()
    if request.method == "DELETE":
        _run(services.remove_case, version, case, request.user)
        return _version(version)
    body = CaseEditSerializer(data=request.data, partial=True)
    body.is_valid(raise_exception=True)
    data = dict(body.validated_data)

    def edit() -> None:
        position = data.pop("position", None)
        numbers = data.pop("requirements", None)
        if data or numbers is not None:
            linked = None if numbers is None else _linked(project, numbers)
            services.edit_case(version, case, request.user, requirements=linked, **data)
        if position is not None:
            services.move_case(version, case, position)

    _run(edit)
    return _version(version)


@extend_schema(request=None, responses=PlanDetailSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("tc")])
def submit(request, key: str, plan_id: str):
    """Submit the draft for a lead's approval."""
    plan = plan_or_404(project_or_404(request, key), plan_id)
    _run(services.submit, _draft(plan), request.user)
    return _plan(request, plan)


@extend_schema(request=ApproveSerializer, responses=PlanDetailSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.APPROVE_PLAN), flag_required("tc")])
def approve(request, key: str, plan_id: str):
    """Approve the draft, which publishes it as the next version (FR-PLAN-05). Owners, admins
    and QA leads."""
    plan = plan_or_404(project_or_404(request, key), plan_id)
    version = _draft(plan)
    body = ApproveSerializer(data=request.data)
    body.is_valid(raise_exception=True)

    def publish() -> None:
        if not PlanVersionCase.objects.filter(plan_version=version).exists():
            raise ServiceError("Add at least one case before approving the plan.")
        services.approve(version, request.user, major=body.validated_data["major"])

    _run(publish)
    return _plan(request, plan)


# --- diff and roll back ----------------------------------------------------------------------


@extend_schema(
    parameters=[
        OpenApiParameter("from", str, description="A version number. Default: see below"),
        OpenApiParameter("to", str, description="A version number, or draft. Default: see below"),
        OpenApiParameter("unchanged", bool, description="Also list the cases that did not change"),
    ],
    responses=PlanDiffSerializer,
)
@api_view(["GET"])
@permission_classes([*requires(Action.VIEW), flag_required("tc")])
def diff(request, key: str, plan_id: str):
    """What changed between two versions of the plan: cases added, removed and changed, down
    to the step (FR-TC-03). Without `from` and `to` it compares the draft with the current
    version or, when there is no draft, the current version with the one before it."""
    plan = plan_or_404(project_or_404(request, key), plan_id)
    params = request.query_params
    if "from" in params or "to" in params:
        old = version_or_404(plan, params.get("from", ""))
        new = version_or_404(plan, params.get("to", ""))
    else:
        newest = list(PlanVersion.objects.filter(plan=plan).order_by("-created_at")[:2])
        if len(newest) < 2:
            raise NotFound()
        new, old = newest
    unchanged = params.get("unchanged", "") in ("1", "true")
    return Response(PlanDiffSerializer(diff_versions(old, new, unchanged)).data)


@extend_schema(request=None, responses=PlanDetailSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.APPROVE_PLAN), flag_required("tc")])
def roll_back(request, key: str, plan_id: str, version: str):
    """Roll back to an earlier version: publishes a new version with that version's cases
    (FR-TC-04). Owners, admins and QA leads."""
    plan = plan_or_404(project_or_404(request, key), plan_id)
    target = version_or_404(plan, version)
    _run(services.roll_back, plan, target, request.user)
    return _plan(request, plan)


# --- one case --------------------------------------------------------------------------------


@extend_schema(responses=CaseDetailSerializer)
@api_view(["GET"])
@permission_classes([*requires(Action.VIEW), flag_required("tc")])
def case_detail(request, key: str, case_id: str):
    """A test case: what it says now, the plans it is in, its revisions and recent results."""
    case = case_or_404(project_or_404(request, key), case_id)
    # A drafted case nobody accepted (or one that was rejected) is not a test case yet.
    if not CaseRevision.objects.filter(test_case=case, review_state=ReviewState.ACCEPTED).exists():
        raise NotFound()
    return Response(CaseDetailSerializer(queries.case_detail(case)).data)


# --- cases drafted by AI (M3-08) -------------------------------------------------------------


class DraftRequirementSerializer(serializers.Serializer):
    display_id = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    text = serializers.CharField()


class CaseDraftSerializer(serializers.Serializer):
    case = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    case_type = serializers.ChoiceField(choices=CaseType.choices, allow_blank=True)
    priority = serializers.ChoiceField(choices=Priority.choices)
    preconditions = serializers.CharField(allow_blank=True)
    steps = serializers.ListField(child=serializers.CharField())
    expected = serializers.CharField()
    review_state = serializers.ChoiceField(choices=ReviewState.choices)
    requirements = DraftRequirementSerializer(many=True)
    assumptions = serializers.ListField(child=serializers.CharField())
    possible_duplicate_of = serializers.CharField(allow_null=True)


class CaseDraftActionsSerializer(serializers.Serializer):
    review = serializers.BooleanField()


class CaseDraftsSerializer(serializers.Serializer):
    plan = serializers.CharField()
    plan_no = serializers.IntegerField()
    title = serializers.CharField()
    drafts = serializers.IntegerField()
    accepted = serializers.IntegerField()
    rejected = serializers.IntegerField()
    items = CaseDraftSerializer(many=True)
    gaps = serializers.ListField(child=serializers.CharField())
    left_out = serializers.IntegerField(help_text="Drafts dropped because a check failed")
    job = JobProgressSerializer(allow_null=True)
    allowance_message = serializers.CharField(allow_blank=True)
    fast_accepts = serializers.IntegerField(allow_null=True)
    actions = CaseDraftActionsSerializer()


class DraftCasesRequestSerializer(serializers.Serializer):
    requirements = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        max_length=drafting.MAX_REQUIREMENTS,
        help_text="Requirement numbers. Default: accepted requirements no accepted case covers",
    )


def _case_drafts(request, plan: TestPlan) -> Response:
    plan = TestPlan.objects.get(pk=plan.pk)
    data = queries.case_drafts(plan, request._request.membership)
    return Response(CaseDraftsSerializer(data).data)


@extend_schema(request=DraftCasesRequestSerializer, responses=CaseDraftsSerializer)
@api_view(["GET", "POST"])
@permission_classes(
    [*requires({"GET": Action.VIEW, "POST": Action.WRITE_TESTING}), flag_required("tc")]
)
def case_drafts(request, key: str, plan_id: str):
    """GET: the cases AI drafted for this plan, with the requirements each covers. POST: draft
    cases for the given requirements, or for every accepted requirement nothing covers yet
    (FR-PLAN-03). Drafts count nowhere until a person accepts them."""
    project = project_or_404(request, key)
    plan = plan_or_404(project, plan_id)
    if request.method == "POST":
        body = DraftCasesRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        numbers = body.validated_data.get("requirements")

        def queue() -> None:
            chosen = (
                drafting.uncovered_requirements(project)[: drafting.MAX_REQUIREMENTS]
                if numbers is None
                else _linked(project, numbers)
            )
            drafting.queue_case_drafting(plan, request.user, chosen)

        _run(queue)
    return _case_drafts(request, plan)


def _draft_revision(project: Project, plan: TestPlan, case_id: str) -> CaseRevision:
    return _run(drafting.draft_revision, plan, case_or_404(project, case_id))


@extend_schema(request=CaseEditSerializer, responses=CaseDraftsSerializer)
@api_view(["PATCH"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("tc")])
def case_draft(request, key: str, plan_id: str, case_id: str):
    """Edit a drafted case before deciding on it. It stays a draft."""
    project = project_or_404(request, key)
    plan = plan_or_404(project, plan_id)
    revision = _draft_revision(project, plan, case_id)
    body = CaseEditSerializer(data=request.data, partial=True)
    body.is_valid(raise_exception=True)
    data = dict(body.validated_data)
    data.pop("position", None)

    def edit() -> None:
        numbers = data.pop("requirements", None)
        linked = None if numbers is None else _linked(project, numbers)
        drafting.edit_case_draft(plan, revision, request.user, requirements=linked, **data)

    _run(edit)
    return _case_drafts(request, plan)


@extend_schema(request=ReviewSerializer, responses={204: None})
@api_view(["POST"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("tc")])
def case_draft_review(request, key: str, plan_id: str, case_id: str):
    """Accept or reject a drafted case (FR-PLAN-04). An accepted case joins the plan's draft
    version, which is opened if the plan has none."""
    project = project_or_404(request, key)
    plan = plan_or_404(project, plan_id)
    revision = _draft_revision(project, plan, case_id)
    body = ReviewSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    _run(
        drafting.decide_case,
        plan,
        revision,
        request.user,
        data["decision"],
        reason=data["reason"],
        viewed_ms=data.get("viewed_ms"),
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(request=AcceptManySerializer, responses=CaseDraftsSerializer)
@api_view(["POST"])
@permission_classes([*requires(Action.WRITE_TESTING), flag_required("tc")])
def case_drafts_accept(request, key: str, plan_id: str):
    """Accept up to 20 drafted cases at once (AI §6)."""
    plan = plan_or_404(project_or_404(request, key), plan_id)
    body = AcceptManySerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    _run(drafting.accept_cases, plan, request.user, data["numbers"], data.get("viewed_ms"))
    return _case_drafts(request, plan)
