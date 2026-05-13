"""Base renderer classes.

The split is intentional: PDF renderers produce HTML via Jinja2 then
hand off to WeasyPrint, while Excel renderers emit ``openpyxl``
workbooks directly. Both write their bytes into ``ReportJob.output_file``
via ``finalize_job(...)``.

WeasyPrint depends on system libraries (pango, cairo, gdk-pixbuf) that
are installed in the production Dockerfile. In dev / CI without those
libs, set ``IAMS_DISABLE_PDF_RENDER=1`` to skip the WeasyPrint call
and write the raw HTML to the file — useful for smoke-testing the
template without the full PDF toolchain.
"""
from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any

from django.core.files.base import ContentFile
from django.template.loader import render_to_string

from iams.models import ReportJob

logger = logging.getLogger(__name__)


class RendererError(Exception):
    """Domain error from a renderer (bad params, missing data, etc.)."""


# ──────────────────────────────────────────────────────────────────────
# PDF renderer base
# ──────────────────────────────────────────────────────────────────────
class BaseRenderer:
    """Subclass to add a PDF report.

    Subclasses must:
      - set ``kind`` (matching ``ReportJob.KIND_*``)
      - set ``template_name`` (under ``iams/reports/templates/``)
      - implement ``gather_context(self, parameters)``

    The base ``run(job)`` handles status transitions and file write.
    """

    kind: str = ""
    template_name: str = ""
    output_format: str = ReportJob.FORMAT_PDF

    def gather_context(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Return the Jinja2 context for ``template_name``.

        Override in subclasses. Raise ``RendererError`` for invalid
        parameters or empty result sets that should fail rather than
        produce an empty PDF.
        """
        raise NotImplementedError

    def render_html(self, parameters: dict[str, Any]) -> str:
        context = self.gather_context(parameters)
        return render_to_string(f"iams/reports/{self.template_name}", context)

    def render_bytes(self, parameters: dict[str, Any]) -> bytes:
        html = self.render_html(parameters)
        if os.environ.get("IAMS_DISABLE_PDF_RENDER") == "1":
            logger.warning("renderer: IAMS_DISABLE_PDF_RENDER=1 — writing raw HTML")
            return html.encode("utf-8")
        try:
            from weasyprint import HTML  # noqa: PLC0415 — lazy import
        except ImportError as exc:
            raise RendererError(
                "WeasyPrint is unavailable. Install system libs (pango, cairo, "
                "gdk-pixbuf) or set IAMS_DISABLE_PDF_RENDER=1 for raw HTML."
            ) from exc
        buf = BytesIO()
        HTML(string=html).write_pdf(target=buf)
        return buf.getvalue()

    def filename(self, job: ReportJob) -> str:
        slug = (job.title or self.kind).lower().replace(" ", "-")
        return f"{slug}-{job.pk}.pdf"

    def run(self, job: ReportJob) -> ReportJob:
        from django.utils import timezone

        job.status = ReportJob.STATUS_RUNNING
        job.started_at = timezone.now()
        job.error = ""
        job.save(update_fields=["status", "started_at", "error", "updated_at"])

        try:
            payload = self.render_bytes(job.parameters or {})
        except RendererError as exc:
            job.status = ReportJob.STATUS_FAILED
            job.error = str(exc)
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error", "completed_at", "updated_at"])
            return job
        except Exception as exc:  # noqa: BLE001
            logger.exception("renderer: unexpected failure", extra={"job_id": str(job.pk)})
            job.status = ReportJob.STATUS_FAILED
            job.error = f"{type(exc).__name__}: {exc}"
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error", "completed_at", "updated_at"])
            return job

        # Write file
        ext = "pdf" if self.output_format == ReportJob.FORMAT_PDF else "xlsx"
        slug = (job.title or self.kind).lower().replace(" ", "-")
        job.output_file.save(f"{slug}.{ext}", ContentFile(payload), save=False)
        job.file_size_kb = max(1, len(payload) // 1024)
        job.status = ReportJob.STATUS_COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=[
            "output_file", "file_size_kb", "status", "completed_at", "updated_at",
        ])
        return job


# ──────────────────────────────────────────────────────────────────────
# Excel renderer base
# ──────────────────────────────────────────────────────────────────────
class BaseExcelRenderer(BaseRenderer):
    """Subclass to add an Excel tabular report.

    Subclasses must implement ``write_rows(workbook, parameters)``.
    The base writes header + records into a single sheet and ships
    the binary through the same ``ReportJob`` flow.
    """

    output_format = ReportJob.FORMAT_XLSX
    sheet_title: str = "Report"
    headers: list[str] = []

    def write_rows(self, sheet, parameters: dict[str, Any]) -> int:
        """Write data rows into ``sheet``; return row count written."""
        raise NotImplementedError

    def render_bytes(self, parameters: dict[str, Any]) -> bytes:
        try:
            from openpyxl import Workbook  # noqa: PLC0415 — lazy import
        except ImportError as exc:
            raise RendererError("openpyxl is unavailable.") from exc
        wb = Workbook()
        ws = wb.active
        ws.title = self.sheet_title[:31]  # Excel limit
        if self.headers:
            ws.append(self.headers)
            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
        try:
            self.write_rows(ws, parameters or {})
        except RendererError:
            raise
        # Auto-size columns roughly
        for col_idx, col_cells in enumerate(ws.columns, start=1):
            width = max((len(str(c.value or "")) for c in col_cells), default=8)
            ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = min(60, width + 2)
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()
