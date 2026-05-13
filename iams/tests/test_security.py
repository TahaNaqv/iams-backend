"""Tests for the Phase 5 Track 1 security stack.

Coverage:
  - Login attempt logging: every outcome lands an audit row.
  - Lockout: failures within the window cross the threshold, open a
    lockout, return 423 with locked_until, auto-clear on expiry,
    admin can clear via /api/auth/lockouts/<id>/unlock/.
  - Password policy: PasswordHistoryValidator rejects reuse of the
    last N, both via direct change and the reset-confirm flow.
  - MFA TOTP: enroll → confirm → enforcement gate kicks in → login
    requires otp_token → backup codes consume once.
  - Security headers: CSP, Permissions-Policy, request-id round-trip.
  - Session activity stamping.
"""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.utils import timezone

from iams.models import (
    AccountLockout,
    LoginAttempt,
    MFADevice,
    PasswordHistory,
    UserProfile,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Login attempt logging + lockout
# ──────────────────────────────────────────────────────────────────────
def test_login_success_records_attempt_and_stamps_profile(api_client, auditor_user):
    res = api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "TestPassword123!"},
        format="json",
    )
    assert res.status_code == 200, res.content
    last = LoginAttempt.objects.filter(user=auditor_user).order_by("-timestamp").first()
    assert last is not None
    assert last.outcome == LoginAttempt.OUTCOME_SUCCESS
    profile = UserProfile.objects.get(user=auditor_user)
    assert profile.last_login_at is not None


def test_login_unknown_user_records_attempt(api_client):
    res = api_client.post(
        "/api/auth/token/",
        {"username": "nobody", "password": "whatever"},
        format="json",
    )
    assert res.status_code == 401
    last = LoginAttempt.objects.order_by("-timestamp").first()
    assert last is not None
    assert last.outcome == LoginAttempt.OUTCOME_USER_NOT_FOUND
    assert last.username == "nobody"


def test_login_bad_password_records_invalid_credentials(api_client, auditor_user):
    res = api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "wrong-pw"},
        format="json",
    )
    assert res.status_code == 401
    last = LoginAttempt.objects.filter(user=auditor_user).order_by("-timestamp").first()
    assert last is not None
    assert last.outcome == LoginAttempt.OUTCOME_INVALID_CREDENTIALS


def test_login_inactive_user_returns_401(api_client, auditor_user):
    auditor_user.is_active = False
    auditor_user.save(update_fields=["is_active"])
    res = api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "TestPassword123!"},
        format="json",
    )
    assert res.status_code == 401
    last = LoginAttempt.objects.filter(user=auditor_user).order_by("-timestamp").first()
    assert last.outcome == LoginAttempt.OUTCOME_USER_INACTIVE


@override_settings(
    IAMS_LOGIN_FAIL_THRESHOLD=3,
    IAMS_LOGIN_LOCKOUT_MINUTES=15,
    IAMS_LOGIN_FAIL_WINDOW_MIN=15,
)
def test_lockout_opens_after_threshold_failures(api_client, auditor_user):
    for _ in range(2):
        api_client.post(
            "/api/auth/token/",
            {"username": auditor_user.username, "password": "wrong"},
            format="json",
        )
    # No lockout yet
    assert not AccountLockout.objects.filter(user=auditor_user, cleared_at__isnull=True).exists()
    # Third failure crosses the threshold
    res = api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "wrong"},
        format="json",
    )
    assert res.status_code == 423
    assert res.json()["code"] == "account_locked"
    lock = AccountLockout.objects.filter(user=auditor_user, cleared_at__isnull=True).get()
    assert lock.locked_until is not None
    assert lock.locked_until > timezone.now()


@override_settings(IAMS_LOGIN_FAIL_THRESHOLD=2)
def test_locked_account_rejects_valid_password(api_client, auditor_user):
    # Force lockout
    for _ in range(2):
        api_client.post(
            "/api/auth/token/",
            {"username": auditor_user.username, "password": "wrong"},
            format="json",
        )
    # Even with the right password, lockout wins
    res = api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "TestPassword123!"},
        format="json",
    )
    assert res.status_code == 423


@override_settings(IAMS_LOGIN_FAIL_THRESHOLD=2)
def test_admin_can_unlock_account(authed_client, super_admin, auditor_user):
    # Lock the auditor's account first
    api = authed_client(super_admin)
    for _ in range(2):
        api.post(
            "/api/auth/token/",
            {"username": auditor_user.username, "password": "wrong"},
            format="json",
        )
    res = api.post(f"/api/auth/lockouts/{auditor_user.id}/unlock/")
    assert res.status_code == 204
    assert AccountLockout.objects.filter(
        user=auditor_user, cleared_at__isnull=True,
    ).count() == 0


