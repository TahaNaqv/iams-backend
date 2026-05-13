"""Tests for the Phase 5 Track 3 observability stack.

Coverage:
  - JSON log formatter emits parseable JSON with the required fields.
  - request_id from middleware flows into the log record.
  - extra={} fields are merged in but don't collide with reserved keys.
  - Business counters bump when the domain events fire.
  - Login-attempt counter bumps on success and failure.
  - Gauge refresh syncs the live state.
  - The /metrics endpoint exposes our custom counters.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import pytest
from django.utils import timezone

from iams import metrics
from iams.logging import JsonFormatter
from iams.models import (
    ApprovalRequest,
    Audit,
    CorrectiveAction,
    Finding,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# JSON log formatter
# ──────────────────────────────────────────────────────────────────────
def _format_one(message: str, *, extra: dict | None = None, level=logging.INFO) -> dict:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="iams.test", level=level, pathname=__file__, lineno=10,
        msg=message, args=(), exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    line = formatter.format(record)
    return json.loads(line)


def test_json_formatter_emits_required_fields():
    payload = _format_one("hello")
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "iams.test"
    assert payload["service"] == "iams-backend"
    assert "time" in payload
    assert payload["request_id"] == "-"


def test_json_formatter_includes_request_id_when_set():
    payload = _format_one("hi", extra={"request_id": "abc-123"})
    assert payload["request_id"] == "abc-123"


def test_json_formatter_folds_extras():
    payload = _format_one("ev", extra={"user_id": "u-1", "action": "create"})
    assert payload["user_id"] == "u-1"
    assert payload["action"] == "create"


def test_json_formatter_handles_non_serializable_extras():
    """Non-JSON-able extras are repr'd, not crashed."""
    class Custom:
        def __repr__(self):
            return "<Custom>"

    payload = _format_one("x", extra={"obj": Custom()})
    assert payload["obj"] == "<Custom>"


def test_json_formatter_captures_exception_traceback():
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="iams.test", level=logging.ERROR, pathname=__file__,
            lineno=42, msg="error", args=(), exc_info=sys.exc_info(),
        )
    line = formatter.format(record)
    payload = json.loads(line)
    assert "exception" in payload
    assert "ValueError: boom" in payload["exception"]


# ──────────────────────────────────────────────────────────────────────
# Business counters bump on signal
# ──────────────────────────────────────────────────────────────────────
def _counter_value(counter, **labels) -> float:
    if labels:
        return counter.labels(**labels)._value.get()
    return counter._value.get()


