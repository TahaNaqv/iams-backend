"""Validates the real 9-role × 11-module Role Access Matrix end-to-end:
module gating (read dimension), department scoping, and the issuance gate.

Unlike test_rbac_matrix (which exercises the legacy 6-role fixtures through
the compat shim), this seeds the canonical matrix from iams.rbac_matrix.
"""
from __future__ import annotations

import datetime

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from iams.models import Audit, Finding, UserProfile
from iams.rbac_matrix import ACCESS_RANK, READ, ROLE_MATRIX
from iams.tests._rbac import seed_canonical_roles

User = get_user_model()


@pytest.fixture
def canonical_roles(db):
    return seed_canonical_roles()


def _user_for(role, *, dept="Alpha", username):
    user = User.objects.create_user(
        username=username, email=f"{username}@iams.test", password="Pw123456!",
    )
    UserProfile.objects.create(user=user, role=role, department=dept, status="Active")
    return user


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return c


# Representative GET (list) endpoint per module → the module key it gates on.
MODULE_ENDPOINTS = {
    "audit_universe": "/api/auditable-entities/",
    "risk_assessment": "/api/risk-assessments/",
    "engagements": "/api/audits/",
    "workpapers": "/api/working-papers/",
    "findings": "/api/findings/",
    "reports": "/api/audit-reports/",
    "follow_up": "/api/follow-ups/",
    "mgmt_responses": "/api/management-responses/",
    "users_roles": "/api/roles/",
    "dashboards": "/api/dashboard/kpis/",
}


@pytest.mark.django_db
@pytest.mark.parametrize("role_name", list(ROLE_MATRIX.keys()))
@pytest.mark.parametrize("module_key,url", list(MODULE_ENDPOINTS.items()))
def test_matrix_read_gating(canonical_roles, role_name, module_key, url):
    """GET a representative endpoint per module: 200 iff the role has >= read
    on that module (scoped read still passes the gate), else 403."""
    role = canonical_roles[role_name]
    user = _user_for(role, username=f"m_{role_name}_{module_key}".replace(" ", "_").replace("/", ""))
    resp = _client(user).get(url)
    level = ROLE_MATRIX[role_name][module_key][0]
    expected_ok = ACCESS_RANK[level] >= ACCESS_RANK[READ]
    if expected_ok:
        assert resp.status_code == 200, (
            f"{role_name} GET {url} ({module_key}={level}) expected 200, got {resp.status_code}"
        )
    else:
        assert resp.status_code == 403, (
            f"{role_name} GET {url} ({module_key}={level}) expected 403, got {resp.status_code}"
        )


def _make_finding(dept, *, issued, title):
    audit = Audit.objects.create(
        title=f"Audit {title}", department=dept, lead_auditor="L",
        status="In Progress", start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 6, 1), priority="Medium", risk_rating="Medium",
    )
    return Finding.objects.create(
        title=title, audit=audit, department=dept, severity="Medium",
        status="Open", owner="o", due_date=datetime.date(2026, 6, 1),
        is_issued=issued,
    )


@pytest.mark.django_db
def test_staff_auditor_scoped_to_own_department(canonical_roles):
    """Staff auditor (findings=edit, scoped) sees only own-department findings
    and gets 404 on a cross-department finding's detail."""
    f_alpha = _make_finding("Alpha", issued=False, title="alpha-f")
    f_beta = _make_finding("Beta", issued=False, title="beta-f")
    user = _user_for(canonical_roles["Staff auditor"], dept="Alpha", username="staff1")
    client = _client(user)

    body = client.get("/api/findings/").json()
    rows = body["results"] if isinstance(body, dict) else body
    ids = {r["id"] for r in rows}
    assert str(f_alpha.id) in ids
    assert str(f_beta.id) not in ids

    # Cross-department detail is invisible (404 via scoped queryset).
    assert client.get(f"/api/findings/{f_beta.id}/").status_code == 404
    assert client.get(f"/api/findings/{f_alpha.id}/").status_code == 200


@pytest.mark.django_db
def test_auditee_sees_only_issued_own_department_findings(canonical_roles):
    """Auditee (findings=read, scoped, issuance-gated) sees only issued
    findings in their own department."""
    issued = _make_finding("Alpha", issued=True, title="issued")
    unissued = _make_finding("Alpha", issued=False, title="unissued")
    other = _make_finding("Beta", issued=True, title="other-dept")
    user = _user_for(canonical_roles["Auditee / client manager"], dept="Alpha", username="auditee1")
    client = _client(user)

    body = client.get("/api/findings/").json()
    rows = body["results"] if isinstance(body, dict) else body
    ids = {r["id"] for r in rows}
    assert str(issued.id) in ids
    assert str(unissued.id) not in ids  # not issued
    assert str(other.id) not in ids     # other department

    # Unissued own-dept finding detail is hidden.
    assert client.get(f"/api/findings/{unissued.id}/").status_code == 404
    assert client.get(f"/api/findings/{issued.id}/").status_code == 200


@pytest.mark.django_db
def test_non_scoped_role_sees_all_findings(canonical_roles):
    """Audit manager (findings=edit, NOT scoped) sees every department."""
    f_alpha = _make_finding("Alpha", issued=False, title="a")
    f_beta = _make_finding("Beta", issued=False, title="b")
    user = _user_for(canonical_roles["Audit manager"], dept="Alpha", username="mgr1")
    body = _client(user).get("/api/findings/").json()
    rows = body["results"] if isinstance(body, dict) else body
    ids = {r["id"] for r in rows}
    assert {str(f_alpha.id), str(f_beta.id)} <= ids


@pytest.mark.django_db
def test_scoped_create_is_stamped_to_own_department(canonical_roles):
    """A scoped Staff auditor (findings=edit, scoped) cannot create a finding
    in another department — the department is forced to their own."""
    audit = Audit.objects.create(
        title="A", department="Beta", lead_auditor="L", status="In Progress",
        start_date=datetime.date(2026, 1, 1), end_date=datetime.date(2026, 6, 1),
        priority="Medium", risk_rating="Medium",
    )
    user = _user_for(canonical_roles["Staff auditor"], dept="Alpha", username="staffcreate")
    resp = _client(user).post("/api/findings/", {
        "title": "sneaky", "auditId": str(audit.id), "department": "Beta",  # tries Beta
        "severity": "Medium", "status": "Open", "owner": "o", "dueDate": "2026-06-01",
    }, format="json")
    assert resp.status_code == 201, resp.content
    # Department was forced to the actor's own department, not "Beta".
    assert Finding.objects.get(id=resp.json()["id"]).department == "Alpha"


@pytest.mark.django_db
def test_qa_reviewer_read_only_cannot_write_findings(canonical_roles):
    """QA reviewer has findings=read → can list but not create."""
    user = _user_for(canonical_roles["QA / quality reviewer"], username="qa1")
    client = _client(user)
    assert client.get("/api/findings/").status_code == 200
    audit = Audit.objects.create(
        title="A", department="Alpha", lead_auditor="L", status="Planned",
        start_date=datetime.date(2026, 1, 1), end_date=datetime.date(2026, 6, 1),
        priority="Medium", risk_rating="Medium",
    )
    resp = client.post("/api/findings/", {
        "title": "x", "auditId": str(audit.id), "department": "Alpha",
        "severity": "Medium", "status": "Open", "owner": "o", "dueDate": "2026-06-01",
    }, format="json")
    assert resp.status_code == 403
