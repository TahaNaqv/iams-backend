"""Tests for ICFR — financial-control testing + deficiency reporting.

Coverage:
  - Control CRUD with (entity, control_id) uniqueness
  - ControlTest CRUD + (control, period, test_type) uniqueness
  - Management vs auditor assessment (FR-ICFR-04) — both independent
  - Auditor assessment takes precedence in ``conclusion`` property
  - Auto-create draft DeficiencyReport on deficient auditor conclusion
  - Recording 'effective' clears tested timestamps appropriately
  - ControlException attachment + evidence_files M2M
  - DeficiencyReport open/close lifecycle + classification promotion
  - Summary aggregator (controlsByFramework, exceptionsBySeverity,
    openMaterialWeaknesses, etc.)
  - RBAC: all ICFR endpoints require view_audits
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from iams.icfr import (
    ICFRError,
    build_icfr_summary,
    close_deficiency,
    open_deficiency,
    record_test_result,
)
from iams.models import (
    Audit,
    AuditLogEntry,
    AuditableEntity,
    Control,
    ControlException,
    ControlTest,
    DeficiencyReport,
    EvidenceFile,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def entity():
    return AuditableEntity.objects.create(
        name="Accounts Payable", department="Finance", owner="o",
        risk_rating="High", status="Active",
    )


@pytest.fixture
def control(entity, super_admin):
    return Control.objects.create(
        entity=entity, control_id="AP-01",
        name="Three-way match", description="PO ↔ Receipt ↔ Invoice",
        framework=Control.FRAMEWORK_SOX,
        control_type=Control.TYPE_PREVENTIVE,
        nature=Control.NATURE_HYBRID,
        frequency=Control.FREQUENCY_TRANSACTIONAL,
        assertion="existence + accuracy",
        risk_rating="High", owner=super_admin.email,
        status=Control.STATUS_ACTIVE,
    )


@pytest.fixture
def test_design(control):
    return ControlTest.objects.create(
        control=control, period="FY2026-Q1",
        test_type=ControlTest.TEST_TYPE_DESIGN,
        planned_sample_size=25, sample_size=25,
        sample_method="random",
    )


@pytest.fixture
def test_operating(control):
    return ControlTest.objects.create(
        control=control, period="FY2026-Q1",
        test_type=ControlTest.TEST_TYPE_OPERATING,
        planned_sample_size=25, sample_size=25,
    )


@pytest.fixture
def audit_for_evidence():
    return Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date.today(), end_date=date.today() + timedelta(days=30),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )


# ══════════════════════════════════════════════════════════════════════
# Control + uniqueness
# ══════════════════════════════════════════════════════════════════════
def test_control_unique_per_entity_control_id(entity):
    Control.objects.create(
        entity=entity, control_id="X-1", name="N",
        framework="SOX", control_type="preventive",
    )
    from django.db import IntegrityError, transaction
    with pytest.raises(IntegrityError), transaction.atomic():
        Control.objects.create(
            entity=entity, control_id="X-1", name="Dup",
            framework="SOX", control_type="preventive",
        )


def test_control_same_id_allowed_on_different_entity(entity):
    Control.objects.create(
        entity=entity, control_id="X-1", name="N",
        framework="SOX", control_type="preventive",
    )
    other = AuditableEntity.objects.create(
        name="Other", department="X", owner="o", risk_rating="Low", status="Active",
    )
    # No IntegrityError
    Control.objects.create(
        entity=other, control_id="X-1", name="OK on different entity",
        framework="SOX", control_type="preventive",
    )


# ══════════════════════════════════════════════════════════════════════
# ControlTest uniqueness
# ══════════════════════════════════════════════════════════════════════
def test_test_unique_per_control_period_type(control):
    ControlTest.objects.create(
        control=control, period="FY2026-Q1",
        test_type=ControlTest.TEST_TYPE_DESIGN,
    )
    from django.db import IntegrityError, transaction
    with pytest.raises(IntegrityError), transaction.atomic():
        ControlTest.objects.create(
            control=control, period="FY2026-Q1",
            test_type=ControlTest.TEST_TYPE_DESIGN,
        )


def test_design_and_operating_coexist_for_same_period(control):
    ControlTest.objects.create(
        control=control, period="FY2026-Q1",
        test_type=ControlTest.TEST_TYPE_DESIGN,
    )
    ControlTest.objects.create(
        control=control, period="FY2026-Q1",
        test_type=ControlTest.TEST_TYPE_OPERATING,
    )
    assert control.tests.count() == 2


# ══════════════════════════════════════════════════════════════════════
# Management vs auditor assessment (FR-ICFR-04)
# ══════════════════════════════════════════════════════════════════════
def test_management_assessment_does_not_complete_test(test_design, super_admin):
    record_test_result(
        test_design, by_user=super_admin, role="management",
        conclusion="effective", notes="Reviewed all sample transactions.",
    )
    test_design.refresh_from_db()
    assert test_design.management_assessment == "effective"
    # IA hasn't tested yet → stays In Progress, NOT Completed
    assert test_design.status == ControlTest.STATUS_IN_PROGRESS
    assert test_design.completed_at is None


def test_auditor_assessment_completes_test(test_design, super_admin):
    record_test_result(
        test_design, by_user=super_admin, role="auditor",
        conclusion="effective",
    )
    test_design.refresh_from_db()
    assert test_design.auditor_assessment == "effective"
    assert test_design.status == ControlTest.STATUS_COMPLETED
    assert test_design.completed_at == date.today()


def test_conclusion_property_prefers_auditor(test_design, super_admin):
    record_test_result(
        test_design, by_user=super_admin, role="management",
        conclusion="effective",
    )
    record_test_result(
        test_design, by_user=super_admin, role="auditor",
        conclusion="deficient",
    )
    test_design.refresh_from_db()
    assert test_design.conclusion == "deficient"


def test_conclusion_falls_back_to_management_when_auditor_not_tested(
    test_design, super_admin
):
    record_test_result(
        test_design, by_user=super_admin, role="management",
        conclusion="effective",
    )
    test_design.refresh_from_db()
    assert test_design.auditor_assessment == "not_tested"
    assert test_design.conclusion == "effective"


def test_record_test_result_validates_role_and_conclusion(test_design, super_admin):
    with pytest.raises(ICFRError, match="role must"):
        record_test_result(
            test_design, by_user=super_admin, role="bogus", conclusion="effective",
        )
    with pytest.raises(ICFRError, match="conclusion must"):
        record_test_result(
            test_design, by_user=super_admin, role="auditor", conclusion="bogus",
        )


# ══════════════════════════════════════════════════════════════════════
# Auto-deficiency on failed auditor test
# ══════════════════════════════════════════════════════════════════════
def test_deficient_auditor_assessment_auto_creates_draft_deficiency(
    test_operating, super_admin
):
    assert not DeficiencyReport.objects.filter(test=test_operating).exists()
    record_test_result(
        test_operating, by_user=super_admin, role="auditor",
        conclusion="deficient", notes="Sample 7 unmatched.",
    )
    deficiency = DeficiencyReport.objects.get(test=test_operating)
    assert deficiency.status == DeficiencyReport.STATUS_DRAFT
    assert deficiency.classification == DeficiencyReport.CLASSIFICATION_CONTROL
    assert deficiency.identified_date == date.today()


def test_deficient_management_only_does_not_auto_create_deficiency(
    test_operating, super_admin
):
    """Management self-assessment of 'deficient' must NOT bypass IA
    review. Auto-deficiency requires the auditor verdict."""
    record_test_result(
        test_operating, by_user=super_admin, role="management",
        conclusion="deficient",
    )
    assert not DeficiencyReport.objects.filter(test=test_operating).exists()


def test_redundant_deficient_auditor_does_not_duplicate(
    test_operating, super_admin
):
    record_test_result(
        test_operating, by_user=super_admin, role="auditor", conclusion="deficient",
    )
    record_test_result(
        test_operating, by_user=super_admin, role="auditor", conclusion="deficient",
    )
    assert DeficiencyReport.objects.filter(test=test_operating).count() == 1


# ══════════════════════════════════════════════════════════════════════
# Deficiency lifecycle
# ══════════════════════════════════════════════════════════════════════
def test_open_deficiency_promotes_classification(test_operating, super_admin):
    record_test_result(
        test_operating, by_user=super_admin, role="auditor", conclusion="deficient",
    )
    deficiency = DeficiencyReport.objects.get(test=test_operating)
    open_deficiency(
        deficiency, by_user=super_admin,
        classification=DeficiencyReport.CLASSIFICATION_MATERIAL,
        narrative="Pervasive 3-way-match failure across Q1.",
        recommendation="Automate match in ERP.",
        target_resolution_date=date.today() + timedelta(days=60),
        owner="ap-lead@iams.test",
    )
    deficiency.refresh_from_db()
    assert deficiency.status == DeficiencyReport.STATUS_OPEN
    assert deficiency.classification == DeficiencyReport.CLASSIFICATION_MATERIAL


def test_close_deficiency_requires_open_first(test_operating, super_admin):
    record_test_result(
        test_operating, by_user=super_admin, role="auditor", conclusion="deficient",
    )
    deficiency = DeficiencyReport.objects.get(test=test_operating)
    # Draft → cannot close
    with pytest.raises(ICFRError, match="draft"):
        close_deficiency(deficiency, by_user=super_admin)
    # Open → can close
    open_deficiency(
        deficiency, by_user=super_admin,
        classification=DeficiencyReport.CLASSIFICATION_CONTROL,
    )
    close_deficiency(
        deficiency, by_user=super_admin,
        management_response="Remediated via automated ERP rule.",
    )
    deficiency.refresh_from_db()
    assert deficiency.status == DeficiencyReport.STATUS_CLOSED
    assert deficiency.actual_resolution_date == date.today()


def test_open_deficiency_validates_classification(test_operating, super_admin):
    record_test_result(
        test_operating, by_user=super_admin, role="auditor", conclusion="deficient",
    )
    deficiency = DeficiencyReport.objects.get(test=test_operating)
    with pytest.raises(ICFRError, match="classification must"):
        open_deficiency(deficiency, by_user=super_admin, classification="bogus")


# ══════════════════════════════════════════════════════════════════════
# Exceptions + evidence M2M
# ══════════════════════════════════════════════════════════════════════
def test_exception_attachment_with_evidence(test_operating, audit_for_evidence):
    evidence = EvidenceFile.objects.create(
        audit=audit_for_evidence, name="invoice-7.pdf", type="pdf",
        file=SimpleUploadedFile("i.pdf", b"x", content_type="application/pdf"),
        size_kb=1, uploaded_at="2026-01-15T09:00:00Z",
    )
    exc = ControlException.objects.create(
        test=test_operating, sample_ref="INV-7",
        description="Missing receiving doc",
        severity=ControlException.SEVERITY_HIGH,
        identified_at=date.today(),
    )
    exc.evidence_files.add(evidence)
    assert exc.evidence_files.count() == 1
    assert evidence in exc.evidence_files.all()


# ══════════════════════════════════════════════════════════════════════
# Summary aggregator
# ══════════════════════════════════════════════════════════════════════
def test_summary_counts_controls_tests_exceptions_deficiencies(
    control, test_design, test_operating, super_admin, audit_for_evidence
):
    # Build a second control on a different entity for the framework split
    other = AuditableEntity.objects.create(
        name="Treasury", department="Finance", owner="o", risk_rating="Medium", status="Active",
    )
    Control.objects.create(
        entity=other, control_id="TR-01", name="Bank rec.",
        framework=Control.FRAMEWORK_COSO, control_type=Control.TYPE_DETECTIVE,
    )

    # Test results
    record_test_result(test_design, by_user=super_admin, role="auditor", conclusion="effective")
    record_test_result(test_operating, by_user=super_admin, role="auditor", conclusion="deficient")

    # Add an exception + promote the auto-created deficiency to material
    evidence = EvidenceFile.objects.create(
        audit=audit_for_evidence, name="x.pdf", type="pdf",
        file=SimpleUploadedFile("x.pdf", b"x", content_type="application/pdf"),
        size_kb=1, uploaded_at="2026-01-15T09:00:00Z",
    )
    exc = ControlException.objects.create(
        test=test_operating, sample_ref="X",
        description="…", severity=ControlException.SEVERITY_HIGH,
        identified_at=date.today(),
    )
    exc.evidence_files.add(evidence)
    deficiency = DeficiencyReport.objects.get(test=test_operating)
    open_deficiency(
        deficiency, by_user=super_admin,
        classification=DeficiencyReport.CLASSIFICATION_MATERIAL,
    )

    summary = build_icfr_summary(period="FY2026-Q1")
    assert summary["totalControls"] == 2
    assert summary["totalTests"] == 2
    assert summary["totalExceptions"] == 1
    assert summary["totalDeficiencies"] == 1
    assert summary["openMaterialWeaknesses"] == 1
    # Frameworks
    frameworks = {row["framework"]: row["count"] for row in summary["controlsByFramework"]}
    assert frameworks["SOX"] == 1
    assert frameworks["COSO"] == 1
    # Conclusions
    by_concl = {row["conclusion"]: row["count"] for row in summary["testsByConclusion"]}
    assert by_concl.get("effective") == 1
    assert by_concl.get("deficient") == 1


def test_summary_respects_period_filter(control, super_admin):
    ControlTest.objects.create(
        control=control, period="FY2025-Q4",
        test_type=ControlTest.TEST_TYPE_DESIGN,
    )
    ControlTest.objects.create(
        control=control, period="FY2026-Q1",
        test_type=ControlTest.TEST_TYPE_DESIGN,
    )
    summary = build_icfr_summary(period="FY2026-Q1")
    assert summary["totalTests"] == 1
    summary_global = build_icfr_summary()
    assert summary_global["totalTests"] == 2


# ══════════════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════════════
def test_api_record_result_records_audit_log(
    authed_client, super_admin, test_design
):
    AuditLogEntry.objects.filter(action="other").delete()
    res = authed_client(super_admin).post(
        f"/api/icfr/tests/{test_design.id}/record-result/",
        {"role": "auditor", "conclusion": "effective", "notes": "All samples OK"},
        format="json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["auditorAssessment"] == "effective"
    assert body["status"] == "completed"
    assert AuditLogEntry.objects.filter(
        details__event="icfr_test_result_recorded"
    ).exists()


def test_api_record_result_400_on_bad_input(authed_client, super_admin, test_design):
    res = authed_client(super_admin).post(
        f"/api/icfr/tests/{test_design.id}/record-result/",
        {"role": "auditor", "conclusion": "tampered"},
        format="json",
    )
    assert res.status_code == 400


def test_api_deficiency_open_then_close(
    authed_client, super_admin, test_operating
):
    # Trigger deficiency via auditor "deficient" verdict
    authed_client(super_admin).post(
        f"/api/icfr/tests/{test_operating.id}/record-result/",
        {"role": "auditor", "conclusion": "deficient"},
        format="json",
    )
    deficiency = DeficiencyReport.objects.get(test=test_operating)
    # Open
    res1 = authed_client(super_admin).post(
        f"/api/icfr/deficiencies/{deficiency.id}/open/",
        {"classification": "significant_deficiency", "narrative": "n", "recommendation": "r"},
        format="json",
    )
    assert res1.status_code == 200, res1.content
    assert res1.json()["status"] == "open"
    assert res1.json()["classification"] == "significant_deficiency"
    # Close
    res2 = authed_client(super_admin).post(
        f"/api/icfr/deficiencies/{deficiency.id}/close/",
        {"managementResponse": "Fixed."},
        format="json",
    )
    assert res2.status_code == 200, res2.content
    assert res2.json()["status"] == "closed"


def test_api_summary_endpoint(authed_client, super_admin, control):
    body = authed_client(super_admin).get("/api/icfr/summary/").json()
    assert body["totalControls"] >= 1
    assert "controlsByFramework" in body
    assert "deficienciesByClassification" in body


def test_api_endpoints_require_view_audits(authed_client, db, roles):
    """A user without view_audits gets 403."""
    from django.contrib.auth import get_user_model
    from iams.models import Permission, Role, UserProfile
    User = get_user_model()
    p = Permission.objects.create(key="random_icfr", name="x", module="test")
    role = Role.objects.create(name="Restricted-ICFR", is_super_admin=False)
    role.permissions.set([p])
    user = User.objects.create_user(
        username="r_icfr", email="ri@iams.test", password="TestPassword123!",
    )
    UserProfile.objects.create(user=user, role=role, department="X", status="Active")
    client = authed_client(user)
    for path in [
        "/api/icfr/controls/", "/api/icfr/tests/",
        "/api/icfr/exceptions/", "/api/icfr/deficiencies/",
        "/api/icfr/summary/",
    ]:
        assert client.get(path).status_code == 403, f"{path} should be 403"
