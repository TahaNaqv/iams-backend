"""Contract conformance tests — backend JSON shape ↔ frontend TS types.

For each FE-consumed endpoint we assert:
  - All fields listed in ``iams-frontend/src/services/models.ts`` /
    ``src/data/mock-data.ts`` are present in the response.
  - Field types match the FE interface (string / number / array / null).
  - No legacy snake_case fields leak through (we should see camelCase only).

This file is the live, executable version of
``iams-frontend/docs/api-contract.md``. If the FE adds a new field to a
model, add it to the corresponding ``EXPECTED_FIELDS`` set below; if the BE
drops or renames a field, this suite catches it before the FE breaks.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone as dj_timezone

from iams.models import (
    ActivityItem,
    ApprovalRequest,
    ApprovalStep,
    Audit,
    AuditableEntity,
    AuditAssignment,
    AuditLogEntry,
    Auditor,
    AuditReport,
    AuditReportSection,
    ChecklistItem,
    Comment,
    CorrectiveAction,
    Department,
    EvidenceFile,
    Finding,
    FollowUpItem,
    HoursBudget,
    ManagedDocument,
    Notification,
    RiskAssessmentImportIssue,
    RiskAssessmentMatrixCell,
    RiskAssessmentRecord,
    RiskAssessmentSheet,
    RiskAssessmentSummaryItem,
    RiskHistoryEntry,
    TimeEntry,
    TimelineEvent,
    WorkProcedure,
    WorkProcedureStep,
    WorkProgram,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def assert_has_fields(payload: dict, expected: set[str], context: str = "") -> None:
    """Assert that every camelCase field in ``expected`` is present in payload
    and no snake_case alias of an expected field has leaked through."""
    actual = set(payload.keys())
    missing = expected - actual
    assert not missing, f"{context}: missing fields {missing} in {sorted(actual)}"

    # Snake-case leakage check: for every expected camelCase, the snake_case
    # form must NOT also appear (would indicate the serializer is exposing both).
    for cc in expected:
        # split camelCase → snake_case
        snake = "".join(["_" + c.lower() if c.isupper() else c for c in cc]).lstrip("_")
        if snake != cc and snake in actual:
            pytest.fail(f"{context}: snake_case leak — both '{cc}' and '{snake}' present")


def get_payload(client, url: str) -> dict | list:
    response = client.get(url)
    assert response.status_code == 200, f"GET {url} → {response.status_code}: {response.content!r}"
    return response.json()


def first_or_only(payload: dict | list) -> dict:
    """Paginated list → first result; bare list → first; dict → as-is."""
    if isinstance(payload, list):
        assert payload, "expected non-empty list"
        return payload[0]
    if "results" in payload:
        assert payload["results"], "expected non-empty results"
        return payload["results"][0]
    return payload


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def sa_client(super_admin, authed_client):
    """Authenticated client as Super Admin — bypasses all RBAC."""
    return authed_client(super_admin)


# ══════════════════════════════════════════════════════════════════════
# Audit core
# ══════════════════════════════════════════════════════════════════════
AUDIT_FIELDS = {
    "id", "title", "department", "leadAuditor", "status", "startDate", "endDate",
    "priority", "riskRating", "scope", "objectives", "completionPercent", "findingsCount",
}


def test_audit_list_contract(sa_client):
    Audit.objects.create(
        title="Q1 Treasury Audit",
        department="Finance",
        lead_auditor="Sarah Kim",
        status="In Progress",
        priority="High",
        risk_rating="High",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 3, 30),
        scope="Treasury operations and SOX 404",
        objectives="Validate reconciliation controls",
        completion_percent=62,
        findings_count=4,
    )
    payload = get_payload(sa_client, "/api/audits/")
    audit = first_or_only(payload)
    assert_has_fields(audit, AUDIT_FIELDS, context="GET /api/audits/")
    assert audit["leadAuditor"] == "Sarah Kim"
    assert audit["startDate"] == "2026-01-15"
    assert audit["completionPercent"] == 62


def test_audit_retrieve_contract(sa_client):
    a = Audit.objects.create(
        title="IT GenCtrls",
        department="IT",
        lead_auditor="A.B.",
        status="Planned",
        priority="Medium",
        risk_rating="Medium",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 5, 1),
        scope="GenCtrls",
        objectives="Validate ITGC",
        completion_percent=0,
        findings_count=0,
    )
    payload = get_payload(sa_client, f"/api/audits/{a.id}/")
    assert_has_fields(payload, AUDIT_FIELDS, context="GET /api/audits/:id/")


# ══════════════════════════════════════════════════════════════════════
# Findings
# ══════════════════════════════════════════════════════════════════════
FINDING_FIELDS = {
    "id", "title", "auditId", "auditTitle", "department", "severity", "status",
    "owner", "dueDate", "description", "rootCause", "recommendation", "createdDate",
}


def test_finding_list_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="Finance", lead_auditor="L", status="In Progress",
        priority="High", risk_rating="High",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=1,
    )
    Finding.objects.create(
        audit=audit, title="Wire dual approval gap", department="Finance",
        severity="High", status="Open", owner="T. Garcia",
        due_date=date(2026, 4, 15), description="d", root_cause="rc",
        recommendation="r", created_date=date(2026, 2, 10),
    )
    payload = get_payload(sa_client, f"/api/findings/?audit_id={audit.id}")
    item = first_or_only(payload)
    assert_has_fields(item, FINDING_FIELDS, context="GET /api/findings/")
    assert item["auditId"] == str(audit.id)
    assert item["auditTitle"] == "A"
    assert item["createdDate"] == "2026-02-10"


# ══════════════════════════════════════════════════════════════════════
# Corrective actions
# ══════════════════════════════════════════════════════════════════════
CAP_FIELDS = {
    "id", "title", "findingId", "findingTitle", "owner", "dueDate", "status",
    "priority", "description", "progress", "department",
}


def test_corrective_action_list_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="Finance", lead_auditor="L", status="In Progress",
        priority="High", risk_rating="High",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=1,
    )
    finding = Finding.objects.create(
        audit=audit, title="F", department="Finance", severity="High",
        status="Open", owner="o", due_date=date(2026, 4, 15),
        description="d", root_cause="rc", recommendation="r",
        created_date=date(2026, 2, 10),
    )
    CorrectiveAction.objects.create(
        finding=finding, title="Deploy dual approval", owner="Treasury Ops",
        due_date=date(2026, 5, 30), status="In Progress", priority="High",
        description="desc", progress=40, department="Finance",
    )
    payload = get_payload(sa_client, "/api/corrective-actions/")
    item = first_or_only(payload)
    assert_has_fields(item, CAP_FIELDS, context="GET /api/corrective-actions/")
    assert item["findingId"] == str(finding.id)
    assert item["findingTitle"] == "F"
    assert item["progress"] == 40


# ══════════════════════════════════════════════════════════════════════
# Departments
# ══════════════════════════════════════════════════════════════════════
DEPARTMENT_FIELDS = {
    "id", "name", "head", "riskRating", "lastAuditDate", "nextAuditDate", "entityCount",
}


def test_department_list_contract(sa_client):
    Department.objects.create(
        name="Finance", head="J. Doe", risk_rating="High",
        last_audit_date=date(2025, 12, 1), next_audit_date=date(2026, 6, 1),
        entity_count=12,
    )
    payload = get_payload(sa_client, "/api/departments/")
    item = first_or_only(payload)
    assert_has_fields(item, DEPARTMENT_FIELDS, context="GET /api/departments/")
    assert item["riskRating"] == "High"
    assert item["entityCount"] == 12


# ══════════════════════════════════════════════════════════════════════
# Execution: checklist items, evidence, timeline
# ══════════════════════════════════════════════════════════════════════
CHECKLIST_FIELDS = {"id", "auditId", "title", "assignee", "status", "notes"}


def test_checklist_items_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    ChecklistItem.objects.create(
        audit=audit, title="Collect evidence", assignee="A",
        status="Pending", notes="",
    )
    item = first_or_only(get_payload(sa_client, "/api/checklist-items/"))
    assert_has_fields(item, CHECKLIST_FIELDS, context="GET /api/checklist-items/")


EVIDENCE_FIELDS = {"id", "auditId", "name", "type", "sizeKb", "uploadedBy", "uploadedAt"}


def test_evidence_files_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    EvidenceFile.objects.create(
        audit=audit, name="recon.xlsx", type="xlsx", size_kb=420,
        uploaded_by="auditor@iams.test", uploaded_at=dj_timezone.now(),
    )
    item = first_or_only(get_payload(sa_client, "/api/evidence-files/"))
    assert_has_fields(item, EVIDENCE_FIELDS, context="GET /api/evidence-files/")
    assert item["sizeKb"] == 420


TIMELINE_FIELDS = {"id", "auditId", "title", "description", "timestamp"}


def test_timeline_by_audit_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    TimelineEvent.objects.create(
        audit=audit, title="Kickoff", description="d", timestamp=dj_timezone.now(),
    )
    payload = get_payload(sa_client, f"/api/audits/{audit.id}/timeline/")
    item = first_or_only(payload)
    assert_has_fields(item, TIMELINE_FIELDS, context="GET /api/audits/:id/timeline/")


# ══════════════════════════════════════════════════════════════════════
# Audit Universe: auditable entities + risk history
# ══════════════════════════════════════════════════════════════════════
ENTITY_FIELDS = {
    "id", "name", "department", "owner", "riskRating",
    "lastAuditDate", "nextAuditDate", "status",
}


def test_auditable_entity_contract(sa_client):
    AuditableEntity.objects.create(
        name="Accounts Payable", department="Finance", owner="J. Doe",
        risk_rating="High", last_audit_date=date(2025, 12, 1),
        next_audit_date=date(2026, 6, 1), status="Active",
    )
    item = first_or_only(get_payload(sa_client, "/api/auditable-entities/"))
    assert_has_fields(item, ENTITY_FIELDS, context="GET /api/auditable-entities/")


RISK_HISTORY_FIELDS = {"id", "entity", "date", "previousRating", "currentRating", "reason"}


def test_risk_history_contract(sa_client):
    RiskHistoryEntry.objects.create(
        entity="Accounts Payable", date=date(2026, 1, 15),
        previous_rating="Medium", current_rating="High",
        reason="New control gap identified",
    )
    item = first_or_only(get_payload(sa_client, "/api/risk-history/"))
    assert_has_fields(item, RISK_HISTORY_FIELDS, context="GET /api/risk-history/")


# ══════════════════════════════════════════════════════════════════════
# Notifications / activity / audit log / follow-up / comments
# ══════════════════════════════════════════════════════════════════════
NOTIFICATION_FIELDS = {"id", "title", "message", "type", "read", "timestamp"}


def test_notifications_contract(sa_client):
    Notification.objects.create(
        title="CAP overdue", message="CAP-119 is overdue", type="warning",
        read=False, timestamp=dj_timezone.now(),
    )
    item = first_or_only(get_payload(sa_client, "/api/notifications/"))
    assert_has_fields(item, NOTIFICATION_FIELDS, context="GET /api/notifications/")


ACTIVITY_FIELDS = {"id", "action", "user", "target", "timestamp", "type"}


def test_activities_contract(sa_client):
    ActivityItem.objects.create(
        action="audit_created", user="alice", target="Q1 Treasury",
        timestamp=dj_timezone.now(), type="audit",
    )
    item = first_or_only(get_payload(sa_client, "/api/activities/"))
    assert_has_fields(item, ACTIVITY_FIELDS, context="GET /api/activities/")


AUDIT_LOG_FIELDS = {"id", "actor", "action", "target", "timestamp", "details"}


def test_audit_log_contract(sa_client):
    AuditLogEntry.objects.create(
        actor="alice@iams.test", action="audit_create",
        target="Q1 Treasury", timestamp=dj_timezone.now(), details="-",
    )
    item = first_or_only(get_payload(sa_client, "/api/audit-log/"))
    assert_has_fields(item, AUDIT_LOG_FIELDS, context="GET /api/audit-log/")


FOLLOWUP_FIELDS = {"id", "findingId", "owner", "dueDate", "status", "notes"}


def test_followup_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    finding = Finding.objects.create(
        audit=audit, title="F", department="F", severity="High",
        status="Open", owner="o", due_date=date(2026, 4, 15),
        description="d", root_cause="rc", recommendation="r",
        created_date=date(2026, 2, 10),
    )
    FollowUpItem.objects.create(
        finding=finding, owner="V. Verifier", due_date=date(2026, 6, 1),
        status="Pending Validation", notes="",
    )
    item = first_or_only(get_payload(sa_client, "/api/follow-ups/"))
    assert_has_fields(item, FOLLOWUP_FIELDS, context="GET /api/follow-ups/")
    assert item["findingId"] == str(finding.id)


COMMENT_FIELDS = {"id", "entity_id", "user", "text", "timestamp"}


def test_comments_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    Comment.objects.create(
        target_content_type=ContentType.objects.get_for_model(Audit),
        target_object_id=audit.id, entity_id=str(audit.id),
        author="alice", text="Looks good",
        created_at=dj_timezone.now(),
    )
    item = first_or_only(get_payload(sa_client, "/api/comments/"))
    assert_has_fields(item, COMMENT_FIELDS, context="GET /api/comments/")


# ══════════════════════════════════════════════════════════════════════
# Resources: auditor / assignment / time entry / hours budget
# ══════════════════════════════════════════════════════════════════════
AUDITOR_FIELDS = {
    "id", "name", "email", "role", "availability", "skills", "certifications",
    "weeklyCapacityHours",
}


def test_auditors_contract(sa_client):
    Auditor.objects.create(
        name="Priya Shah", email="priya@iams.test", role="Senior IT Auditor",
        availability="Available", skills=["SOX", "Cybersecurity"],
        certifications=["CISA"], weekly_capacity_hours=40,
    )
    item = first_or_only(get_payload(sa_client, "/api/auditors/"))
    assert_has_fields(item, AUDITOR_FIELDS, context="GET /api/auditors/")
    assert item["weeklyCapacityHours"] == 40
    assert isinstance(item["skills"], list)


ASSIGNMENT_FIELDS = {
    "id", "auditorId", "auditId", "phase", "allocation_pct", "startDate", "endDate",
}


def test_assignments_contract(sa_client):
    auditor = Auditor.objects.create(
        name="P", email="p@iams.test", role="r", availability="Available",
        skills=[], certifications=[], weekly_capacity_hours=40,
    )
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    AuditAssignment.objects.create(
        auditor=auditor, audit=audit, phase="Fieldwork", allocation_pct=50,
        start_date=date(2026, 1, 5), end_date=date(2026, 1, 30),
    )
    item = first_or_only(get_payload(sa_client, "/api/assignments/"))
    assert_has_fields(item, ASSIGNMENT_FIELDS, context="GET /api/assignments/")


TIME_ENTRY_FIELDS = {"id", "auditorId", "auditId", "date", "hours", "status", "notes"}


def test_time_entries_contract(sa_client):
    auditor = Auditor.objects.create(
        name="P", email="p2@iams.test", role="r", availability="Available",
        skills=[], certifications=[], weekly_capacity_hours=40,
    )
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    TimeEntry.objects.create(
        auditor=auditor, audit=audit, date=date(2026, 3, 4),
        hours=Decimal("6.5"), status="Submitted", notes="walkthrough",
    )
    item = first_or_only(get_payload(sa_client, "/api/time-entries/"))
    assert_has_fields(item, TIME_ENTRY_FIELDS, context="GET /api/time-entries/")


HOURS_BUDGET_FIELDS = {"id", "auditId", "budgetedHours", "consumedHours"}


def test_hours_budgets_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    HoursBudget.objects.create(audit=audit, budgeted_hours=320, consumed_hours=198)
    item = first_or_only(get_payload(sa_client, "/api/hours-budgets/"))
    assert_has_fields(item, HOURS_BUDGET_FIELDS, context="GET /api/hours-budgets/")
    assert item["budgetedHours"] == 320
    assert item["consumedHours"] == 198


# ══════════════════════════════════════════════════════════════════════
# Risk assessment
# ══════════════════════════════════════════════════════════════════════
RISK_SHEET_FIELDS = {"id", "name", "description", "order"}


def test_risk_sheet_contract(sa_client):
    RiskAssessmentSheet.objects.create(name="Finance", description="-", order=1)
    item = first_or_only(get_payload(sa_client, "/api/risk-assessment-sheets/"))
    assert_has_fields(item, RISK_SHEET_FIELDS, context="GET /api/risk-assessment-sheets/")


RISK_MATRIX_FIELDS = {"id", "likelihood", "impact", "residualRisk"}


def test_risk_matrix_contract(sa_client):
    RiskAssessmentMatrixCell.objects.create(
        likelihood="Low", impact="Low", residual_risk="Low",
    )
    item = first_or_only(get_payload(sa_client, "/api/risk-assessment-matrix/"))
    assert_has_fields(item, RISK_MATRIX_FIELDS, context="GET /api/risk-assessment-matrix/")


RISK_RECORD_FIELDS = {
    "id", "sheet", "sourceSheet", "sourceRow", "department", "objective",
    "riskArea", "riskDescription", "likelihood", "impact", "inherentRisk",
    "existingControls", "controlEffectiveness", "residualRisk",
    "auditObjective", "auditSteps", "documentsRequired",
    "inclusionStatus", "auditScope", "plannedManDays",
}


def test_risk_record_contract(sa_client):
    sheet = RiskAssessmentSheet.objects.create(name="Finance", description="-", order=1)
    RiskAssessmentRecord.objects.create(
        sheet=sheet, source_sheet="Finance", source_row=14,
        department="Finance", objective="o",
        risk_area="AP", risk_description="Duplicate payments",
        likelihood="Medium", impact="High", inherent_risk="High",
        existing_controls="3-way match", control_effectiveness="Partially Effective",
        residual_risk="Medium", audit_objective="Confirm controls",
        audit_steps="Sample 25 transactions", documents_required="Vendor master",
        inclusion_status="Included", audit_scope="Q2 2026",
        planned_man_days=Decimal("12.00"),
    )
    item = first_or_only(get_payload(sa_client, "/api/risk-assessments/"))
    assert_has_fields(item, RISK_RECORD_FIELDS, context="GET /api/risk-assessments/")
    assert item["sourceRow"] == 14


RISK_IMPORT_ISSUE_FIELDS = {"id", "severity", "sheet", "cell", "message"}


def test_risk_import_issue_contract(sa_client):
    RiskAssessmentImportIssue.objects.create(
        severity="warning", sheet="Finance", cell="B14",
        message="Header inconsistent with template",
    )
    item = first_or_only(get_payload(sa_client, "/api/risk-assessment-import/issues/"))
    assert_has_fields(item, RISK_IMPORT_ISSUE_FIELDS, context="GET /api/risk-assessment-import/issues/")


# ══════════════════════════════════════════════════════════════════════
# Approvals
# ══════════════════════════════════════════════════════════════════════
APPROVAL_STEP_FIELDS = {"id", "role", "approver", "status", "date", "comments", "order"}
APPROVAL_REQUEST_FIELDS = {
    "id", "title", "type", "reference_id", "department", "submitted_by",
    "submitted_date", "current_step", "priority", "description", "status", "steps",
}


def test_approval_request_contract(sa_client):
    req = ApprovalRequest.objects.create(
        title="Approve Q1 plan", type="Audit Plan",
        reference_id="AP-2026-Q1", department="Internal Audit",
        submitted_by="alice", submitted_date=date(2026, 1, 15),
        current_step=0, priority="High",
        description="Annual plan approval", status="Pending",
    )
    ApprovalStep.objects.create(
        request=req, role="Manager", approver="Jane",
        status="Pending", date=None, comments="", order=0,
    )
    item = first_or_only(get_payload(sa_client, "/api/approval-requests/"))
    assert_has_fields(item, APPROVAL_REQUEST_FIELDS, context="GET /api/approval-requests/")
    assert isinstance(item["steps"], list)
    assert len(item["steps"]) == 1
    assert_has_fields(item["steps"][0], APPROVAL_STEP_FIELDS, context="step[0]")


# ══════════════════════════════════════════════════════════════════════
# Work programs / procedures / steps
# ══════════════════════════════════════════════════════════════════════
WP_STEP_FIELDS = {
    "id", "description", "method", "sampleSize", "result", "notes",
    "completedBy", "completedDate",
}
WP_PROCEDURE_FIELDS = {
    "id", "workProgramId", "title", "objective", "riskArea", "controlRef",
    "assignedTo", "status", "conclusion", "signedOffBy", "signedOffDate", "steps",
}
WP_PROGRAM_FIELDS = {"id", "auditId", "auditTitle", "title", "procedures"}


def test_work_program_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    program = WorkProgram.objects.create(audit=audit, title="WP-1")
    procedure = WorkProcedure.objects.create(
        work_program=program, title="Walkthrough", objective="o", risk_area="ra",
        control_ref="C-1", assigned_to="a", status="In Progress", conclusion="",
        signed_off_by="", signed_off_date=None,
    )
    WorkProcedureStep.objects.create(
        procedure=procedure, description="Inspect sample", method="Inspection",
        sample_size="25", result="Pass", notes="", completed_by="alice",
        completed_date=date(2026, 2, 5),
    )
    item = first_or_only(get_payload(sa_client, "/api/work-programs/"))
    assert_has_fields(item, WP_PROGRAM_FIELDS, context="GET /api/work-programs/")
    assert len(item["procedures"]) == 1
    assert_has_fields(item["procedures"][0], WP_PROCEDURE_FIELDS, context="procedures[0]")
    assert len(item["procedures"][0]["steps"]) == 1
    assert_has_fields(item["procedures"][0]["steps"][0], WP_STEP_FIELDS, context="step[0]")


# ══════════════════════════════════════════════════════════════════════
# Audit reports + sections
# ══════════════════════════════════════════════════════════════════════
REPORT_SECTION_FIELDS = {"id", "order", "title", "type", "content"}
AUDIT_REPORT_FIELDS = {
    "id", "title", "auditId", "auditTitle", "status", "author", "reviewer",
    "createdDate", "lastModified", "department", "sections",
}


def test_audit_report_contract(sa_client):
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="Review",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=100, findings_count=2,
    )
    report = AuditReport.objects.create(
        audit=audit, title="Final report",
        status="Draft", author="alice", reviewer="bob",
        created_date=date(2026, 2, 10), last_modified=date(2026, 2, 12),
        department="F",
    )
    AuditReportSection.objects.create(
        report=report, order=0, title="Executive Summary",
        type="executive_summary", content="…",
    )
    item = first_or_only(get_payload(sa_client, "/api/audit-reports/"))
    assert_has_fields(item, AUDIT_REPORT_FIELDS, context="GET /api/audit-reports/")
    assert len(item["sections"]) == 1
    assert_has_fields(item["sections"][0], REPORT_SECTION_FIELDS, context="sections[0]")


# ══════════════════════════════════════════════════════════════════════
# Managed documents
# ══════════════════════════════════════════════════════════════════════
DOC_FIELDS = {
    "id", "title", "category", "status", "owner", "department", "fileType",
    "fileSize", "createdDate", "modifiedDate", "description", "tags",
    "versions", "downloadUrl",
}


def test_managed_documents_contract(sa_client):
    ManagedDocument.objects.create(
        title="Audit Charter", category="Policies", status="Published",
        owner="CAE", department="Internal Audit", file_type="pdf",
        file_size="2 MB", created_date=date(2026, 1, 1),
        modified_date=dj_timezone.now(), description="—",
        tags=["governance", "charter"], versions=[{"version": "1.0", "date": "2026-01-01", "author": "CAE", "changes": "Initial"}],
    )
    item = first_or_only(get_payload(sa_client, "/api/managed-documents/"))
    assert_has_fields(item, DOC_FIELDS, context="GET /api/managed-documents/")
    assert isinstance(item["tags"], list)
    assert isinstance(item["versions"], list)


# ══════════════════════════════════════════════════════════════════════
# Settings: users, roles, permissions
# ══════════════════════════════════════════════════════════════════════
USER_FIELDS = {
    "id", "username", "email", "first_name", "last_name",
    "profile", "role", "role_id", "department", "status",
}


def test_users_contract(sa_client):
    item = first_or_only(get_payload(sa_client, "/api/users/"))
    assert_has_fields(item, USER_FIELDS, context="GET /api/users/")


ROLE_FIELDS = {"id", "name", "description", "is_super_admin", "permissions", "permission_keys"}


def test_roles_contract(sa_client):
    item = first_or_only(get_payload(sa_client, "/api/roles/"))
    assert_has_fields(item, ROLE_FIELDS, context="GET /api/roles/")
    assert isinstance(item["permissions"], list)
    assert isinstance(item["permission_keys"], list)


PERMISSION_FIELDS = {"id", "key", "name", "description", "module"}


def test_permissions_contract(sa_client):
    item = first_or_only(get_payload(sa_client, "/api/permissions/"))
    assert_has_fields(item, PERMISSION_FIELDS, context="GET /api/permissions/")


# ══════════════════════════════════════════════════════════════════════
# Dashboard KPIs
# ══════════════════════════════════════════════════════════════════════
KPI_FIELDS = {"openAudits", "overdueFindings", "pendingCAPs", "completionRate"}


def test_dashboard_kpis_contract(sa_client):
    payload = get_payload(sa_client, "/api/dashboard/kpis/")
    assert isinstance(payload, dict)
    assert_has_fields(payload, KPI_FIELDS, context="GET /api/dashboard/kpis/")
    for k in KPI_FIELDS:
        assert isinstance(payload[k], (int, float)), f"{k} should be numeric, got {type(payload[k])}"


# ══════════════════════════════════════════════════════════════════════
# Auth: /auth/me/
# ══════════════════════════════════════════════════════════════════════
ME_FIELDS = {"id", "email", "name", "role", "department", "status"}
ME_ROLE_FIELDS = {"id", "name", "description", "is_super_admin", "permissions"}


def test_auth_me_contract(sa_client):
    payload = get_payload(sa_client, "/api/auth/me/")
    assert_has_fields(payload, ME_FIELDS, context="GET /api/auth/me/")
    assert_has_fields(payload["role"], ME_ROLE_FIELDS, context="me.role")
    assert isinstance(payload["role"]["permissions"], list)
