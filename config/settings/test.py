"""Test settings.

Optimized for speed: in-memory SQLite, fast password hasher, no migrations
(use --create-db once or rely on model definitions), eager Celery, console
email, no cache.
"""
from __future__ import annotations

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK

DEBUG = False
SECRET_KEY = "test-secret-key-not-for-production"  # noqa: S105 — test-only
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Fast password hashing — never use in prod
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# No real cache during tests
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Celery in eager mode → tasks run synchronously in-process
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"

# Email goes nowhere
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Disable browsable API in tests
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
]

# No throttling in tests — clear defaults AND raise scoped rates effectively to infinity
# so views with explicit ``throttle_classes = [ScopedRateThrottle]`` don't fire 429s.
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "anon": None,
    "user": None,
    "auth_burst": None,
}

# Suppress noisy logs during tests
import logging  # noqa: E402

logging.disable(logging.CRITICAL)
