"""A provider that says what a test tells it to, and remembers what it was asked."""

import json

from apps.ai.providers import ProviderUnavailable, Reply, Request, StubProvider, prompt

SCRIPTED = "apps.ai.tests.fakes.Scripted"


class Scripted:
    """`replies` are used in order: a dict or list is sent as JSON, a string as it is, and
    `ProviderUnavailable` is raised. When they run out it answers like the stub."""

    replies: list = []
    requests: list[Request] = []

    @classmethod
    def script(cls, *replies) -> None:
        cls.replies, cls.requests = list(replies), []

    @classmethod
    def sent(cls) -> str:
        """Everything a real provider would have been sent, as one text to search."""
        return "\n".join(prompt(r) for r in cls.requests)

    def complete(self, request: Request) -> Reply:
        type(self).requests.append(request)
        if not type(self).replies:
            return StubProvider().complete(request)
        reply = type(self).replies.pop(0)
        if reply is ProviderUnavailable:
            raise ProviderUnavailable
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return Reply(text, "scripted-1", 1000, 500)
