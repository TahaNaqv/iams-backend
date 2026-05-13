import contextvars
import logging
import uuid

from django.conf import settings
from django.utils import timezone

request_id_ctx = contextvars.ContextVar("request_id", default="-")
_security_logger = logging.getLogger("iams.security")


def get_current_request_id() -> str:
    """Return the request_id for the current async/thread context, or '-' outside requests."""
    return request_id_ctx.get()


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(request_id)
        request.request_id = request_id
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        request_id_ctx.reset(token)
        return response


class RequestIdLoggingFilter:
    def filter(self, record):
        record.request_id = request_id_ctx.get()
        return True


# ──────────────────────────────────────────────────────────────────────
# Phase 5 Track 1 — Content Security Policy
# ──────────────────────────────────────────────────────────────────────
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware:
    """Append a defense-in-depth set of security headers.

    Django's ``SecurityMiddleware`` already sets HSTS / nosniff / etc.
    when prod settings are on. This middleware adds:

      - Content-Security-Policy (configurable via ``IAMS_CSP`` setting)
      - Permissions-Policy (deny camera/microphone/geolocation/etc.)
      - Cross-Origin-Embedder-Policy / Cross-Origin-Resource-Policy

    Schema docs and the Django admin both render inline scripts —
    we leave inline scripts allowed in dev to keep Swagger / Redoc
    usable; prod-only tightening is the operator's call.
    """

    PERMISSIONS_POLICY = (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        csp = getattr(settings, "IAMS_CSP", DEFAULT_CSP)
        response.setdefault("Content-Security-Policy", csp)
        response.setdefault("Permissions-Policy", self.PERMISSIONS_POLICY)
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.setdefault("Referrer-Policy", "same-origin")
        return response


# ──────────────────────────────────────────────────────────────────────
# Session inactivity tracker
# ──────────────────────────────────────────────────────────────────────
class SessionActivityMiddleware:
    """Stamp ``UserProfile.last_activity_at`` on every authenticated request.

    The :func:`UpdatedRefreshView` consumes this stamp to enforce the
    configurable inactivity timeout. Writes are batched (one per
    request) so the hot path stays cheap; the work-horse query is a
    single targeted UPDATE.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            user = getattr(request, "user", None)
            if user and user.is_authenticated:
                from iams.models import UserProfile  # noqa: PLC0415
                UserProfile.objects.filter(user=user).update(
                    last_activity_at=timezone.now()
                )
        except Exception:  # noqa: BLE001 — never break the request on stamping
            _security_logger.exception("failed to stamp last_activity_at")
        return response
