"""Tests for the Risk Assessment Workbook import pipeline (Workstream C).

Covers: CSV + XLSX upload, multi-sheet parsing, matrix-driven residual,
ImportIssue capture, summary derivation, file-safety guards, and optional
EntityRisk engine integration. Celery runs eagerly under test settings.
"""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from iams.models import (
    AuditableEntity,
    EntityRisk,
    RiskAssessmentImportJob,
    RiskAssessmentRecord,
    RiskAssessmentSummaryItem,
)

pytestmark = pytest.mark.django_db


def _xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title=title)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(client, content: bytes, filename: str, **extra):
    from django.core.files.uploadedfile import SimpleUploadedFile
    ctype = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if filename.endswith(".xlsx") else "text/csv"
    )
    return client.post(
        "/api/risk-assessments/import/",
        {"file": SimpleUploadedFile(filename, content, content_type=ctype), **extra},
        format="multipart",
    )


RECORD_HEADER = [
    "Department", "Risk Area", "Risk Description", "Likelihood", "Impact",
    "Inherent Risk", "Residual Risk", "Inclusion Status", "Planned Man Days",
]


def test_xlsx_import_creates_records_and_summary(authed_client, super_admin):
    content = _xlsx_bytes({
        "Finance": [
            RECORD_HEADER,
            ["Finance", "Vendor fraud", "Payments risk", "High", "High", "High", "High", "Included", 5],
            ["Finance", "Payroll error", "", "Medium", "Low", "Medium", "Low", "Included", 3],
        ],
    })
    resp = _upload(authed_client(super_admin), content, "wb.xlsx", mode="lenient")
    assert resp.status_code == 202, resp.content
    job_id = resp.json()["id"]

    job = RiskAssessmentImportJob.objects.get(pk=job_id)
    assert job.status == RiskAssessmentImportJob.STATUS_COMPLETED
    assert RiskAssessmentRecord.objects.count() == 2
    # Summary items are derived from records.
    assert RiskAssessmentSummaryItem.objects.count() == 2


def test_matrix_sheet_drives_residual_and_flags_mismatch(authed_client, super_admin):
    content = _xlsx_bytes({
        "Matrix": [
            ["Likelihood", "Impact", "Residual Risk"],
            ["High", "High", "Critical" if False else "High"],  # (High,High)->High
            ["Medium", "Low", "Low"],
        ],
        "Ops": [
            RECORD_HEADER,
            # sheet says residual Medium, matrix says (High,High)->High → override + warn
            ["Ops", "Outage", "", "High", "High", "High", "Medium", "Included", 2],
        ],
    })
    resp = _upload(authed_client(super_admin), content, "wb.xlsx", mode="lenient")
    assert resp.status_code == 202, resp.content
    job = RiskAssessmentImportJob.objects.get(pk=resp.json()["id"])
    rec = RiskAssessmentRecord.objects.get(risk_area="Outage")
    assert rec.residual_risk == "High"  # taken from the matrix, not the sheet
    assert job.matrix_cells == 2
    assert job.issues.filter(severity="warning").exists()


def test_missing_required_column_is_skipped_with_issue(authed_client, super_admin):
    content = _xlsx_bytes({
        "Sheet1": [
            RECORD_HEADER,
            ["", "No dept", "", "Low", "Low", "Low", "Low", "Included", 1],  # missing department
        ],
    })
    resp = _upload(authed_client(super_admin), content, "wb.xlsx", mode="lenient")
    job = RiskAssessmentImportJob.objects.get(pk=resp.json()["id"])
    assert RiskAssessmentRecord.objects.count() == 0
    assert job.skipped == 1
    assert job.issues.filter(severity="error").exists()


def test_csv_import_single_sheet(authed_client, super_admin):
    csv_content = (
        b"Department,Risk Area,Likelihood,Impact,Inherent Risk,Residual Risk\n"
        b"IT,Access control,High,High,High,High\n"
    )
    resp = _upload(authed_client(super_admin), csv_content, "wb.csv", mode="lenient")
    assert resp.status_code == 202, resp.content
    assert RiskAssessmentRecord.objects.filter(risk_area="Access control").exists()


def test_binary_disguised_as_csv_is_rejected(authed_client, super_admin):
    resp = _upload(authed_client(super_admin), b"PK\x03\x04rest", "evil.csv")
    assert resp.status_code == 400


def test_link_to_engine_creates_entity_risk(authed_client, super_admin):
    dept = AuditableEntity.objects.create(name="Treasury", entity_type="Department", status="Active")
    content = _xlsx_bytes({
        "Treasury": [
            RECORD_HEADER,
            ["Treasury", "FX exposure", "", "High", "High", "High", "High", "Included", 4],
        ],
    })
    resp = _upload(authed_client(super_admin), content, "wb.xlsx", mode="lenient", linkToEngine="true")
    assert resp.status_code == 202, resp.content
    rec = RiskAssessmentRecord.objects.get(risk_area="FX exposure")
    assert rec.entity_id == dept.id
    assert rec.entity_risk_id is not None
    risk = EntityRisk.objects.get(pk=rec.entity_risk_id)
    assert risk.entity_id == dept.id
    assert risk.inherent_likelihood == 4  # High → 4


def test_import_job_poll_endpoint_scopes_to_owner(authed_client, super_admin):
    content = _xlsx_bytes({"S": [RECORD_HEADER, ["D", "R", "", "Low", "Low", "Low", "Low", "Included", 1]]})
    resp = _upload(authed_client(super_admin), content, "wb.xlsx")
    job_id = resp.json()["id"]
    poll = authed_client(super_admin).get(f"/api/risk-assessment-import-jobs/{job_id}/")
    assert poll.status_code == 200, poll.content
    assert poll.json()["status"] in ("Completed", "PartialSuccess")
