"""Settings for the test suite: local settings, but no counters survive between requests.

Throttle and lockout tests switch on a real cache explicitly (see tests/security/).
"""

from .local import *  # noqa: F403

CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}

# Existing suites build owners and admins without authenticator apps; the tests that cover
# enforcement switch it on themselves, and test_defaults checks the real default.
ENFORCE_MFA_ROLES = []
