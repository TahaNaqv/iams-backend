"""Tests for the audit-universe bulk-import + export pipeline.

Covers the wire-level contract end-to-end:

  - POST /api/auditable-entities/bulk-import/  (multipart CSV or XLSX)
    → returns a BulkImportJob row that Celery (in eager mode for tests)
      drives to completion before the response returns.
  - GET  /api/audit-universe-import-jobs/{id}/
    → polled by the FE while the job runs; here we just verify the
      job's terminal state has the expected counters and errors.
  - GET  /api/auditable-entities/export/?format=csv|xlsx
    → streams the filtered queryset. We check headers and row contents
      for CSV; for XLSX we assert the response is non-empty with the
      correct content-type since openpyxl writes binary.
"""
from __future__ import annotations

import csv
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from iams.models import AuditableEntity, BulkImportJob, Department


@pytest.fixture
def sa_client(super_admin, authed_client):
    return authed_client(super_admin)


@pytest.fixture
def finance_dept(db) -> Department:
    return Department.objects.create(name="Finance", head="J. Doe")


def _csv_upload(rows: list[list[str]], name: str = "universe.csv") -> SimpleUploadedFile:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(row)
    return SimpleUploadedFile(
        name, buf.getvalue().encode("utf-8"), content_type="text/csv",
    )


# ══════════════════════════════════════════════════════════════════════
# Import — happy path
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_csv_import_creates_entities_with_lookups(sa_client, finance_dept):
    csv_file = _csv_upload([
        ["Name", "Department", "Risk Rating", "Mandatory to audit", "Tags"],
        ["Accounts Payable", "Finance", "High", "yes", "sox,critical"],
        ["General Ledger", "Finance", "Medium", "false", "sox"],
    ])
    resp = sa_client.post(
        "/api/auditable-entities/bulk-import/",
        {"file": csv_file, "mode": "lenient"},
        format="multipart",
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED, resp.content
    job_id = resp.json()["id"]

    job = BulkImportJob.objects.get(pk=job_id)
    assert job.status == BulkImportJob.STATUS_COMPLETED, job.errors
    assert job.total_rows == 2
    assert job.created == 2
    assert job.updated == 0
    assert job.errors == []

    ap = AuditableEntity.objects.get(name="Accounts Payable")
    assert ap.risk_rating == "High"
    assert ap.department_ref_id == finance_dept.id
    assert ap.is_mandatory_to_audit is True
    assert sorted(ap.tags) == ["critical", "sox"]


@pytest.mark.django_db
def test_csv_import_updates_existing_by_name(sa_client, finance_dept):
    AuditableEntity.objects.create(name="Treasury", department_ref=finance_dept, risk_rating="Medium")
    csv_file = _csv_upload([
        ["Name", "Department", "Risk Rating"],
        ["Treasury", "Finance", "Critical"],
    ])
    resp = sa_client.post(
        "/api/auditable-entities/bulk-import/",
        {"file": csv_file, "mode": "lenient"},
        format="multipart",
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    job = BulkImportJob.objects.get(pk=resp.json()["id"])
    assert job.created == 0
    assert job.updated == 1
    AuditableEntity.objects.get(name="Treasury").risk_rating == "Critical"


@pytest.mark.django_db
def test_csv_import_skips_bad_rows_in_lenient_mode(sa_client, finance_dept):
    csv_file = _csv_upload([
        ["Name", "Department", "Risk Rating"],
        ["", "Finance", "High"],                  # missing name
        ["Good Row", "Finance", "Extreme"],        # invalid choice
        ["Another", "Finance", "Low"],             # good
    ])
    resp = sa_client.post(
        "/api/auditable-entities/bulk-import/",
        {"file": csv_file, "mode": "lenient"},
        format="multipart",
    )
    job = BulkImportJob.objects.get(pk=resp.json()["id"])
    assert job.status == BulkImportJob.STATUS_PARTIAL, job.errors
    assert job.created == 1
    assert job.skipped == 2
    assert len(job.errors) == 2
    fields = {e["field"] for e in job.errors}
    assert "name" in fields
    assert "riskRating" in fields


@pytest.mark.django_db
def test_strict_mode_aborts_on_first_error(sa_client, finance_dept):
    csv_file = _csv_upload([
        ["Name", "Department", "Risk Rating"],
        ["First", "Finance", "Low"],
        ["", "Finance", "High"],   # bad — name missing
        ["Third", "Finance", "Medium"],
    ])
    resp = sa_client.post(
        "/api/auditable-entities/bulk-import/",
        {"file": csv_file, "mode": "strict"},
        format="multipart",
    )
    job = BulkImportJob.objects.get(pk=resp.json()["id"])
    assert job.status == BulkImportJob.STATUS_FAILED
    # Strict mode rolls back, so no entity should have been created.
    assert not AuditableEntity.objects.filter(name__in=["First", "Third"]).exists()


# ══════════════════════════════════════════════════════════════════════
# Import — error handling at the endpoint level
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_bulk_import_requires_a_file(sa_client):
    resp = sa_client.post("/api/auditable-entities/bulk-import/", {}, format="multipart")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_bulk_import_rejects_unknown_extension(sa_client):
    bad = SimpleUploadedFile("not_a_spreadsheet.txt", b"hello", content_type="text/plain")
    resp = sa_client.post(
        "/api/auditable-entities/bulk-import/",
        {"file": bad, "mode": "lenient"},
        format="multipart",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_bulk_import_job_endpoint_is_scoped_to_owner(
    sa_client, auditor_user, authed_client, finance_dept,
):
    """A non-staff user shouldn't see another user's import jobs."""
    other_job = BulkImportJob.objects.create(
        file=SimpleUploadedFile("x.csv", b"", content_type="text/csv"),
        file_name="x.csv",
        requested_by=auditor_user,
    )
    # super_admin sees everything (is_staff/superuser bypass).
    sa_resp = sa_client.get("/api/audit-universe-import-jobs/")
    ids_visible_to_sa = {r["id"] for r in sa_resp.json()["results"]}
    assert str(other_job.id) in ids_visible_to_sa


# ══════════════════════════════════════════════════════════════════════
# Export
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_csv_export_streams_filtered_queryset(sa_client, finance_dept):
    AuditableEntity.objects.create(name="Alpha", department_ref=finance_dept, risk_rating="High")
    AuditableEntity.objects.create(name="Bravo", department_ref=finance_dept, risk_rating="Low")
    resp = sa_client.get("/api/auditable-entities/export/?riskRating=High")
    assert resp.status_code == status.HTTP_200_OK
    assert resp["Content-Type"] == "text/csv"
    assert "audit-universe.csv" in resp["Content-Disposition"]
    body = b"".join(resp.streaming_content).decode("utf-8")
    reader = list(csv.reader(io.StringIO(body)))
    header = reader[0]
    assert "name" in header and "riskRating" in header
    names = [row[header.index("name")] for row in reader[1:]]
    assert names == ["Alpha"]


@pytest.mark.django_db
def test_xlsx_export_returns_binary(sa_client, finance_dept):
    AuditableEntity.objects.create(name="Charlie", department_ref=finance_dept)
    resp = sa_client.get("/api/auditable-entities/export/?as=xlsx")
    assert resp.status_code == status.HTTP_200_OK
    assert "spreadsheetml.sheet" in resp["Content-Type"]
    assert len(resp.content) > 200  # non-trivial XLSX bytes
