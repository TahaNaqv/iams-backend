"""Open Issues Report (FR-RPT-05).

Every non-closed Finding paired with its non-closed CAP(s), grouped by
severity. Useful for the monthly issues-tracking meeting.
"""
from __future__ import annotations

from typing import Any

from iams.models import CorrectiveAction, Finding

from .base import BaseRenderer


class OpenIssuesRenderer(BaseRenderer):
    kind = "open_issues"
    template_name = "open_issues.html"

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        department = parameters.get("department")
        f_qs = Finding.objects.exclude(status="Closed").select_related("audit")
        c_qs = CorrectiveAction.objects.exclude(status="Closed").select_related("finding")
        if department:
            f_qs = f_qs.filter(department=department)
            c_qs = c_qs.filter(department=department)

        findings = list(f_qs.order_by("severity", "due_date"))
        caps_by_finding: dict[str, list[CorrectiveAction]] = {}
        for cap in c_qs:
            caps_by_finding.setdefault(str(cap.finding_id), []).append(cap)

        rows = []
        for f in findings:
            rows.append({
                "finding": f,
                "caps": caps_by_finding.get(str(f.id), []),
            })

        return {
            "report_title": "Open Issues",
            "department_filter": department or "All departments",
            "rows": rows,
            "total_findings": len(findings),
            "total_caps": sum(len(v) for v in caps_by_finding.values()),
        }