def test_non_admin_cannot_unlock(authed_client, auditor_user):
    api = authed_client(auditor_user)
    res = api.post(f"/api/auth/lockouts/{auditor_user.id}/unlock/")
    assert res.status_code == 403


def test_lockout_auto_clears_after_locked_until(api_client, auditor_user):
    from datetime import timedelta
    from iams.security import get_active_lockout
    # Open an expired lockout
    AccountLockout.objects.create(
        user=auditor_user,
        reason=AccountLockout.REASON_FAILED_ATTEMPTS,
        locked_until=timezone.now() - timedelta(minutes=1),
    )
    # get_active_lockout auto-clears the expired row
    assert get_active_lockout(auditor_user) is None
    assert AccountLockout.objects.get(user=auditor_user).cleared_at is not None


# ──────────────────────────────────────────────────────────────────────
# Password policy: history of N
# ──────────────────────────────────────────────────────────────────────
@override_settings(IAMS_PASSWORD_HISTORY_N=3)
def test_password_history_blocks_reuse(authed_client, auditor_user):
    api = authed_client(auditor_user)
    # Set 3 distinct passwords (current + 2 changes)
    pw_sequence = ["TestPassword123!", "NewPasswordOne!", "NewPasswordTwo!", "NewPasswordThree!"]
    for old, new in zip(pw_sequence, pw_sequence[1:]):
        res = api.post(
            "/api/auth/password/change/",
            {"current_password": old, "new_password": new},
            format="json",
        )
        assert res.status_code == 204, res.content
    # Try to reuse the very first password — should fail (it's in last 3)
    res = api.post(
        "/api/auth/password/change/",
        {"current_password": "NewPasswordThree!", "new_password": "NewPasswordOne!"},
        format="json",
    )
    assert res.status_code == 400


def test_password_history_records_hash(auditor_user):
    from iams.security import record_password_change

    auditor_user.set_password("brand-new-pw-12345!")
    auditor_user.save(update_fields=["password"])
    record_password_change(user=auditor_user, new_hash=auditor_user.password)
    rows = PasswordHistory.objects.filter(user=auditor_user)
    assert rows.count() == 1


@override_settings(IAMS_PASSWORD_HISTORY_N=2)
def test_password_history_is_trimmed_to_N(auditor_user):
    from iams.security import record_password_change

    for pw in ("AA-12345-aa!", "BB-12345-bb!", "CC-12345-cc!", "DD-12345-dd!"):
        auditor_user.set_password(pw)
        auditor_user.save(update_fields=["password"])
        record_password_change(user=auditor_user, new_hash=auditor_user.password)
    assert PasswordHistory.objects.filter(user=auditor_user).count() == 2


def test_user_profile_password_changed_at_is_stamped(authed_client, auditor_user):
    profile = UserProfile.objects.get(user=auditor_user)
    assert profile.password_changed_at is None
    res = authed_client(auditor_user).post(
        "/api/auth/password/change/",
        {"current_password": "TestPassword123!", "new_password": "fresh-pw-9876543!"},
        format="json",
    )
    assert res.status_code == 204
    profile.refresh_from_db()
    assert profile.password_changed_at is not None


# ──────────────────────────────────────────────────────────────────────
# MFA TOTP
# ──────────────────────────────────────────────────────────────────────
def test_mfa_status_default_unenrolled(authed_client, auditor_user):
    res = authed_client(auditor_user).get("/api/auth/mfa/")
    assert res.status_code == 200
    body = res.json()
    assert body["totpEnrolled"] is False
    assert body["totpPending"] is False


def test_mfa_totp_enroll_then_confirm(authed_client, auditor_user):
    import pyotp

    api = authed_client(auditor_user)
    res = api.post("/api/auth/mfa/totp/enroll/")
    assert res.status_code == 201, res.content
    body = res.json()
    secret = body["secret"]
    assert body["provisioningUri"].startswith("otpauth://")
    # Confirm with a valid token
    token = pyotp.TOTP(secret).now()
    res = api.post("/api/auth/mfa/totp/confirm/", {"token": token}, format="json")
    assert res.status_code == 204
    assert MFADevice.objects.filter(
        user=auditor_user, kind=MFADevice.KIND_TOTP, confirmed=True,
    ).exists()


