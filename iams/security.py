"""Security services (Phase 5 Track 1).

Three concerns, one module:

  1. **Login attempt recording** — every auth attempt → ``LoginAttempt``
     row + lockout-window check.
  2. **Lockout management** — ``register_failure(...)`` increments the
     attempt counter and opens an ``AccountLockout`` row when the
     threshold is crossed; ``clear_lockout(...)`` is the admin unlock.
  3. **Password reuse prevention** — ``PasswordHistoryValidator`` plugs
     into ``AUTH_PASSWORD_VALIDATORS`` and rejects reuse of the last N
     passwords for the given user.

Tunables (all via Django settings, with sane defaults):

  - ``IAMS_LOGIN_FAIL_THRESHOLD``  (default 5)
  - ``IAMS_LOGIN_LOCKOUT_MINUTES`` (default 15)
  - ``IAMS_LOGIN_FAIL_WINDOW_MIN`` (default 15) — window over which
    failures accumulate toward the threshold.
  - ``IAMS_PASSWORD_HISTORY_N``    (default 5)
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.utils import timezone

logger = logging.getLogger(__name__)

User = get_user_model()


# ──────────────────────────────────────────────────────────────────────
# Tunables
# ──────────────────────────────────────────────────────────────────────
def _fail_threshold() -> int:
    return int(getattr(settings, "IAMS_LOGIN_FAIL_THRESHOLD", 5))


def _lockout_minutes() -> int:
    return int(getattr(settings, "IAMS_LOGIN_LOCKOUT_MINUTES", 15))


def _fail_window_min() -> int:
    return int(getattr(settings, "IAMS_LOGIN_FAIL_WINDOW_MIN", 15))


def _password_history_n() -> int:
    return int(getattr(settings, "IAMS_PASSWORD_HISTORY_N", 5))


# ──────────────────────────────────────────────────────────────────────
# Request introspection helpers
# ──────────────────────────────────────────────────────────────────────
def request_metadata(request) -> dict[str, str]:
    """Pull IP / UA / request_id from a DRF / Django request."""
    if request is None:
        return {"ip_address": "", "user_agent": "", "request_id": ""}
    meta = getattr(request, "META", {}) or {}
    # Honor X-Forwarded-For when present (set by the reverse proxy).
    fwd = meta.get("HTTP_X_FORWARDED_FOR", "")
    ip = (fwd.split(",")[0].strip() if fwd else meta.get("REMOTE_ADDR", "")) or ""
    return {
        "ip_address": ip,
        "user_agent": (meta.get("HTTP_USER_AGENT") or "")[:512],
        "request_id": getattr(request, "request_id", "") or "",
    }


# ──────────────────────────────────────────────────────────────────────
# Login attempt + lockout
# ──────────────────────────────────────────────────────────────────────
def record_login_attempt(
    *,
    username: str,
    outcome: str,
    user=None,
    request=None,
    details: dict[str, Any] | None = None,
):
    """Insert a single ``LoginAttempt`` row.

    Idempotency: callers are expected to call this exactly once per
    attempt. Errors writing the row are logged but do not raise — we
    never want auth to fail because the audit row failed.
    """
    from iams.models import LoginAttempt

    meta = request_metadata(request)
    try:
        row = LoginAttempt.objects.create(
            username=(username or "")[:255],
            user=user,
            outcome=outcome,
            ip_address=meta["ip_address"] or None,
            user_agent=meta["user_agent"],
            request_id=meta["request_id"][:64],
            details=details or {},
        )
    except Exception:  # noqa: BLE001 — never break auth on logging failure
        logger.exception("failed to record LoginAttempt")
        return None
    try:
        from iams.metrics import login_attempts_total
        login_attempts_total.labels(outcome=outcome).inc()
    except Exception:  # noqa: BLE001
        logger.exception("metrics: failed to bump login_attempts_total")
    return row


def get_active_lockout(user):
    """Return the active ``AccountLockout`` for ``user`` or None.

    "Active" = ``cleared_at`` is NULL AND (``locked_until`` is NULL or
    in the future). If a row that's auto-expired is still uncleared,
    we clear it lazily here so subsequent code sees a clean state.
    """
    from iams.models import AccountLockout

    row = (
        AccountLockout.objects.filter(user=user, cleared_at__isnull=True)
        .order_by("-locked_at")
        .first()
    )
    if row is None:
        return None
    if row.locked_until and row.locked_until <= timezone.now():
        # Auto-expire: stamp cleared_at and return None.
        row.cleared_at = timezone.now()
        row.note = (row.note + "\n[auto-cleared on expiry]").strip()
        row.save(update_fields=["cleared_at", "note", "updated_at"])
        return None
    return row


def register_failure(*, user, request=None, outcome: str = "invalid_credentials"):
    """Record a failure and open a lockout if the threshold was crossed.

    Returns ``(lockout, was_just_locked)``:
      - ``lockout``: the active AccountLockout row (may have just been opened)
      - ``was_just_locked``: True iff this call triggered the lockout (so
        callers can emit a specific notification / audit-log event).
    """
    from iams.models import LoginAttempt

    record_login_attempt(
        username=user.username if user else "",
        outcome=outcome,
        user=user,
        request=request,
    )

    if user is None:
        return None, False

    existing = get_active_lockout(user)
    if existing is not None:
        return existing, False

    # Count failures in the rolling window.
    window_start = timezone.now() - timedelta(minutes=_fail_window_min())
    recent_failures = LoginAttempt.objects.filter(
        user=user,
        timestamp__gte=window_start,
    ).exclude(outcome=LoginAttempt.OUTCOME_SUCCESS).count()

    if recent_failures < _fail_threshold():
        return None, False

    # Open a lockout window.
    from iams.models import AccountLockout

    lockout = AccountLockout.objects.create(
        user=user,
        reason=AccountLockout.REASON_FAILED_ATTEMPTS,
        locked_until=timezone.now() + timedelta(minutes=_lockout_minutes()),
        failed_attempt_count=recent_failures,
        note=f"Auto-locked after {recent_failures} failures within {_fail_window_min()}m.",
    )
    try:
        from iams.metrics import account_lockouts_total
        account_lockouts_total.labels(reason=lockout.reason).inc()
    except Exception:  # noqa: BLE001
        logger.exception("metrics: failed to bump account_lockouts_total")
    logger.warning(
        "account_locked",
        extra={
            "user_id": str(user.pk),
            "username": user.username,
            "failures": recent_failures,
        },
    )
    return lockout, True


def clear_lockout(*, user, cleared_by=None, note: str = "") -> bool:
    """Admin unlock. Returns True if a lockout was cleared."""
    lock = get_active_lockout(user)
    if lock is None:
        return False
    lock.cleared_at = timezone.now()
    lock.cleared_by = cleared_by
    if note:
        lock.note = (lock.note + f"\n[{note}]").strip()
    lock.save(update_fields=["cleared_at", "cleared_by", "note", "updated_at"])
    return True


# ──────────────────────────────────────────────────────────────────────
# Password history
# ──────────────────────────────────────────────────────────────────────
def record_password_change(*, user, new_hash: str) -> None:
    """Push the just-set password hash onto the user's history and trim.

    Called by both ``PasswordChangeSerializer`` and the reset-confirm
    serializer. Trimming keeps storage bounded.
    """
    from iams.models import PasswordHistory, UserProfile

    PasswordHistory.objects.create(user=user, password_hash=new_hash)
    keep_n = _password_history_n()
    overflow_ids = list(
        PasswordHistory.objects.filter(user=user)
        .order_by("-set_at")
        .values_list("id", flat=True)[keep_n:]
    )
    if overflow_ids:
        PasswordHistory.objects.filter(id__in=overflow_ids).delete()

    # Stamp the profile.
    UserProfile.objects.filter(user=user).update(password_changed_at=timezone.now())


class PasswordHistoryValidator:
    """Reject a password that matches any of the user's last N hashes.

    Wired into ``AUTH_PASSWORD_VALIDATORS``. Django passes the
    candidate ``password`` and ``user`` to ``validate(...)``; we test
    against each history hash with ``check_password`` (constant-time).
    """

    def __init__(self, history_n: int | None = None):
        self.history_n = history_n if history_n is not None else _password_history_n()

    def validate(self, password: str, user=None) -> None:
        if user is None or user.pk is None:
            return
        from iams.models import PasswordHistory

        recent = (
            PasswordHistory.objects.filter(user=user)
            .order_by("-set_at")
            .values_list("password_hash", flat=True)[: self.history_n]
        )
        for h in recent:
            if check_password(password, h):
                raise ValidationError(
                    f"Password matches one of the last {self.history_n} you've used. Pick a different one.",
                    code="password_reused",
                )

    def get_help_text(self) -> str:
        return f"Your new password must not match any of the last {self.history_n} you've used."


def hash_password(raw: str) -> str:
    """Thin wrapper so call sites don't need to import Django's hasher."""
    return make_password(raw)


# ──────────────────────────────────────────────────────────────────────
# MFA enforcement gate
# ──────────────────────────────────────────────────────────────────────
def mfa_enforcement_required(user) -> bool:
    """Return True iff the user must complete MFA setup before login.

    Two conditions independently trigger enforcement:
      - The user's role has ``mfa_required=True``.
      - More than ``IAMS_MFA_GRACE_DAYS`` (default 30) have elapsed
        since account creation OR last password change, whichever is
        most recent — the "soft escalation" path.

    Returns False if the user already has a confirmed TOTP device.
    """
    from iams.models import MFADevice

    profile = getattr(user, "profile", None)

    if MFADevice.objects.filter(
        user=user, kind=MFADevice.KIND_TOTP, confirmed=True
    ).exists():
        return False

    if profile and profile.role and profile.role.mfa_required:
        return True

    grace_days = int(getattr(settings, "IAMS_MFA_GRACE_DAYS", 30))
    anchor = None
    if profile and profile.password_changed_at:
        anchor = profile.password_changed_at
    elif user.date_joined:
        anchor = user.date_joined
    if anchor and (timezone.now() - anchor) > timedelta(days=grace_days):
        return True

    return False
