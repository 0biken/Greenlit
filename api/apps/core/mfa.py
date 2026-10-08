"""Two-step verification rules (SEC §3): owners and admins must enrol before using an organisation.

Enrolment itself is allauth's (`/_allauth/browser/v1/account/authenticators/totp`). This module
only decides who must have it, and refuses org-scoped requests until they do. Endpoints that
need only a signed-in user (`/api/me/`, creating or joining an organisation) stay open, so a
new owner can get to the enrolment screen.
"""

from allauth.mfa.utils import is_mfa_enabled
from django.conf import settings
from rest_framework.exceptions import APIException


class MfaRequired(APIException):
    status_code = 403
    default_code = "mfa_required"
    default_detail = {
        "detail": "Two-step verification is required for your role. Set it up to continue.",
        "code": "mfa_required",
    }


def roles_requiring_mfa() -> frozenset[str]:
    return frozenset(settings.ENFORCE_MFA_ROLES)


def user_has_mfa(user) -> bool:
    return bool(user and user.is_authenticated and is_mfa_enabled(user))


def needs_mfa_enrolment(user, role: str) -> bool:
    """True when `role` must use two-step verification and `user` has not set it up."""
    return role in roles_requiring_mfa() and not user_has_mfa(user)