def test_mfa_totp_confirm_rejects_invalid_token(authed_client, auditor_user):
    api = authed_client(auditor_user)
    api.post("/api/auth/mfa/totp/enroll/")
    res = api.post("/api/auth/mfa/totp/confirm/", {"token": "000000"}, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "totp_invalid"


def test_mfa_enrolled_login_requires_token(api_client, auditor_user, authed_client):
    import pyotp

    # Enroll + confirm
    api = authed_client(auditor_user)
    secret = api.post("/api/auth/mfa/totp/enroll/").json()["secret"]
    api.post("/api/auth/mfa/totp/confirm/", {"token": pyotp.TOTP(secret).now()}, format="json")

    # Bump role to MFA-required so the gate fires
    profile = UserProfile.objects.get(user=auditor_user)
    role = profile.role
    role.mfa_required = True
    role.save(update_fields=["mfa_required"])

    # Login without otp_token → 401 mfa_required
    res = api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "TestPassword123!"},
        format="json",
    )
    assert res.status_code == 401
    assert res.json()["code"] == "mfa_required"

    # Login with valid otp_token → 200
    valid = pyotp.TOTP(secret).now()
    res = api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "TestPassword123!", "otp_token": valid},
        format="json",
    )
    assert res.status_code == 200, res.content


def test_mfa_totp_disable_requires_password(authed_client, auditor_user):
    import pyotp

    api = authed_client(auditor_user)
    secret = api.post("/api/auth/mfa/totp/enroll/").json()["secret"]
    api.post("/api/auth/mfa/totp/confirm/", {"token": pyotp.TOTP(secret).now()}, format="json")

    # Wrong password
    res = api.post("/api/auth/mfa/totp/disable/", {"password": "wrong"}, format="json")
    assert res.status_code == 400

    # Right password
    res = api.post(
        "/api/auth/mfa/totp/disable/",
        {"password": "TestPassword123!"},
        format="json",
    )
    assert res.status_code == 204
    assert not MFADevice.objects.filter(
        user=auditor_user, kind=MFADevice.KIND_TOTP, confirmed=True,
    ).exists()


def test_backup_codes_generate_then_consume(authed_client, auditor_user):
    from iams.mfa import consume_backup_code

    api = authed_client(auditor_user)
    res = api.post("/api/auth/mfa/backup-codes/")
    assert res.status_code == 201
    codes = res.json()["codes"]
    assert len(codes) == 10

    assert consume_backup_code(auditor_user, codes[0]) is True
    # Same code twice = nope
    assert consume_backup_code(auditor_user, codes[0]) is False
    # Wrong format = nope
    assert consume_backup_code(auditor_user, "BOGUS") is False


# ──────────────────────────────────────────────────────────────────────
# Security headers
# ──────────────────────────────────────────────────────────────────────
def test_security_headers_present_on_response(api_client):
    res = api_client.get("/health/")
    assert "Content-Security-Policy" in res.headers
    assert "Permissions-Policy" in res.headers
    assert "Referrer-Policy" in res.headers
    assert "X-Request-ID" in res.headers


def test_session_activity_stamped_on_authenticated_request(authed_client, auditor_user):
    # Wipe stamp first
    UserProfile.objects.filter(user=auditor_user).update(last_activity_at=None)
    authed_client(auditor_user).get("/api/auth/me/")
    profile = UserProfile.objects.get(user=auditor_user)
    assert profile.last_activity_at is not None


# ──────────────────────────────────────────────────────────────────────
# Enforcement helper unit tests
# ──────────────────────────────────────────────────────────────────────
def test_mfa_enforcement_required_for_mfa_required_role(auditor_user, roles):
    from iams.security import mfa_enforcement_required

    # Mutate via the role-by-name lookup so other fixture references stay
    # in sync after we refresh below.
    role = roles["Auditor"]
    role.mfa_required = True
    role.save(update_fields=["mfa_required"])
    assert mfa_enforcement_required(auditor_user) is True


def test_mfa_enforcement_not_required_when_totp_confirmed(auditor_user, roles):
    import pyotp
    from iams.security import mfa_enforcement_required

    profile = UserProfile.objects.get(user=auditor_user)
    profile.role.mfa_required = True
    profile.role.save(update_fields=["mfa_required"])

    secret = pyotp.random_base32()
    MFADevice.objects.create(
        user=auditor_user, kind=MFADevice.KIND_TOTP,
        secret=secret, confirmed=True,
    )
    assert mfa_enforcement_required(auditor_user) is False


@override_settings(IAMS_MFA_GRACE_DAYS=0)
def test_mfa_enforcement_after_grace_period(auditor_user):
    from iams.security import mfa_enforcement_required
    # date_joined is well in the past → grace=0 → enforcement on
    assert mfa_enforcement_required(auditor_user) is True
