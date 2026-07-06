"""Risk Assessment Workbook import worker.

A multipart POST to ``/api/risk-assessments/import/`` creates a
``RiskAssessmentImportJob`` and enqueues this task. Unlike the flat
AuditableEntity import (``iams.tasks.bulk_import``), a risk-assessment
workbook fans out across many worksheets:

  * **Department / record sheets** → one ``RiskAssessmentSheet`` plus a
    ``RiskAssessmentRecord`` per data row (validated through
    ``RiskAssessmentRecordSerializer`` so the API's rules stay in one place).
  * a **matrix sheet** (name contains "matr") → ``RiskAssessmentMatrixCell``
    rows — the ``(likelihood, impact) → residual`` lookup table.
  * a **summary sheet** (name contains "summary") is skipped for direct import;
    summary items are *derived* from the records instead (see
    ``_rebuild_summary``) so they can't drift from their source rows.

Matrix-driven residual: when a matrix cell exists for a record's
(likelihood, impact) pair, the record's residual is taken from the matrix and
a mismatch with the sheet's own value is flagged as a warning issue.

Engine integration: when the job's ``link_to_engine`` is set, each record is
resolved to a Department-type ``AuditableEntity`` (by name) and an
``EntityRisk`` is created/updated, feeding the real roll-up.

Strict mode aborts the whole import on the first bad row; lenient mode wraps
each row in a savepoint so a bad row is skipped with a captured issue.
"""
from __future__ import annotations

import csv
import io
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# Human header → serializer camelCase key.
COLUMN_ALIASES: dict[str, str] = {
    "department": "department",
    "department / function": "department",
    "function": "department",
    "objective": "objective",
    "risk area": "riskArea",
    "risk": "riskArea",
    "risk description": "riskDescription",
    "description": "riskDescription",
    "grading": "grading",
    "likelihood": "likelihood",
    "impact": "impact",
    "inherent risk": "inherentRisk",
    "existing controls": "existingControls",
    "controls": "existingControls",
    "control effectiveness": "controlEffectiveness",
    "residual risk": "residualRisk",
    "audit objective": "auditObjective",
    "audit steps": "auditSteps",
    "documents required": "documentsRequired",
    "inclusion status": "inclusionStatus",
    "inclusion": "inclusionStatus",
    "audit scope": "auditScope",
    "scope": "auditScope",
    "planned man days": "plannedManDays",
    "man days": "plannedManDays",
    "notes": "notes",
}

_LEVELS = {"high", "medium", "low"}
# Qualitative ↔ numeric (mirrors frontend src/lib/risk-score.ts qualitativeToValue).
_LEVEL_TO_VALUE = {"High": 4, "Medium": 3, "Low": 2}


def _norm_header(h: str) -> str:
    return COLUMN_ALIASES.get((h or "").strip().lower(), "")


def _title_level(value) -> str:
    """Normalise a free-text High/Medium/Low cell to title case, else ''."""
    s = str(value or "").strip().lower()
    return s.title() if s in _LEVELS else ""


def _classify_sheet(title: str) -> str:
    low = (title or "").strip().lower()
    if "matr" in low:
        return "matrix"
    if "summary" in low:
        return "summary"
    return "records"


def _rows_from_worksheet(ws):
    """Yield ``(row_index, header_list, values_list)`` — header is row 1."""
    it = ws.iter_rows(values_only=True)
    try:
        header = [str(c or "").strip() for c in next(it)]
    except StopIteration:
        return
    for idx, raw in enumerate(it, start=2):
        if not raw or all(c is None or c == "" for c in raw):
            continue
        yield idx, header, list(raw)


def _record_payload(header: list[str], values: list, *, sheet_name: str, row_index: int) -> dict:
    payload: dict = {"sourceSheet": sheet_name, "sourceRow": row_index}
    for col_name, value in zip(header, values, strict=False):
        key = _norm_header(col_name)
        if not key or value in (None, ""):
            continue
        if key in ("inherentRisk", "residualRisk"):
            payload[key] = _title_level(value) or "Medium"
        elif key == "plannedManDays":
            payload[key] = str(value)
        else:
            payload[key] = str(value).strip() if isinstance(value, str) else value
    return payload


