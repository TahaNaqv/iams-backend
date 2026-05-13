"""Audit Summary Report (FR-RPT-01).

One audit engagement, end-to-end: scope, dates, lead auditor, status,
findings table (severity + status + owner), CAP rollup, top exceptions
if ICFR tests touched the audit's entity.

Parameters:
  audit_id   (required, UUID)   — the engagement to summarise
"""
from __future__ import annotations

from typing import Any

from iams.models import (
    Audit,
    CorrectiveAction,
    Finding,
)

from .base import BaseRenderer, RendererError


class AuditSummaryRenderer(BaseRenderer):
    kind = "audit_summary"
    template_name = "audit_summary.html"

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        audit_id = parameters.get("audit_id")
        if not audit_id:
            raise RendererError("audit_id is required.")
        try:
            audit = (
                Audit.objects
                .prefetch_related("findings", "findings__corrective_actions")
                .get(pk=audit_id)
            )
        except Audit.DoesNotExist as exc:
            raise RendererError(f"Audit {audit_id} not found.") from exc

        findings = list(audit.findings.all().order_by(
            # severity sort: critical / high / medium / low
            "-severity", "due_date",
        ))
        caps = list(
            CorrectiveAction.objects
            .filter(finding__audit=audit)
            .order_by("status", "due_date")
        )
        severity_counts = {
            level: sum(1 for f in findings if f.severity == level)
            for level in ("Critical", "High", "Medium", "Low")
        }
        cap_status_counts = {
            s: sum(1 for c in caps if c.status == s)
            for s in ("Open", "In Progress", "Overdue", "Closed")
        }
        return {
            "audit": audit,
            "findings": findings,
            "caps": caps,
            "severity_counts": severity_counts,
            "cap_status_counts": cap_status_counts,
            "report_title": f"Audit Summary — {audit.title}",
        }
