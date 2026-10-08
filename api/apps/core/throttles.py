"""Rate limits per IP, user and organisation (M1-16, SEC §8).

All three apply to every API view by default (see REST_FRAMEWORK in settings). The counters sit
in the cache and are keyed by ID or address only. `upload` and `ai_job` are extra scopes for the
file service and the AI features to add on the views that need them.
"""

from rest_framework.throttling import SimpleRateThrottle


class IpThrottle(SimpleRateThrottle):
    """Every request, signed in or not, keyed by the caller's address."""

    scope = "ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class UserThrottle(SimpleRateThrottle):
    scope = "user"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class OrgThrottle(SimpleRateThrottle):
    """Shared by everyone acting in one organisation, so one tenant cannot starve the rest."""

    scope = "org"

    def get_cache_key(self, request, view):
        org = getattr(request._request, "org", None)
        if org is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": org.pk}


class UploadThrottle(UserThrottle):
    scope = "upload"


class AiJobThrottle(OrgThrottle):
    scope = "ai_job"
