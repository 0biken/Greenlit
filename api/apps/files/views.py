"""File endpoints (M1-14). A file is reachable only through a project the caller can see."""

from uuid import UUID

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.models import Project
from apps.core.policy import Action, project_or_404, requires, visible_projects
from apps.core.throttles import IpThrottle, OrgThrottle, UploadThrottle, UserThrottle
from apps.core.views_orgs import _run
from apps.files import services
from apps.files.models import StoredFile
from apps.files.storage import LocalStorage, get_storage, link_ttl, safe_filename
from apps.files.types import KINDS


class FileSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    name = serializers.CharField(source="original_name")
    size_bytes = serializers.IntegerField()
    state = serializers.CharField()
    detected_type = serializers.CharField()
    sha256 = serializers.CharField()
    rejection_reason = serializers.CharField()
    created_at = serializers.DateTimeField()
    available_at = serializers.DateTimeField(allow_null=True)


class UploadRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=sorted(KINDS))
    name = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=0)


class UploadTargetSerializer(serializers.Serializer):
    method = serializers.CharField()
    url = serializers.CharField()
    # The S3 form fields. DRF moves declared fields off the class, so this does not replace
    # Serializer.fields at runtime; only the type checker sees a clash.
    fields = serializers.DictField(child=serializers.CharField())  # type: ignore[assignment]
    headers = serializers.DictField(child=serializers.CharField())
    expires_at = serializers.DateTimeField()


class UploadStartedSerializer(serializers.Serializer):
    file = FileSerializer()
    upload = UploadTargetSerializer()


class DownloadSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_at = serializers.DateTimeField()


_project = project_or_404


def _file(request, file_id: UUID) -> StoredFile:
    visible = visible_projects(Project.objects.all(), request._request.membership)
    stored = StoredFile.objects.filter(pk=file_id, project__in=visible).first()
    if stored is None:
        raise NotFound()
    return stored


@extend_schema(request=UploadRequestSerializer, responses={201: UploadStartedSerializer})
@api_view(["POST"])
@permission_classes(requires(Action.WRITE_TESTING))
@throttle_classes([IpThrottle, UserThrottle, OrgThrottle, UploadThrottle])
def start_upload(request, key: str):
    """Start an upload: returns a link valid for 15 minutes to send the bytes to."""
    body = UploadRequestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    stored, target = _run(
        services.request_upload,
        request._request.membership,
        _project(request, key),
        data["kind"],
        data["name"],
        data["size"],
    )
    payload = {"file": stored, "upload": target.__dict__}
    return Response(UploadStartedSerializer(payload).data, status=status.HTTP_201_CREATED)


@extend_schema(request=None, responses={202: FileSerializer})
@api_view(["POST"])
@permission_classes(requires(Action.WRITE_TESTING))
def complete_upload(request, file_id: UUID):
    """The bytes are sent: identify, hash and scan them in the background."""
    stored = _run(services.complete_upload, _file(request, file_id), request.user)
    return Response(FileSerializer(stored).data, status=status.HTTP_202_ACCEPTED)


@extend_schema(responses=FileSerializer)
@api_view(["GET"])
@permission_classes(requires(Action.VIEW))
def file_detail(request, file_id: UUID):
    return Response(FileSerializer(_file(request, file_id)).data)


@extend_schema(responses={200: DownloadSerializer, 409: None})
@api_view(["GET"])
@permission_classes(requires(Action.VIEW))
def download(request, file_id: UUID):
    """A link valid for 15 minutes. Refused until the file has been scanned."""
    stored = _file(request, file_id)
    try:
        url = services.download_url(stored)
    except services.ServiceError as error:
        return Response(
            {"detail": error.message, "code": error.code}, status=status.HTTP_409_CONFLICT
        )
    return Response(
        DownloadSerializer({"url": url, "expires_at": timezone.now() + link_ttl()}).data
    )


# --- Local development storage -----------------------------------------------------------------
# These stand in for the S3 bucket. The signed token in the URL is the permission, exactly like
# a presigned S3 link, so there is no session or CSRF check.


def _local() -> LocalStorage:
    storage = get_storage()
    if settings.FILE_STORAGE_BACKEND != "local" or not isinstance(storage, LocalStorage):
        raise Http404()
    return storage


@csrf_exempt
@require_http_methods(["PUT"])
def local_upload(request, token: str):
    storage = _local()
    grant = LocalStorage.read_token(token, "put")
    if grant is None:
        return HttpResponse(status=403)
    if request.content_type != grant["type"]:
        return HttpResponse(status=400)
    written = storage.write_stream(grant["key"], request, grant["max"])
    if written is None:
        return HttpResponse(status=413)
    return HttpResponse(status=204)


@require_http_methods(["GET"])
def local_download(request, token: str):
    storage = _local()
    grant = LocalStorage.read_token(token, "get")
    if grant is None or not storage.exists(grant["key"]):
        return HttpResponse(status=403)
    response = FileResponse(
        storage.open(grant["key"]),
        as_attachment=True,
        filename=safe_filename(grant["name"]),
        content_type=grant["type"],
    )
    # Never let a browser render an uploaded file here, whatever it contains.
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
