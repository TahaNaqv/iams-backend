"""CAP Status Report (FR-RPT-03).

Open / In Progress / Overdue / Closed rollup, plus the overdue list
with owners, due dates, days late.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Count, Q

from iams.models import CorrectiveAction

from .base import BaseRenderer


class CAPStatusRenderer(BaseRenderer):
    kind = "cap_status"
    template_name = "cap_status.html"

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        today = date.today()
        qs = CorrectiveAction.objects.all()
        department = parameters.get("department")
        if department:
            qs = qs.filter(department=department)

        total = qs.count()
        by_status = list(qs.values("status").annotate(count=Count("id")).order_by("status"))
        by_priority = list(qs.values("priority").annotate(count=Count("id")).order_by("priority"))

        overdue = list(
            qs.exclude(status="Closed")
            .filter(due_date__lt=today)
            .order_by("due_date")
        )
        for cap in overdue:
            cap.days_late = (today - cap.due_date).days if cap.due_date else 0  # type: ignore

        return {
            "total": total,
            "department_filter": department or "All departments",
            "by_status": by_status,
            "by_priority": by_priority,
            "overdue": overdue,
            "overdue_count": len(overdue),
            "report_title": "Corrective Action Plan Status",
            "as_of": today,
        }
