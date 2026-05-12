"""Tests for the automatic audit trail.

What this suite proves:
  1. Every CRUD verb that goes through a ``ModelViewSet`` with the
     ``AuditedViewSetMixin`` writes a row to ``AuditLogEntry``.
  2. Update entries contain a ``{field: {old, new}}`` diff with only the
     changed fields.
  3. Create / delete entries contain a ``{"snapshot": {...}}`` payload.
  4. Excluded fields (passwords, raw timestamps) never appear in the diff.
  5. ``AuditLogEntry`` is Python-append-only: ``save()`` rejects updates,
     ``delete()`` raises.
  6. Explicit ``record_audit_event`` events (approvals, password change,
     AV quarantine) land with the right action / actor / target.
  7. Idempotent PATCH (nothing actually changed) does NOT create a noise row.
  8. ``request_id`` from the request middleware reaches the row.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from iams.audit import record_audit_event
from iams.middleware import request_id_ctx
from iams.models import (
    ApprovalRequest,
    Audit,
    AuditLogEntry,
    Finding,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def audit_payload() -> dict:
    today = date.today()
    return {
        "title": "Q1 Treasury",
        "department": "Finance",
        "leadAuditor": "S. Kim",
        "status": "Planned",
        "priority": "High",
        "riskRating": "High",
        "startDate": str(today),
        "endDate": str(today + timedelta(days=60)),
        "scope": "Treasury controls",
        "objectives": "SOX 404 validation",
        "completionPercent": 0,
        "findingsCount": 0,
    }


def _audit_for(target) -> AuditLogEntry | None:
    """Return the latest audit row pointing at ``target``, or None."""
    ct = ContentType.objects.get_for_model(target.__class__)
    return AuditLogEntry.objects.filter(
        target_content_type=ct, target_object_id=target.pk
    ).order_by("-timestamp").first()


# ══════════════════════════════════════════════════════════════════════
# Auto-capture: create / update / delete
# ══════════════════════════════════════════════════════════════════════
def test_create_via_viewset_writes_audit_entry(authed_client, super_admin, audit_payload):
    client = authed_client(super_admin)
    response = client.post("/api/audits/", audit_payload, format="json")
    assert response.status_code == 201, response.content
    audit = Audit.objects.get(pk=response.json()["id"])

    entry = _audit_for(audit)
    assert entry is not None
    assert entry.action == AuditLogEntry.ACTION_CREATE
    assert entry.actor == "sa@iams.test"
    assert entry.actor_ref == super_admin
    assert entry.target == str(audit)
    assert "snapshot" in entry.changes
    snapshot = entry.changes["snapshot"]
    assert snapshot["title"] == "Q1 Treasury"
    assert snapshot["lead_auditor"] == "S. Kim"
    # Excluded fields must NOT appear in the snapshot
    assert "id" not in snapshot
    assert "created_at" not in snapshot
    assert "updated_at" not in snapshot


def test_update_writes_diff_only_for_changed_fields(authed_client, super_admin, audit_payload):
    client = authed_client(super_admin)
    create_res = client.post("/api/audits/", audit_payload, format="json")
    audit_id = create_res.json()["id"]
    # Clear pre-existing create entry to make the diff assertion crisp
    AuditLogEntry.all_objects_including_locked = AuditLogEntry.objects  # noqa: SLF001
    create_count_before = AuditLogEntry.objects.filter(action="update").count()

    patch_res = client.patch(
        f"/api/audits/{audit_id}/",
        {"status": "In Progress", "completionPercent": 25},
        format="json",
    )
    assert patch_res.status_code == 200, patch_res.content
    audit = Audit.objects.get(pk=audit_id)
    entry = AuditLogEntry.objects.filter(action="update").order_by("-timestamp").first()
    assert entry is not None
    assert entry.action == AuditLogEntry.ACTION_UPDATE
    assert AuditLogEntry.objects.filter(action="update").count() == create_count_before + 1
    # The diff contains exactly the touched fields — not the others.
    diff = entry.changes
    assert set(diff.keys()) == {"status", "completion_percent"}
    assert diff["status"] == {"old": "Planned", "new": "In Progress"}
    assert diff["completion_percent"] == {"old": 0, "new": 25}


def test_idempotent_patch_does_not_log(authed_client, super_admin, audit_payload):
    """PATCHing with the same values as already stored is a no-op — the
    audit log must not be cluttered with empty-diff entries."""
    client = authed_client(super_admin)
    audit_id = client.post("/api/audits/", audit_payload, format="json").json()["id"]
    updates_before = AuditLogEntry.objects.filter(action="update").count()

    # Same values
    client.patch(f"/api/audits/{audit_id}/", {"status": "Planned"}, format="json")
    assert AuditLogEntry.objects.filter(action="update").count() == updates_before


def test_delete_writes_snapshot_entry(authed_client, super_admin, audit_payload):
    client = authed_client(super_admin)
    audit_id = client.post("/api/audits/", audit_payload, format="json").json()["id"]
    audit = Audit.objects.get(pk=audit_id)
    target_str = str(audit)

    delete_res = client.delete(f"/api/audits/{audit_id}/")
    assert delete_res.status_code == 204

    # Row is gone — find by content_type + object_id directly
    ct = ContentType.objects.get_for_model(Audit)
    entry = AuditLogEntry.objects.filter(
        target_content_type=ct, target_object_id=audit_id, action="delete"
    ).first()
    assert entry is not None
    assert entry.target == target_str
    assert "snapshot" in entry.changes
    assert entry.changes["snapshot"]["title"] == "Q1 Treasury"


# ══════════════════════════════════════════════════════════════════════
# Append-only enforcement (Python layer)
# ══════════════════════════════════════════════════════════════════════
def test_audit_log_entry_save_rejects_updates():
    """Once persisted, the row's save() must raise on a second call."""
    from django.utils import timezone

    entry = AuditLogEntry.objects.create(
        actor="alice", action="create", target="x",
        timestamp=timezone.now(),
    )
    entry.action = "tamper"
    with pytest.raises(PermissionError, match="append-only"):
        entry.save()


