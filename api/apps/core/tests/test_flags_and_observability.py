import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView

from apps.core.flags import MODULE_FLAGS, enabled_flags, flag_required, is_enabled
from apps.core.models import User
from config.observability import init_sentry, scrub_event


def test_flags_default_to_off(settings):
    settings.FEATURE_FLAGS = []
    assert enabled_flags() == frozenset()
    assert not is_enabled("plan")


def test_all_turns_every_module_on(settings):
    settings.FEATURE_FLAGS = ["all"]
    assert enabled_flags() == frozenset(MODULE_FLAGS)


def test_listed_flags_are_the_only_ones_on(settings):
    settings.FEATURE_FLAGS = ["plan", " RUN "]
    assert enabled_flags() == {"plan", "run"}
    assert is_enabled("run") and not is_enabled("rpt")


def test_a_misspelt_flag_in_configuration_fails_loudly(settings):
    settings.FEATURE_FLAGS = ["plans"]
    with pytest.raises(ImproperlyConfigured, match="plans"):
        enabled_flags()


def test_asking_for_an_unknown_flag_fails():
    with pytest.raises(ValueError):
        is_enabled("nope")
    with pytest.raises(ValueError):
        flag_required("nope")


def test_disabled_module_answers_not_found(settings):
    class PlanView(APIView):
        permission_classes = [flag_required("plan")]

        def get(self, request):
            from rest_framework.response import Response

            return Response({"ok": True})

    view = PlanView.as_view()
    request = APIRequestFactory().get("/x")
    settings.FEATURE_FLAGS = []
    assert view(request).status_code == 404
    settings.FEATURE_FLAGS = ["plan"]
    assert view(request).status_code == 200


@pytest.mark.django_db
def test_flags_endpoint_lists_enabled_modules(settings):
    settings.FEATURE_FLAGS = ["tc", "plan"]
    assert APIClient().get("/api/flags/").status_code in (401, 403)

    client = APIClient()
    client.force_authenticate(User.objects.create_user("flags@example.com", "x" * 14))
    response = client.get("/api/flags/")
    assert response.status_code == 200
    assert response.json() == {"enabled": ["plan", "tc"]}


def test_sentry_does_nothing_without_a_dsn():
    assert init_sentry("", "test") is False


def test_scrubbing_removes_everything_that_can_hold_document_text():
    event = {
        "request": {
            "url": "https://app/api/x/",
            "method": "POST",
            "data": {"text": "unreleased feature: the PRD says..."},
            "cookies": {"sessionid": "secret"},
            "query_string": "q=confidential",
            "headers": {"Authorization": "x"},
        },
        "user": {"id": "u-1", "email": "person@example.com", "ip_address": "1.2.3.4"},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "bad quote: 'the new pricing is...'",
                    "stacktrace": {
                        "frames": [{"function": "parse", "vars": {"doc_text": "secret"}}]
                    },
                }
            ]
        },
        "breadcrumbs": {"values": [{"category": "query", "message": "SELECT ... 'secret'"}]},
        "extra": {"doc": "secret"},
        "logentry": {"message": "failed on 'secret'"},
    }
    scrubbed = scrub_event(event, {})
    assert scrubbed["request"] == {"url": "https://app/api/x/", "method": "POST"}
    assert scrubbed["user"] == {"id": "u-1"}
    frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame and frame["function"] == "parse"
    assert scrubbed["exception"]["values"][0]["value"] == ""
    assert scrubbed["exception"]["values"][0]["type"] == "ValueError"
    for key in ("breadcrumbs", "extra", "logentry"):
        assert key not in scrubbed
    assert "secret" not in repr(scrubbed) and "confidential" not in repr(scrubbed)
