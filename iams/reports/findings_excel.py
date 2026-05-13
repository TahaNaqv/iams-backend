"""Findings export (Excel, FR-RPT-07).

One row per finding with audit + severity + status + owner + due date
+ days-open. Optional filters: ``audit_id``, ``severity``, ``status``,
``department``.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from iams.models import Finding

from .base import BaseExcelRenderer


class FindingsExcelRenderer(BaseExcelRenderer):
    kind = "findings_excel"
    sheet_title = "Findings"
    headers = [
        "ID", "Title", "Audit", "Department", "Severity", "Status",
        "Owner", "Created", "Due", "Days Open",
    ]

    def write_rows(self, sheet, parameters: dict[str, Any]) -> int:
        qs = Finding.objects.select_related("audit")
        if (a := parameters.get("audit_id")):
            qs = qs.filter(audit_id=a)
        if (s := parameters.get("severity")):
            qs = qs.filter(severity=s)
        if (st := parameters.get("status")):
            qs = qs.filter(status=st)
        if (d := parameters.get("department")):
            qs = qs.filter(department=d)
        today = date.today()
        n = 0
        for f in qs.order_by("-created_date", "severity"):
            days_open = (today - f.created_date).days if f.created_date else None
            sheet.append([
                str(f.id), f.title,
                f.audit.title if f.audit_id else "", f.department,
                f.severity, f.status, f.owner,
                f.created_date.isoformat() if f.created_date else "",
                f.due_date.isoformat() if f.due_date else "",
                days_open,
            ])
            n += 1
        return n
