"""The model provider, behind one small interface (ARCH §4, decision D-008 still open).

Only `apps.ai.client` calls a provider. Until a provider is chosen the default is `StubProvider`,
which answers from the document itself without any network call, so the whole drafting flow can
be built, tested and shown. A real provider is one more class here and a setting.
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from typing import Protocol

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


class StubProvider:
    """Drafts requirements by rule, from the document's own sentences. It stands in for a model
    so that nothing downstream has to be faked: its quotes are real, its JSON is checked like
    any other reply, and it never reads instructions out of the document."""

    model = "stub-1"

    def complete(self, request: Request) -> Reply:
        if request.feature != "draft_requirements":
            raise ProviderUnavailable(f"The stub provider cannot do {request.feature}.")
        requirements, gaps = [], []
        for match in _SENTENCE.finditer(request.document):
            sentence = match.group().strip(" \t-*#>")
            words = sentence.split()
            if len(words) < 5 or not _STATES.search(sentence):
                continue
            vague = bool(_VAGUE.search(sentence))
            requirements.append(
                {
                    "title": " ".join(words[:9]).rstrip(".,;:")[:120],
                    "text": sentence,
                    "priority": "high"
                    if re.search(r"\b(must|shall|cannot)\b", sentence, re.I)
                    else "medium",
                    "quote": " ".join(words[:30]),
                    "vague": vague,
                }
            )
            if vague:
                word = _VAGUE.search(sentence).group().lower()  # type: ignore[union-attr]
                start = " ".join(words[:12])
                gaps.append(f'The document says "{word}" without a number to test against: {start}')
        text = json.dumps({"requirements": requirements, "gaps": gaps})
        return Reply(text, self.model, len(prompt(request)) // 4, len(text) // 4)


@cache
def _provider(path: str) -> Provider:
    return import_string(path)()


def get_provider() -> Provider:
    return _provider(settings.AI_PROVIDER)
