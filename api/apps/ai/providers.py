"""The model provider, behind one small interface (ARCH §4, decision D-008 still open).

Only `apps.ai.client` calls a provider. Until a provider is chosen the default is `StubProvider`,
which answers from the document itself without any network call, so the whole drafting flow can
be built, tested and shown. A real provider is one more class here and a setting.
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from typing import Any, Protocol

import requests
from django.conf import settings
from django.utils.module_loading import import_string


class ProviderUnavailable(Exception):
    """The provider could not be reached or refused to answer. Worth trying again."""


@dataclass(frozen=True)
class Request:
    feature: str
    instructions: str  # the ground rules and the feature's own instructions
    document: str  # untrusted text, sent inside its own delimited section
    existing: str  # this organisation's own records the model should know about
    schema: dict


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float = 0.0


class Provider(Protocol):
    def complete(self, request: Request) -> Reply: ...


def prompt(request: Request) -> str:
    """The one message a real provider is sent: rules first, then the data in its sections."""
    return (
        f"{request.instructions}\n\n<existing>\n{request.existing}\n</existing>\n\n"
        f"<document>\n{request.document}\n</document>\n\n"
        f"Schema:\n{json.dumps(request.schema, sort_keys=True)}"
    )


_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_STATES = re.compile(
    r"\b(must|shall|should|can|cannot|will|needs? to|is able to|are able to)\b", re.I
)
_VAGUE = re.compile(
    r"\b(fast|quick|quickly|easy|easily|simple|intuitive|user-friendly|seamless)\b", re.I
)


_REQUIREMENT = re.compile(r"^\[(REQ-\d+)\] ", re.MULTILINE)
UNSAID = "The requirement does not say what happens when the input is invalid"


class StubProvider:
    """Drafts by rule, from the text it is given. It stands in for a model so that nothing
    downstream has to be faked: its quotes are real, its JSON is checked like any other reply,
    and it never reads instructions out of the data."""

    model = "stub-1"

    def complete(self, request: Request) -> Reply:
        if request.feature == "draft_requirements":
            answer = self._requirements(request.document)
        elif request.feature == "draft_cases":
            answer = self._cases(request.document)
        else:
            raise ProviderUnavailable(f"The stub provider cannot do {request.feature}.")
        text = json.dumps(answer)
        return Reply(text, self.model, len(prompt(request)) // 4, len(text) // 4)

    def _requirements(self, document: str) -> dict:
        requirements, gaps = [], []
        for match in _SENTENCE.finditer(document):
            sentence = match.group().strip(" \t-*#>")
            words = sentence.split()
            if len(words) < 5 or not _STATES.search(sentence):
                continue
            vague = _VAGUE.search(sentence)
            strong = re.search(r"\b(must|shall|cannot)\b", sentence, re.I)
            requirements.append(
                {
                    "title": " ".join(words[:9]).rstrip(".,;:")[:120],
                    "text": sentence,
                    "priority": "high" if strong else "medium",
                    "quote": " ".join(words[:30]),
                    "vague": bool(vague),
                }
            )
            if vague:
                start = " ".join(words[:12])
                gaps.append(
                    f'The document says "{vague.group().lower()}" without a number to test '
                    f"against: {start}"
                )
        return {"requirements": requirements, "gaps": gaps}

    def _cases(self, document: str) -> dict:
        """A positive and a negative case for each `[REQ-n] title` block in the document."""
        cases, gaps = [], []
        parts = _REQUIREMENT.split(document)[1:]  # [id, body, id, body, ...]
        for req_id, body in zip(parts[::2], parts[1::2], strict=True):
            title, _, text = body.strip().partition("\n")
            title = title.strip()
            start = "Open [the screen where this is done]"
            cases.append(
                {
                    "title": title[:120],
                    "type": "positive",
                    "priority": "medium",
                    "requirement_ids": [req_id],
                    "preconditions": "",
                    "steps": [start, f"Do this with [valid input]: {title}"],
                    "expected": text.strip() or title,
                    "assumptions": [],
                }
            )
            cases.append(
                {
                    "title": f"Refused with invalid input: {title}"[:120],
                    "type": "negative",
                    "priority": "medium",
                    "requirement_ids": [req_id],
                    "preconditions": "",
                    "steps": [start, f"Try this with [invalid or missing input]: {title}"],
                    "expected": "It is refused with a clear message, and nothing is saved.",
                    "assumptions": [UNSAID],
                }
            )
            gaps.append(f"{req_id} does not say what happens when the input is invalid.")
        return {"cases": cases, "gaps": gaps}


class GeminiProvider:
    """Google's Gemini through its REST API. Only the prompt and the schema in the prompt are
    sent: no tools, no files. The key comes from `GEMINI_API_KEY`; errors carry the status code
    and never the reply body, which can echo document text."""

    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self) -> None:
        self.model = settings.GEMINI_MODEL
        self.key = settings.GEMINI_API_KEY

    def complete(self, request: Request) -> Reply:
        if not self.key:
            raise ProviderUnavailable("GEMINI_API_KEY is not set.")
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt(request)}]}],
            # The schema is in the prompt; Gemini's own schema subset rejects some of ours.
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        }
        try:
            response = requests.post(
                self.URL.format(model=self.model),
                headers={"x-goog-api-key": self.key},
                json=body,
                timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise ProviderUnavailable(
                f"Gemini could not be reached ({type(exc).__name__})."
            ) from exc
        if response.status_code != 200:
            raise ProviderUnavailable(f"Gemini answered {response.status_code}.")
        try:
            data = response.json()
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
            usage = data.get("usageMetadata", {})
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable("Gemini sent a reply that could not be read.") from exc
        tokens_out = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        return Reply(text, self.model, usage.get("promptTokenCount", 0), tokens_out)


@cache
def _provider(path: str) -> Provider:
    return import_string(path)()


def get_provider() -> Provider:
    return _provider(settings.AI_PROVIDER)
