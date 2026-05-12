"""Production settings.

All security headers, MinIO storage, real SMTP, Sentry, structured logging.
DEBUG must remain False. Secrets are required (no defaults) — fail-fast on
missing config rather than silently shipping insecure defaults.
"""
from __future__ import annotations

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F401, F403
from .base import REST_FRAMEWORK, env

# ──────────────────────────────────────────────────────────────────────
# Hard requirements (no defaults — fail loudly on missing config)
# ──────────────────────────────────────────────────────────────────────
SECRET_KEY = env("SECRET_KEY")  # raises if missing
DEBUG = False
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# ──────────────────────────────────────────────────────────────────────
# Strict security headers
# ──────────────────────────────────────────────────────────────────────
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31_536_000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"

# ──────────────────────────────────────────────────────────────────────
# Object storage — MinIO via django-storages (S3 protocol)
# ──────────────────────────────────────────────────────────────────────
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_BUCKET_NAME"),
            "endpoint_url": env("S3_ENDPOINT_URL"),
            "access_key": env("S3_ACCESS_KEY"),
            "secret_key": env("S3_SECRET_KEY"),
            "region_name": env("S3_REGION", default="us-east-1"),
            "use_ssl": env.bool("S3_USE_SSL", default=True),
            "addressing_style": env("S3_ADDRESSING_STYLE", default="path"),
            "file_overwrite": False,
            "default_acl": None,
            "object_parameters": {
                "ServerSideEncryption": "AES256",
            },
            "querystring_auth": True,
            "querystring_expire": env.int("S3_SIGNED_URL_EXPIRY", default=900),
        },
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Strip the browsable API in production
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
]

# ──────────────────────────────────────────────────────────────────────
# Email — SMTP relay (Postfix or corporate gateway)
# ──────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = env("EMAIL_BACKEND", default="anymail.backends.smtp.EmailBackend")

# ──────────────────────────────────────────────────────────────────────
# Sentry (self-hosted instance)
# ──────────────────────────────────────────────────────────────────────
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(transaction_style="url"),
            CeleryIntegration(),
        ],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        send_default_pii=False,
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        release=env("SENTRY_RELEASE", default=None),
    )

# ──────────────────────────────────────────────────────────────────────
# Log to stdout in JSON-friendly format for Promtail → Loki ingestion
# ──────────────────────────────────────────────────────────────────────
# (LOGGING is inherited from base; level is INFO in prod by default)
