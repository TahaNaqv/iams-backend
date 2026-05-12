"""Tests for the antivirus scan Celery task and quarantine flow.

We never want to talk to a real clamd in tests — instead we patch
``iams.tasks.scans._get_clamd_client`` to return a stub that returns
canned INSTREAM results. Each test asserts the row state after the
scan completes.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone as dj_timezone

from iams.models import Audit, EvidenceFile, ManagedDocument
from iams.tasks.scans import scan_uploaded_file


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def audit(db) -> Audit:
    return Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )


def _make_evidence(audit: Audit, *, content: bytes = b"hello world") -> EvidenceFile:
    """Create an EvidenceFile with attached bytes via SimpleUploadedFile."""
    upload = SimpleUploadedFile("evidence.txt", content, content_type="text/plain")
    return EvidenceFile.objects.create(
        audit=audit,
        file=upload,
        name="evidence.txt",
        type="text/plain",
        size_kb=max(1, len(content) // 1024),
        uploaded_by="auditor@iams.test",
        uploaded_at=dj_timezone.now(),
    )


def _stub_client(stream_return) -> MagicMock:
    client = MagicMock()
    client.instream.return_value = stream_return
    return client


# ──────────────────────────────────────────────────────────────────────
# Clean file
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_scan_marks_clean_when_clamd_returns_ok(audit, settings):
    settings.CLAMD_SKIP = False  # exercise the real client path
    evidence = _make_evidence(audit)

    with patch(
        "iams.tasks.scans._get_clamd_client",
        return_value=_stub_client({"stream": ("OK", None)}),
    ):
        result = scan_uploaded_file(
            model_label="EvidenceFile", object_id=str(evidence.id)
        )

    evidence.refresh_from_db()
    assert result == {
        "scanned": True,
        "status": "clean",
        "signature": "",
        "object_id": str(evidence.id),
    }
    assert evidence.scan_status == EvidenceFile.SCAN_CLEAN
    assert evidence.scan_signature == ""
    assert evidence.quarantined is False
    assert evidence.scanned_at is not None


# ──────────────────────────────────────────────────────────────────────
# Infected file
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_scan_quarantines_when_clamd_reports_found(audit, settings):
    settings.CLAMD_SKIP = False
    evidence = _make_evidence(audit, content=b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR")

    with patch(
        "iams.tasks.scans._get_clamd_client",
        return_value=_stub_client({"stream": ("FOUND", "Eicar-Test-Signature")}),
    ):
        scan_uploaded_file(model_label="EvidenceFile", object_id=str(evidence.id))

    evidence.refresh_from_db()
    assert evidence.scan_status == EvidenceFile.SCAN_INFECTED
    assert evidence.scan_signature == "Eicar-Test-Signature"
    assert evidence.quarantined is True


# ──────────────────────────────────────────────────────────────────────
# Clamd error → quarantine fail-closed
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_scan_quarantines_on_unexpected_clamd_error(audit, settings):
    settings.CLAMD_SKIP = False
    evidence = _make_evidence(audit)
    client = MagicMock()
    client.instream.side_effect = RuntimeError("clamd exploded")

    with patch("iams.tasks.scans._get_clamd_client", return_value=client):
        scan_uploaded_file(model_label="EvidenceFile", object_id=str(evidence.id))

    evidence.refresh_from_db()
    assert evidence.scan_status == EvidenceFile.SCAN_ERROR
    assert evidence.scan_signature == "RuntimeError"
    assert evidence.quarantined is True


# ──────────────────────────────────────────────────────────────────────
# CLAMD_SKIP env → marked clean without scanning
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_clamd_skip_marks_clean_without_calling_client(audit, settings):
    settings.CLAMD_SKIP = True
    evidence = _make_evidence(audit)

    with patch("iams.tasks.scans._get_clamd_client") as get_client:
        result = scan_uploaded_file(
            model_label="EvidenceFile", object_id=str(evidence.id)
        )

    get_client.assert_not_called()
    assert result["reason"] == "clamd_skip"
    evidence.refresh_from_db()
    assert evidence.scan_status == EvidenceFile.SCAN_CLEAN
    assert evidence.quarantined is False


# ──────────────────────────────────────────────────────────────────────
# Oversize file
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_scan_quarantines_oversized_file(audit, settings):
    settings.CLAMD_SKIP = False
    settings.CLAMD_MAX_FILE_MB = 0  # force the size check to trip
    evidence = _make_evidence(audit, content=b"any content")

    with patch("iams.tasks.scans._get_clamd_client") as get_client:
        result = scan_uploaded_file(
            model_label="EvidenceFile", object_id=str(evidence.id)
        )

    get_client.assert_not_called()
    assert result["reason"] == "too_large"
    evidence.refresh_from_db()
    assert evidence.scan_status == EvidenceFile.SCAN_ERROR
    assert evidence.scan_signature == "file_too_large"
    assert evidence.quarantined is True


# ──────────────────────────────────────────────────────────────────────
# Missing row (raced with delete)
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_scan_silently_skips_when_row_deleted():
    result = scan_uploaded_file(
        model_label="EvidenceFile",
        object_id="00000000-0000-0000-0000-000000000000",
    )
    assert result == {"scanned": False, "reason": "row_missing"}


# ──────────────────────────────────────────────────────────────────────
# Unknown model_label is a programmer error → handled, not raised
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_scan_handles_unknown_model_label():
    result = scan_uploaded_file(model_label="NotARealModel", object_id="abc")
    assert result == {"scanned": False, "reason": "unknown_model_label"}


# ══════════════════════════════════════════════════════════════════════
# Upload endpoint integration — dispatches the scan
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_evidence_upload_dispatches_scan_task(authed_client, super_admin, audit, settings):
    """POST to the audit-evidence endpoint creates a row and dispatches scan.

    Test settings have ``CELERY_TASK_ALWAYS_EAGER=True``, so the scan runs
    synchronously in the request. With ``CLAMD_SKIP=True`` it short-circuits
    to 'clean' without needing a real clamd.
    """
    settings.CLAMD_SKIP = True
    client = authed_client(super_admin)
    file = SimpleUploadedFile("notes.txt", b"meeting notes", content_type="text/plain")
    response = client.post(
        f"/api/audits/{audit.id}/evidence/",
        {"file": file, "name": "Notes", "type": "txt"},
        format="multipart",
    )
    assert response.status_code == 201
    body = response.json()
    # Initial response shows whatever state the scan finished in. With eager
    # Celery + CLAMD_SKIP, it's already 'clean' by the time the response returns.
    assert body["scanStatus"] in ("pending", "clean")

    # After the task ran, the row must be clean (eager mode means it ran
    # before this point — re-fetch to be safe).
    evidence = EvidenceFile.objects.get(pk=body["id"])
    assert evidence.scan_status == EvidenceFile.SCAN_CLEAN
    assert evidence.quarantined is False


# ══════════════════════════════════════════════════════════════════════
# Download endpoint — refuses quarantined files
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_evidence_download_refuses_quarantined_file(
    authed_client, super_admin, audit, settings
):
    settings.CLAMD_SKIP = False
    evidence = _make_evidence(audit)

    with patch(
        "iams.tasks.scans._get_clamd_client",
        return_value=_stub_client({"stream": ("FOUND", "EICAR-test")}),
    ):
        scan_uploaded_file(model_label="EvidenceFile", object_id=str(evidence.id))

    evidence.refresh_from_db()
    assert evidence.quarantined is True

    client = authed_client(super_admin)
    response = client.get(f"/api/evidence-files/{evidence.id}/download/")
    assert response.status_code == 403
    body = response.json()
    assert body["detail"] == "File is quarantined."
    assert body["scanStatus"] == "infected"
    assert body["scanSignature"] == "EICAR-test"


@pytest.mark.django_db
def test_evidence_download_409_while_scan_pending(
    authed_client, super_admin, audit, settings
):
    """If a row is scanned in pending state (e.g., race between upload and
    scan task), downloads must 409, not silently succeed."""
    settings.CLAMD_SKIP = False
    evidence = _make_evidence(audit)
    # Force pending state (eager mode would normally complete it)
    evidence.scan_status = EvidenceFile.SCAN_PENDING
    evidence.save(update_fields=["scan_status"])

    client = authed_client(super_admin)
    response = client.get(f"/api/evidence-files/{evidence.id}/download/")
    assert response.status_code == 409
    assert response.json()["scanStatus"] == "pending"


@pytest.mark.django_db
def test_evidence_download_succeeds_when_clean(
    authed_client, super_admin, audit, settings
):
    settings.CLAMD_SKIP = True
    evidence = _make_evidence(audit)
    scan_uploaded_file(model_label="EvidenceFile", object_id=str(evidence.id))
    evidence.refresh_from_db()
    assert evidence.scan_status == "clean"

    client = authed_client(super_admin)
    response = client.get(f"/api/evidence-files/{evidence.id}/download/")
    assert response.status_code == 200
    assert "url" in response.json()


# ══════════════════════════════════════════════════════════════════════
# ManagedDocument upload path
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_managed_document_upload_dispatches_scan(authed_client, super_admin, settings):
    settings.CLAMD_SKIP = True
    client = authed_client(super_admin)
    file = SimpleUploadedFile("policy.pdf", b"%PDF-1.4\n%fake", content_type="application/pdf")
    response = client.post(
        "/api/managed-documents/",
        {
            "title": "Audit Charter",
            "category": "Policies",
            "status": "Draft",
            "owner": "CAE",
            "department": "Internal Audit",
            "fileType": "pdf",
            "fileSize": "2 KB",
            "description": "—",
            "file": file,
        },
        format="multipart",
    )
    assert response.status_code == 201, response.content
    doc = ManagedDocument.objects.get(pk=response.json()["id"])
    assert doc.scan_status == EvidenceFile.SCAN_CLEAN
    assert doc.quarantined is False


@pytest.mark.django_db
def test_managed_document_serializer_omits_download_url_when_quarantined(
    sa_client_override, super_admin, settings
):
    """Phase 1 hardening: managed-document download URL must be hidden
    once a file has failed AV scanning so the FE can't accidentally link
    to it.

    Uses a locally-built ``sa_client_override`` because the standard
    ``authed_client`` fixture isn't available in this scope; we build it
    inline from ``super_admin``.
    """
    settings.CLAMD_SKIP = True
    doc = ManagedDocument.objects.create(
        title="X", category="Policies", status="Draft",
        owner="o", department="d", file_type="pdf",
        file_size="1 KB", description="-",
        file=SimpleUploadedFile("x.pdf", b"data", content_type="application/pdf"),
        tags=[], versions=[],
    )
    doc.quarantined = True
    doc.scan_status = EvidenceFile.SCAN_INFECTED
    doc.save(update_fields=["quarantined", "scan_status"])

    response = sa_client_override.get(f"/api/managed-documents/{doc.id}/")
    assert response.status_code == 200
    body = response.json()
    assert body["downloadUrl"] is None
    assert body["quarantined"] is True
    assert body["scanStatus"] == "infected"


@pytest.fixture
def sa_client_override(super_admin, authed_client):
    return authed_client(super_admin)
