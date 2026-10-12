"""Settings shared by every environment. Secrets come from the environment only (SEC §6)."""

from pathlib import Path

import environ
from django.utils.csp import CSP

from config.observability import init_sentry

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "rest_framework",
    "drf_spectacular",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.mfa",
    "allauth.usersessions",
    "allauth.headless",
    # One Django app per PRD module (ARCH §4).
    "apps.core",
    "apps.requirements",
    "apps.plans",
    "apps.runs",
    "apps.defects",
    "apps.inbox",
    "apps.reports",
    "apps.ai",
    "apps.files",
]

SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.SessionAbsoluteLimitMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.core.middleware.TenancyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.csp",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# The app connects as a role without BYPASSRLS; migrations use a separate role (SEC §5).
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

AUTH_USER_MODEL = "core.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Passwords: at least 12 characters, breached-list check, Argon2id (SEC §3).
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "apps.core.validators.BreachedPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Sessions: Secure, HttpOnly, SameSite; 12-hour idle, 30-day maximum (SEC §3).
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 12 * 60 * 60  # idle timeout; each request renews it
SESSION_ABSOLUTE_MAX_AGE = 30 * 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# Rate limits per IP, user and organisation on the whole API (SEC §8). Counters live in the cache
# (Redis in staging and production; decision record 011) and hold no tenant data.
# Behind a proxy, set NUM_PROXIES to the number of trusted proxies. At 0 the forwarded-for header
# is ignored, so a caller cannot reset their limit by faking it.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.core.throttles.IpThrottle",
        "apps.core.throttles.UserThrottle",
        "apps.core.throttles.OrgThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "ip": "1200/min",  # generous: an agency office shares one address
        "user": "600/min",
        "org": "3000/min",
        "upload": "120/hour",  # per user; used by the file service
        "ai_job": "60/hour",  # per organisation; used by AI drafting
    },
    "NUM_PROXIES": env.int("NUM_PROXIES", default=0),
}

# Counters for rate limits and sign-in lockouts. Never put tenant records in this cache (AI-04).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_URL", default="redis://localhost:6379/1"),
    }
}

# Content Security Policy for responses Django itself serves (JSON, admin). The single-page app's
# own policy is set by whatever hosts it; see docs/security-headers.md.
SECURE_CSP = {
    "default-src": [CSP.NONE],
    "script-src": [CSP.SELF, CSP.NONCE],
    "style-src": [CSP.SELF, CSP.NONCE],
    "img-src": [CSP.SELF, "data:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "form-action": [CSP.SELF],
    "base-uri": [CSP.NONE],
    "object-src": [CSP.NONE],
    "frame-ancestors": [CSP.NONE],
}
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# The front end is a different origin in development (Vite), so it must be trusted for CSRF.
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS", default=[env("FRONTEND_URL", default="http://localhost:5173")]
)

