"""Tests for Phase 6 Track 3 — i18n backend bits.

The FE owns the bulk of the i18n surface (locale bundles, RTL flip).
The backend's contribution is just storing + serving the per-user
preference. Tests cover:

  - UserProfile.language defaults to "en"
  - GET /api/auth/me/ surfaces it
  - PATCH /api/auth/me/ {language: "ar"} persists it
  - Unsupported language rejected with 400
"""
from __future__ import annotations

import pytest

from iams.models import UserProfile

pytestmark = pytest.mark.django_db


def test_user_profile_language_defaults_to_english(auditor_user):
    profile = UserProfile.objects.get(user=auditor_user)
    assert profile.language == "en"


def test_me_surfaces_language(authed_client, auditor_user):
    res = authed_client(auditor_user).get("/api/auth/me/")
    assert res.status_code == 200
    body = res.json()
    assert body["language"] == "en"


def test_me_patch_updates_language(authed_client, auditor_user):
    res = authed_client(auditor_user).patch(
        "/api/auth/me/", {"language": "ar"}, format="json",
    )
    assert res.status_code == 200, res.content
    assert res.json()["language"] == "ar"
    UserProfile.objects.get(user=auditor_user).refresh_from_db()
    assert UserProfile.objects.get(user=auditor_user).language == "ar"


def test_me_patch_supports_french(authed_client, auditor_user):
    res = authed_client(auditor_user).patch(
        "/api/auth/me/", {"language": "fr"}, format="json",
    )
    assert res.status_code == 200
    assert UserProfile.objects.get(user=auditor_user).language == "fr"


def test_me_patch_rejects_unsupported_language(authed_client, auditor_user):
    res = authed_client(auditor_user).patch(
        "/api/auth/me/", {"language": "es"}, format="json",
    )
    assert res.status_code == 400


def test_me_patch_other_fields_does_not_reset_language(authed_client, auditor_user):
    # Set Arabic first
    authed_client(auditor_user).patch(
        "/api/auth/me/", {"language": "ar"}, format="json",
    )
    # Update something else — language must persist
    res = authed_client(auditor_user).patch(
        "/api/auth/me/", {"first_name": "Renamed"}, format="json",
    )
    assert res.status_code == 200
    assert UserProfile.objects.get(user=auditor_user).language == "ar"
