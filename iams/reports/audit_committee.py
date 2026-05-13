"""Audit Committee Pack (FR-DASH-11).

The board-facing roll-up that combines the executive KPIs, the top
risks, the audit completion rate, the open material weaknesses
(from ICFR), and the rating summaries.

Parameters: ``period`` (optional)
"""
from __future__ import annotations

from typing import Any

from iams.dashboards import (
    core_kpis,
    rating_summary,
    risk_heatmap_by_department,
    trends,
    upcoming_audits,
)

from .base import BaseRenderer


class AuditCommitteePackRenderer(BaseRenderer):
    kind = "audit_committee_pack"
    template_name = "audit_committee.html"

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        period = parameters.get("period")
        return {
            "report_title": "Audit Committee Pack",
            "period": period or "All periods",
            "kpis": core_kpis(period=period),
            "trends": trends(period="YoY"),
            "heatmap": risk_heatmap_by_department(),
            "ratings": rating_summary(period=period),
            "upcoming": upcoming_audits(limit=10),
        }
