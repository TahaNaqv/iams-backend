"""Annual QAIP Report (FR-QAIP-04).

Mirrors the ``/api/qaip/dashboard/`` endpoint into a print-ready
document. The dashboard JSON is the canonical source.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Avg, Count

from iams.models import (
    AuditKPI,
    QAIPAssessment,
    QAIPFinding,
    StakeholderSurvey,
)

from .base import BaseRenderer, RendererError


class QAIPAnnualRenderer(BaseRenderer):
    kind = "qaip_annual"
    template_name = "qaip_annual.html"

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        period = parameters.get("period")
        if not period:
            raise RendererError("period is required for the annual QAIP report.")

        assessments = QAIPAssessment.objects.filter(period=period)
        findings = QAIPFinding.objects.filter(assessment__period=period)
        surveys = StakeholderSurvey.objects.all()
        if period.isdigit() and len(period) == 4:
            surveys = surveys.filter(submitted_at__year=int(period))
        kpis = AuditKPI.objects.filter(period=period)

        return {
            "report_title": f"QAIP Annual Report — {period}",
            "period": period,
            "assessments": list(assessments),
            "findings_by_rating": list(
                findings.values("rating").annotate(count=Count("id")).order_by("rating")
            ),
            "findings_open": findings.exclude(status="closed").count(),
            "avg_satisfaction": float(
                surveys.aggregate(avg=Avg("satisfaction_score"))["avg"] or 0
            ),
            "survey_count": surveys.count(),
            "kpis": list(kpis.order_by("kpi_type")),
        }
