"""Time-entries export (Excel, FR-RPT-07).

One row per submitted time entry. Optional filters by auditor + audit.
"""
from __future__ import annotations

from typing import Any

from iams.models import TimeEntry

from .base import BaseExcelRenderer


class TimeEntriesExcelRenderer(BaseExcelRenderer):
    kind = "time_entries_excel"
    sheet_title = "Time Entries"
    headers = ["ID", "Auditor", "Audit", "Date", "Hours", "Status", "Notes"]

    def write_rows(self, sheet, parameters: dict[str, Any]) -> int:
        qs = TimeEntry.objects.select_related("auditor", "audit")
        if (a := parameters.get("auditor_id")):
            qs = qs.filter(auditor_id=a)
        if (au := parameters.get("audit_id")):
            qs = qs.filter(audit_id=au)
        n = 0
        for t in qs.order_by("-date"):
            sheet.append([
                str(t.id),
                t.auditor.name if t.auditor_id else "",
                t.audit.title if t.audit_id else "",
                t.date.isoformat() if t.date else "",
                float(t.hours) if t.hours is not None else None,
                t.status, t.notes,
            ])
            n += 1
        return n