SPECTACULAR_SETTINGS = {
    "TITLE": "Greenlit API",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Names for choice lists that would otherwise collide in the schema (several are called
    # "outcome", "state" or "status"), so the generated TypeScript types keep stable names.
    "ENUM_NAME_OVERRIDES": {
        "ResultOutcomeEnum": "apps.runs.models.Outcome",
        "RetestOutcomeEnum": "apps.defects.models.RetestOutcome",
        "TrackerStatusEnum": "apps.defects.models.TrackerStatus",
        "QaStatusEnum": "apps.defects.models.QaStatus",
        "SeverityEnum": "apps.core.choices.Priority",
        "ReleaseStateEnum": "apps.runs.models.ReleaseState",
        "RunStateEnum": "apps.runs.models.RunState",
    },
}

# Job queue (ARCH §3). Redis is the broker only, not an application cache.
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TIMEZONE = "UTC"

# Feature flags (apps/core/flags.py). Empty by default: a module is off until a deployment lists it.
FEATURE_FLAGS = env.list("FEATURE_FLAGS", default=[])

# Error tracking, with request data, variables and breadcrumbs scrubbed (config/observability.py).
SENTRY_ENVIRONMENT = env("SENTRY_ENVIRONMENT", default="local")
SENTRY_ENABLED = init_sentry(env("SENTRY_DSN", default=""), SENTRY_ENVIRONMENT)

# Invitations (FR-ORG-01). The link in the email points at the front end.
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Greenlit <no-reply@greenlit.local>")
INVITE_TTL_DAYS = 7

# --- Sign-in (M1-07, decision 012): allauth's headless API for the single-page app ------------
ACCOUNT_ADAPTER = "apps.core.auth_adapter.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "apps.core.auth_adapter.SocialAccountAdapter"
MFA_ADAPTER = "apps.core.auth_adapter.MFAAdapter"
ACCOUNT_SIGNUP_FORM_CLASS = "apps.core.forms.SignupForm"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
# 5 failed attempts in 15 minutes slow that address and that IP (SEC §3); the warning email is
# sent by AccountAdapter.authentication_failed.
ACCOUNT_RATE_LIMITS = {"login_failed": "5/15m/ip,5/15m/key"}
# Recovery never reveals whether an email is registered; the link works for 30 minutes.
ACCOUNT_PREVENT_ENUMERATION = True
# allauth has no setting of its own for this; its reset links use Django's token generator.
PASSWORD_RESET_TIMEOUT = 30 * 60
# Changing a password makes Django reject every other session (its hash no longer matches).

HEADLESS_ONLY = True
HEADLESS_CLIENTS = ("browser",)
HEADLESS_FRONTEND_URLS = {
    "account_confirm_email": f"{FRONTEND_URL}/verify-email/{{key}}",
    "account_reset_password": f"{FRONTEND_URL}/reset-password",
    "account_reset_password_from_key": f"{FRONTEND_URL}/reset-password/{{key}}",
    "account_signup": f"{FRONTEND_URL}/sign-up",
    "socialaccount_login_error": f"{FRONTEND_URL}/sign-in?error=social",
}

# Where the client IP comes from for sign-in limits; matches NUM_PROXIES for the API throttles.
ALLAUTH_TRUSTED_PROXY_COUNT = env.int("NUM_PROXIES", default=0)

MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
MFA_TOTP_ISSUER = "Greenlit"
# Roles that must set up an authenticator app before using an organisation (SEC §3).
ENFORCE_MFA_ROLES = env.list("ENFORCE_MFA_ROLES", default=["owner", "admin"])
# Keys that encrypt TOTP secrets at rest; the first encrypts, all decrypt (so keys can rotate).
FIELD_ENCRYPTION_KEYS = env.list("FIELD_ENCRYPTION_KEYS", default=[])

# Breached-password check against Pwned Passwords (apps/core/validators.py). Fails open.
BREACHED_PASSWORD_CHECK = env.bool("BREACHED_PASSWORD_CHECK", default=True)

# Google sign-in. Create the OAuth client in Google Cloud and set these; until then the
# provider is configured but cannot complete a login.
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": env("GOOGLE_CLIENT_ID", default=""),
            "secret": env("GOOGLE_CLIENT_SECRET", default=""),
            "key": "",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "VERIFIED_EMAIL": True,
    }
}
SOCIALACCOUNT_AUTO_SIGNUP = True
# A Google account is never silently attached to an existing password account with the same
# address: that would let anyone who controls a matching Google address take the account over.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_LOGIN_ON_GET = False

# --- Files (M1-14, apps/files) ------------------------------------------------------------------
# "s3" in staging and production (a private bucket); "local" stores files in a folder for
# development. Links to send or fetch a file are valid for 15 minutes (SEC §6).
FILE_STORAGE_BACKEND = env("FILE_STORAGE_BACKEND", default="s3")
FILE_STORAGE_LOCAL_ROOT = BASE_DIR / "var" / "files"
FILE_STORAGE_BUCKET = env("FILE_STORAGE_BUCKET", default="greenlit-files")
FILE_STORAGE_ENDPOINT = env("FILE_STORAGE_ENDPOINT", default="")
FILE_STORAGE_REGION = env("FILE_STORAGE_REGION", default="")
FILE_STORAGE_ACCESS_KEY = env("FILE_STORAGE_ACCESS_KEY", default="")
FILE_STORAGE_SECRET_KEY = env("FILE_STORAGE_SECRET_KEY", default="")
FILE_LINK_TTL_SECONDS = 15 * 60
ORG_STORAGE_QUOTA_BYTES = env.int("ORG_STORAGE_QUOTA_BYTES", default=10 * 1024**3)  # starter plan

# "clamav" outside development; "stub" only flags the EICAR test file (apps/files/scanner.py).
MALWARE_SCANNER = env("MALWARE_SCANNER", default="clamav")
CLAMAV_HOST = env("CLAMAV_HOST", default="localhost")
CLAMAV_PORT = env.int("CLAMAV_PORT", default=3310)
