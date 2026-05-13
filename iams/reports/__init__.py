"""Report generation engine — registry + base renderer.

Each report kind has a renderer subclassing ``BaseRenderer``. The
``RENDERERS`` registry maps ``ReportJob.kind`` strings to renderer
classes so the Celery task can dispatch generically.

Adding a new report = subclass ``BaseRenderer`` (PDF) or
``BaseExcelRenderer`` (Excel), implement ``gather_context()`` (PDF)
or ``write_rows()`` (Excel), and register the class in this file.
"""
from __future__ import annotations

from iams.models import ReportJob

from .annual_plan import AnnualPlanRenderer
from .audit_committee import AuditCommitteePackRenderer
from .audit_summary import AuditSummaryRenderer
from .base import BaseExcelRenderer, BaseRenderer, RendererError
from .cap_status import CAPStatusRenderer
from .caps_excel import CAPsExcelRenderer
from .department_risk import DepartmentRiskProfileRenderer
from .finding_trends import FindingTrendsRenderer
from .findings_excel import FindingsExcelRenderer
from .icfr_summary import ICFRSummaryRenderer
from .open_issues import OpenIssuesRenderer
from .qaip_annual import QAIPAnnualRenderer
from .time_entries_excel import TimeEntriesExcelRenderer

# Registry: kind → renderer class. The Celery task imports this and
# dispatches by kind. Subclasses that aren't here are unreachable from
# the API even if they exist on disk (intentional — explicit allow-list).
RENDERERS: dict[str, type[BaseRenderer | BaseExcelRenderer]] = {
    ReportJob.KIND_AUDIT_SUMMARY: AuditSummaryRenderer,
    ReportJob.KIND_FINDING_TRENDS: FindingTrendsRenderer,
    ReportJob.KIND_CAP_STATUS: CAPStatusRenderer,
    ReportJob.KIND_ANNUAL_PLAN: AnnualPlanRenderer,
    ReportJob.KIND_DEPARTMENT_RISK: DepartmentRiskProfileRenderer,
    ReportJob.KIND_OPEN_ISSUES: OpenIssuesRenderer,
    ReportJob.KIND_ICFR_SUMMARY: ICFRSummaryRenderer,
    ReportJob.KIND_QAIP_ANNUAL: QAIPAnnualRenderer,
    ReportJob.KIND_AUDIT_COMMITTEE: AuditCommitteePackRenderer,
    ReportJob.KIND_FINDINGS_EXCEL: FindingsExcelRenderer,
    ReportJob.KIND_CAPS_EXCEL: CAPsExcelRenderer,
    ReportJob.KIND_TIME_ENTRIES_EXCEL: TimeEntriesExcelRenderer,
}


__all__ = [
    "BaseRenderer",
    "BaseExcelRenderer",
    "RendererError",
    "RENDERERS",
    "AuditSummaryRenderer",
    "FindingTrendsRenderer",
    "CAPStatusRenderer",
    "AnnualPlanRenderer",
    "DepartmentRiskProfileRenderer",
    "OpenIssuesRenderer",
    "ICFRSummaryRenderer",
    "QAIPAnnualRenderer",
    "AuditCommitteePackRenderer",
    "FindingsExcelRenderer",
    "CAPsExcelRenderer",
    "TimeEntriesExcelRenderer",
]
