"""Per-module feature flags (ARCH §9: each module ships behind a flag, to staging first).

Flags are named after the PRD module codes. Organisations, projects and roles (ORG) are
foundations and are always on. A deployment turns modules on with the `FEATURE_FLAGS`
environment variable, a comma-separated list, or `all`. Production lists its flags explicitly.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission

MODULE_FLAGS: tuple[str, ...] = ("plan", "shot", "imp", "tc", "run", "def", "inb", "rpt")


def enabled_flags() -> frozenset[str]:
    configured = {str(flag).strip().lower() for flag in settings.FEATURE_FLAGS if str(flag).strip()}
    if "all" in configured:
        return frozenset(MODULE_FLAGS)
    unknown = configured - set(MODULE_FLAGS)
    if unknown:
        raise ImproperlyConfigured(f"Unknown feature flags: {', '.join(sorted(unknown))}")
    return frozenset(configured)


def is_enabled(flag: str) -> bool:
    if flag not in MODULE_FLAGS:
        raise ValueError(f"Unknown feature flag: {flag}")
    return flag in enabled_flags()


def flag_required(flag: str) -> type[BasePermission]:
    """DRF permission class. A disabled module answers "not found", as if it did not exist."""
    if flag not in MODULE_FLAGS:
        raise ValueError(f"Unknown feature flag: {flag}")

    class FlagRequired(BasePermission):
        def has_permission(self, request, view) -> bool:
            if not is_enabled(flag):
                raise NotFound()
            return True

    FlagRequired.__name__ = f"FlagRequired_{flag}"
    return FlagRequired
