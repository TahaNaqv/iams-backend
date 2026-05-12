"""Automatic audit-trail capture for DRF ViewSets.

Apply the ``AuditedViewSetMixin`` to any ``ModelViewSet`` and every
create / update / delete that flows through it will write a row to
``AuditLogEntry`` with:

  - **actor** + **actor_ref** from ``request.user``
  - **action** — ``create`` / ``update`` / ``delete``
  - **target** — ``str(instance)``
  - **target_content_type** + **target_object_id** — GenericFK to the row
  - **timestamp** — ``timezone.now()``
  - **request_id** — from the ``X-Request-ID`` middleware context
  - **ip_address** — from ``REMOTE_ADDR`` (or ``X-Forwarded-For`` first hop)
  - **user_agent** — truncated to 400 chars
  - **changes** — for updates: ``{field: {old, new}}`` of changed fields;
                  for creates/deletes: ``{"snapshot": {...}}``

Excluded fields (passwords, derived timestamps, FK ``*_id`` aliases that
duplicate the real ForeignKey, large binary file fields) are configurable
per-viewset via ``audit_excluded_fields``.

The mixin is **idempotent**: applying it twice does not double-log; it
captures at the ``perform_*`` layer, which DRF only calls once per request.

Also exports a procedural helper for non-CRUD events (logins, approvals,
exports, AV quarantine) — see ``record_audit_event``.
"""
from __future__ import annotations

import logging
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from iams.middleware import get_current_request_id
from iams.models import AuditLogEntry

logger = logging.getLogger(__name__)


# Fields we never log — they're either noisy (auto timestamps), derived
# (FK ``*_id`` aliases that mirror the real ForeignKey), or sensitive.
_GLOBAL_EXCLUDED_FIELDS: set[str] = {
    "id",
    "created_at",
    "updated_at",
    "password",
    "last_login",
    # FileField: comparing file bytes is expensive and meaningless;
    # uploads are tracked via a separate file_upload action.
}


def _serialize_field_value(value: Any) -> Any:
    """Make a field value JSON-serializable for the ``changes`` payload."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize_field_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_field_value(v) for k, v in value.items()}
    # Dates / datetimes / UUIDs / Decimals / FileField etc. — coerce to str.
    return str(value)


def _snapshot(instance: models.Model, excluded: set[str]) -> dict[str, Any]:
    """Build a {field_name: value} snapshot, skipping excluded + file fields."""
    snapshot: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        name = field.name
        if name in excluded:
            continue
        if isinstance(field, models.FileField):
            # Record the file path (cheap, deterministic) — never the bytes.
            file_value = getattr(instance, name, None)
            snapshot[name] = getattr(file_value, "name", None) if file_value else None
            continue
        try:
            snapshot[name] = _serialize_field_value(getattr(instance, name))
        except Exception:  # noqa: BLE001 — never let a snapshot failure crash the request
            logger.exception("audit snapshot: failed to read %s.%s", instance.__class__.__name__, name)
            snapshot[name] = "<unreadable>"
    return snapshot


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Compute a ``{field: {old, new}}`` diff between two snapshots."""
    diff: dict[str, dict[str, Any]] = {}
    keys = set(before) | set(after)
    for key in keys:
        old_value = before.get(key)
        new_value = after.get(key)
        if old_value != new_value:
            diff[key] = {"old": old_value, "new": new_value}
    return diff


def _request_metadata(request) -> dict[str, str]:
    """Extract IP, user agent, request_id from a DRF request."""
    if request is None:
        return {"ip_address": None, "user_agent": "", "request_id": get_current_request_id()}
    # X-Forwarded-For wins if present (we trust the nginx proxy);
    # otherwise fall back to REMOTE_ADDR.
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")
    ua = (request.META.get("HTTP_USER_AGENT") or "")[:400]
    return {"ip_address": ip or None, "user_agent": ua, "request_id": get_current_request_id()}


