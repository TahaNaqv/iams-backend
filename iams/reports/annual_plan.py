"""Annual Audit Plan Report (FR-RPT-06, FR-PLAN-05).

Renders the approved Annual Plan: top entities by risk (from the
``RiskScoringModel`` referenced in parameters), the corresponding
ApprovalRequest's chain status, and the proposed engagement list.

Parameters:
  year               (required, int)
  scoring_model_id   (required, UUID — pulled from EntityRiskScore)
  reference_id       (optional — the ApprovalRequest reference; defaults to
                      "PLAN-{year}" used by ``generate_audit_plan_draft``)
"""
from __future__ import annotations

from typing import Any

from iams.models import ApprovalRequest, EntityRiskScore, RiskScoringModel

from .base import BaseRenderer, RendererError


class AnnualPlanRenderer(BaseRenderer):
    kind = "annual_audit_plan"
    template_name = "annual_plan.html"

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        year = parameters.get("year")
        model_id = parameters.get("scoring_model_id")
        if not year or not model_id:
            raise RendererError("year and scoring_model_id are required.")
        try:
            model = RiskScoringModel.objects.get(pk=model_id)
        except RiskScoringModel.DoesNotExist as exc:
            raise RendererError(f"Scoring model {model_id} not found.") from exc

        scores = list(
            EntityRiskScore.objects
            .filter(scoring_model=model, is_current=True)
            .select_related("entity")
            .order_by("rank", "-composite_score")
        )
        ref = parameters.get("reference_id") or f"PLAN-{year}"
        approval = ApprovalRequest.objects.filter(reference_id=ref, type="Audit Plan").first()
        approval_steps = list(approval.steps.order_by("order")) if approval else []

        return {
            "year": int(year),
            "scoring_model": model,
            "scores": scores,
            "approval": approval,
            "approval_steps": approval_steps,
            "report_title": f"{year} Annual Audit Plan",
        }
