"""ICFR Summary Report for external audit coordination (FR-ICFR-05).

Consumes the existing ``iams.icfr.build_icfr_summary`` aggregator
(Phase 3 Track 4) so the PDF and the JSON dashboard stay aligned.
"""
from __future__ import annotations

from typing import Any

from iams.icfr import build_icfr_summary

from .base import BaseRenderer


class ICFRSummaryRenderer(BaseRenderer):
    kind = "icfr_summary"
    template_name = "icfr_summary.html"

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        period = parameters.get("period")
        payload = build_icfr_summary(period=period)
        return {
            "report_title": "ICFR Summary",
            "period": period or "All periods",
            "summary": payload,
        }
