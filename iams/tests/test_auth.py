"""Tests for the Phase 1 auth endpoints.

Coverage:
    GET   /api/auth/me/                       → returns the JWT-authenticated user
    PATCH /api/auth/me/                       → updates own profile (name/email)
    POST  /api/auth/password/change/          → authenticated, requires current password
    POST  /api/auth/password/reset/           → anonymous; always 202; sends email if user exists
    POST  /api/auth/password/reset/confirm/   → completes reset with uid+token

Tests rely on Celery being in eager mode (set in ``config.settings.test``)
so password reset emails are produced synchronously into ``mail.outbox``.
"""
from __future__ import annotations

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


# ──────────────────────────────────────────────────────────────────────
# GET /api/auth/me/
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_me_get_returns_user_with_role_and_permissions(authed_client, audit_manager):
    client = authed_client(audit_manager)
    response = client.get("/api/auth/me/")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "manager@iams.test"
    assert body["role"]["name"] == "Audit Manager"
    assert "view_audits" in body["role"]["permissions"]


@pytest.mark.django_db
def test_me_get_super_admin_has_all_permissions(authed_client, super_admin, permissions):
    client = authed_client(super_admin)
    body = client.get("/api/auth/me/").json()
    # Super admin should see every permission key
    assert set(body["role"]["permissions"]) == set(permissions.keys())


@pytest.mark.django_db
def test_me_get_unauthenticated_is_rejected(api_client):
    assert api_client.get("/api/auth/me/").status_code == 401


# ──────────────────────────────────────────────────────────────────────
# PATCH /api/auth/me/
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_me_patch_updates_name_and_email(authed_client, auditor_user):
    client = authed_client(auditor_user)
    response = client.patch(
        "/api/auth/me/",
        {"first_name": "Updated", "last_name": "Name", "email": "new@iams.test"},
        format="json",
    )
    assert response.status_code == 200
    auditor_user.refresh_from_db()
    assert auditor_user.first_name == "Updated"
    assert auditor_user.email == "new@iams.test"


@pytest.mark.django_db
def test_me_patch_rejects_duplicate_email(authed_client, auditor_user, audit_manager):
    client = authed_client(auditor_user)
    response = client.patch(
        "/api/auth/me/", {"email": audit_manager.email}, format="json"
    )
    assert response.status_code == 400
    assert "email" in response.json()


@pytest.mark.django_db
def test_me_patch_cannot_change_role(authed_client, auditor_user, roles):
    """PATCH /auth/me/ deliberately exposes only first_name/last_name/email."""
    client = authed_client(auditor_user)
    super_admin_role_id = str(roles["Super Admin"].id)
    response = client.patch(
        "/api/auth/me/", {"role_id": super_admin_role_id, "status": "Inactive"}, format="json"
    )
    # Request succeeds — the fields are silently ignored, not surfaced
    assert response.status_code == 200
    auditor_user.profile.refresh_from_db()
    assert auditor_user.profile.role.name == "Auditor"  # unchanged
    assert auditor_user.profile.status == "Active"  # unchanged


# ──────────────────────────────────────────────────────────────────────
# POST /api/auth/password/change/
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_password_change_with_correct_current_password(authed_client, auditor_user):
    client = authed_client(auditor_user)
    response = client.post(
        "/api/auth/password/change/",
        {"current_password": "TestPassword123!", "new_password": "NewSecurePass456$"},
        format="json",
    )
    assert response.status_code == 204
    auditor_user.refresh_from_db()
    assert auditor_user.check_password("NewSecurePass456$")
    assert not auditor_user.check_password("TestPassword123!")


@pytest.mark.django_db
def test_password_change_rejects_wrong_current_password(authed_client, auditor_user):
    client = authed_client(auditor_user)
    response = client.post(
        "/api/auth/password/change/",
        {"current_password": "WrongOldPassword!", "new_password": "NewSecurePass456$"},
        format="json",
    )
    assert response.status_code == 400
    assert "currentPassword" in response.json() or "current_password" in response.json()


