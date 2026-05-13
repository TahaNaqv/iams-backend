"""Performance and query-budget tests (Phase 5 Track 2).

These tests enforce query-count budgets on the *list* endpoints that
power the FE's dashboard, notifications bell, and inbox. The point is
not to assert exact numbers (those drift) but to catch N+1 regressions:
when a query budget is silently breached because someone added a new
FK traversal without ``select_related``, the test fails loudly.

Budgets are set to "current + slack" so they tolerate harmless changes
(an extra count query for pagination, a session-touch UPDATE) but
flag any per-row query.

Coverage:
  - Default ``DefaultPagination.page_size == 25`` (NFR target).
  - Pagination envelope shape stays stable across pages.
  - Notifications list with 20 rows fires a bounded number of queries.
  - Audit log list with 20 rows fires a bounded number of queries.
  - Findings list with 50 rows + nested audit FK is bounded.
  - CAPs list with 50 rows + finding + audit FK traversal is bounded.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from iams.models import (
    Audit,
    AuditLogEntry,
    CorrectiveAction,
    Finding,
    Notification,
)
from iams.pagination import DefaultPagination

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _make_audits(n: int) -> list[Audit]:
    today = date.today()
    return [
        Audit.objects.create(
            title=f"A{i}", department="Finance", lead_auditor="lead@iams.test",
            status="In Progress", priority="Medium", risk_rating="Medium",
            start_date=today, end_date=today + timedelta(days=30),
            scope="s", objectives="o", completion_percent=10, findings_count=0,
        )
        for i in range(n)
    ]


def _make_findings(audit, n: int) -> list[Finding]:
    return [
        Finding.objects.create(
            audit=audit, title=f"F{i}", department="Finance",
            severity="Medium", status="Open", owner="auditor@iams.test",
            due_date=date.today() + timedelta(days=30),
            description="d", root_cause="rc", recommendation="r",
            created_date=date.today(),
        )
        for i in range(n)
    ]


def _make_notifications(user, n: int) -> list[Notification]:
    audit_ct = ContentType.objects.get_for_model(Audit)
    audit = _make_audits(1)[0]
    return [
        Notification.objects.create(
            recipient=user,
            kind=Notification.KIND_GENERIC,
            type="info",
            module="System",
            title=f"N{i}",
            message="m",
            timestamp=timezone.now(),
            target_content_type=audit_ct,
            target_object_id=audit.id,
        )
        for i in range(n)
    ]


def _make_log_entries(n: int) -> list[AuditLogEntry]:
    audit_ct = ContentType.objects.get_for_model(Audit)
    audit = _make_audits(1)[0]
    return [
        AuditLogEntry.objects.create(
            actor="alice", action="update", target=f"Audit:{i}",
            target_content_type=audit_ct,
            target_object_id=audit.id,
            timestamp=timezone.now(),
            details={},
        )
        for i in range(n)
    ]


# ══════════════════════════════════════════════════════════════════════
# Pagination
# ══════════════════════════════════════════════════════════════════════
def test_default_pagination_size_is_25():
    """NFR-Performance — default page size tightened from 100 to 25."""
    assert DefaultPagination.page_size == 25
    assert DefaultPagination.max_page_size == 200


def test_pagination_envelope_shape(authed_client, super_admin):
    _make_audits(30)
    res = authed_client(super_admin).get("/api/audits/")
    assert res.status_code == 200
    body = res.json()
    assert {"count", "next", "previous", "page", "pageSize", "totalPages", "results"} <= set(body)
    assert body["pageSize"] == 25
    assert len(body["results"]) == 25
    assert body["totalPages"] == 2


def test_pagination_page_size_query_param_respects_max(authed_client, super_admin):
    """``?page_size=500`` is capped at ``max_page_size`` (200)."""
    _make_audits(5)
    res = authed_client(super_admin).get("/api/audits/?page_size=500")
    assert res.status_code == 200
    body = res.json()
    assert body["pageSize"] == 200


# ══════════════════════════════════════════════════════════════════════
# Query budgets — N+1 regression guards
# ══════════════════════════════════════════════════════════════════════
def test_notifications_list_is_not_n_plus_one(authed_client, super_admin):
    """20 notifications should fire a bounded number of queries.

    Without ``select_related("target_content_type")``, every notification
    in the page would trigger a separate ContentType lookup via
    ``get_targetType``, blowing the budget linearly.
    """
    _make_notifications(super_admin, 20)
    client = authed_client(super_admin)
    # Warm any auth caches
    client.get("/api/notifications/")
    with CaptureQueriesContext(connection) as ctx:
        res = client.get("/api/notifications/")
    assert res.status_code == 200
    # Budget: <= 12. With select_related the count is ~6-9; without it
    # the per-row CT lookups push it to 25+. Either side of the limit
    # is a clear signal.
    assert len(ctx) <= 12, f"Notifications list fired {len(ctx)} queries"
    body = res.json()
    rows = body["results"] if isinstance(body, dict) else body
    assert len(rows) == 20


def test_audit_log_list_is_not_n_plus_one(authed_client, super_admin):
    _make_log_entries(20)
    client = authed_client(super_admin)
    client.get("/api/audit-log/")  # warm caches
    with CaptureQueriesContext(connection) as ctx:
        res = client.get("/api/audit-log/")
    assert res.status_code == 200
    assert len(ctx) <= 12, f"Audit log list fired {len(ctx)} queries"


def test_findings_list_is_not_n_plus_one(authed_client, super_admin):
    """50 findings each pointing at one audit — list must not query
    each audit individually (FindingSerializer reads ``audit.title``)."""
    audit = _make_audits(1)[0]
    _make_findings(audit, 50)
    client = authed_client(super_admin)
    client.get("/api/findings/?page_size=50")
    with CaptureQueriesContext(connection) as ctx:
        res = client.get("/api/findings/?page_size=50")
    assert res.status_code == 200
    # Budget: <= 12. select_related("audit") keeps us low; without it,
    # we'd see 50+ queries from the per-row ``audit.title`` access.
    assert len(ctx) <= 12, f"Findings list fired {len(ctx)} queries"


def test_caps_list_is_not_n_plus_one(authed_client, super_admin):
    """50 CAPs each pointing at one finding (which points at one audit)
    — list must not query the finding or audit per row."""
    audit = _make_audits(1)[0]
    finding = _make_findings(audit, 1)[0]
    for i in range(50):
        CorrectiveAction.objects.create(
            finding=finding, title=f"CAP{i}", owner="o@x.com",
            due_date=date.today() + timedelta(days=10),
            status="Open", priority="Medium",
            description="d", progress=0, department="Finance",
        )
    client = authed_client(super_admin)
    client.get("/api/corrective-actions/?page_size=50")
    with CaptureQueriesContext(connection) as ctx:
        res = client.get("/api/corrective-actions/?page_size=50")
    assert res.status_code == 200
    # CAP serializer hits ``finding`` + ``finding.audit`` chain;
    # select_related("finding", "finding__audit") keeps it flat.
    assert len(ctx) <= 12, f"CAPs list fired {len(ctx)} queries"


def test_dashboard_kpis_query_budget(authed_client, super_admin):
    """Dashboard KPIs aggregator should be bounded irrespective of row count.

    Cache hits on the second call drop the budget to near-zero — but the
    first call should still be tight.
    """
    _make_audits(20)
    audit = _make_audits(1)[0]
    _make_findings(audit, 20)
    client = authed_client(super_admin)
    with CaptureQueriesContext(connection) as ctx:
        res = client.get("/api/dashboard/kpis/")
    assert res.status_code == 200
    # Aggregator does 5 distinct count queries + session/auth overhead.
    assert len(ctx) <= 12, f"Dashboard KPIs fired {len(ctx)} queries"

    # Second call — cache hit. Bounds tighter.
    with CaptureQueriesContext(connection) as ctx2:
        res2 = client.get("/api/dashboard/kpis/")
    assert res2.status_code == 200
    assert len(ctx2) <= 8, f"Cached dashboard KPIs fired {len(ctx2)} queries"


def test_audits_list_query_budget(authed_client, super_admin):
    _make_audits(50)
    client = authed_client(super_admin)
    client.get("/api/audits/?page_size=50")
    with CaptureQueriesContext(connection) as ctx:
        res = client.get("/api/audits/?page_size=50")
    assert res.status_code == 200
    assert len(ctx) <= 10, f"Audits list fired {len(ctx)} queries"
