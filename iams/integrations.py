"""ERP / HR integrations (Phase 6 Track 2, FR-INT-02, FR-INT-03).

Three concerns, one module:

  1. **HMAC verification** of inbound webhook signatures. External
     systems (SAP, Oracle, Odoo) post JSON to
     ``/api/integrations/webhooks/<source-id>/<resource>/`` with a
     ``X-IAMS-Signature: sha256=<hex>`` header. We re-compute the
     signature using the per-source ``inbound_secret`` and reject any
     mismatch with 401.

  2. **Inbound importers** for ``auditable_entity`` and ``finding``.
     Both are *idempotent upserts* keyed on
     ``(external_source, external_id)`` — re-posting the same payload
     updates the existing row instead of creating duplicates. Every
     attempt (success, validation failure, signature failure) is
     captured in an ``IntegrationEvent`` row.

  3. **Outbound user push** to AD / HRIS. When a User is created /
     updated, every ``IntegrationSource`` with
     ``outbound_pushes_users=True`` receives a JSON POST containing the
     user payload. Network failures are captured as ``IntegrationEvent``
     rows with ``status=failed`` so the operator can retry.

Design notes:

  - Inbound payloads are validated against a small set of required
    fields. Unknown / extra fields are stored on the IntegrationEvent
    row so a payload contract change shows up in the audit log without
    crashing the importer.

  - Outbound retry isn't built into this module — that's a Celery
    retry decorator at the task layer. Network failures are *logged*
    here, not retried.

  - HMAC uses ``hmac.compare_digest`` for constant-time comparison.
    Without this, a timing attack could leak the secret one byte at a
    time.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import requests
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# HMAC signing / verification
# ──────────────────────────────────────────────────────────────────────
SIGNATURE_HEADER = "X-IAMS-Signature"
SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    """Return the ``sha256=<hex>`` signature for ``body``."""
    if not secret:
        return ""
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return f"{SIGNATURE_PREFIX}{mac.hexdigest()}"


def verify_signature(*, secret: str, body: bytes, header_value: str) -> bool:
    """Constant-time check of the inbound signature header."""
    if not secret or not header_value:
        return False
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected, header_value)


# ──────────────────────────────────────────────────────────────────────
# Inbound importers
# ──────────────────────────────────────────────────────────────────────
class IngestError(Exception):
    """Raised by an importer when the payload is invalid."""


def _record_event(*, source, direction, resource_type, external_id, status,
                  payload, error=""):
    from iams.models import IntegrationEvent
    return IntegrationEvent.objects.create(
        source=source,
        direction=direction,
        resource_type=resource_type,
        external_id=external_id[:128] if external_id else "",
        status=status,
        error=error[:2000] if error else "",
        payload=payload or {},
    )


REQUIRED_ENTITY_FIELDS = {"external_id", "name", "department"}
REQUIRED_FINDING_FIELDS = {"external_id", "audit_external_id", "title", "severity"}


def ingest_auditable_entity(source, payload: dict[str, Any]):
    """Idempotent upsert of an ``AuditableEntity`` from an inbound webhook.

    Required payload fields:
      - ``external_id``: caller's identifier (SAP CompanyCode, Odoo
        ``res.partner.id``, etc.)
      - ``name`` / ``department``: canonical attributes

    Optional fields: ``owner``, ``risk_rating``, ``status``.

    Returns the (entity, created_bool).
    """
    from iams.models import AuditableEntity, IntegrationEvent

    # Validate *before* opening the atomic block so a rejection event
    # row persists even when we raise IngestError.
    missing = REQUIRED_ENTITY_FIELDS - payload.keys()
    if missing:
        _record_event(
            source=source, direction=IntegrationEvent.DIRECTION_INBOUND,
            resource_type="auditable_entity",
            external_id=str(payload.get("external_id", "")),
            status=IntegrationEvent.STATUS_REJECTED, payload=payload,
            error=f"missing required fields: {sorted(missing)}",
        )
        raise IngestError(f"missing required fields: {sorted(missing)}")

    with transaction.atomic():
        defaults = {
            "name": payload["name"],
            "department": payload["department"],
            "owner": payload.get("owner", ""),
            "risk_rating": payload.get("risk_rating", "Medium"),
            "status": payload.get("status", "Active"),
        }
        entity, created = AuditableEntity.objects.update_or_create(
            external_source=source.name,
            external_id=str(payload["external_id"]),
            defaults=defaults,
        )
        source.last_inbound_at = timezone.now()
        source.last_error = ""
        source.save(update_fields=["last_inbound_at", "last_error", "updated_at"])
        _record_event(
            source=source, direction=IntegrationEvent.DIRECTION_INBOUND,
            resource_type="auditable_entity",
            external_id=str(payload["external_id"]),
            status=IntegrationEvent.STATUS_ACCEPTED, payload=payload,
        )
    return entity, created


def ingest_finding(source, payload: dict[str, Any]):
    """Idempotent upsert of a ``Finding`` from an inbound webhook.

    Required payload fields:
      - ``external_id`` — caller's identifier for this finding
      - ``audit_external_id`` — must match an Audit whose
        ``external_id``/``external_source`` we've previously ingested
        (or one we can create on the fly if ``audit_title`` is present)
      - ``title``, ``severity``

    Optional: ``status``, ``owner``, ``due_date``, ``description``,
    ``root_cause``, ``recommendation``, ``department``.
    """
    from datetime import date

    from iams.models import Audit, Finding, IntegrationEvent

    # Validate *before* opening the atomic block so rejection events
    # persist even when we raise IngestError.
    missing = REQUIRED_FINDING_FIELDS - payload.keys()
    if missing:
        _record_event(
            source=source, direction=IntegrationEvent.DIRECTION_INBOUND,
            resource_type="finding",
            external_id=str(payload.get("external_id", "")),
            status=IntegrationEvent.STATUS_REJECTED, payload=payload,
            error=f"missing required fields: {sorted(missing)}",
        )
        raise IngestError(f"missing required fields: {sorted(missing)}")

    audit_external_id = str(payload["audit_external_id"])
    audit_exists = Audit.objects.filter(
        external_source=source.name,
        external_id=audit_external_id,
    ).exists()
    if not audit_exists and "audit_title" not in payload:
        _record_event(
            source=source, direction=IntegrationEvent.DIRECTION_INBOUND,
            resource_type="finding",
            external_id=str(payload["external_id"]),
            status=IntegrationEvent.STATUS_REJECTED, payload=payload,
            error=f"no Audit with external_id={audit_external_id} and audit_title not provided",
        )
        raise IngestError(f"no Audit with external_id={audit_external_id}")

    with transaction.atomic():
        audit = Audit.objects.filter(
            external_source=source.name,
            external_id=audit_external_id,
        ).first()
        if audit is None:
            audit = Audit.objects.create(
                title=payload["audit_title"],
                department=payload.get("audit_department",
                                       payload.get("department", "Unknown")),
                lead_auditor=payload.get("audit_lead_auditor", "auto@iams.local"),
                status="In Progress",
                start_date=date.today(),
                end_date=date.today(),
                scope=payload.get("audit_scope", ""),
                objectives=payload.get("audit_objectives", ""),
                risk_rating=payload.get("audit_risk_rating", "Medium"),
                external_source=source.name,
                external_id=audit_external_id,
            )

        due_date = payload.get("due_date")
        if isinstance(due_date, str):
            from datetime import datetime
            try:
                due_date = datetime.fromisoformat(due_date).date()
            except ValueError:
                due_date = None
        if due_date is None:
            due_date = date.today()

        defaults = {
            "title": payload["title"],
            "audit": audit,
            "department": payload.get("department", audit.department),
            "severity": payload["severity"],
            "status": payload.get("status", "Open"),
            "owner": payload.get("owner", ""),
            "due_date": due_date,
            "description": payload.get("description", ""),
            "root_cause": payload.get("root_cause", ""),
            "recommendation": payload.get("recommendation", ""),
            "created_date": date.today(),
        }
        finding, created = Finding.objects.update_or_create(
            external_source=source.name,
            external_id=str(payload["external_id"]),
            defaults=defaults,
        )
        source.last_inbound_at = timezone.now()
        source.last_error = ""
        source.save(update_fields=["last_inbound_at", "last_error", "updated_at"])
        _record_event(
            source=source, direction=IntegrationEvent.DIRECTION_INBOUND,
            resource_type="finding",
            external_id=str(payload["external_id"]),
            status=IntegrationEvent.STATUS_ACCEPTED, payload=payload,
        )
    return finding, created


# ──────────────────────────────────────────────────────────────────────
# Outbound: user push
# ──────────────────────────────────────────────────────────────────────
def serialize_user_for_outbound(user) -> dict[str, Any]:
    """Build the user payload sent to AD/HRIS outbound targets.

    Intentionally narrow: just the fields HRIS actually wants, never
    the password / MFA / lockout state.
    """
    profile = getattr(user, "profile", None)
    return {
        "external_id": str(user.pk),
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_active": user.is_active,
        "role": profile.role.name if profile and profile.role else None,
        "department": profile.department if profile else "",
        "status": profile.status if profile else "Active",
    }


def push_user(source, user, *, timeout_s: float = 10.0):
    """POST the user payload to ``source.outbound_url``.

    Records an ``IntegrationEvent`` row regardless of outcome.
    Returns the event row (status = accepted | failed).
    """
    from iams.models import IntegrationEvent

    payload = serialize_user_for_outbound(user)
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: compute_signature(source.outbound_token or "", body),
    }
    if source.outbound_token:
        headers["Authorization"] = f"Bearer {source.outbound_token}"

    try:
        res = requests.post(
            source.outbound_url, data=body, headers=headers, timeout=timeout_s,
        )
        ok = 200 <= res.status_code < 300
        event = _record_event(
            source=source,
            direction=IntegrationEvent.DIRECTION_OUTBOUND,
            resource_type="user",
            external_id=str(user.pk),
            status=IntegrationEvent.STATUS_ACCEPTED if ok else IntegrationEvent.STATUS_FAILED,
            payload=payload,
            error="" if ok else f"HTTP {res.status_code}: {res.text[:500]}",
        )
        source.last_outbound_at = timezone.now()
        if not ok:
            source.last_error = f"user push: HTTP {res.status_code}"
            source.save(update_fields=["last_outbound_at", "last_error", "updated_at"])
        else:
            source.last_error = ""
            source.save(update_fields=["last_outbound_at", "last_error", "updated_at"])
        return event
    except requests.RequestException as exc:
        event = _record_event(
            source=source,
            direction=IntegrationEvent.DIRECTION_OUTBOUND,
            resource_type="user",
            external_id=str(user.pk),
            status=IntegrationEvent.STATUS_FAILED,
            payload=payload,
            error=f"{type(exc).__name__}: {exc}"[:2000],
        )
        source.last_error = f"user push: {type(exc).__name__}"
        source.save(update_fields=["last_error", "updated_at"])
        logger.warning(
            "integration: outbound user push failed for source=%s",
            source.name,
            extra={"source": source.name, "user_id": str(user.pk)},
        )
        return event


def push_user_to_all_targets(user):
    """Iterate every active source with outbound_pushes_users=True."""
    from iams.models import IntegrationSource

    targets = IntegrationSource.objects.filter(
        status=IntegrationSource.STATUS_ACTIVE,
        outbound_enabled=True,
        outbound_pushes_users=True,
    )
    return [push_user(t, user) for t in targets]
