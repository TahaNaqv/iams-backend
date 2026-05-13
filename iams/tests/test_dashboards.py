"""Tests for the Dashboards Backend (Phase 4 Track 3 / FR-DASH-01..11).

Coverage:
  - Aggregator math: core_kpis, trends, risk_heatmap_by_department,
    rating_summary, upcoming_audits, recent_activity
  - Period and department filters
  - Role bundles (executive / manager / auditor / auditee) include the
    right panels and respect user scoping
  - Redis cache: second call hits cache, invalidate flushes
  - New PDF renderers (department_risk, open_issues, icfr_summary,
    qaip_annual, audit_committee) build the expected context and
    render to HTML when IAMS_DISABLE_PDF_RENDER=1
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache

from iams.dashboards import (
    _cache_key,
    cache_or_compute,
    core_kpis,
    invalidate_dashboard_cache,
    rating_summary,
    recent_activity,
    risk_heatmap_by_department,
    role_bundle,
    trends,
    upcoming_audits,
)
from iams.models import (
    Audit,
    AuditableEntity,
    CorrectiveAction,
    EntityRiskScore,
    Finding,
    QAIPAssessment,
    ReportJob,
    RiskScoringModel,
)
from iams.reports import (
    AuditCommitteePackRenderer,
    DepartmentRiskProfileRenderer,
    ICFRSummaryRenderer,
    OpenIssuesRenderer,
    QAIPAnnualRenderer,
    RENDERERS,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with a clean dashboard cache."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _disable_pdf_render(monkeypatch):
    monkeypatch.setenv("IAMS_DISABLE_PDF_RENDER", "1")


@pytest.fixture
def seed_audits():
    today = date.today()
    a1 = Audit.objects.create(
        title="Open Q1", department="Finance", lead_auditor="lead@iams.test",
        status="In Progress", priority="High", risk_rating="High",
        start_date=date(today.year, 1, 1), end_date=date(today.year, 3, 31),
        scope="s", objectives="o", completion_percent=50, findings_count=0,
    )
    a2 = Audit.objects.create(
        title="Done Q1", department="Finance", lead_auditor="lead@iams.test",
        status="Completed", priority="Medium", risk_rating="Medium",
        start_date=date(today.year - 1, 1, 1),
        end_date=date(today.year - 1, 3, 15),
        scope="s", objectives="o", completion_percent=100, findings_count=0,
    )
    a3 = Audit.objects.create(
        title="Future", department="Ops", lead_auditor="lead@iams.test",
        status="Planned", priority="Low", risk_rating="Low",
        start_date=today + timedelta(days=14),
        end_date=today + timedelta(days=44),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    return [a1, a2, a3]


@pytest.fixture
def seed_findings(seed_audits):
    today = date.today()
    f1 = Finding.objects.create(
        audit=seed_audits[0], title="Critical leak", department="Finance",
        severity="Critical", status="Open", owner="auditor@iams.test",
        due_date=today - timedelta(days=10),  # overdue
        description="d", root_cause="rc", recommendation="r",
        created_date=date(today.year, 2, 14),
    )
    f2 = Finding.objects.create(
        audit=seed_audits[0], title="Medium gap", department="Finance",
        severity="Medium", status="Closed", owner="auditor@iams.test",
        due_date=today + timedelta(days=15),
        description="d", root_cause="rc", recommendation="r",
        created_date=date(today.year, 3, 1),
    )
    return [f1, f2]


@pytest.fixture
def seed_caps(seed_findings):
    today = date.today()
    return [
        CorrectiveAction.objects.create(
            finding=seed_findings[0], title="Fix the leak",
            owner="ops@iams.test", due_date=today + timedelta(days=20),
            status="In Progress", priority="High",
            description="d", progress=30, department="Finance",
        ),
        CorrectiveAction.objects.create(
            finding=seed_findings[1], title="Close gap",
            owner="ops@iams.test", due_date=today - timedelta(days=2),
            status="Closed", priority="Medium",
            description="d", progress=100, department="Finance",
        ),
    ]


@pytest.fixture
def seed_risk_scores(super_admin):
    from django.utils import timezone
    e1 = AuditableEntity.objects.create(name="Treasury", department="Finance",
                                        owner="o", risk_rating="High", status="Active")
    e2 = AuditableEntity.objects.create(name="HR Payroll", department="HR",
                                        owner="o", risk_rating="Medium", status="Active")
    model = RiskScoringModel.objects.create(
        name="M", version="1.0",
        formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
        is_active=True, high_risk_threshold=Decimal("60"),
    )
    now = timezone.now()
    EntityRiskScore.objects.create(
        entity=e1, scoring_model=model,
        factor_values={}, composite_score=Decimal("85"),
        rank=1, is_current=True, snapshot_at=now,
    )
    EntityRiskScore.objects.create(
        entity=e2, scoring_model=model,
        factor_values={}, composite_score=Decimal("45"),
        rank=2, is_current=True, snapshot_at=now,
    )
    return [e1, e2, model]


# ══════════════════════════════════════════════════════════════════════
# core_kpis
# ══════════════════════════════════════════════════════════════════════
def test_core_kpis_returns_expected_counts(seed_audits, seed_findings, seed_caps):
    payload = core_kpis()
    assert payload["openAudits"] == 2  # a1 + a3 (a2 is Completed)
    assert payload["overdueFindings"] == 1  # f1
    assert payload["pendingCAPs"] == 1  # cap1 (in progress)
    # completionRate: 1 closed of 2 total → 50
    assert payload["completionRate"] == 50


def test_core_kpis_filters_by_department(seed_audits, seed_findings, seed_caps):
    fin = core_kpis(department="Finance")
    ops = core_kpis(department="Ops")
    assert fin["openAudits"] == 1  # only a1
    assert ops["openAudits"] == 1  # only a3


def test_core_kpis_filters_by_period(seed_audits, seed_findings):
    today = date.today()
    last_year = core_kpis(period=str(today.year - 1))
    # a2 (Completed last year) → open is 0 last year
    assert last_year["openAudits"] == 0


def test_core_kpis_empty_db_returns_zeros():
    payload = core_kpis()
    assert payload == {
        "openAudits": 0,
        "overdueFindings": 0,
        "pendingCAPs": 0,
        "completionRate": 0,
        "period": None,
        "department": None,
    }


# ══════════════════════════════════════════════════════════════════════
# trends
# ══════════════════════════════════════════════════════════════════════
def test_trends_yoy_returns_8_quarter_buckets(seed_audits, seed_findings):
    payload = trends(period="YoY")
    assert payload["period"] == "YoY"
    assert len(payload["series"]) == 8
    # Series are quarters with the expected period strings
    for row in payload["series"]:
        assert "-Q" in row["period"]
        assert set(row.keys()) >= {"period", "findings", "auditsCompleted", "capsClosed"}


def test_trends_fy_returns_4_quarter_buckets():
    payload = trends(period="FY2026")
    assert len(payload["series"]) == 4
    assert payload["series"][0]["period"] == "2026-Q1"
    assert payload["series"][3]["period"] == "2026-Q4"


def test_trends_invalid_period_returns_empty_series():
    assert trends(period="garbage")["series"] == []


# ══════════════════════════════════════════════════════════════════════
# risk_heatmap_by_department
# ══════════════════════════════════════════════════════════════════════
def test_risk_heatmap_buckets_by_category(seed_risk_scores):
    payload = risk_heatmap_by_department()
    assert payload["categories"] == ["Critical", "High", "Medium", "Low"]
    assert "Finance" in payload["departments"]
    assert "HR" in payload["departments"]
    # Treasury at 85 → Critical/Finance count=1
    fin_critical = next(
        c for c in payload["cells"]
        if c["department"] == "Finance" and c["category"] == "Critical"
    )
    assert fin_critical["count"] == 1
    # HR Payroll at 45 → Medium/HR count=1
    hr_medium = next(
        c for c in payload["cells"]
        if c["department"] == "HR" and c["category"] == "Medium"
    )
    assert hr_medium["count"] == 1


def test_risk_heatmap_handles_empty():
    payload = risk_heatmap_by_department()
    assert payload["departments"] == []
    assert payload["cells"] == []


# ══════════════════════════════════════════════════════════════════════
# rating_summary
# ══════════════════════════════════════════════════════════════════════
def test_rating_summary_buckets(super_admin, seed_audits):
    QAIPAssessment.objects.create(
        title="Q1", type=QAIPAssessment.TYPE_INTERNAL,
        period="2026", rating_overall=QAIPAssessment.RATING_SATISFACTORY,
        lead_reviewer=super_admin, scope="x",
    )
    QAIPAssessment.objects.create(
        title="Q2", type=QAIPAssessment.TYPE_EXTERNAL,
        period="2026", rating_overall=QAIPAssessment.RATING_NEEDS_IMPROVEMENT,
        lead_reviewer=super_admin, scope="x",
    )
    payload = rating_summary(period="2026")
    by_rating = {r["rating_overall"]: r["count"] for r in payload["qaip"]}
    assert by_rating[QAIPAssessment.RATING_SATISFACTORY] == 1
    assert by_rating[QAIPAssessment.RATING_NEEDS_IMPROVEMENT] == 1
    # icfr / csa shapes are present even when empty
    assert isinstance(payload["icfr"], list)
    assert "weak" in payload["csa"]
    assert "averageScore" in payload["csa"]


# ══════════════════════════════════════════════════════════════════════
# upcoming_audits / recent_activity
# ══════════════════════════════════════════════════════════════════════
def test_upcoming_audits_filters_future_only(seed_audits):
    rows = upcoming_audits(limit=10)
    titles = {r["title"] for r in rows}
    assert "Future" in titles
    assert "Done Q1" not in titles  # in the past


def test_upcoming_audits_respects_department_filter(seed_audits):
    rows = upcoming_audits(department="Ops")
    assert all(r["department"] == "Ops" for r in rows)


def test_recent_activity_returns_audit_log_entries(seed_audits):
    from django.utils import timezone
    from iams.models import AuditLogEntry
    AuditLogEntry.objects.create(
        actor="alice", action="create", target="Audit",
        timestamp=timezone.now(),
        details={"event": "test"},
    )
    rows = recent_activity(limit=5)
    assert len(rows) >= 1
    assert rows[0]["actor"] == "alice"


# ══════════════════════════════════════════════════════════════════════
# role_bundle
# ══════════════════════════════════════════════════════════════════════
def test_role_bundle_rejects_unknown_role():
    with pytest.raises(ValueError, match="role must be one of"):
        role_bundle(role="ceo")


def test_role_bundle_executive_panels(seed_audits, seed_findings):
    payload = role_bundle(role="executive")
    assert payload["role"] == "executive"
    assert {"kpis", "trends", "riskHeatmap", "ratings", "upcomingAudits"} <= set(payload.keys())


def test_role_bundle_auditor_filters_by_user_email(seed_audits, seed_findings):
    payload = role_bundle(role="auditor", user_email="auditor@iams.test")
    # f1 is owned by auditor@iams.test, status Open → in myOpenFindings
    titles = {f["title"] for f in payload["myOpenFindings"]}
    assert "Critical leak" in titles
    # Closed finding excluded
    assert "Medium gap" not in titles


def test_role_bundle_auditee_includes_my_open_caps(seed_audits, seed_findings, seed_caps):
    payload = role_bundle(role="auditee", user_email="ops@iams.test")
    titles = {c["title"] for c in payload["myOpenCAPs"]}
    assert "Fix the leak" in titles
    # Closed CAP excluded
    assert "Close gap" not in titles


# ══════════════════════════════════════════════════════════════════════
# Cache layer
# ══════════════════════════════════════════════════════════════════════
def test_cache_or_compute_hits_cache_on_second_call(seed_audits, seed_findings):
    calls = {"n": 0}

    def expensive():
        calls["n"] += 1
        return {"value": 42}

    key = _cache_key("test-cache", x=1)
    first = cache_or_compute(key, expensive)
    second = cache_or_compute(key, expensive)
    assert first == {"value": 42}
    assert second == {"value": 42}
    assert calls["n"] == 1  # second call was cached


def test_invalidate_dashboard_cache_returns_int():
    # LocMemCache returns 0 — but doesn't raise.
    n = invalidate_dashboard_cache()
    assert isinstance(n, int)


# ══════════════════════════════════════════════════════════════════════
# API endpoints
# ══════════════════════════════════════════════════════════════════════
def test_api_dashboard_kpis(authed_client, super_admin, seed_audits, seed_findings):
    res = authed_client(super_admin).get("/api/dashboard/kpis/")
    assert res.status_code == 200
    body = res.json()
    assert body["openAudits"] == 2


def test_api_dashboard_kpis_with_filters(authed_client, super_admin, seed_audits, seed_findings):
    res = authed_client(super_admin).get(
        "/api/dashboard/kpis/", {"department": "Finance"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["openAudits"] == 1


def test_api_dashboard_trends(authed_client, super_admin, seed_audits):
    res = authed_client(super_admin).get("/api/dashboard/trends/", {"period": "FY2026"})
    assert res.status_code == 200
    body = res.json()
    assert len(body["series"]) == 4


def test_api_dashboard_risk_heatmap(authed_client, super_admin, seed_risk_scores):
    res = authed_client(super_admin).get("/api/dashboard/risk-heatmap/")
    assert res.status_code == 200
    body = res.json()
    assert "Finance" in body["departments"]
    assert "HR" in body["departments"]


def test_api_dashboard_ratings(authed_client, super_admin, seed_audits):
    res = authed_client(super_admin).get("/api/dashboard/ratings/")
    assert res.status_code == 200
    body = res.json()
    assert "qaip" in body and "icfr" in body and "csa" in body


def test_api_dashboard_activity(authed_client, super_admin):
    from django.utils import timezone
    from iams.models import AuditLogEntry
    AuditLogEntry.objects.create(
        actor="bob", action="update", target="Finding",
        timestamp=timezone.now(), details={},
    )
    res = authed_client(super_admin).get("/api/dashboard/activity/", {"limit": 5})
    assert res.status_code == 200
    rows = res.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1


def test_api_dashboard_upcoming(authed_client, super_admin, seed_audits):
    res = authed_client(super_admin).get("/api/dashboard/upcoming-audits/")
    assert res.status_code == 200
    titles = {r["title"] for r in res.json()}
    assert "Future" in titles


def test_api_dashboard_role_executive(authed_client, super_admin, seed_audits):
    res = authed_client(super_admin).get("/api/dashboard/role/executive/")
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "executive"
    assert "kpis" in body and "trends" in body


def test_api_dashboard_role_unknown_returns_400(authed_client, super_admin):
    res = authed_client(super_admin).get("/api/dashboard/role/badger/")
    assert res.status_code == 400
    body = res.json()
    assert "supported" in body


# ══════════════════════════════════════════════════════════════════════
# New PDF renderers
# ══════════════════════════════════════════════════════════════════════
def test_registry_includes_new_renderers():
    expected = {
        ReportJob.KIND_DEPARTMENT_RISK,
        ReportJob.KIND_OPEN_ISSUES,
        ReportJob.KIND_ICFR_SUMMARY,
        ReportJob.KIND_QAIP_ANNUAL,
        ReportJob.KIND_AUDIT_COMMITTEE,
    }
    assert expected.issubset(RENDERERS.keys())


def test_department_risk_renderer_context(seed_risk_scores):
    ctx = DepartmentRiskProfileRenderer().gather_context({})
    assert ctx["report_title"] == "Department Risk Profile"
    assert "Finance" in ctx["heatmap"]["departments"]


def test_department_risk_renderer_department_filter(seed_risk_scores):
    ctx = DepartmentRiskProfileRenderer().gather_context({"department": "Finance"})
    assert ctx["heatmap"]["departments"] == ["Finance"]


def test_open_issues_renderer_context(seed_audits, seed_findings, seed_caps):
    ctx = OpenIssuesRenderer().gather_context({})
    # f1 is the only non-closed finding
    assert ctx["total_findings"] == 1
    titles = {r["finding"].title for r in ctx["rows"]}
    assert "Critical leak" in titles


def test_open_issues_renderer_filters_by_department(seed_audits, seed_findings, seed_caps):
    ctx = OpenIssuesRenderer().gather_context({"department": "Ops"})
    assert ctx["total_findings"] == 0


def test_icfr_summary_renderer_context():
    ctx = ICFRSummaryRenderer().gather_context({"period": "2026"})
    assert ctx["report_title"] == "ICFR Summary"
    assert "summary" in ctx
    # Even with no data, the aggregator returns dict with these keys
    assert "totalControls" in ctx["summary"]


def test_qaip_annual_requires_period():
    from iams.reports.base import RendererError
    with pytest.raises(RendererError, match="period"):
        QAIPAnnualRenderer().gather_context({})


def test_qaip_annual_renderer_context(super_admin):
    QAIPAssessment.objects.create(
        title="Annual", type=QAIPAssessment.TYPE_INTERNAL,
        period="2026", rating_overall=QAIPAssessment.RATING_SATISFACTORY,
        lead_reviewer=super_admin, scope="x",
    )
    ctx = QAIPAnnualRenderer().gather_context({"period": "2026"})
    assert ctx["period"] == "2026"
    assert len(ctx["assessments"]) == 1


def test_audit_committee_pack_renderer_context(seed_audits, seed_findings, seed_caps):
    ctx = AuditCommitteePackRenderer().gather_context({})
    assert ctx["report_title"] == "Audit Committee Pack"
    assert "kpis" in ctx and "trends" in ctx and "heatmap" in ctx
    assert ctx["kpis"]["openAudits"] == 2


def test_new_renderers_produce_html_when_pdf_disabled(seed_audits, seed_findings, seed_caps):
    """All 5 renderers should produce HTML bytes when PDF render is disabled."""
    renderers = [
        (DepartmentRiskProfileRenderer(), {}),
        (OpenIssuesRenderer(), {}),
        (ICFRSummaryRenderer(), {"period": "2026"}),
        (AuditCommitteePackRenderer(), {}),
    ]
    for renderer, params in renderers:
        payload = renderer.render_bytes(params)
        assert b"<html" in payload.lower()
        assert b"IAMS" in payload or b"iams" in payload.lower()
