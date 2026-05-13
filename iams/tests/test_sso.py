"""Tests for Phase 6 Track 1 — Keycloak / OIDC SSO.

Covers the application-side surfaces. The actual code-exchange flow
against a live Keycloak isn't tested here (that's an integration test
against a running IdP); we test:

  - sso_enabled() / sso_config_payload() correctness
  - SSOConfigView returns the right shape
  - SSOLoginView 302s to the right URL when enabled, 503 when not
  - SSOCallbackView state-mismatch / missing-code 4xx paths
  - resolve_role_from_groups() respects precedence + is_active
  - IAMSOIDCAuthenticationBackend.create_user provisions correctly
  - IAMSOIDCAuthenticationBackend.update_user re-syncs role from groups
  - KeycloakGroupRoleMap CRUD: read needs manage_roles, write needs manage_settings
  - Password login still works when SSO is enabled (additive, not exclusive)
"""
from __future__ import annotations

import pytest
from django.test import override_settings

from iams.models import KeycloakGroupRoleMap, Role, UserProfile
from iams.sso import (
    IAMSOIDCAuthenticationBackend,
    resolve_role_from_groups,
    sso_config_payload,
    sso_enabled,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Discovery
# ──────────────────────────────────────────────────────────────────────
def test_sso_disabled_by_default():
    assert sso_enabled() is False
    payload = sso_config_payload()
    assert payload["enabled"] is False
    assert payload["loginUrl"] is None


@override_settings(
    IAMS_SSO_ENABLED=True,
    OIDC_RP_CLIENT_ID="iams-backend",
    OIDC_OP_AUTHORIZATION_ENDPOINT="https://kc.local/realms/iams/auth",
    OIDC_OP_TOKEN_ENDPOINT="https://kc.local/realms/iams/token",
)
def test_sso_enabled_when_fully_configured():
    assert sso_enabled() is True
    payload = sso_config_payload()
    assert payload["enabled"] is True
    assert payload["loginUrl"] == "/api/auth/sso/login/"
    assert payload["providerName"]


@override_settings(IAMS_SSO_ENABLED=True)
def test_sso_disabled_when_endpoints_missing():
    """IAMS_SSO_ENABLED alone isn't enough — the OIDC endpoints must be set."""
    assert sso_enabled() is False


def test_sso_config_endpoint(api_client):
    res = api_client.get("/api/auth/sso/config/")
    assert res.status_code == 200
    assert res.json()["enabled"] is False


# ──────────────────────────────────────────────────────────────────────
# Login / callback flow
# ──────────────────────────────────────────────────────────────────────
def test_sso_login_503_when_disabled(api_client):
    res = api_client.get("/api/auth/sso/login/")
    assert res.status_code == 503
    assert res.json()["code"] == "sso_disabled"


@override_settings(
    IAMS_SSO_ENABLED=True,
    OIDC_RP_CLIENT_ID="iams-backend",
    OIDC_OP_AUTHORIZATION_ENDPOINT="https://kc.local/realms/iams/auth",
    OIDC_OP_TOKEN_ENDPOINT="https://kc.local/realms/iams/token",
)
def test_sso_login_redirects_to_idp(api_client):
    res = api_client.get("/api/auth/sso/login/?return_to=/dashboard")
    assert res.status_code == 302
    assert res["Location"].startswith("https://kc.local/realms/iams/auth")
    assert "client_id=iams-backend" in res["Location"]
    assert "state=" in res["Location"]


def test_sso_callback_503_when_disabled(api_client):
    res = api_client.get("/api/auth/sso/callback/?code=x&state=y")
    assert res.status_code == 503


@override_settings(
    IAMS_SSO_ENABLED=True,
    OIDC_RP_CLIENT_ID="iams-backend",
    OIDC_OP_AUTHORIZATION_ENDPOINT="https://kc.local/realms/iams/auth",
    OIDC_OP_TOKEN_ENDPOINT="https://kc.local/realms/iams/token",
)
def test_sso_callback_rejects_missing_code(api_client):
    res = api_client.get("/api/auth/sso/callback/")
    assert res.status_code == 400
    assert res.json()["code"] == "sso_invalid"


@override_settings(
    IAMS_SSO_ENABLED=True,
    OIDC_RP_CLIENT_ID="iams-backend",
    OIDC_OP_AUTHORIZATION_ENDPOINT="https://kc.local/realms/iams/auth",
    OIDC_OP_TOKEN_ENDPOINT="https://kc.local/realms/iams/token",
)
def test_sso_callback_rejects_state_mismatch(api_client):
    # No prior /login/ → no session state → mismatch
    res = api_client.get("/api/auth/sso/callback/?code=abc&state=tampered")
    assert res.status_code == 400
    assert res.json()["code"] == "sso_state_mismatch"


# ──────────────────────────────────────────────────────────────────────
# Group → role mapping
# ──────────────────────────────────────────────────────────────────────
def test_resolve_role_returns_none_for_no_match(roles):
    assert resolve_role_from_groups(["/Unknown"]) is None


def test_resolve_role_picks_lowest_precedence(roles):
    KeycloakGroupRoleMap.objects.create(
        group_name="/IAMS/Auditors", role=roles["Auditor"], precedence=10,
    )
    KeycloakGroupRoleMap.objects.create(
        group_name="/IAMS/Managers", role=roles["Audit Manager"], precedence=5,
    )
    chosen = resolve_role_from_groups(["/IAMS/Auditors", "/IAMS/Managers"])
    assert chosen.name == "Audit Manager"


def test_resolve_role_ignores_inactive_mapping(roles):
    KeycloakGroupRoleMap.objects.create(
        group_name="/IAMS/Auditors", role=roles["Auditor"], is_active=False,
    )
    assert resolve_role_from_groups(["/IAMS/Auditors"]) is None


# ──────────────────────────────────────────────────────────────────────
# JIT user provisioning
# ──────────────────────────────────────────────────────────────────────
def test_create_user_provisions_default_role(roles):
    backend = IAMSOIDCAuthenticationBackend()
    user = backend.create_user({
        "preferred_username": "alice",
        "email": "alice@iams.test",
        "given_name": "Alice",
        "family_name": "Doe",
    })
    profile = UserProfile.objects.get(user=user)
    # default role name "Viewer" — auto-created if absent
    assert profile.role.name == "Viewer"
    assert profile.status == "Active"
    assert not user.has_usable_password()


def test_create_user_uses_group_mapping_when_present(roles):
    KeycloakGroupRoleMap.objects.create(
        group_name="/IAMS/Managers", role=roles["Audit Manager"],
    )
    backend = IAMSOIDCAuthenticationBackend()
    user = backend.create_user({
        "preferred_username": "bob",
        "email": "bob@iams.test",
        "groups": ["/IAMS/Managers"],
    })
    assert UserProfile.objects.get(user=user).role.name == "Audit Manager"


def test_update_user_remaps_role_from_groups(roles, auditor_user):
    KeycloakGroupRoleMap.objects.create(
        group_name="/IAMS/Managers", role=roles["Audit Manager"], precedence=5,
    )
    backend = IAMSOIDCAuthenticationBackend()
    profile_before = UserProfile.objects.get(user=auditor_user)
    assert profile_before.role.name == "Auditor"
    backend.update_user(auditor_user, {
        "preferred_username": auditor_user.username,
        "email": auditor_user.email,
        "groups": ["/IAMS/Managers"],
    })
    profile_after = UserProfile.objects.get(user=auditor_user)
    assert profile_after.role.name == "Audit Manager"


def test_filter_users_by_claims_matches_email_case_insensitive(auditor_user):
    backend = IAMSOIDCAuthenticationBackend()
    qs = backend.filter_users_by_claims({"email": auditor_user.email.upper()})
    assert qs.filter(pk=auditor_user.pk).exists()


# ──────────────────────────────────────────────────────────────────────
# KeycloakGroupRoleMap REST API
# ──────────────────────────────────────────────────────────────────────
def test_group_role_map_list_requires_manage_roles(authed_client, auditor_user):
    """Plain Auditor lacks manage_roles → 403."""
    res = authed_client(auditor_user).get("/api/sso/group-role-maps/")
    assert res.status_code == 403


def test_group_role_map_list_visible_to_admin(authed_client, super_admin):
    res = authed_client(super_admin).get("/api/sso/group-role-maps/")
    assert res.status_code == 200


def test_group_role_map_create_requires_manage_settings(
    authed_client, super_admin, roles,
):
    res = authed_client(super_admin).post(
        "/api/sso/group-role-maps/",
        {
            "groupName": "/IAMS/Auditors",
            "roleId": str(roles["Auditor"].id),
            "precedence": 10,
            "isActive": True,
        },
        format="json",
    )
    assert res.status_code == 201, res.content
    assert KeycloakGroupRoleMap.objects.filter(group_name="/IAMS/Auditors").exists()


# ──────────────────────────────────────────────────────────────────────
# Password login coexists with SSO
# ──────────────────────────────────────────────────────────────────────
@override_settings(
    IAMS_SSO_ENABLED=True,
    OIDC_RP_CLIENT_ID="iams-backend",
    OIDC_OP_AUTHORIZATION_ENDPOINT="https://kc.local/realms/iams/auth",
    OIDC_OP_TOKEN_ENDPOINT="https://kc.local/realms/iams/token",
)
def test_password_login_still_works_when_sso_enabled(api_client, auditor_user):
    res = api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "TestPassword123!"},
        format="json",
    )
    assert res.status_code == 200
    assert "access" in res.json()
