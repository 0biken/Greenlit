"""Settings for the test suite: local settings, but no counters survive between requests.

Throttle and lockout tests switch on a real cache explicitly (see tests/security/).
"""

from .local import *  # noqa: F403

CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}

# Existing suites build owners and admins without authenticator apps; the tests that cover
# enforcement switch it on themselves, and test_defaults checks the real default.
ENFORCE_MFA_ROLES = []

# Tests never call a real model, whatever api/.env says: the stub drafts by rule, and tests that
# need other replies script them with apps.ai.tests.fakes.Scripted.
AI_PROVIDER = "apps.ai.providers.StubProvider"
GEMINI_API_KEY = ""

# No waiting between tries when a test makes the AI provider fail.
AI_RETRY_WAITS = (0, 0, 0)

# Uploaded files go to a throwaway folder, never the developer's api/var/files.
import tempfile  # noqa: E402

FILE_STORAGE_LOCAL_ROOT = Path(tempfile.mkdtemp(prefix="greenlit-test-files-"))  # noqa: F405