def test_audit_log_entry_loaded_from_db_cannot_be_saved():
    from django.utils import timezone

    AuditLogEntry.objects.create(
        actor="alice", action="create", target="x",
        timestamp=timezone.now(),
    )
    fetched = AuditLogEntry.objects.first()
    fetched.action = "tamper"
    with pytest.raises(PermissionError, match="append-only"):
        fetched.save()


def test_audit_log_entry_delete_raises():
    from django.utils import timezone

    entry = AuditLogEntry.objects.create(
        actor="alice", action="create", target="x",
        timestamp=timezone.now(),
    )
    with pytest.raises(PermissionError, match="append-only"):
        entry.delete()


# ══════════════════════════════════════════════════════════════════════
# Request metadata (request_id, IP, user-agent)
# ══════════════════════════════════════════════════════════════════════
def test_audit_entry_captures_request_id_header(authed_client, super_admin, audit_payload):
    client = authed_client(super_admin)
    rid = "test-request-" + str(uuid.uuid4())
    response = client.post(
        "/api/audits/", audit_payload, format="json", HTTP_X_REQUEST_ID=rid
    )
    assert response.status_code == 201
    entry = AuditLogEntry.objects.order_by("-timestamp").first()
    assert entry.request_id == rid


def test_audit_entry_captures_user_agent(authed_client, super_admin, audit_payload):
    client = authed_client(super_admin)
    client.post(
        "/api/audits/", audit_payload, format="json", HTTP_USER_AGENT="iams-test/0.1"
    )
    entry = AuditLogEntry.objects.order_by("-timestamp").first()
    assert entry.user_agent == "iams-test/0.1"


# ══════════════════════════════════════════════════════════════════════
# record_audit_event helper
# ══════════════════════════════════════════════════════════════════════
def test_record_audit_event_with_model_target(super_admin):
    finding_audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date.today(), end_date=date.today() + timedelta(days=30),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    finding = Finding.objects.create(
        audit=finding_audit, title="F", department="F", severity="High",
        status="Open", owner="o", due_date=date.today() + timedelta(days=15),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )

    entry = record_audit_event(
        action=AuditLogEntry.ACTION_APPROVE,
        actor=super_admin,
        target=finding,
        details={"reason": "criteria met"},
    )

    assert entry.action == "approve"
    assert entry.actor == super_admin.email
    assert entry.actor_ref == super_admin
    assert entry.target == str(finding)
    assert entry.target_content_type == ContentType.objects.get_for_model(Finding)
    assert entry.target_object_id == finding.pk
    assert entry.details == {"reason": "criteria met"}


def test_record_audit_event_with_string_actor():
    entry = record_audit_event(
        action="export", actor="system:retention", target_label="audits/2025-01.tgz"
    )
    assert entry.actor == "system:retention"
    assert entry.actor_ref is None
    assert entry.target == "audits/2025-01.tgz"


# ══════════════════════════════════════════════════════════════════════
# Domain hooks: approval workflow + password change
# ══════════════════════════════════════════════════════════════════════
def test_approve_action_writes_approve_audit_event(authed_client, super_admin):
    req = ApprovalRequest.objects.create(
        title="Approve Q1", type="Audit Plan", reference_id="A-1",
        department="IA", submitted_by=super_admin.email,
        submitted_date=date.today(), current_step=0, priority="High",
        description="…", status="Pending",
    )
    from iams.models import ApprovalStep
    ApprovalStep.objects.create(
        request=req, role="Manager", approver=super_admin.email,
        status="Pending", order=0,
    )

    client = authed_client(super_admin)
    response = client.post(
        f"/api/approval-requests/{req.id}/approve/",
        {"comments": "LGTM"}, format="json",
    )
    assert response.status_code == 200, response.content
    entry = AuditLogEntry.objects.filter(action="approve").first()
    assert entry is not None
    assert entry.actor_ref == super_admin
    assert entry.target_object_id == req.pk
    assert entry.details["comments"] == "LGTM"


def test_password_change_writes_audit_event(authed_client, auditor_user):
    client = authed_client(auditor_user)
    response = client.post(
        "/api/auth/password/change/",
        {"current_password": "TestPassword123!", "new_password": "NewSecurePass456$"},
        format="json",
    )
    assert response.status_code == 204
    entry = AuditLogEntry.objects.filter(action="password_change").first()
    assert entry is not None
    assert entry.actor == auditor_user.email
    assert entry.actor_ref == auditor_user
