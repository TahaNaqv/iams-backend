"""CAPs export (Excel, FR-RPT-07).

One row per corrective action with finding link, owner, due date,
status, priority, progress, days-late if overdue.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from iams.models import CorrectiveAction

from .base import BaseExcelRenderer


class CAPsExcelRenderer(BaseExcelRenderer):
    kind = "caps_excel"
    sheet_title = "CAPs"
    headers = [
        "ID", "Title", "Finding", "Owner", "Status", "Priority",
        "Progress %", "Due", "Days Late", "Department",
    ]

    def write_rows(self, sheet, parameters: dict[str, Any]) -> int:
        qs = CorrectiveAction.objects.select_related("finding")
        if (s := parameters.get("status")):
            qs = qs.filter(status=s)
        if (d := parameters.get("department")):
            qs = qs.filter(department=d)
        today = date.today()
        n = 0
        for cap in qs.order_by("status", "due_date"):
            days_late = (today - cap.due_date).days if cap.due_date and cap.due_date < today and cap.status != "Closed" else None
            sheet.append([
                str(cap.id), cap.title,
                cap.finding.title if cap.finding_id else "",
                cap.owner, cap.status, cap.priority, cap.progress,
                cap.due_date.isoformat() if cap.due_date else "",
                days_late, cap.department,
            ])
            n += 1
        return n