@pytest.mark.django_db
def test_password_change_rejects_weak_new_password(authed_client, auditor_user):
    client = authed_client(auditor_user)
    response = client.post(
        "/api/auth/password/change/",
        {"current_password": "TestPassword123!", "new_password": "short"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_password_change_requires_authentication(api_client):
    response = api_client.post(
        "/api/auth/password/change/",
        {"current_password": "x", "new_password": "y"},
        format="json",
    )
    assert response.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# POST /api/auth/password/reset/  (request)
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_password_reset_request_sends_email_for_known_user(api_client, auditor_user):
    mail.outbox.clear()
    response = api_client.post(
        "/api/auth/password/reset/",
        {"email": auditor_user.email},
        format="json",
    )
    assert response.status_code == 202
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == [auditor_user.email]
    assert "Reset your IAMS password" in sent.subject
    # Plain-text body should include a /reset-password/ URL
    assert "/reset-password/" in sent.body


@pytest.mark.django_db
def test_password_reset_request_returns_202_for_unknown_email(api_client):
    """Must not reveal whether the email is registered."""
    mail.outbox.clear()
    response = api_client.post(
        "/api/auth/password/reset/",
        {"email": "nobody@nowhere.test"},
        format="json",
    )
    assert response.status_code == 202
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_password_reset_request_rejects_invalid_email_format(api_client):
    response = api_client.post(
        "/api/auth/password/reset/", {"email": "not-an-email"}, format="json"
    )
    assert response.status_code == 400


# ──────────────────────────────────────────────────────────────────────
# POST /api/auth/password/reset/confirm/
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_password_reset_confirm_with_valid_token(api_client, auditor_user):
    uid = urlsafe_base64_encode(force_bytes(auditor_user.pk))
    token = default_token_generator.make_token(auditor_user)
    response = api_client.post(
        "/api/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "BrandNewPass789!"},
        format="json",
    )
    assert response.status_code == 204
    auditor_user.refresh_from_db()
    assert auditor_user.check_password("BrandNewPass789!")


@pytest.mark.django_db
def test_password_reset_confirm_rejects_bad_token(api_client, auditor_user):
    uid = urlsafe_base64_encode(force_bytes(auditor_user.pk))
    response = api_client.post(
        "/api/auth/password/reset/confirm/",
        {"uid": uid, "token": "invalid-token", "new_password": "BrandNewPass789!"},
        format="json",
    )
    assert response.status_code == 400
    assert "token" in response.json()


@pytest.mark.django_db
def test_password_reset_confirm_rejects_bad_uid(api_client):
    response = api_client.post(
        "/api/auth/password/reset/confirm/",
        {"uid": "garbage", "token": "x", "new_password": "BrandNewPass789!"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_password_reset_confirm_rejects_weak_password(api_client, auditor_user):
    uid = urlsafe_base64_encode(force_bytes(auditor_user.pk))
    token = default_token_generator.make_token(auditor_user)
    response = api_client.post(
        "/api/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "short"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_password_reset_token_single_use(api_client, auditor_user):
    """A successful reset must invalidate the token (password hash changes)."""
    uid = urlsafe_base64_encode(force_bytes(auditor_user.pk))
    token = default_token_generator.make_token(auditor_user)

    first = api_client.post(
        "/api/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "FirstNewPass123!"},
        format="json",
    )
    assert first.status_code == 204

    second = api_client.post(
        "/api/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "SecondNewPass456!"},
        format="json",
    )
    assert second.status_code == 400


# ──────────────────────────────────────────────────────────────────────
# Full round-trip
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_full_password_reset_round_trip(api_client, auditor_user):
    """Anonymous request → email arrives → confirm → user can log in with new password."""
    mail.outbox.clear()

    # 1. Request reset
    req = api_client.post(
        "/api/auth/password/reset/", {"email": auditor_user.email}, format="json"
    )
    assert req.status_code == 202
    assert len(mail.outbox) == 1

    # 2. Extract uid + token from the email
    body = mail.outbox[0].body
    # body contains something like .../reset-password/<uid>/<token>
    marker = "/reset-password/"
    assert marker in body
    tail = body.split(marker, 1)[1].split()[0]  # uid/token (until first whitespace)
    uid, token = tail.split("/", 1)
    token = token.rstrip("/").strip()

    # 3. Confirm
    confirm = api_client.post(
        "/api/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "RoundTripPass321!"},
        format="json",
    )
    assert confirm.status_code == 204

    # 4. Log in with the new password
    login = api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "RoundTripPass321!"},
        format="json",
    )
    assert login.status_code == 200
    assert "access" in login.json()
