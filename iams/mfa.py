"""Multi-factor authentication (TOTP) for IAMS (Phase 5 Track 1).

The IAMS MFA stack is intentionally minimal — pyotp for RFC 6238 TOTP,
the standard 30-second window, and a small set of one-time backup codes
that bypass the authenticator app when a user loses their device.

Design notes:

  - The shared secret is stored as plain base32 in ``MFADevice.secret``.
    At-rest encryption is delegated to the storage layer (LUKS on the
    PostgreSQL volume in production); we don't double-encrypt with a
    Fernet key that itself has to live somewhere.
  - Backup codes are stored as **Django password hashes** in a single
    ``MFADevice(kind="backup_codes")`` row — the ``secret`` column
    holds the JSON ``{"codes": [hash1, hash2, ...]}``. Codes are
    one-shot: once consumed, the hash is removed from the list.
  - ``verify_totp_token`` accepts ±1 window of clock drift (the pyotp
    default), so a token issued within 30 seconds of the boundary
    still passes.
"""
from __future__ import annotations

import json
import logging
import secrets
import string
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

if TYPE_CHECKING:
    from iams.models import MFADevice

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# TOTP setup + verify
# ──────────────────────────────────────────────────────────────────────
def generate_totp_secret() -> str:
    """Return a fresh base32 TOTP secret (160 bits)."""
    import pyotp

    return pyotp.random_base32(length=32)


def totp_provisioning_uri(*, secret: str, account_name: str) -> str:
    """Build the ``otpauth://`` URI the FE renders as a QR code."""
    import pyotp

    issuer = getattr(settings, "IAMS_MFA_TOTP_ISSUER", "IAMS")
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def verify_totp_token(*, device, token: str) -> bool:
    """Validate ``token`` against ``device.secret``.

    Returns True iff the token is valid for the current 30s window
    (or the window immediately preceding it; pyotp default ``valid_window=1``).

    On success, stamps ``device.last_used_at``.
    """
    if not token or not device or device.kind != "totp":
        return False
    import pyotp

    totp = pyotp.TOTP(device.secret)
    if totp.verify(token, valid_window=1):
        device.last_used_at = timezone.now()
        device.save(update_fields=["last_used_at", "updated_at"])
        return True
    return False


def begin_totp_enrollment(user) -> tuple["MFADevice", str]:
    """Create an *unconfirmed* TOTP device + return (device, provisioning URI).

    If the user already has a confirmed device, the caller should reject
    the request (see :func:`MFADeviceCreateView.post`). If they have an
    older unconfirmed row, we replace it — the previous QR is no longer
    valid.
    """
    from iams.models import MFADevice

    # Drop stale unconfirmed rows so the user can restart the flow.
    MFADevice.objects.filter(
        user=user, kind=MFADevice.KIND_TOTP, confirmed=False,
    ).delete()

    secret = generate_totp_secret()
    device = MFADevice.objects.create(
        user=user, kind=MFADevice.KIND_TOTP,
        name="Authenticator app", secret=secret, confirmed=False,
    )
    uri = totp_provisioning_uri(secret=secret, account_name=user.email or user.username)
    return device, uri


def confirm_totp_enrollment(user, token: str) -> bool:
    """Mark the user's unconfirmed TOTP device as confirmed iff ``token`` is valid."""
    from iams.models import MFADevice

    device = (
        MFADevice.objects.filter(
            user=user, kind=MFADevice.KIND_TOTP, confirmed=False,
        )
        .order_by("-created_at")
        .first()
    )
    if device is None:
        return False
    if not verify_totp_token(device=device, token=token):
        return False
    device.confirmed = True
    device.save(update_fields=["confirmed", "updated_at"])
    return True


# ──────────────────────────────────────────────────────────────────────
# Backup codes
# ──────────────────────────────────────────────────────────────────────
BACKUP_CODE_COUNT = 10
BACKUP_CODE_LENGTH = 10  # 10 alphanumeric chars; ~52 bits entropy


def _new_backup_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(BACKUP_CODE_LENGTH))


def generate_backup_codes(user) -> list[str]:
    """Generate a fresh set of backup codes, replace any existing set.

    Returns the *raw* codes (display once to the user, then they're
    gone). The ``MFADevice`` row stores only the hashes.
    """
    from iams.models import MFADevice

    # Wipe prior backup-codes rows for this user.
    MFADevice.objects.filter(user=user, kind=MFADevice.KIND_BACKUP_CODES).delete()

    raw_codes = [_new_backup_code() for _ in range(BACKUP_CODE_COUNT)]
    hashed = [make_password(c) for c in raw_codes]
    MFADevice.objects.create(
        user=user, kind=MFADevice.KIND_BACKUP_CODES,
        name="Backup codes", secret=json.dumps({"codes": hashed}),
        confirmed=True,
    )
    return raw_codes


def consume_backup_code(user, code: str) -> bool:
    """Check ``code`` against the user's backup-codes row.

    On success, the matching hash is removed (one-shot). Returns True
    iff a code was consumed.
    """
    from iams.models import MFADevice

    if not code:
        return False
    row = MFADevice.objects.filter(
        user=user, kind=MFADevice.KIND_BACKUP_CODES,
    ).first()
    if row is None:
        return False
    try:
        payload = json.loads(row.secret or "{}")
    except json.JSONDecodeError:
        logger.exception("backup-codes row contains malformed JSON")
        return False
    codes = list(payload.get("codes") or [])
    for i, h in enumerate(codes):
        if check_password(code, h):
            codes.pop(i)
            row.secret = json.dumps({"codes": codes})
            row.last_used_at = timezone.now()
            row.save(update_fields=["secret", "last_used_at", "updated_at"])
            return True
    return False


# ──────────────────────────────────────────────────────────────────────
# Status helpers (for the FE "MFA setup" panel)
# ──────────────────────────────────────────────────────────────────────
def get_mfa_status(user) -> dict[str, object]:
    """Return a JSON-serializable snapshot of the user's MFA state."""
    from iams.models import MFADevice

    totp = MFADevice.objects.filter(
        user=user, kind=MFADevice.KIND_TOTP,
    ).order_by("-confirmed", "-created_at").first()
    backup = MFADevice.objects.filter(
        user=user, kind=MFADevice.KIND_BACKUP_CODES,
    ).first()

    backup_remaining = 0
    if backup is not None:
        try:
            payload = json.loads(backup.secret or "{}")
        except json.JSONDecodeError:
            payload = {}
        backup_remaining = len(payload.get("codes") or [])

    from iams.security import mfa_enforcement_required

    return {
        "totpEnrolled": bool(totp and totp.confirmed),
        "totpPending": bool(totp and not totp.confirmed),
        "backupCodesRemaining": backup_remaining,
        "enforcementRequired": mfa_enforcement_required(user),
    }
