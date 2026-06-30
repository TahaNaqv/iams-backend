"""Shared pytest fixtures for the IAMS test suite.

These fixtures are picked up by every test under ``iams/tests/``. They cover
the most common needs:

- ``api_client`` — a DRF ``APIClient`` with no auth
- ``admin_user`` / ``auditor_user`` / ``auditee_user`` — pre-seeded users
- ``authed_client`` factory — returns an APIClient with JWT for any user
- ``permissions`` — the 12 RBAC permission rows seeded by ``seed_rbac``
- ``roles`` — the 6 predefined roles with their permission sets
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from iams.models import Module, Permission, Role, RoleModuleAccess, UserProfile
from iams.rbac_matrix import MODULES
from iams.tests._rbac import cells_from_keys as _cells_from_keys

User = get_user_model()


# ──────────────────────────────────────────────────────────────────────
# Permissions & roles
# ──────────────────────────────────────────────────────────────────────
PERMISSION_KEYS = [
    "view_audits",
    "create_audits",
    "edit_audits",
    "delete_audits",
    "manage_findings",
    "manage_caps",
    "view_reports",
    "export_reports",
    "manage_users",
    "manage_roles",
    "manage_permissions",
    "manage_settings",
]

ROLE_DEFINITIONS: dict[str, list[str]] = {
    "Super Admin": PERMISSION_KEYS,  # gets all via is_super_admin in real seed
    "Audit Manager": [
        "view_audits",
        "create_audits",
        "edit_audits",
        "manage_findings",
        "manage_caps",
        "view_reports",
        "export_reports",
    ],
    "Lead Auditor": [
        "view_audits",
        "create_audits",
        "edit_audits",
        "manage_findings",
        "manage_caps",
        "view_reports",
    ],
    "Auditor": ["view_audits", "manage_findings", "manage_caps", "view_reports"],
    "Department Head": ["view_audits", "view_reports"],
    "Executive": ["view_audits", "view_reports", "export_reports"],
}


@pytest.fixture
def permissions(db) -> dict[str, Permission]:
    return {
        key: Permission.objects.create(key=key, name=key.replace("_", " ").title(), module="test")
        for key in PERMISSION_KEYS
    }


@pytest.fixture
def modules(db) -> dict[str, Module]:
    return {
        key: Module.objects.create(key=key, name=name, order=order)
        for key, name, order in MODULES
    }


@pytest.fixture
def roles(db, permissions, modules) -> dict[str, Role]:
    role_map: dict[str, Role] = {}
    for name, perm_keys in ROLE_DEFINITIONS.items():
        role = Role.objects.create(
            name=name,
            is_super_admin=(name == "Super Admin"),
        )
        role.permissions.set([permissions[k] for k in perm_keys])
        # Seed the matrix cells the new HasPermission shim resolves against,
        # reconstructed from the legacy key set so effective access is identical.
        for module_key, level in _cells_from_keys(perm_keys).items():
            RoleModuleAccess.objects.create(
                role=role, module=modules[module_key], level=level
            )
        role_map[name] = role
    return role_map


# ──────────────────────────────────────────────────────────────────────
# Users (one per role)
# ──────────────────────────────────────────────────────────────────────
def _make_user(role: Role, *, email: str, username: str) -> User:
    user = User.objects.create_user(
        username=username,
        email=email,
        password="TestPassword123!",
        first_name=role.name.split()[0],
        last_name="User",
    )
    UserProfile.objects.create(user=user, role=role, department="Internal Audit", status="Active")
    return user


@pytest.fixture
def super_admin(db, roles) -> User:
    return _make_user(roles["Super Admin"], email="sa@iams.test", username="sa")


@pytest.fixture
def audit_manager(db, roles) -> User:
    return _make_user(roles["Audit Manager"], email="manager@iams.test", username="manager")


@pytest.fixture
def auditor_user(db, roles) -> User:
    return _make_user(roles["Auditor"], email="auditor@iams.test", username="auditor")


@pytest.fixture
def auditee_user(db, roles) -> User:
    return _make_user(roles["Department Head"], email="auditee@iams.test", username="auditee")


@pytest.fixture
def viewer_user(db, roles) -> User:
    return _make_user(roles["Executive"], email="exec@iams.test", username="viewer")


# ──────────────────────────────────────────────────────────────────────
# API clients
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def api_client() -> APIClient:
    """Unauthenticated APIClient."""
    return APIClient()


@pytest.fixture
def authed_client():
    """Factory: ``authed_client(user)`` returns a JWT-authenticated APIClient."""
    def _make(user: User) -> APIClient:
        client = APIClient()
        refresh = RefreshToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        return client

    return _make
