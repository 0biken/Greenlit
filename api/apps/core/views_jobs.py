"""Job progress for the browser, and re-running failed jobs (M1-17, ARCH §6, D-010: polling)."""

from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.core import audit, jobs
from apps.core.models import Job, JobState
from apps.core.policy import Action, requires


class JobSerializer(serializers.Serializer):
    # `args` are left out: they hold IDs that may belong to projects the viewer cannot see.
    id = serializers.UUIDField()
    kind = serializers.CharField()
    state = serializers.CharField()
    progress = serializers.JSONField()
    error = serializers.CharField()
    attempts = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)


@extend_schema(
    parameters=[OpenApiParameter("state", str, enum=JobState.values, required=False)],
    responses=JobSerializer(many=True),
)
@api_view(["GET"])
@permission_classes(requires(Action.VIEW))
def job_list(request):
    """The organisation's newest jobs; `?state=dead` lists the ones waiting for an admin."""
    rows = Job.objects.order_by("-created_at")
    state = request.query_params.get("state")
    if state:
        if state not in JobState.values:
            raise ValidationError({"state": f"Use one of: {', '.join(JobState.values)}."})
        rows = rows.filter(state=state)
    return Response(JobSerializer(rows[:100], many=True).data)


def _job(job_id: UUID) -> Job:
    job = Job.objects.filter(pk=job_id).first()
    if job is None:
        raise NotFound()
    return job


@extend_schema(responses=JobSerializer)
@api_view(["GET"])
@permission_classes(requires(Action.VIEW))
def job_detail(request, job_id: UUID):
    """One job, for polling its progress."""
    return Response(JobSerializer(_job(job_id)).data)


@extend_schema(request=None, responses={202: JobSerializer, 409: None})
@api_view(["POST"])
@permission_classes(requires(Action.MANAGE_JOBS))
def job_rerun(request, job_id: UUID):
    """Run a failed or dead job again from its first attempt."""
    job = _job(job_id)
    previous = job.state
    if not jobs.rerun(job):
        return Response(
            {"detail": "Only a failed job can be re-run.", "code": "not_rerunnable"},
            status=status.HTTP_409_CONFLICT,
        )
    if previous != JobState.QUEUED:
        audit.record(
            "job.rerun",
            "job",
            job.pk,
            actor=request.user,
            before={"state": previous},
            after={"state": JobState.QUEUED.value},
        )
    return Response(JobSerializer(_job(job_id)).data, status=status.HTTP_202_ACCEPTED)
