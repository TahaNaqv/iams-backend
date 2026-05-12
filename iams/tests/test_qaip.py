"""Tests for the QAIP (Quality Assurance & Improvement Program) module.

Coverage:
  - QAIPAssessment CRUD + nested-findings serialisation
  - QAIPFinding CRUD scoped by assessment
  - StakeholderSurvey: anonymity scrubbing on save + on serialisation,
    DB check constraint on satisfaction_score 1-5
  - AuditKPI: computed variance + favorable, uniqueness on
    (kpi_type, period)
  - Dashboard endpoint math: counts, averages, latest-period fallback
  - RBAC gating: view_reports required
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone as dj_timezone

from iams.models import (
    Audit,
    AuditKPI,
    QAIPAssessment,
    QAIPFinding,
    StakeholderSurvey,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def audit():
    return Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="Completed",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=100, findings_count=0,
    )


@pytest.fixture
def assessment(audit_manager):
    return QAIPAssessment.objects.create(
        title="2026 Internal QA Review",
        type=QAIPAssessment.TYPE_INTERNAL,
        period="2026",
        lead_reviewer=audit_manager,
        status=QAIPAssessment.STATUS_IN_PROGRESS,
        scope="Methodology + working-paper review",
        methodology="Sample-based review of 10 audits",
    )


# ══════════════════════════════════════════════════════════════════════
# QAIPAssessment + QAIPFinding
# ══════════════════════════════════════════════════════════════════════
def test_assessment_list_returns_camelcase_payload(authed_client, super_admin, assessment):
    body = authed_client(super_admin).get("/api/qaip/assessments/").json()
    rows = body["results"] if isinstance(body, dict) else body
    item = rows[0]
    assert item["type"] == "internal"
    assert item["period"] == "2026"
    assert item["leadReviewerName"] is not None
    assert "findingsCount" in item
    assert item["findingsCount"] == 0


def test_assessment_filterable_by_type_and_status(authed_client, super_admin, audit_manager):
    QAIPAssessment.objects.create(
        title="Internal", type="internal", period="2026",
        lead_reviewer=audit_manager, status="completed",
    )
    QAIPAssessment.objects.create(
        title="External", type="external", period="2026",
        lead_reviewer=audit_manager, status="planned",
    )
    c = authed_client(super_admin)
    body = c.get("/api/qaip/assessments/?type=external").json()
    rows = body["results"] if isinstance(body, dict) else body
    types = {r["type"] for r in rows}
    assert types == {"external"}

    body2 = c.get("/api/qaip/assessments/?status=planned").json()
    rows2 = body2["results"] if isinstance(body2, dict) else body2
    statuses = {r["status"] for r in rows2}
    assert statuses == {"planned"}


def test_finding_nested_count_in_assessment(authed_client, super_admin, assessment):
    QAIPFinding.objects.create(
        assessment=assessment, title="Documentation gap",
        description="…", rating="high", recommendation="Update template",
    )
    QAIPFinding.objects.create(
        assessment=assessment, title="Closed item",
        description="…", rating="low", status="closed",
    )
    body = authed_client(super_admin).get(f"/api/qaip/assessments/{assessment.id}/").json()
    assert body["findingsCount"] == 2
    assert body["openFindingsCount"] == 1
    assert len(body["findings"]) == 2


def test_finding_create_via_api(authed_client, super_admin, assessment):
    res = authed_client(super_admin).post(
        "/api/qaip/findings/",
        {
            "assessmentId": str(assessment.id),
            "title": "Working-paper quality",
            "description": "Sample-based review found inconsistent sign-off.",
            "rating": "medium",
            "recommendation": "Adopt standard sign-off template",
            "owner": "audit-manager@iams.test",
            "dueDate": str(date.today() + timedelta(days=30)),
        },
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["rating"] == "medium"
    assert body["status"] == "open"


def test_finding_filter_by_assessment_id(authed_client, super_admin, assessment, audit_manager):
    other = QAIPAssessment.objects.create(
        title="Other", type="external", period="2025",
        lead_reviewer=audit_manager, status="completed",
    )
    QAIPFinding.objects.create(assessment=assessment, title="A", rating="low")
    QAIPFinding.objects.create(assessment=other, title="B", rating="low")
    body = authed_client(super_admin).get(
        f"/api/qaip/findings/?assessment_id={assessment.id}"
    ).json()
    rows = body["results"] if isinstance(body, dict) else body
    titles = {r["title"] for r in rows}
    assert titles == {"A"}


# ══════════════════════════════════════════════════════════════════════
# StakeholderSurvey
# ══════════════════════════════════════════════════════════════════════
def test_survey_anonymous_scrubs_respondent_on_save(audit, auditor_user):
    survey = StakeholderSurvey.objects.create(
        audit=audit,
        respondent_role="auditee",
        respondent=auditor_user,
        satisfaction_score=4,
        feedback="Great team.",
        anonymous=True,
        submitted_at=dj_timezone.now(),
    )
    survey.refresh_from_db()
    assert survey.respondent is None  # model save() cleared it
    assert survey.anonymous is True


def test_survey_anonymous_hides_respondent_in_serializer(
    authed_client, super_admin, audit, auditor_user
):
    """Even if the DB row somehow has a respondent for an anonymous
    survey (legacy import), the serializer must not leak the FK."""
    # Bypass save() by going through .update() to plant a bad row
    survey = StakeholderSurvey.objects.create(
        audit=audit, respondent_role="auditee",
        respondent=None, anonymous=True,
        satisfaction_score=5, submitted_at=dj_timezone.now(),
    )
    StakeholderSurvey.objects.filter(pk=survey.pk).update(respondent=auditor_user)
    body = authed_client(super_admin).get(f"/api/qaip/surveys/{survey.id}/").json()
    assert body["respondentId"] is None


def test_survey_db_check_constraint_blocks_out_of_range(audit):
    """The Q-based check constraint must reject 0 and 6."""
    from django.db import transaction
    for bad in (0, 6, 99):
        # Each failed INSERT pollutes the test transaction; wrap each in
        # its own atomic block so we can keep trying.
        with pytest.raises(IntegrityError), transaction.atomic():
            StakeholderSurvey.objects.create(
                audit=audit, respondent_role="auditee",
                satisfaction_score=bad,
                submitted_at=dj_timezone.now(),
            )


def test_survey_serializer_rejects_out_of_range_at_validation(
    authed_client, super_admin, audit
):
    res = authed_client(super_admin).post(
        "/api/qaip/surveys/",
        {
            "auditId": str(audit.id),
            "respondentRole": "auditee",
            "satisfactionScore": 10,  # invalid
            "submittedAt": dj_timezone.now().isoformat(),
        },
        format="json",
    )
    assert res.status_code == 400
    body = res.json()
    # Serializer-level range check fires before the DB check.
    assert "satisfactionScore" in body


def test_survey_filter_by_audit_and_role(authed_client, super_admin, audit):
    other_audit = Audit.objects.create(
        title="X", department="X", lead_auditor="L", status="Completed",
        priority="Low", risk_rating="Low",
        start_date=date.today(), end_date=date.today() + timedelta(days=10),
        scope="s", objectives="o", completion_percent=100, findings_count=0,
    )
    StakeholderSurvey.objects.create(
        audit=audit, respondent_role="auditee",
        satisfaction_score=4, submitted_at=dj_timezone.now(),
    )
    StakeholderSurvey.objects.create(
        audit=other_audit, respondent_role="executive",
        satisfaction_score=5, submitted_at=dj_timezone.now(),
    )
    c = authed_client(super_admin)
    body = c.get(f"/api/qaip/surveys/?audit_id={audit.id}").json()
    rows = body["results"] if isinstance(body, dict) else body
    assert len(rows) == 1
    assert rows[0]["respondentRole"] == "auditee"

    body2 = c.get("/api/qaip/surveys/?respondent_role=executive").json()
    rows2 = body2["results"] if isinstance(body2, dict) else body2
    assert all(r["respondentRole"] == "executive" for r in rows2)


# ══════════════════════════════════════════════════════════════════════
# AuditKPI
# ══════════════════════════════════════════════════════════════════════
def test_kpi_variance_and_favorable_higher_is_better():
    k = AuditKPI(
        kpi_type="coverage", period="2026-Q1",
        target=Decimal("80"), actual=Decimal("85"),
        direction=AuditKPI.HIGHER_IS_BETTER,
    )
    assert k.variance == Decimal("5")
    assert k.variance_is_favorable is True


def test_kpi_variance_and_favorable_lower_is_better():
    k = AuditKPI(
        kpi_type="report_cycle_days", period="2026-Q1",
        target=Decimal("30"), actual=Decimal("25"),
        direction=AuditKPI.LOWER_IS_BETTER,
    )
    assert k.variance == Decimal("-5")
    assert k.variance_is_favorable is True


def test_kpi_zero_variance_is_favorable():
    k = AuditKPI(
        kpi_type="quality", period="2026-Q1",
        target=Decimal("90"), actual=Decimal("90"),
        direction=AuditKPI.HIGHER_IS_BETTER,
    )
    assert k.variance == 0
    assert k.variance_is_favorable is True


def test_kpi_unique_per_type_period():
    AuditKPI.objects.create(
        kpi_type="coverage", period="2026-Q1",
        target=Decimal("80"), actual=Decimal("85"),
    )
    with pytest.raises(IntegrityError):
        AuditKPI.objects.create(
            kpi_type="coverage", period="2026-Q1",
            target=Decimal("90"), actual=Decimal("85"),
        )


def test_kpi_api_emits_variance_and_favorable(authed_client, super_admin):
    AuditKPI.objects.create(
        kpi_type="timeliness", period="2026-Q1",
        target=Decimal("95.00"), actual=Decimal("88.50"),
        unit="%", direction=AuditKPI.HIGHER_IS_BETTER,
    )
    body = authed_client(super_admin).get("/api/qaip/kpis/").json()
    rows = body["results"] if isinstance(body, dict) else body
    # DRF serializes Decimal as a numeric (float) value in JSON by default.
    assert float(rows[0]["variance"]) == pytest.approx(-6.5)
    assert rows[0]["favorable"] is False


# ══════════════════════════════════════════════════════════════════════
# Dashboard
# ══════════════════════════════════════════════════════════════════════
def test_dashboard_aggregates_assessments_findings_surveys_kpis(
    authed_client, super_admin, audit_manager, audit
):
    a1 = QAIPAssessment.objects.create(
        title="Internal Q1", type="internal", period="2026",
        lead_reviewer=audit_manager, status="completed",
    )
    QAIPAssessment.objects.create(
        title="External", type="external", period="2026",
        lead_reviewer=audit_manager, status="planned",
    )
    QAIPFinding.objects.create(assessment=a1, title="Critical X", rating="critical")
    QAIPFinding.objects.create(assessment=a1, title="Closed Y", rating="low", status="closed")
    StakeholderSurvey.objects.create(
        audit=audit, respondent_role="auditee",
        satisfaction_score=5, submitted_at=dj_timezone.now(),
    )
    StakeholderSurvey.objects.create(
        audit=audit, respondent_role="auditee",
        satisfaction_score=3, submitted_at=dj_timezone.now(),
    )
    AuditKPI.objects.create(
        kpi_type="coverage", period="2026-Q1",
        target=Decimal("80"), actual=Decimal("85"),
    )

    body = authed_client(super_admin).get("/api/qaip/dashboard/").json()
    types_counted = {row["type"]: row["count"] for row in body["assessmentsByType"]}
    assert types_counted["internal"] == 1
    assert types_counted["external"] == 1
    assert body["openQaipFindings"] == 1
    assert body["criticalQaipFindings"] == 1
    assert body["avgSatisfaction"] == 4.0
    assert body["surveyResponseCount"] == 2
    # Latest-period fallback for KPIs
    kpi_kinds = {k["kpiType"] for k in body["kpis"]}
    assert "coverage" in kpi_kinds


def test_dashboard_respects_period_filter(authed_client, super_admin, audit_manager):
    QAIPAssessment.objects.create(
        title="A", type="internal", period="2025", lead_reviewer=audit_manager,
    )
    QAIPAssessment.objects.create(
        title="B", type="internal", period="2026", lead_reviewer=audit_manager,
    )
    body = authed_client(super_admin).get("/api/qaip/dashboard/?period=2026").json()
    by_type = {row["type"]: row["count"] for row in body["assessmentsByType"]}
    assert by_type.get("internal") == 1


# ══════════════════════════════════════════════════════════════════════
# RBAC: read needs view_reports
# ══════════════════════════════════════════════════════════════════════
def test_qaip_endpoints_require_view_reports(authed_client, db, roles):
    """A user without view_reports must get 403 on QAIP reads."""
    # ``Department Head`` from conftest fixture lacks view_reports? Let me check:
    # ROLE_DEFINITIONS["Department Head"] = ["view_audits", "view_reports"]
    # → does have view_reports. We need a user without it.
    from django.contrib.auth import get_user_model
    from iams.models import Permission, Role, UserProfile

    User = get_user_model()
    # Build a Restricted role with no permissions
    p = Permission.objects.create(key="random_perm", name="random_perm", module="test")
    restricted = Role.objects.create(name="Restricted-QAIP", is_super_admin=False)
    restricted.permissions.set([p])
    user = User.objects.create_user(
        username="r_qaip", email="rq@iams.test", password="TestPassword123!",
    )
    UserProfile.objects.create(user=user, role=restricted, department="X", status="Active")

    client = authed_client(user)
    for path in [
        "/api/qaip/assessments/", "/api/qaip/findings/",
        "/api/qaip/surveys/", "/api/qaip/kpis/",
        "/api/qaip/dashboard/",
    ]:
        res = client.get(path)
        assert res.status_code == 403, f"{path} should be 403, got {res.status_code}"
