"""Department Risk Profile (FR-RPT-04).

Consumes ``dashboards.risk_heatmap_by_department`` so the report stays
in sync with the FE dashboard widget. Filters optional by department.
"""
from __future__ import annotations

from typing import Any

from iams.dashboards import risk_heatmap_by_department

from .base import BaseRenderer


class DepartmentRiskProfileRenderer(BaseRenderer):
    kind = "department_risk_profile"
    template_name = "department_risk.html"

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        payload = risk_heatmap_by_department()
        # Optional filter
        dept = parameters.get("department")
        if dept:
            payload["departments"] = [d for d in payload["departments"] if d == dept]
            payload["cells"] = [c for c in payload["cells"] if c["department"] == dept]
        return {
            "report_title": "Department Risk Profile",
            "heatmap": payload,
            "department_filter": dept or "All departments",
        }