def _cell_ref(header: list[str], row_index: int, key: str) -> str:
    """Best-effort ``A1``-style ref for the column mapped to ``key``."""
    for col_idx, col_name in enumerate(header):
        if _norm_header(col_name) == key:
            letter = chr(ord("A") + col_idx) if col_idx < 26 else "?"
            return f"{letter}{row_index}"
    return f"row {row_index}"


@shared_task(name="iams.risk_assessment.process_import")
def process_risk_assessment_import(job_id: str) -> dict:
    """Drive a ``RiskAssessmentImportJob`` to completion."""
    from iams.domain_serializers import RiskAssessmentRecordSerializer
    from iams.models import (
        RiskAssessmentImportIssue,
        RiskAssessmentImportJob,
        RiskAssessmentMatrixCell,
        RiskAssessmentSheet,
    )

    try:
        job = RiskAssessmentImportJob.objects.get(pk=job_id)
    except RiskAssessmentImportJob.DoesNotExist:
        logger.info("risk-assessment-import: job %s vanished before run", job_id)
        return {"processed": 0, "reason": "missing"}

    if job.status not in (RiskAssessmentImportJob.STATUS_PENDING,):
        return {"processed": 0, "reason": "already_processed"}

    strict = job.mode == RiskAssessmentImportJob.MODE_STRICT
    job.status = RiskAssessmentImportJob.STATUS_IMPORTING
    job.save(update_fields=["status", "updated_at"])

    counters = {"sheets": 0, "created": 0, "updated": 0, "matrix": 0, "summary": 0, "skipped": 0}
    issues: list = []

    def add_issue(severity, sheet, cell, message, row=0):
        if len(issues) < 500:
            issues.append(
                RiskAssessmentImportIssue(
                    job=job, severity=severity, sheet=sheet or "", cell=cell or "",
                    row_number=row, message=message[:500],
                )
            )

    def run():
        matrix_lookup = _load_matrix(job, RiskAssessmentMatrixCell, counters)
        for title, kind, rows in _iter_sheets(job):
            if kind == "matrix":
                continue  # already loaded up-front
            if kind == "summary":
                continue  # summary is derived, not imported
            _import_record_sheet(
                job, title, rows, matrix_lookup, counters, add_issue,
                RiskAssessmentSheet, RiskAssessmentRecordSerializer, strict,
            )

    try:
        if strict:
            with transaction.atomic():
                run()
        else:
            run()
    except _StrictAbort as exc:
        job.status = RiskAssessmentImportJob.STATUS_FAILED
        _finalize(job, counters, issues)
        _bump_metric(job.status)
        return {"status": job.status, "reason": str(exc)}
    except Exception as exc:
        logger.exception("risk-assessment-import: job %s crashed", job_id)
        job.status = RiskAssessmentImportJob.STATUS_FAILED
        add_issue("error", "", "", f"Import crashed: {exc}")
        _finalize(job, counters, issues)
        _bump_metric(job.status)
        return {"status": job.status}

    # Derive summary items from the imported records (kept in sync, never drift).
    counters["summary"] = _rebuild_summary(job)

    job.status = (
        RiskAssessmentImportJob.STATUS_PARTIAL
        if any(i.severity == "error" for i in issues)
        else RiskAssessmentImportJob.STATUS_COMPLETED
    )
    _finalize(job, counters, issues)
    _bump_metric(job.status)
    logger.info(
        "risk-assessment-import: job %s finished status=%s created=%d updated=%d",
        job_id, job.status, counters["created"], counters["updated"],
    )
    return {"status": job.status, **counters}


class _StrictAbort(Exception):
    pass


