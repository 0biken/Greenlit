"""GeminiProvider against a faked HTTP layer: no network, no real key."""

import pytest
import requests

from apps.ai.providers import GeminiProvider, ProviderUnavailable, Request


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _request():
    return Request("draft_requirements", "rules", "doc text", "", {"type": "object"})


@pytest.fixture
def provider(settings):
    settings.GEMINI_API_KEY = "test-key"
    settings.GEMINI_MODEL = "gemini-test"
    return GeminiProvider()


def test_reply_text_and_tokens(provider, monkeypatch):
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json)
        return FakeResponse(
            payload={
                "candidates": [
                    {"content": {"parts": [{"text": '{"requirements": '}, {"text": "[]}"}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "candidatesTokenCount": 10,
                    "thoughtsTokenCount": 5,
                },
            }
        )

    monkeypatch.setattr(requests, "post", post)
    reply = provider.complete(_request())
    assert reply.text == '{"requirements": []}'
    assert (reply.model, reply.tokens_in, reply.tokens_out) == ("gemini-test", 120, 15)
    assert "gemini-test:generateContent" in sent["url"]
    assert sent["headers"] == {"x-goog-api-key": "test-key"}
    assert "tools" not in sent["body"]
    assert sent["body"]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize("status", [400, 403, 429, 503])
def test_http_errors_are_unavailable_without_the_body(provider, monkeypatch, status):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: FakeResponse(status, {"error": "secret doc text"})
    )
    with pytest.raises(ProviderUnavailable) as caught:
        provider.complete(_request())
    assert str(status) in str(caught.value)
    assert "secret doc text" not in str(caught.value)


def test_network_error_is_unavailable(provider, monkeypatch):
    def post(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(ProviderUnavailable):
        provider.complete(_request())


def test_unreadable_reply_is_unavailable(provider, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(payload={"candidates": []}))
    with pytest.raises(ProviderUnavailable):
        provider.complete(_request())


def test_missing_key_is_unavailable(settings):
    settings.GEMINI_API_KEY = ""
    with pytest.raises(ProviderUnavailable):
        GeminiProvider().complete(_request())
