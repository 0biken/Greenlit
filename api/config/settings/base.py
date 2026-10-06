"""Settings shared by every environment. Secrets come from the environment only (SEC §6)."""

from pathlib import Path

import environ

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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_RATE_LIMITS = {"login_failed": "5/15m"}
# Recovery never reveals whether an email is registered (SEC §3).
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_PASSWORD_RESET_TIMEOUT = 30 * 60

# Sessions: Secure, HttpOnly, SameSite; 12-hour idle, 30-day maximum (SEC §3).
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Greenlit API",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
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
