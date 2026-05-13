"""Finding Trends Report (FR-RPT-02).

Aggregates findings across the org by severity, status, and department
over the requested period.

Parameters (all optional):
  period     ("YYYY", "YYYY-Q1", or a specific date range later)
  department (filter to one department)
"""
from __future__ import annotations

from typing import Any

from django.db.models import Count

from iams.models import Finding

from .base import BaseRenderer


class FindingTrendsRenderer(BaseRenderer):
    kind = "finding_trends"
    template_name = "finding_trends.html"

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        qs = Finding.objects.all()
        period = parameters.get("period")
        if period and len(period) == 4 and period.isdigit():
            qs = qs.filter(created_date__year=int(period))
        elif period and "-Q" in (period or ""):
            year_str, q_str = period.split("-Q", 1)
            try:
                year = int(year_str)
                q = int(q_str)
                if 1 <= q <= 4:
                    month_start = (q - 1) * 3 + 1
                    month_end = month_start + 2
                    qs = qs.filter(
                        created_date__year=year,
                        created_date__month__gte=month_start,
                        created_date__month__lte=month_end,
                    )
            except (TypeError, ValueError):
                pass

        department = parameters.get("department")
        if department:
            qs = qs.filter(department=department)

        by_severity = list(qs.values("severity").annotate(count=Count("id")).order_by("severity"))
        by_status = list(qs.values("status").annotate(count=Count("id")).order_by("status"))
        by_department = list(qs.values("department").annotate(count=Count("id")).order_by("-count")[:20])
        total = qs.count()

        return {
            "total": total,
            "period": period or "All time",
            "department_filter": department or "All departments",
            "by_severity": by_severity,
            "by_status": by_status,
            "by_department": by_department,
            "report_title": "Finding Trends",
        }
