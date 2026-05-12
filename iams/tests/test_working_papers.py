"""Tests for the Working Papers module (Phase 3 Track 1).

Covers:
  - CRUD via the API (upload, edit, list, filter by audit, search)
  - Sign-off flow: auditor → reviewer = finalized + locked
  - Sign-off authorisation rules (no double-sign, no self-review)
  - Python-level lock-on-finalize (save/delete refuse after signoff)
  - Version chain (new-version flips is_current, copies cross-refs forward)
  - Cross-reference findings via M2M
  - searchable_text populates from metadata + plain-text contents
  - AV scan dispatched on upload; download honors quarantine/pending
  - Audit-log captures sign-off + version events
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from iams.models import Audit, AuditLogEntry, EvidenceFile, Finding, WorkingPaper
from iams.working_papers import (
    SignOffError,
    create_new_version,
    populate_searchable_text,
    sign_as_auditor,
    sign_as_reviewer,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def audit() -> Audit:
    return Audit.objects.create(
        title="Q1 Treasury", department="Finance", lead_auditor="L",
        status="In Progress", priority="High", risk_rating="High",
        start_date=date(2026, 1, 1), end_date=date(2026, 3, 31),
        scope="s", objectives="o", completion_percent=20, findings_count=0,
    )


@pytest.fixture
def finding(audit) -> Finding:
    return Finding.objects.create(
        audit=audit, title="F", department="Finance", severity="High",
        status="Open", owner="o", due_date=date.today() + timedelta(days=14),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )


def _make_wp(audit: Audit, *, reference="WP-001", title="Walkthrough",
             file_content: bytes = b"Sample working paper content") -> WorkingPaper:
    upload = SimpleUploadedFile("wp.txt", file_content, content_type="text/plain")
    wp = WorkingPaper.objects.create(
        audit=audit, reference=reference, title=title,
        description="Initial walkthrough notes",
        file=upload, file_type="txt",
        file_size_kb=max(1, len(file_content) // 1024),
    )
    return wp


# ══════════════════════════════════════════════════════════════════════
# Sign-off rules
# ══════════════════════════════════════════════════════════════════════
def test_sign_as_auditor_records_signature_and_moves_to_under_review(audit, auditor_user):
    wp = _make_wp(audit)
    assert wp.status == WorkingPaper.STATUS_DRAFT
    sign_as_auditor(wp, by_user=auditor_user)
    wp.refresh_from_db()
    assert wp.auditor_signed_at is not None
    assert wp.auditor_signed_by == auditor_user
    assert wp.status == WorkingPaper.STATUS_UNDER_REVIEW
    assert wp.signed_off_at is None  # not finalized yet


def test_sign_as_auditor_rejects_double_sign(audit, auditor_user):
    wp = _make_wp(audit)
    sign_as_auditor(wp, by_user=auditor_user)
    with pytest.raises(SignOffError, match="already signed"):
        sign_as_auditor(wp, by_user=auditor_user)


def test_sign_as_reviewer_requires_auditor_first(audit, audit_manager):
    wp = _make_wp(audit)
    with pytest.raises(SignOffError, match="Auditor must sign before"):
        sign_as_reviewer(wp, by_user=audit_manager)


def test_sign_as_reviewer_refuses_same_user_as_auditor(audit, auditor_user):
    """IIA 2330 separation of duties — reviewer ≠ auditor."""
    wp = _make_wp(audit)
    sign_as_auditor(wp, by_user=auditor_user)
    with pytest.raises(SignOffError, match="separation of duties"):
        sign_as_reviewer(wp, by_user=auditor_user)


def test_full_signoff_finalizes_and_locks(audit, auditor_user, audit_manager):
    wp = _make_wp(audit)
    sign_as_auditor(wp, by_user=auditor_user)
    sign_as_reviewer(wp, by_user=audit_manager)
    wp.refresh_from_db()
    assert wp.is_finalized()
    assert wp.signed_off_at is not None
    assert wp.status == WorkingPaper.STATUS_SIGNED


# ══════════════════════════════════════════════════════════════════════
# Lock-on-finalize (Python-level)
# ══════════════════════════════════════════════════════════════════════
def test_signed_working_paper_save_is_locked(audit, auditor_user, audit_manager):
    wp = _make_wp(audit)
    sign_as_auditor(wp, by_user=auditor_user)
    sign_as_reviewer(wp, by_user=audit_manager)
    wp.refresh_from_db()
    wp.title = "Tampered title"
    with pytest.raises(PermissionError, match="locked"):
        wp.save()


def test_signed_working_paper_delete_is_locked(audit, auditor_user, audit_manager):
    wp = _make_wp(audit)
    sign_as_auditor(wp, by_user=auditor_user)
    sign_as_reviewer(wp, by_user=audit_manager)
    wp.refresh_from_db()
    with pytest.raises(PermissionError, match="locked"):
        wp.delete()


def test_signed_working_paper_allows_scan_field_updates(audit, auditor_user, audit_manager):
    """The AV scan task runs after the upload; we must allow its writes
    even if the row gets signed in the meantime."""
    wp = _make_wp(audit)
    sign_as_auditor(wp, by_user=auditor_user)
    sign_as_reviewer(wp, by_user=audit_manager)
    wp.refresh_from_db()
    # Allowed: scan-only update
    wp.scan_status = WorkingPaper.scan_status.field.default
    wp.scan_status = "clean"
    wp.scanned_at = timezone.now()
    wp.save(update_fields=["scan_status", "scanned_at"])  # must not raise


# ══════════════════════════════════════════════════════════════════════
# Version chain
# ══════════════════════════════════════════════════════════════════════
def test_create_new_version_flips_parent_is_current_false(audit):
    v1 = _make_wp(audit)
    assert v1.is_current_version is True

    v2 = create_new_version(v1, title="v2 title")
    v1.refresh_from_db()
    assert v1.is_current_version is False
    assert v2.is_current_version is True
    assert v2.version == 2
    assert v2.parent == v1
    assert v2.title == "v2 title"
    assert v2.status == WorkingPaper.STATUS_DRAFT


def test_new_version_copies_findings_forward(audit, finding):
    v1 = _make_wp(audit)
    v1.findings.add(finding)
    v2 = create_new_version(v1)
    assert list(v2.findings.values_list("pk", flat=True)) == [finding.pk]


def test_new_version_clears_signatures(audit, auditor_user, audit_manager):
    v1 = _make_wp(audit)
    sign_as_auditor(v1, by_user=auditor_user)
    sign_as_reviewer(v1, by_user=audit_manager)
    v1.refresh_from_db()

    v2 = create_new_version(v1)
    assert v2.auditor_signed_at is None
    assert v2.reviewer_signed_at is None
    assert v2.signed_off_at is None


def test_only_one_current_version_per_audit_reference(audit):
    """Partial unique constraint enforces a single current row per chain."""
    v1 = _make_wp(audit, reference="WP-100")
    # Trying to create another v1 with the same reference and is_current=True
    # should violate the constraint.
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        WorkingPaper.objects.create(
            audit=audit, reference="WP-100", title="dup",
            file=SimpleUploadedFile("x.txt", b"x", content_type="text/plain"),
            file_type="txt", file_size_kb=1,
            is_current_version=True, version=1,
        )


# ══════════════════════════════════════════════════════════════════════
# searchable_text
# ══════════════════════════════════════════════════════════════════════
def test_populate_searchable_text_from_metadata(audit):
    wp = _make_wp(audit, title="AP Walkthrough", file_content=b"Verbatim notes from the AP team meeting")
    text = populate_searchable_text(wp)
    assert "AP Walkthrough" in text
    assert "Verbatim notes" in text  # txt file content is inlined


# ══════════════════════════════════════════════════════════════════════
# API: CRUD + filters
# ══════════════════════════════════════════════════════════════════════
def test_api_create_dispatches_av_scan(authed_client, super_admin, audit, settings):
    settings.CLAMD_SKIP = True  # eager scan completes immediately as "clean"
    client = authed_client(super_admin)
    file = SimpleUploadedFile("wp.txt", b"sample working paper", content_type="text/plain")
    response = client.post(
        "/api/working-papers/",
        {
            "auditId": str(audit.id),
            "reference": "WP-API-001",
            "title": "Created via API",
            "description": "Initial",
            "file": file,
            "fileType": "txt",
        },
        format="multipart",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    wp = WorkingPaper.objects.get(pk=body["id"])
    # AV scan ran eagerly (eager Celery + CLAMD_SKIP)
    assert wp.scan_status == "clean"
    # searchable_text populated
    assert "Created via API" in wp.searchable_text


def test_api_list_filter_by_audit(authed_client, super_admin, audit):
    other = Audit.objects.create(
        title="Other", department="X", lead_auditor="L", status="Planned",
        priority="Low", risk_rating="Low",
        start_date=date.today(), end_date=date.today() + timedelta(days=10),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    _make_wp(audit, reference="WP-A")
    _make_wp(other, reference="WP-B")
    client = authed_client(super_admin)
    body = client.get(f"/api/working-papers/?audit_id={audit.id}").json()
    rows = body["results"] if isinstance(body, dict) else body
    refs = [r["reference"] for r in rows]
    assert "WP-A" in refs
    assert "WP-B" not in refs


def test_api_list_search_matches_title(authed_client, super_admin, audit):
    _make_wp(audit, title="Bank reconciliation walkthrough")
    _make_wp(audit, reference="WP-002", title="Inventory count")
    client = authed_client(super_admin)
    body = client.get("/api/working-papers/?search=reconciliation").json()
    rows = body["results"] if isinstance(body, dict) else body
    titles = [r["title"] for r in rows]
    assert any("reconciliation" in t.lower() for t in titles)
    assert not any("inventory" in t.lower() for t in titles)


def test_api_currentonly_filter(authed_client, super_admin, audit):
    v1 = _make_wp(audit)
    create_new_version(v1)  # creates v2 current
    v1.refresh_from_db()
    assert v1.is_current_version is False

    client = authed_client(super_admin)
    body = client.get("/api/working-papers/?currentOnly=true").json()
    rows = body["results"] if isinstance(body, dict) else body
    versions = [r["version"] for r in rows]
    assert 2 in versions
    assert 1 not in versions


def test_api_sign_actions_record_audit_log(
    authed_client, super_admin, audit_manager, audit
):
    wp = _make_wp(audit)
    AuditLogEntry.objects.all().delete()

    # Auditor signs (super_admin)
    sa = authed_client(super_admin)
    res = sa.post(f"/api/working-papers/{wp.id}/sign/auditor/")
    assert res.status_code == 200, res.content
    assert AuditLogEntry.objects.filter(details__event="working_paper_auditor_signed").exists()

    # Reviewer signs (audit_manager — different user)
    mgr = authed_client(audit_manager)
    res = mgr.post(f"/api/working-papers/{wp.id}/sign/reviewer/")
    assert res.status_code == 200, res.content
    log = AuditLogEntry.objects.filter(details__event="working_paper_reviewer_signed").first()
    assert log is not None
    assert log.details["finalized"] is True


def test_api_update_rejected_after_signoff(
    authed_client, super_admin, audit_manager, audit
):
    wp = _make_wp(audit)
    sign_as_auditor(wp, by_user=super_admin)
    sign_as_reviewer(wp, by_user=audit_manager)

    client = authed_client(super_admin)
    res = client.patch(
        f"/api/working-papers/{wp.id}/",
        {"title": "Tampered"}, format="json",
    )
    assert res.status_code == 403
    wp.refresh_from_db()
    assert wp.title != "Tampered"


def test_api_versions_endpoint_returns_full_chain(
    authed_client, super_admin, audit
):
    v1 = _make_wp(audit)
    v2 = create_new_version(v1)
    v3 = create_new_version(v2)

    client = authed_client(super_admin)
    body = client.get(f"/api/working-papers/{v3.id}/versions/").json()
    rows = body["results"] if isinstance(body, dict) else body
    assert [r["version"] for r in rows] == [1, 2, 3]


def test_api_new_version_endpoint(authed_client, super_admin, audit):
    v1 = _make_wp(audit)
    client = authed_client(super_admin)
    file = SimpleUploadedFile("v2.txt", b"second revision", content_type="text/plain")
    res = client.post(
        f"/api/working-papers/{v1.id}/new-version/",
        {"title": "v2", "file": file},
        format="multipart",
    )
    assert res.status_code == 201, res.content
    v2 = WorkingPaper.objects.get(pk=res.json()["id"])
    assert v2.version == 2
    assert v2.parent == v1


def test_api_download_refuses_quarantined_working_paper(
    authed_client, super_admin, audit
):
    wp = _make_wp(audit)
    wp.quarantined = True
    wp.scan_status = "infected"
    wp.scan_signature = "EICAR-test"
    wp.save(update_fields=["quarantined", "scan_status", "scan_signature"])

    client = authed_client(super_admin)
    res = client.get(f"/api/working-papers/{wp.id}/download/")
    assert res.status_code == 403
    body = res.json()
    assert body["scanStatus"] == "infected"
    assert body["scanSignature"] == "EICAR-test"
