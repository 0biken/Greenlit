from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# Plain HTTP on localhost.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# No-Docker development fallbacks. Staging and production must not set these.
# Jobs run inline, so Redis is not needed locally.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# The file service (M1-14) reads these. "local" stores files in a folder; "s3" uses object storage.
FILE_STORAGE_BACKEND = "local"
FILE_STORAGE_LOCAL_ROOT = BASE_DIR / "var" / "files"  # noqa: F405
# "stub" accepts every file; "clamav" talks to a real scanner.
MALWARE_SCANNER = "stub"

FEATURE_FLAGS = ["all"]

# No Redis needed on a developer machine: counters live in this process's memory.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# No outside calls on a developer machine.
BREACHED_PASSWORD_CHECK = False
