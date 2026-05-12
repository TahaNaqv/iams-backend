"""Local development settings.

DEBUG=True, browsable API enabled, console email backend by default
(can be flipped to mailhog via env), MinIO accessed locally if configured.
"""
from __future__ import annotations

from .base import *  # noqa: F401, F403
from .base import INSTALLED_APPS, MIDDLEWARE, REST_FRAMEWORK, env

DEBUG = True
ALLOWED_HOSTS = ["*"]  # dev only — never in prod

# Enable browsable API renderer in dev for quick exploration
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# Optional Django Debug Toolbar — enabled only if explicitly turned on
if env.bool("ENABLE_DEBUG_TOOLBAR", default=False):
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
    INTERNAL_IPS = ["127.0.0.1", "localhost"]

# Local media storage in dev (MinIO is opt-in via env)
USE_S3_STORAGE = env.bool("USE_S3_STORAGE", default=False)
if USE_S3_STORAGE:
    from .base import STORAGES  # noqa: F401

    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_BUCKET_NAME", default="iams-evidence"),
            "endpoint_url": env("S3_ENDPOINT_URL", default="http://localhost:9000"),
            "access_key": env("S3_ACCESS_KEY", default="minioadmin"),
            "secret_key": env("S3_SECRET_KEY", default="minioadmin"),
            "region_name": env("S3_REGION", default="us-east-1"),
            "use_ssl": env.bool("S3_USE_SSL", default=False),
            "addressing_style": "path",  # required for MinIO
            "file_overwrite": False,
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 900,  # 15 min signed URL
        },
    }

# Insecure cookies allowed in dev only
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