def record_audit_event(
    *,
    action: str,
    actor: Any = None,
    target: Any = None,
    target_label: str = "",
    changes: dict | None = None,
    details: dict | None = None,
    request=None,
) -> AuditLogEntry:
    """Procedural helper for non-CRUD events (login, approval, export, etc.).

    Args:
        action:       One of the ``AuditLogEntry.ACTION_*`` constants.
        actor:        ``User`` instance or display string.
        target:       Optional model instance the action concerns.
        target_label: Human label if no model instance is available.
        changes:      Diff payload (``{field: {old, new}}``).
        details:      Free-form JSON context.
        request:      DRF request — used to pull IP, user-agent, request_id.
    """
    actor_user = actor if hasattr(actor, "pk") else None
    actor_display: str
    if hasattr(actor, "email"):
        actor_display = actor.email or actor.get_username()
    elif isinstance(actor, str):
        actor_display = actor
    else:
        actor_display = "system"

    target_ct = None
    target_id = None
    if target is not None and hasattr(target, "pk"):
        target_ct = ContentType.objects.get_for_model(target.__class__)
        target_id = target.pk
        if not target_label:
            target_label = str(target)

    meta = _request_metadata(request)

    return AuditLogEntry.objects.create(
        actor=actor_display[:200],
        actor_ref=actor_user,
        action=action[:64],
        target=target_label[:255],
        target_content_type=target_ct,
        target_object_id=target_id,
        timestamp=timezone.now(),
        request_id=meta["request_id"][:64],
        ip_address=meta["ip_address"],
        user_agent=meta["user_agent"],
        changes=changes or {},
        details=details or {},
    )


# ──────────────────────────────────────────────────────────────────────
# Mixin
# ──────────────────────────────────────────────────────────────────────
class AuditedViewSetMixin:
    """Drop-in mixin for DRF ViewSets.

    Captures audit log entries on ``perform_create`` / ``perform_update``
    / ``perform_destroy`` automatically. To opt a specific viewset out,
    set ``audit_enabled = False``.
    """

    audit_enabled: bool = True
    audit_excluded_fields: set[str] = set()

    def _audit_excluded(self) -> set[str]:
        return _GLOBAL_EXCLUDED_FIELDS | set(self.audit_excluded_fields)

    def _audit_actor(self):
        request = getattr(self, "request", None)
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None, "anonymous"
        display = getattr(user, "email", None) or user.get_username()
        return user, display

    def _audit_capture(
        self,
        *,
        action: str,
        instance: models.Model,
        changes: dict | None = None,
    ) -> None:
        if not self.audit_enabled:
            return
        try:
            actor_user, actor_display = self._audit_actor()
            meta = _request_metadata(getattr(self, "request", None))
            AuditLogEntry.objects.create(
                actor=actor_display[:200],
                actor_ref=actor_user,
                action=action[:64],
                target=str(instance)[:255],
                target_content_type=ContentType.objects.get_for_model(instance.__class__),
                target_object_id=instance.pk,
                timestamp=timezone.now(),
                request_id=meta["request_id"][:64],
                ip_address=meta["ip_address"],
                user_agent=meta["user_agent"],
                changes=changes or {},
                details={},
            )
        except Exception:  # noqa: BLE001 — audit failure must never break the user action
            logger.exception(
                "audit capture failed",
                extra={"action": action, "model": instance.__class__.__name__},
            )

    # ── DRF hooks ──────────────────────────────────────────────────
    def perform_create(self, serializer) -> None:
        instance = serializer.save()
        snapshot = _snapshot(instance, self._audit_excluded())
        self._audit_capture(
            action=AuditLogEntry.ACTION_CREATE,
            instance=instance,
            changes={"snapshot": snapshot},
        )

    def perform_update(self, serializer) -> None:
        excluded = self._audit_excluded()
        before = _snapshot(serializer.instance, excluded)
        instance = serializer.save()
        after = _snapshot(instance, excluded)
        diff = _diff(before, after)
        # If nothing changed (idempotent PATCH), skip — no point in noise.
        if not diff:
            return
        self._audit_capture(
            action=AuditLogEntry.ACTION_UPDATE,
            instance=instance,
            changes=diff,
        )

    def perform_destroy(self, instance) -> None:
        snapshot = _snapshot(instance, self._audit_excluded())
        target_label = str(instance)[:255]
        target_pk = instance.pk
        target_ct = ContentType.objects.get_for_model(instance.__class__)
        instance.delete()
        # Build the entry directly — ``instance`` is gone, can't go through
        # ``_audit_capture`` (which derives target_content_type from instance).
        try:
            actor_user, actor_display = self._audit_actor()
            meta = _request_metadata(getattr(self, "request", None))
            AuditLogEntry.objects.create(
                actor=actor_display[:200],
                actor_ref=actor_user,
                action=AuditLogEntry.ACTION_DELETE,
                target=target_label,
                target_content_type=target_ct,
                target_object_id=target_pk,
                timestamp=timezone.now(),
                request_id=meta["request_id"][:64],
                ip_address=meta["ip_address"],
                user_agent=meta["user_agent"],
                changes={"snapshot": snapshot},
                details={},
            )
        except Exception:  # noqa: BLE001
            logger.exception("audit capture failed on destroy")
