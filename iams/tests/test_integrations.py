"""Tests for Phase 6 Track 2 — ERP / HR integrations.

Coverage:
  - HMAC: compute → verify round-trip; tampered body / header → False.
  - Inbound entity ingest: idempotent upsert by external_id; required
    fields enforced; IntegrationEvent rows captured for both accepted
    and rejected.
  - Inbound finding ingest: parent Audit resolution by external_id;
    auto-create when audit_title is provided; upsert idempotency.
  - Webhook endpoint: bad signature → 401; unknown resource → 404;
    unknown source → 404; bad payload → 400; success → 201/200.
  - Outbound user push: successful POST records accepted; HTTP non-2xx
    records failed; network exception records failed.
  - Signal handler fans out to all outbound-enabled targets.
  - REST surface: admin-only; secrets not echoed in responses.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

from iams.integrations import (
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    IngestError,
    compute_signature,
    ingest_auditable_entity,
    ingest_finding,
    push_user,
    push_user_to_all_targets,
    verify_signature,
)
from iams.models import (
    Audit,
    AuditableEntity,
    Finding,
    IntegrationEvent,
    IntegrationSource,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def inbound_source(db):
    return IntegrationSource.objects.create(
        name="sap",
        kind=IntegrationSource.KIND_SAP,
        inbound_enabled=True,
        inbound_secret="supersecret",
        status=IntegrationSource.STATUS_ACTIVE,
    )


@pytest.fixture
def outbound_source(db):
    return IntegrationSource.objects.create(
        name="hris",
        kind=IntegrationSource.KIND_HRIS,
        outbound_enabled=True,
        outbound_pushes_users=True,
        outbound_url="https://hris.example.com/users/",
        outbound_token="bearer-token-123",
        status=IntegrationSource.STATUS_ACTIVE,
    )


# ══════════════════════════════════════════════════════════════════════
# HMAC
# ══════════════════════════════════════════════════════════════════════
def test_signature_round_trip():
    body = b'{"hello":"world"}'
    sig = compute_signature("secret", body)
    assert sig.startswith(SIGNATURE_PREFIX)
    assert verify_signature(secret="secret", body=body, header_value=sig) is True


def test_signature_rejects_tampered_body():
    body = b'{"hello":"world"}'
    sig = compute_signature("secret", body)
    assert verify_signature(secret="secret", body=b'{"hello":"WORLD"}', header_value=sig) is False


def test_signature_rejects_wrong_secret():
    body = b'{"x":1}'
    sig = compute_signature("right", body)
    assert verify_signature(secret="wrong", body=body, header_value=sig) is False


def test_signature_empty_inputs_return_false():
    assert verify_signature(secret="", body=b"x", header_value="sha256=abc") is False
    assert verify_signature(secret="s", body=b"x", header_value="") is False


# ══════════════════════════════════════════════════════════════════════
# Inbound entity importer
# ══════════════════════════════════════════════════════════════════════
def test_ingest_entity_creates_new_row(inbound_source):
    entity, created = ingest_auditable_entity(inbound_source, {
        "external_id": "SAP-001",
        "name": "Treasury",
        "department": "Finance",
        "owner": "alice@iams.test",
        "risk_rating": "High",
    })
    assert created is True
    assert entity.name == "Treasury"
    assert entity.external_source == "sap"
    assert entity.external_id == "SAP-001"

    # IntegrationEvent recorded
    ev = IntegrationEvent.objects.filter(
        source=inbound_source, resource_type="auditable_entity",
    ).get()
    assert ev.status == IntegrationEvent.STATUS_ACCEPTED


def test_ingest_entity_is_idempotent(inbound_source):
    payload = {
        "external_id": "SAP-002", "name": "Payroll", "department": "HR",
    }
    e1, c1 = ingest_auditable_entity(inbound_source, payload)
    e2, c2 = ingest_auditable_entity(inbound_source, payload)
    assert c1 is True
    assert c2 is False
    assert e1.pk == e2.pk
    assert AuditableEntity.objects.filter(external_id="SAP-002").count() == 1


def test_ingest_entity_updates_mutable_fields(inbound_source):
    ingest_auditable_entity(inbound_source, {
        "external_id": "SAP-003", "name": "Old", "department": "X",
        "risk_rating": "Low",
    })
    entity, _ = ingest_auditable_entity(inbound_source, {
        "external_id": "SAP-003", "name": "New Name", "department": "X",
        "risk_rating": "Critical",
    })
    assert entity.name == "New Name"
    assert entity.risk_rating == "Critical"


def test_ingest_entity_rejects_missing_fields(inbound_source):
    with pytest.raises(IngestError, match="missing required fields"):
        ingest_auditable_entity(inbound_source, {"external_id": "X"})
    ev = IntegrationEvent.objects.filter(
        source=inbound_source, status=IntegrationEvent.STATUS_REJECTED,
    ).first()
    assert ev is not None
    assert "missing required fields" in ev.error


# ══════════════════════════════════════════════════════════════════════
# Inbound finding importer
# ══════════════════════════════════════════════════════════════════════
def test_ingest_finding_requires_known_audit(inbound_source):
    with pytest.raises(IngestError, match="no Audit"):
        ingest_finding(inbound_source, {
            "external_id": "F-1",
            "audit_external_id": "UNKNOWN",
            "title": "x", "severity": "Medium",
        })


def test_ingest_finding_creates_audit_on_the_fly(inbound_source):
    finding, created = ingest_finding(inbound_source, {
        "external_id": "F-2",
        "audit_external_id": "AUD-001",
        "audit_title": "Q1 SAP Audit",
        "title": "Reconciliation gap",
        "severity": "High",
        "owner": "auditor@iams.test",
        "department": "Finance",
    })
    assert created is True
    assert finding.title == "Reconciliation gap"
    assert finding.audit.title == "Q1 SAP Audit"
    assert finding.external_source == "sap"


def test_ingest_finding_idempotent_upsert(inbound_source):
    payload = {
        "external_id": "F-3",
        "audit_external_id": "AUD-002",
        "audit_title": "X", "title": "T", "severity": "Medium",
    }
    _, c1 = ingest_finding(inbound_source, payload)
    _, c2 = ingest_finding(inbound_source, {**payload, "severity": "Critical"})
    assert c1 is True
    assert c2 is False
    f = Finding.objects.get(external_id="F-3")
    assert f.severity == "Critical"


# ══════════════════════════════════════════════════════════════════════
# Webhook endpoint
# ══════════════════════════════════════════════════════════════════════
def test_webhook_rejects_bad_signature(api_client, inbound_source):
    body = json.dumps({"external_id": "x", "name": "n", "department": "d"})
    res = api_client.post(
        f"/api/integrations/webhooks/{inbound_source.id}/auditable-entities/",
        body, content_type="application/json",
        HTTP_X_IAMS_SIGNATURE="sha256=deadbeef",
    )
    assert res.status_code == 401
    assert res.json()["code"] == "signature_invalid"


def test_webhook_rejects_unknown_resource(api_client, inbound_source):
    body = json.dumps({})
    sig = compute_signature(inbound_source.inbound_secret, body.encode())
    res = api_client.post(
        f"/api/integrations/webhooks/{inbound_source.id}/bogus/",
        body, content_type="application/json",
        HTTP_X_IAMS_SIGNATURE=sig,
    )
    assert res.status_code == 404
    assert "supported" in res.json()


def test_webhook_rejects_unknown_source(api_client):
    import uuid
    fake_id = uuid.uuid4()
    res = api_client.post(
        f"/api/integrations/webhooks/{fake_id}/auditable-entities/",
        "{}", content_type="application/json",
        HTTP_X_IAMS_SIGNATURE="sha256=abc",
    )
    assert res.status_code == 404


def test_webhook_accepts_valid_payload(api_client, inbound_source):
    payload = {
        "external_id": "WHT-1",
        "name": "Webhook Test",
        "department": "QA",
    }
    body = json.dumps(payload)
    sig = compute_signature(inbound_source.inbound_secret, body.encode())
    res = api_client.post(
        f"/api/integrations/webhooks/{inbound_source.id}/auditable-entities/",
        body, content_type="application/json",
        HTTP_X_IAMS_SIGNATURE=sig,
    )
    assert res.status_code == 201, res.content
    body_res = res.json()
    assert body_res["created"] is True
    assert AuditableEntity.objects.filter(external_id="WHT-1").exists()


def test_webhook_rejects_disabled_source(api_client):
    src = IntegrationSource.objects.create(
        name="paused", inbound_enabled=False,
        inbound_secret="x", status=IntegrationSource.STATUS_ACTIVE,
    )
    res = api_client.post(
        f"/api/integrations/webhooks/{src.id}/auditable-entities/",
        "{}", content_type="application/json",
        HTTP_X_IAMS_SIGNATURE="sha256=abc",
    )
    assert res.status_code == 404


def test_webhook_returns_400_on_invalid_payload(api_client, inbound_source):
    body = json.dumps({"external_id": "X"})  # missing name + department
    sig = compute_signature(inbound_source.inbound_secret, body.encode())
    res = api_client.post(
        f"/api/integrations/webhooks/{inbound_source.id}/auditable-entities/",
        body, content_type="application/json",
        HTTP_X_IAMS_SIGNATURE=sig,
    )
    assert res.status_code == 400
    assert res.json()["code"] == "payload_invalid"


# ══════════════════════════════════════════════════════════════════════
# Outbound user push
# ══════════════════════════════════════════════════════════════════════
def test_push_user_success(outbound_source, super_admin):
    mock_response = MagicMock(status_code=200, text="ok")
    with patch("iams.integrations.requests.post", return_value=mock_response) as p:
        event = push_user(outbound_source, super_admin)
    assert event.status == IntegrationEvent.STATUS_ACCEPTED
    # The signature header is set with a valid HMAC of the body.
    sent_body = p.call_args.kwargs["data"]
    headers = p.call_args.kwargs["headers"]
    assert SIGNATURE_HEADER in headers
    assert headers["Authorization"].startswith("Bearer ")
    expected = compute_signature(outbound_source.outbound_token, sent_body)
    assert headers[SIGNATURE_HEADER] == expected


def test_push_user_http_failure_recorded(outbound_source, super_admin):
    mock_response = MagicMock(status_code=500, text="server error")
    with patch("iams.integrations.requests.post", return_value=mock_response):
        event = push_user(outbound_source, super_admin)
    assert event.status == IntegrationEvent.STATUS_FAILED
    assert "HTTP 500" in event.error


def test_push_user_network_exception_recorded(outbound_source, super_admin):
    import requests
    with patch(
        "iams.integrations.requests.post",
        side_effect=requests.ConnectionError("no route"),
    ):
        event = push_user(outbound_source, super_admin)
    assert event.status == IntegrationEvent.STATUS_FAILED
    assert "ConnectionError" in event.error


def test_push_user_to_all_targets_fans_out(super_admin, outbound_source):
    other = IntegrationSource.objects.create(
        name="ad", kind=IntegrationSource.KIND_AD,
        outbound_enabled=True, outbound_pushes_users=True,
        outbound_url="https://ad.example/users/", outbound_token="t",
        status=IntegrationSource.STATUS_ACTIVE,
    )
    # Paused source should be skipped
    IntegrationSource.objects.create(
        name="paused-hris", outbound_enabled=True, outbound_pushes_users=True,
        outbound_url="https://paused/", outbound_token="t",
        status=IntegrationSource.STATUS_PAUSED,
    )
    mock_response = MagicMock(status_code=204, text="")
    with patch("iams.integrations.requests.post", return_value=mock_response):
        events = push_user_to_all_targets(super_admin)
    sources_hit = {e.source_id for e in events}
    assert outbound_source.id in sources_hit
    assert other.id in sources_hit
    assert len(events) == 2  # paused excluded


# ══════════════════════════════════════════════════════════════════════
# Signal fan-out (User post_save → outbound push)
# ══════════════════════════════════════════════════════════════════════
def test_user_save_triggers_outbound_signal(outbound_source):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    mock_response = MagicMock(status_code=200, text="ok")
    with patch("iams.integrations.requests.post", return_value=mock_response) as p:
        User.objects.create_user(
            username="newuser", email="new@iams.test", password="TestPassword123!",
        )
    # The mock got called at least once (the fan-out hit our outbound source).
    assert p.called


# ══════════════════════════════════════════════════════════════════════
# REST surface
# ══════════════════════════════════════════════════════════════════════
def test_integration_source_list_admin_only(authed_client, auditor_user, super_admin, inbound_source):
    assert authed_client(auditor_user).get("/api/integrations/sources/").status_code == 403
    assert authed_client(super_admin).get("/api/integrations/sources/").status_code == 200


def test_integration_source_response_omits_secret(authed_client, super_admin, inbound_source):
    res = authed_client(super_admin).get(f"/api/integrations/sources/{inbound_source.id}/")
    assert res.status_code == 200
    body = res.json()
    assert "inbound_secret" not in body
    assert "inboundSecret" not in body


def test_integration_event_filters(authed_client, super_admin, inbound_source):
    IntegrationEvent.objects.create(
        source=inbound_source, direction="inbound",
        resource_type="auditable_entity", external_id="A",
        status="accepted", payload={},
    )
    IntegrationEvent.objects.create(
        source=inbound_source, direction="outbound",
        resource_type="user", external_id="42",
        status="failed", payload={},
    )
    body = authed_client(super_admin).get(
        f"/api/integrations/events/?direction=inbound&source_id={inbound_source.id}",
    ).json()
    rows = body["results"] if isinstance(body, dict) else body
    assert len(rows) == 1
    assert rows[0]["direction"] == "inbound"