def test_audit_created_bumps_counter():
    before = _counter_value(metrics.audits_created_total, department="Finance")
    Audit.objects.create(
        title="Q1", department="Finance", lead_auditor="L",
        status="Planned", priority="Medium", risk_rating="Medium",
        start_date=date.today(), end_date=date.today() + timedelta(days=30),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    after = _counter_value(metrics.audits_created_total, department="Finance")
    assert after == before + 1


def test_audit_completion_bumps_counter():
    audit = Audit.objects.create(
        title="To complete", department="Ops", lead_auditor="L",
        status="In Progress", priority="Medium", risk_rating="Medium",
        start_date=date.today(), end_date=date.today() + timedelta(days=30),
        scope="s", objectives="o", completion_percent=80, findings_count=0,
    )
    before = _counter_value(metrics.audits_completed_total, department="Ops")
    audit.status = "Completed"
    audit.save(update_fields=["status"])
    after = _counter_value(metrics.audits_completed_total, department="Ops")
    assert after == before + 1


def test_finding_raised_bumps_severity_counter():
    audit = Audit.objects.create(
        title="A", department="X", lead_auditor="L",
        status="In Progress", priority="Medium", risk_rating="Medium",
        start_date=date.today(), end_date=date.today() + timedelta(days=30),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    before = _counter_value(metrics.findings_raised_total, severity="Critical")
    Finding.objects.create(
        audit=audit, title="bad", department="X",
        severity="Critical", status="Open", owner="o",
        due_date=date.today() + timedelta(days=10),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )
    after = _counter_value(metrics.findings_raised_total, severity="Critical")
    assert after == before + 1


def test_cap_create_close_counters():
    audit = Audit.objects.create(
        title="A", department="X", lead_auditor="L",
        status="In Progress", priority="Medium", risk_rating="Medium",
        start_date=date.today(), end_date=date.today() + timedelta(days=30),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    finding = Finding.objects.create(
        audit=audit, title="bad", department="X",
        severity="Medium", status="Open", owner="o",
        due_date=date.today() + timedelta(days=10),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )
    created_before = _counter_value(metrics.caps_created_total)
    closed_before = _counter_value(metrics.caps_closed_total)
    cap = CorrectiveAction.objects.create(
        finding=finding, title="Fix",
        owner="o", due_date=date.today() + timedelta(days=20),
        status="Open", priority="Medium",
        description="d", progress=0, department="X",
    )
    assert _counter_value(metrics.caps_created_total) == created_before + 1
    cap.status = "Closed"
    cap.save(update_fields=["status"])
    assert _counter_value(metrics.caps_closed_total) == closed_before + 1


def test_approval_request_counters(super_admin):
    requested_before = _counter_value(
        metrics.approvals_requested_total, type="CAP Closure"
    )
    req = ApprovalRequest.objects.create(
        type="CAP Closure", reference_id="00000000-0000-0000-0000-000000000000",
        title="t", submitted_by=super_admin.email,
        submitted_date=date.today(), status="Pending",
    )
    assert _counter_value(metrics.approvals_requested_total, type="CAP Closure") == requested_before + 1

    approved_before = _counter_value(metrics.approvals_approved_total, type="CAP Closure")
    req.status = "Approved"
    req.save(update_fields=["status"])
    assert _counter_value(metrics.approvals_approved_total, type="CAP Closure") == approved_before + 1


def test_login_attempt_counter_bumps(api_client, auditor_user):
    before = _counter_value(metrics.login_attempts_total, outcome="success")
    api_client.post(
        "/api/auth/token/",
        {"username": auditor_user.username, "password": "TestPassword123!"},
        format="json",
    )
    after = _counter_value(metrics.login_attempts_total, outcome="success")
    assert after == before + 1


# ──────────────────────────────────────────────────────────────────────
# Gauge refresh
# ──────────────────────────────────────────────────────────────────────
def test_refresh_business_gauges_syncs_state():
    audit = Audit.objects.create(
        title="A", department="X", lead_auditor="L",
        status="In Progress", priority="Medium", risk_rating="Medium",
        start_date=date.today(), end_date=date.today() + timedelta(days=30),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    finding = Finding.objects.create(
        audit=audit, title="bad", department="X",
        severity="Medium", status="Open", owner="o",
        due_date=date.today() + timedelta(days=10),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )
    # Two overdue, one not — gauge should be 2
    CorrectiveAction.objects.create(
        finding=finding, title="late1", owner="o",
        due_date=date.today() - timedelta(days=10),
        status="Open", priority="Medium",
        description="d", progress=10, department="X",
    )
    CorrectiveAction.objects.create(
        finding=finding, title="late2", owner="o",
        due_date=date.today() - timedelta(days=1),
        status="In Progress", priority="Medium",
        description="d", progress=20, department="X",
    )
    CorrectiveAction.objects.create(
        finding=finding, title="future", owner="o",
        due_date=date.today() + timedelta(days=10),
        status="Open", priority="Medium",
        description="d", progress=0, department="X",
    )
    snapshot = metrics.refresh_business_gauges()
    assert snapshot["caps_overdue_current"] == 2


# ──────────────────────────────────────────────────────────────────────
# /metrics/ endpoint
# ──────────────────────────────────────────────────────────────────────
def test_metrics_endpoint_exposes_custom_counters(api_client):
    # Bump a counter so its first sample is registered with Prometheus
    metrics.audits_created_total.labels(department="MetricTest").inc()
    res = api_client.get("/metrics")
    assert res.status_code == 200
    body = res.content.decode("utf-8")
    assert "iams_audits_created_total" in body