def _finalize(job, counters, issues):
    from iams.models import RiskAssessmentImportIssue

    if issues:
        RiskAssessmentImportIssue.objects.bulk_create(issues)
    job.sheets_created = counters["sheets"]
    job.records_created = counters["created"]
    job.records_updated = counters["updated"]
    job.matrix_cells = counters["matrix"]
    job.summary_items = counters["summary"]
    job.skipped = counters["skipped"]
    job.finished_at = timezone.now()
    job.save()


def _bump_metric(status):
    try:
        from iams import metrics as m

        if hasattr(m, "risk_assessment_imports_total"):
            m.risk_assessment_imports_total.labels(status=status).inc()
    except Exception:  # noqa: S110 — metrics must never break an import
        pass


def _open_workbook(job):
    """Return (worksheets_iterable, close_fn) for xlsx, or None for csv."""
    name = (job.file.name or "").lower()
    job.file.open("rb")
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook

        wb = load_workbook(filename=job.file, read_only=True, data_only=True)
        return wb, lambda: (wb.close(), job.file.close())
    return None, job.file.close


def _iter_sheets(job):
    """Yield ``(title, kind, rows_iterable)`` for each worksheet (or the single
    CSV pseudo-sheet)."""
    name = (job.file.name or "").lower()
    if name.endswith(".xlsx"):
        wb, close = _open_workbook(job)
        try:
            for ws in wb.worksheets:
                yield ws.title, _classify_sheet(ws.title), list(_rows_from_worksheet(ws))
        finally:
            close()
    else:
        job.file.open("rb")
        try:
            text = io.TextIOWrapper(job.file, encoding="utf-8-sig", newline="")
            reader = csv.reader(text)
            all_rows = list(reader)
            if not all_rows:
                return
            header = [str(c or "").strip() for c in all_rows[0]]
            rows = []
            for idx, raw in enumerate(all_rows[1:], start=2):
                if not raw or all(c == "" for c in raw):
                    continue
                rows.append((idx, header, list(raw)))
            yield "Import", "records", rows
        finally:
            job.file.close()


def _load_matrix(job, MatrixCell, counters) -> dict:
    """Upsert matrix cells from the matrix sheet; return the lookup dict."""
    lookup: dict = {}
    for _title, kind, rows in _iter_sheets(job):
        if kind != "matrix":
            continue
        for _row_index, header, values in rows:
            lik = imp = res = ""
            for col_name, value in zip(header, values, strict=False):
                key = _norm_header(col_name)
                if key == "likelihood":
                    lik = _title_level(value)
                elif key == "impact":
                    imp = _title_level(value)
                elif key in ("residualRisk", "inherentRisk"):
                    res = _title_level(value)
            if not (lik and imp and res):
                continue
            MatrixCell.objects.update_or_create(
                likelihood=lik, impact=imp, defaults={"residual_risk": res},
            )
            lookup[(lik, imp)] = res
            counters["matrix"] += 1
    return lookup


