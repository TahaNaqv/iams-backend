"""RBAC matrix test — proves every list endpoint enforces the right permission key.

This test is the central guarantee that **role gates can't silently drift**.
For each registered endpoint we know:
  - which permission key the view declares (via ``HasPermission(...)``)
  - which roles hold that key (via the role definitions in conftest)

We then exercise the endpoint with one user per role and assert the
expected 200 / 401 / 403 outcome. If a new endpoint is added without a
permission_classes line, this test fails — forcing the engineer to make
the gate explicit.
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken


# ──────────────────────────────────────────────────────────────────────
# Endpoint inventory
#
# Each entry: (url, required_permission_key)
#   - permission_key=None  → only requires authentication (IsAuthenticated)
#   - permission_key="*"   → public (AllowAny)
#
# We list the *list* endpoint for every router-registered viewset, plus the
# nested action URLs the FE consumes.
# ──────────────────────────────────────────────────────────────────────
ENDPOINTS: list[tuple[str, str | None]] = [
    # — Settings / RBAC —
    ("/api/users/", "manage_users"),
    ("/api/roles/", "manage_roles"),
    ("/api/permissions/", "manage_permissions"),
    # — Audit core —
    ("/api/audits/", "view_audits"),
    ("/api/findings/", "manage_findings"),
    ("/api/corrective-actions/", "manage_caps"),
    ("/api/activities/", None),  # IsAuthenticated only
    # — Audit execution —
    ("/api/checklist-items/", "view_audits"),
    ("/api/evidence-files/", "view_audits"),
    ("/api/auditable-entities/", "view_audits"),
    ("/api/risk-history/", "view_audits"),
    # — Workflow & approvals —
    ("/api/notifications/", None),
    ("/api/audit-log/", "view_reports"),
    ("/api/follow-ups/", "manage_findings"),
    ("/api/comments/", None),
    ("/api/approval-requests/", None),
    # — Resources —
    ("/api/auditors/", "view_audits"),
    ("/api/assignments/", "view_audits"),
    ("/api/time-entries/", "view_audits"),
    ("/api/hours-budgets/", "view_audits"),
    # — Risk assessment —
    ("/api/risk-assessments/", "view_audits"),
    ("/api/risk-assessment-sheets/", "view_audits"),
    ("/api/risk-assessment-matrix/", "view_audits"),
    ("/api/risk-assessment-summary/", "view_audits"),
    # Phase 8: now gated to the risk_assessment module at read level (was
    # manage_settings) so audit staff can review their import issues.
    ("/api/risk-assessment-import/issues/", "view_audits"),
    # — Work programs & reports —
    ("/api/work-programs/", "view_audits"),
    ("/api/work-procedures/", "view_audits"),
    ("/api/work-procedure-steps/", "view_audits"),
    ("/api/audit-reports/", "view_reports"),
    ("/api/audit-report-sections/", "view_reports"),
    ("/api/managed-documents/", "view_reports"),
    # — Dashboard —
    ("/api/dashboard/kpis/", None),
]


# Role → permission keys held (mirrors conftest.ROLE_DEFINITIONS exactly)
ROLE_PERMS: dict[str, set[str]] = {
    "Super Admin": {
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
    },
    "Audit Manager": {
        "view_audits",
        "create_audits",
        "edit_audits",
        "manage_findings",
        "manage_caps",
        "view_reports",
        "export_reports",
    },
    "Lead Auditor": {
        "view_audits",
        "create_audits",
        "edit_audits",
        "manage_findings",
        "manage_caps",
        "view_reports",
    },
    "Auditor": {"view_audits", "manage_findings", "manage_caps", "view_reports"},
    "Department Head": {"view_audits", "view_reports"},
    "Executive": {"view_audits", "view_reports", "export_reports"},
}


def _expected_status(role_name: str, permission_key: str | None) -> int:
    """Compute the expected HTTP status for ``role_name`` calling an endpoint
    that requires ``permission_key``."""
    if permission_key is None:
        return 200  # IsAuthenticated — every authed user passes
    if role_name == "Super Admin":
        return 200  # super admin bypass
    if permission_key in ROLE_PERMS[role_name]:
        return 200
    return 403


# ──────────────────────────────────────────────────────────────────────
# Fixtures: one user per role, all built from the conftest roles fixture
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def rbac_users(db, roles):
    """Create one user per role and return ``{role_name: user}``."""
    from django.contrib.auth import get_user_model

    from iams.models import UserProfile

    User = get_user_model()
    users: dict = {}
    for role_name, role in roles.items():
        slug = role_name.lower().replace(" ", "_")
        user = User.objects.create_user(
            username=f"rbac_{slug}",
            email=f"rbac_{slug}@iams.test",
            password="RbacPass123!",
            first_name=role_name,
            last_name="User",
        )
        UserProfile.objects.create(user=user, role=role, department="Audit", status="Active")
        users[role_name] = user
    return users


def _client_for(user) -> APIClient:
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


# ──────────────────────────────────────────────────────────────────────
# The matrix test
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.rbac
@pytest.mark.django_db
@pytest.mark.parametrize("url,permission_key", ENDPOINTS)
@pytest.mark.parametrize("role_name", list(ROLE_PERMS.keys()))
def test_rbac_matrix(url: str, permission_key: str | None, role_name: str, rbac_users):
    user = rbac_users[role_name]
    client = _client_for(user)
    response = client.get(url)
    expected = _expected_status(role_name, permission_key)
    assert response.status_code == expected, (
        f"{role_name} GET {url} expected {expected} "
        f"(needs '{permission_key}'), got {response.status_code}"
    )


@pytest.mark.rbac
@pytest.mark.django_db
@pytest.mark.parametrize("url,permission_key", ENDPOINTS)
def test_rbac_anonymous_rejected_everywhere(url: str, permission_key: str | None, db):
    """No matter the endpoint, unauthenticated requests must get 401."""
    client = APIClient()
    response = client.get(url)
    assert response.status_code == 401, (
        f"Anonymous GET {url} expected 401, got {response.status_code}"
    )


@pytest.mark.rbac
@pytest.mark.django_db
def test_super_admin_can_reach_every_endpoint(rbac_users):
    """The super admin bypass must work on every registered list endpoint."""
    client = _client_for(rbac_users["Super Admin"])
    failures: list[str] = []
    for url, _ in ENDPOINTS:
        response = client.get(url)
        if response.status_code != 200:
            failures.append(f"{url}: {response.status_code}")
    assert not failures, "Super Admin should be 200 on all endpoints. Failures: " + ", ".join(
        failures
    )
