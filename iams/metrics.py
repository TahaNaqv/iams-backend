"""Custom Prometheus metrics for IAMS business events (Phase 5 Track 3).

`django-prometheus` already exposes the standard metrics (request
latency histograms, DB connection pool, GC stats). This module adds
the **business-level** counters / gauges that the Grafana board needs:

  - Audits created, audits completed (by department)
  - Findings raised (by severity)
  - CAPs created, CAPs closed, CAPs overdue (rolling)
  - Approvals requested, approved, rejected
  - Login outcomes (success / failed / locked / mfa_required)
  - Report jobs (created / completed / failed)

All counters are imported lazily so any caller-side metric mutations
that happen before app-ready don't blow up. Counters and gauges live
in the default Prometheus registry; ``/metrics/`` (mounted by
``django_prometheus.urls``) serves them.

Cardinality rules:
  - Per-department labels are kept (~50 departments max in practice).
  - Per-severity / outcome labels are bounded enums.
  - **Never** label by audit_id / finding_id / user_id — that would
    explode cardinality. Counters answer "how many" not "which one";
    the audit trail handles per-event detail.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge


# ──────────────────────────────────────────────────────────────────────
# Audits / Findings / CAPs lifecycle
# ──────────────────────────────────────────────────────────────────────
audits_created_total = Counter(
    "iams_audits_created_total",
    "Audits created (lifecycle counter).",
    ["department"],
)

audits_completed_total = Counter(
    "iams_audits_completed_total",
    "Audits transitioned to status='Completed'.",
    ["department"],
)

findings_raised_total = Counter(
    "iams_findings_raised_total",
    "Findings raised (lifecycle counter).",
    ["severity"],
)

caps_created_total = Counter(
    "iams_caps_created_total",
    "CAPs created (lifecycle counter).",
)

caps_closed_total = Counter(
    "iams_caps_closed_total",
    "CAPs transitioned to status='Closed'.",
)

caps_overdue_current = Gauge(
    "iams_caps_overdue_current",
    "Current number of CAPs past their due_date and not closed.",
)


# ──────────────────────────────────────────────────────────────────────
# Approvals
# ──────────────────────────────────────────────────────────────────────
approvals_requested_total = Counter(
    "iams_approvals_requested_total",
    "ApprovalRequest rows created.",
    ["type"],
)

approvals_approved_total = Counter(
    "iams_approvals_approved_total",
    "ApprovalRequest rows reaching final approval.",
    ["type"],
)

approvals_rejected_total = Counter(
    "iams_approvals_rejected_total",
    "ApprovalRequest rows rejected at any step.",
    ["type"],
)

approvals_pending_current = Gauge(
    "iams_approvals_pending_current",
    "Current number of ApprovalRequest rows in status='Pending'.",
)


# ──────────────────────────────────────────────────────────────────────
# Auth / security
# ──────────────────────────────────────────────────────────────────────
login_attempts_total = Counter(
    "iams_login_attempts_total",
    "Authentication attempts grouped by outcome.",
    ["outcome"],
)

account_lockouts_total = Counter(
    "iams_account_lockouts_total",
    "Account lockouts opened (by reason).",
    ["reason"],
)


# ──────────────────────────────────────────────────────────────────────
# Reports
# ──────────────────────────────────────────────────────────────────────
report_jobs_total = Counter(
    "iams_report_jobs_total",
    "Report jobs queued, grouped by kind.",
    ["kind"],
)

report_jobs_completed_total = Counter(
    "iams_report_jobs_completed_total",
    "Report jobs that completed successfully (kind label).",
    ["kind"],
)

report_jobs_failed_total = Counter(
    "iams_report_jobs_failed_total",
    "Report jobs that failed (kind label).",
    ["kind"],
)


# ──────────────────────────────────────────────────────────────────────
# Audit universe (Phase 7)
# ──────────────────────────────────────────────────────────────────────
audit_universe_entities_created_total = Counter(
    "iams_audit_universe_entities_created_total",
    "AuditableEntity rows created (any path: API, clone, bulk import).",
)

audit_universe_entities_updated_total = Counter(
    "iams_audit_universe_entities_updated_total",
    "AuditableEntity rows updated via the API.",
)

audit_universe_entities_archived_total = Counter(
    "iams_audit_universe_entities_archived_total",
    "AuditableEntity rows soft-deleted (archived).",
)

audit_universe_bulk_imports_total = Counter(
    "iams_audit_universe_bulk_imports_total",
    "Bulk-import jobs that reached a terminal status (status label).",
    ["status"],
)

audit_universe_bulk_import_rows_total = Counter(
    "iams_audit_universe_bulk_import_rows_total",
    "Rows processed by bulk-import (outcome label: created/updated/skipped).",
    ["outcome"],
)


# ──────────────────────────────────────────────────────────────────────
# Gauge refreshers — called by the dashboard cache-refresh beat task.
# ──────────────────────────────────────────────────────────────────────
def refresh_business_gauges() -> dict[str, int]:
    """Sync the live-state gauges from the DB.

    Called by ``iams.tasks.dashboards.refresh_dashboard_caches`` so
    every 5 minutes the gauges are accurate even if some signals were
    dropped (process restart, lost message). Returns the new values
    so callers can log them.
    """
    from datetime import date

    from iams.models import ApprovalRequest, CorrectiveAction

    overdue = (
        CorrectiveAction.objects.exclude(status="Closed")
        .filter(due_date__lt=date.today()).count()
    )
    pending = ApprovalRequest.objects.filter(status="Pending").count()

    caps_overdue_current.set(overdue)
    approvals_pending_current.set(pending)
    return {
        "caps_overdue_current": overdue,
        "approvals_pending_current": pending,
    }