def _import_record_sheet(job, title, rows, matrix_lookup, counters, add_issue,
                         Sheet, RecordSerializer, strict):
    if not rows:
        return
    sheet, created = Sheet.objects.get_or_create(
        name=title, defaults={"description": "", "order": counters["sheets"]}
    )
    if created:
        counters["sheets"] += 1

    for row_index, header, values in rows:
        payload = _record_payload(header, values, sheet_name=title, row_index=row_index)
        if not payload.get("department") or not payload.get("riskArea"):
            counters["skipped"] += 1
            add_issue("error", title, _cell_ref(header, row_index, "riskArea"),
                      "Row missing required 'department' or 'risk area'.", row_index)
            if strict:
                raise _StrictAbort("missing required column")
            continue

        # Matrix-driven residual: prefer the matrix value; flag a mismatch.
        lik = _title_level(payload.get("likelihood")) or ""
        imp = _title_level(payload.get("impact")) or ""
        matrix_res = matrix_lookup.get((lik, imp)) if (lik and imp) else None
        if matrix_res:
            sheet_res = payload.get("residualRisk")
            if sheet_res and sheet_res != matrix_res:
                add_issue("warning", title, _cell_ref(header, row_index, "residualRisk"),
                          f"Residual '{sheet_res}' overridden by matrix '{matrix_res}' "
                          f"for ({lik}, {imp}).", row_index)
            payload["residualRisk"] = matrix_res

        payload["sheet"] = str(sheet.id)
        sid = transaction.savepoint() if not strict else None
        try:
            ser = RecordSerializer(data=payload)
            if not ser.is_valid():
                counters["skipped"] += 1
                field, msgs = next(iter(ser.errors.items()))
                add_issue("error", title, _cell_ref(header, row_index, field),
                          f"{field}: {msgs[0] if isinstance(msgs, list) else msgs}", row_index)
                if strict:
                    raise _StrictAbort("invalid row")
                if sid:
                    transaction.savepoint_rollback(sid)
                continue
            record = ser.save()
            counters["created"] += 1
            if job.link_to_engine:
                _link_record_to_engine(record, add_issue, title, row_index)
            if sid:
                transaction.savepoint_commit(sid)
        except _StrictAbort:
            raise
        except Exception as exc:
            if sid:
                transaction.savepoint_rollback(sid)
            counters["skipped"] += 1
            add_issue("error", title, "", f"Save failed: {exc}", row_index)
            if strict:
                raise _StrictAbort("save failed") from exc


def _link_record_to_engine(record, add_issue, sheet_title, row_index):
    """Resolve the record's department to a Department entity and create/update
    an ``EntityRisk`` from its qualitative levels, feeding the real roll-up."""
    from iams.models import AuditableEntity, EntityRisk

    dept = (record.department or "").strip()
    if not dept:
        return
    entity = (
        AuditableEntity.objects.filter(entity_type="Department", name__iexact=dept).first()
        or AuditableEntity.objects.filter(name__iexact=dept).first()
    )
    if entity is None:
        add_issue("info", sheet_title, "", f"No auditable entity matches department '{dept}'; "
                  "record not linked to the engine.", row_index)
        return
    inh_l = _LEVEL_TO_VALUE.get(_title_level(record.likelihood) or "Medium", 3)
    inh_i = _LEVEL_TO_VALUE.get(_title_level(record.impact) or "Medium", 3)
    res_v = _LEVEL_TO_VALUE.get(record.residual_risk, inh_i)
    risk, _ = EntityRisk.objects.update_or_create(
        entity=entity,
        title=record.risk_area[:255],
        defaults={
            "description": record.risk_description or "",
            "inherent_likelihood": inh_l,
            "inherent_impact": inh_i,
            "residual_likelihood": min(inh_l, res_v),
            "residual_impact": min(inh_i, res_v),
            "existing_controls": record.existing_controls or "",
        },
    )
    record.entity = entity
    record.entity_risk = risk
    record.save(update_fields=["entity", "entity_risk", "updated_at"])


def _rebuild_summary(job) -> int:
    """Derive one summary item per imported record for this job's sheets.

    Summary items structurally duplicate record fields; deriving them here (vs
    trusting a summary sheet) keeps them from drifting from their source rows.
    """
    from iams.models import RiskAssessmentRecord, RiskAssessmentSummaryItem

    # Only touch records from sheets this job created/updated in this run —
    # approximated as records whose source sheet was seen. For simplicity and
    # idempotency we rebuild summary items for records that lack one.
    count = 0
    records = RiskAssessmentRecord.objects.filter(summary_items__isnull=True)
    to_create = []
    for rec in records.iterator(chunk_size=500):
        to_create.append(RiskAssessmentSummaryItem(
            record=rec,
            inclusion_status=rec.inclusion_status,
            audit_scope=rec.audit_scope or "",
            planned_man_days=rec.planned_man_days,
        ))
        count += 1
    if to_create:
        RiskAssessmentSummaryItem.objects.bulk_create(to_create)
    return count
