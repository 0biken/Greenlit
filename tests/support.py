"""Helpers shared by the permission table and the isolation suite."""

import re

from django.urls import URLPattern, URLResolver, get_resolver

from apps.core.policy import AuthenticatedOnly, Public

HANDLED = ("get", "post", "put", "patch", "delete")

# Values for URL parameters in sample calls.
PARAMS = {"key": "SAMPLE"}


def api_endpoints():
    """Yield (route, view class) for every route under api/."""

    def walk(patterns, prefix=""):
        for p in patterns:
            route = prefix + str(p.pattern)
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, route)
            elif isinstance(p, URLPattern) and route.startswith("api/"):
                cls = getattr(p.callback, "cls", None) or getattr(p.callback, "view_class", None)
                yield route, cls

    yield from walk(get_resolver().url_patterns)


def declared(view_cls):
    """'public', 'authenticated', a {METHOD: Action} dict, or None if nothing is declared."""
    perms = list(view_cls.permission_classes)
    for perm in perms:
        actions = getattr(perm, "actions", None)
        if actions is not None:
            return actions
    if any(issubclass(p, Public) for p in perms):
        return "public"
    if any(issubclass(p, AuthenticatedOnly) for p in perms):
        return "authenticated"
    return None


def methods_of(view_cls):
    return [m for m in HANDLED if hasattr(view_cls, m)]


def url_for(route: str, params: dict[str, str] | None = None) -> str:
    values = {**PARAMS, **(params or {})}
    return "/" + re.sub(r"<(?:\w+:)?(\w+)>", lambda m: values[m.group(1)], route)
