"""Base settings shared by all environments.

Environment-specific modules (dev, prod, test) import from here and override
as needed. Never set DEBUG, SECRET_KEY, or DB credentials with hardcoded
production values here — those come from env vars in the environment-specific
modules.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import environ

# ──────────────────────────────────────────────────────────────────────
# Paths & environment
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(
        list,
        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ],
    ),
    CSRF_TRUSTED_ORIGINS=(list, []),
)

# Load .env if present (no error if missing — env vars may be set externally)
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

# ──────────────────────────────────────────────────────────────────────
# Core security (overridden per environment)
# ──────────────────────────────────────────────────────────────────────
SECRET_KEY = env("SECRET_KEY", default="django-insecure-PLACEHOLDER-OVERRIDE-IN-ENV")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# ──────────────────────────────────────────────────────────────────────
# Applications
# ──────────────────────────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django_celery_beat",
    "django_celery_results",
    "django_prometheus",
    # Phase 6 Track 1 — OIDC client for Keycloak SSO. Apps remain loaded
    # even when SSO is disabled (IAMS_SSO_ENABLED=False); the runtime
    # check gates the endpoints.
    "mozilla_django_oidc",
]

LOCAL_APPS = [
    "iams",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ──────────────────────────────────────────────────────────────────────
# Middleware
# ──────────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "iams.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "iams.middleware.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "iams.middleware.SessionActivityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ──────────────────────────────────────────────────────────────────────
# Templates
# ──────────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

# ──────────────────────────────────────────────────────────────────────
# Database — defaults to PostgreSQL via env; dev module may swap to SQLite
# ──────────────────────────────────────────────────────────────────────
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

# ──────────────────────────────────────────────────────────────────────
# Cache (Redis)
# ──────────────────────────────────────────────────────────────────────
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,  # graceful degradation if Redis down
        },
        "KEY_PREFIX": "iams",
        "TIMEOUT": 300,
    }
}
DJANGO_REDIS_IGNORE_EXCEPTIONS = True

# ──────────────────────────────────────────────────────────────────────
# Password validation
# ──────────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    # Phase 5 — reject reuse of the last N passwords. N is tunable via
    # ``IAMS_PASSWORD_HISTORY_N``; default 5.
    {"NAME": "iams.security.PasswordHistoryValidator"},
]

# ──────────────────────────────────────────────────────────────────────
# Phase 5 Track 1 — Security tunables
# ──────────────────────────────────────────────────────────────────────
IAMS_LOGIN_FAIL_THRESHOLD = env.int("IAMS_LOGIN_FAIL_THRESHOLD", default=5)
IAMS_LOGIN_LOCKOUT_MINUTES = env.int("IAMS_LOGIN_LOCKOUT_MINUTES", default=15)
IAMS_LOGIN_FAIL_WINDOW_MIN = env.int("IAMS_LOGIN_FAIL_WINDOW_MIN", default=15)
IAMS_PASSWORD_HISTORY_N = env.int("IAMS_PASSWORD_HISTORY_N", default=5)
IAMS_MFA_GRACE_DAYS = env.int("IAMS_MFA_GRACE_DAYS", default=30)
IAMS_MFA_TOTP_ISSUER = env("IAMS_MFA_TOTP_ISSUER", default="IAMS")
# Session inactivity timeout — refresh tokens are auto-blacklisted on
# ``last_activity_at`` exceeding this many minutes (enforced by the
# token-refresh view).
IAMS_SESSION_INACTIVITY_MINUTES = env.int(
    "IAMS_SESSION_INACTIVITY_MINUTES", default=60
)

# ──────────────────────────────────────────────────────────────────────
# Phase 6 Track 1 — Keycloak / OIDC single sign-on
# ──────────────────────────────────────────────────────────────────────
# SSO is opt-in: the FE login page calls /api/auth/sso/config/ and only
# shows the "Sign in with corporate account" button when this is True
# AND a discovery endpoint + client_id are configured.
IAMS_SSO_ENABLED = env.bool("IAMS_SSO_ENABLED", default=False)
IAMS_SSO_PROVIDER_NAME = env("IAMS_SSO_PROVIDER_NAME", default="Corporate SSO")

# Keycloak realm endpoints (set when SSO is enabled).
# Typical Keycloak layout:
#   issuer              = https://keycloak.iams.internal/realms/iams
#   authorization       = ${issuer}/protocol/openid-connect/auth
#   token / userinfo    = ${issuer}/protocol/openid-connect/{token,userinfo}
#   end-session         = ${issuer}/protocol/openid-connect/logout
#   jwks                = ${issuer}/protocol/openid-connect/certs
OIDC_RP_CLIENT_ID = env("OIDC_RP_CLIENT_ID", default="")
OIDC_RP_CLIENT_SECRET = env("OIDC_RP_CLIENT_SECRET", default="")
OIDC_OP_AUTHORIZATION_ENDPOINT = env("OIDC_OP_AUTHORIZATION_ENDPOINT", default="")
OIDC_OP_TOKEN_ENDPOINT = env("OIDC_OP_TOKEN_ENDPOINT", default="")
OIDC_OP_USER_ENDPOINT = env("OIDC_OP_USER_ENDPOINT", default="")
OIDC_OP_JWKS_ENDPOINT = env("OIDC_OP_JWKS_ENDPOINT", default="")
OIDC_OP_LOGOUT_ENDPOINT = env("OIDC_OP_LOGOUT_ENDPOINT", default="")
OIDC_RP_SIGN_ALGO = env("OIDC_RP_SIGN_ALGO", default="RS256")
OIDC_RP_SCOPES = env("OIDC_RP_SCOPES", default="openid email profile groups")

# Authentication backends — keep ModelBackend for password / service
# accounts; the OIDC backend handles SSO callbacks.
AUTHENTICATION_BACKENDS = [
    "iams.sso.IAMSOIDCAuthenticationBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# JIT user provisioning: first SSO login creates a UserProfile with the
# named role unless a Keycloak-group → role mapping says otherwise.
IAMS_SSO_DEFAULT_ROLE = env("IAMS_SSO_DEFAULT_ROLE", default="Viewer")

# When True, an SSO-provisioned user inherits ``mfa_required=True``
# implicitly (Keycloak is enforcing MFA at the IdP layer so the
# in-app MFA prompt becomes redundant). Leave False to keep the
# in-app MFA gate as a defense-in-depth second factor.
IAMS_SSO_TRUSTS_IDP_MFA = env.bool("IAMS_SSO_TRUSTS_IDP_MFA", default=True)

# ──────────────────────────────────────────────────────────────────────
# Internationalization
# ──────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("en", "English"),
    ("ar", "Arabic"),
    ("fr", "French"),
]

# ──────────────────────────────────────────────────────────────────────
# Static & media files
# ──────────────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS: list[Path] = []

# WhiteNoise: compress + hash for cache-busting
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# File upload limits (100MB per the requirements doc)
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ──────────────────────────────────────────────────────────────────────
# CORS / CSRF
# ──────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# ──────────────────────────────────────────────────────────────────────
# Django REST Framework
# ──────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "300/minute",
        "auth_burst": "10/minute",
    },
    "DEFAULT_PAGINATION_CLASS": "iams.pagination.DefaultPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    # JSON contract: the existing serializers declare camelCase fields
    # explicitly via ``source="snake_case"``. We therefore use the standard
    # JSON renderer/parser (not the camel-case auto-translator) to avoid
    # double translation. New serializers must follow the same convention.
    # The OpenAPI post-processing hook still camelizes any stray snake_case
    # fields in the schema (idempotent on already-camelCase fields).
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "iams.exceptions.iams_exception_handler",
}

# ──────────────────────────────────────────────────────────────────────
# SimpleJWT
# ──────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "rest_framework_simplejwt.serializers.TokenObtainPairSerializer",
}

# ──────────────────────────────────────────────────────────────────────
# drf-spectacular (OpenAPI 3.1)
# ──────────────────────────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "IAMS API",
    "DESCRIPTION": "Internal Audit Management System — REST API.",
    "VERSION": "0.2.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/",
    "COMPONENT_SPLIT_REQUEST": True,
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "drf_spectacular.contrib.djangorestframework_camel_case.camelize_serializer_fields",
    ],
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "SERVERS": [
        {"url": "http://localhost:8001/api", "description": "Local dev"},
    ],
    "TAGS": [
        {"name": "auth", "description": "Authentication & current user"},
        {"name": "users", "description": "User management"},
        {"name": "roles", "description": "Roles & permissions (RBAC)"},
        {"name": "audits", "description": "Audit engagements"},
        {"name": "findings", "description": "Audit findings"},
        {"name": "corrective-actions", "description": "Corrective action plans (CAPs)"},
        {"name": "risk", "description": "Risk assessment & matrix"},
        {"name": "workflow", "description": "Approvals & follow-ups"},
        {"name": "resources", "description": "Auditors, assignments, time entries"},
        {"name": "reports", "description": "Reports & dashboards"},
        {"name": "documents", "description": "Working papers & managed documents"},
        {"name": "system", "description": "Health, readiness, audit log"},
    ],
}

# ──────────────────────────────────────────────────────────────────────
# Celery
# ──────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "default"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # hard kill after 30 min
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # warn at 25 min
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Static beat schedule — django_celery_beat overlays the DB rows on top of
# this, so values here are the "out of the box" defaults that the
# scheduler will install on first start.
#
# Times are in ``TIME_ZONE`` (TIME_ZONE setting). Adjust to local prod
# business hours via env if needed.
from celery.schedules import crontab  # noqa: E402 — needed by the dict below

CELERY_BEAT_SCHEDULE = {
    # Nightly at 02:00 local — find CAPs that are overdue or due in ≤3 days
    # and notify their owners (deduplicated to once-per-24h per CAP).
    "cap-overdue-scan-nightly": {
        "task": "iams.notify.cap_overdue_scan",
        "schedule": crontab(hour=2, minute=0),
    },
    # Monday 08:00 local — send each active user a weekly workload digest.
    "weekly-digest-monday-morning": {
        "task": "iams.notify.weekly_digest",
        "schedule": crontab(day_of_week="monday", hour=8, minute=0),
    },
    # Nightly at 03:00 local — escalate any pending approval steps past
    # their SLA (deduped to once per 24h via ApprovalStep.escalated_at).
    "approval-escalation-nightly": {
        "task": "iams.workflows.escalate_overdue_steps",
        "schedule": crontab(hour=3, minute=0),
    },
    # Every 5 minutes — drop dashboard cache keys so the next poll
    # repopulates with fresh aggregates. Phase 4 Track 3.
    "dashboard-cache-refresh": {
        "task": "iams.dashboards.refresh_caches",
        "schedule": crontab(minute="*/5"),
    },
}

# ──────────────────────────────────────────────────────────────────────
# Email (overridden per env)
# ──────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="iams-noreply@example.local")

# ──────────────────────────────────────────────────────────────────────
# Logging — structured JSON-friendly with request_id correlation
# ──────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        # Phase 5 Track 3 — JSON formatter for Promtail/Loki ingestion.
        # One JSON object per line; ``request_id`` correlates entries
        # to incoming requests via ``RequestIdMiddleware``.
        "json": {
            "()": "iams.logging.JsonFormatter",
        },
        # Plain-text fallback for local dev terminals where JSON is
        # noisier than helpful. ``LOG_FORMAT=text`` env switches.
        "structured": {
            "format": (
                "%(asctime)s level=%(levelname)s logger=%(name)s "
                "request_id=%(request_id)s %(message)s"
            ),
        },
    },
    "filters": {
        "request_id": {
            "()": "iams.middleware.RequestIdLoggingFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": env("LOG_FORMAT", default="json"),
            "filters": ["request_id"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("LOG_LEVEL", default="INFO"),
    },
    "loggers": {
        "django.db.backends": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
        "django.security": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "iams": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "celery": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}

# ──────────────────────────────────────────────────────────────────────
# Antivirus scanning (ClamAV daemon, see iams.tasks.scans)
# ──────────────────────────────────────────────────────────────────────
CLAMD_HOST = env("CLAMD_HOST", default="clamav")
CLAMD_PORT = env.int("CLAMD_PORT", default=3310)
CLAMD_SCAN_TIMEOUT = env.int("CLAMD_SCAN_TIMEOUT", default=60)
CLAMD_MAX_FILE_MB = env.int("CLAMD_MAX_FILE_MB", default=100)
CLAMD_SKIP = env.bool("CLAMD_SKIP", default=False)

# ──────────────────────────────────────────────────────────────────────
# Super admin seeding (used by manage.py seed_rbac)
# ──────────────────────────────────────────────────────────────────────
SUPER_ADMIN_EMAIL = env("SUPER_ADMIN_EMAIL", default="admin@iams.local")
SUPER_ADMIN_PASSWORD = env("SUPER_ADMIN_PASSWORD", default="change-me-in-production")
