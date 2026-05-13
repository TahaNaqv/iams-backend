"""Dashboard aggregators (FR-DASH-01..11).

Pure functions that return JSON-serializable payloads. Each function is
cacheable — the view layer wraps them in a Redis cache via
``cache_or_compute(key, fn, ttl)`` so the same payload doesn't get
recomputed on every poll.

Role-specific bundles (Executive / Manager / Auditor / Auditee) reuse
the same primitives — only the *combination* and the row-filter
predicates change per role.

Materialized views (Phase 5 hardening) would back the slowest
aggregators; for now we rely on the indexes added in Phase 0 + Track 1.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.db.models import Avg, Count, Q

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Cache helper
# ──────────────────────────────────────────────────────────────────────
DEFAULT_TTL = 45  # seconds — between two FE 60s polls so each gets a fresh-enough payload


def _cache_key(prefix: str, **params: Any) -> str:
    """Build a stable cache key from a kwargs dict.

    Order-stable JSON dump + sha256 keeps the key compact even when
    callers pass complex param sets.
    """
    payload = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"iams:dashboard:{prefix}:{digest}"


def cache_or_compute(key: str, fn, *, ttl: int = DEFAULT_TTL):
    """Run ``fn()`` only on a cache miss; otherwise return the cached value.

    Cache failures (Redis down) degrade gracefully thanks to
    ``DJANGO_REDIS_IGNORE_EXCEPTIONS=True`` set in Phase 0 settings.
    """
    cached = cache.get(key)
    if cached is not None:
        return cached
    value = fn()
    try:
        cache.set(key, value, ttl)
    except Exception:  # noqa: BLE001
        logger.exception("dashboard cache write failed")
    return value


def invalidate_dashboard_cache() -> int:
    """Drop every dashboard cache key. Returns the number of keys removed.

    Called by the beat task ``iams.dashboards.refresh_caches`` and by
    domain signals when state changes that would invalidate every
    cached payload (rare; most state changes are too granular to
    bother).
    """
    try:
        return cache.delete_pattern("iams:dashboard:*") or 0
    except (AttributeError, NotImplementedError):
        # django-redis exposes delete_pattern; LocMemCache (tests) does
        # not. In that case the per-key TTL drains naturally.
        return 0


# ──────────────────────────────────────────────────────────────────────
# Core KPIs (FR-DASH-02) — extends the existing /dashboard/kpis/
# ──────────────────────────────────────────────────────────────────────
def core_kpis(*, period: str | None = None, department: str | None = None) -> dict[str, Any]:
    """Top-line numbers shown in the four KPI cards.

    ``period`` accepts "YYYY" or "YYYY-Qn". ``department`` filters
    audits/findings/CAPs by department name (free-text).
    """
    from iams.models import Audit, CorrectiveAction, Finding

    today = date.today()

    audits = Audit.objects.all()
    findings = Finding.objects.all()
    caps = CorrectiveAction.objects.all()

    audits = _filter_by_period_year(audits, "start_date", period)
    findings = _filter_by_period_year(findings, "created_date", period)
    # CAPs don't have a created_date field on the audit-cycle scale —
    # we filter on due_date for symmetry.
    caps = _filter_by_period_year(caps, "due_date", period)

    if department:
        audits = audits.filter(department=department)
        findings = findings.filter(department=department)
        caps = caps.filter(department=department)

    open_audits = audits.exclude(status="Completed").count()
    overdue_findings = findings.filter(~Q(status="Closed"), due_date__lt=today).count()
    pending_caps = caps.exclude(status="Closed").count()
    total_caps = caps.count()
    closed_caps = caps.filter(status="Closed").count()
    completion_rate = int((closed_caps / total_caps) * 100) if total_caps else 0

    return {
        "openAudits": open_audits,
        "overdueFindings": overdue_findings,
        "pendingCAPs": pending_caps,
        "completionRate": completion_rate,
        "period": period,
        "department": department,
    }


# ──────────────────────────────────────────────────────────────────────
# Trends (FR-DASH-10)
# ──────────────────────────────────────────────────────────────────────
def trends(*, period: str = "YoY", department: str | None = None) -> dict[str, Any]:
    """Year-over-year (or rolling-quarter) finding/audit/CAP trends.

    ``period`` values:
      - ``"YoY"`` (default) — last 8 quarters, this year vs last
      - ``"FY{N}"`` — quarters of fiscal year N (1..4)
    """
    from iams.models import Audit, CorrectiveAction, Finding

    today = date.today()
    if period == "YoY":
        # Walk back 8 quarter buckets from current quarter
        current_q = (today.month - 1) // 3 + 1
        current_year = today.year
        windows = []
        for offset in range(7, -1, -1):
            q = current_q - offset
            y = current_year
            while q < 1:
                q += 4
                y -= 1
            windows.append((y, q))
    else:
        try:
            year = int(period.replace("FY", "")) if period.startswith("FY") else int(period)
            windows = [(year, q) for q in range(1, 5)]
        except (ValueError, TypeError):
            windows = []

    findings_qs = Finding.objects.all()
    audits_qs = Audit.objects.all()
    caps_qs = CorrectiveAction.objects.all()
    if department:
        findings_qs = findings_qs.filter(department=department)
        audits_qs = audits_qs.filter(department=department)
        caps_qs = caps_qs.filter(department=department)

    series = []
    for year, q in windows:
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        f_count = findings_qs.filter(
            created_date__year=year,
            created_date__month__gte=start_month,
            created_date__month__lte=end_month,
        ).count()
        a_count = audits_qs.filter(
            status="Completed",
            end_date__year=year,
            end_date__month__gte=start_month,
            end_date__month__lte=end_month,
        ).count()
        # CAPs closed in that quarter
        c_count = caps_qs.filter(
            status="Closed",
            # Use updated_at as a proxy for closure date; in Phase 5 we
            # add an explicit closed_at field.
            updated_at__year=year,
            updated_at__month__gte=start_month,
            updated_at__month__lte=end_month,
        ).count()
        series.append({
            "period": f"{year}-Q{q}",
            "findings": f_count,
            "auditsCompleted": a_count,
            "capsClosed": c_count,
        })

    return {
        "period": period,
        "department": department,
        "series": series,
    }


# ──────────────────────────────────────────────────────────────────────
# Risk heat map by department (FR-DASH-04)
# ──────────────────────────────────────────────────────────────────────
def risk_heatmap_by_department() -> dict[str, Any]:
    """Aggregate the count + average composite score of current risk
    scores grouped by department × risk category.

    Risk category is bucketed from composite score:
      - Critical:  >= 80
      - High:       60..80
      - Medium:     40..60
      - Low:        < 40
    """
    from iams.models import AuditableEntity, EntityRiskScore

    rows = (
        EntityRiskScore.objects
        .filter(is_current=True)
        .select_related("entity")
        .values("entity__department", "composite_score")
    )
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        dept = row["entity__department"] or "—"
        score = float(row["composite_score"] or 0)
        if score >= 80:
            cat = "Critical"
        elif score >= 60:
            cat = "High"
        elif score >= 40:
            cat = "Medium"
        else:
            cat = "Low"
        buckets.setdefault(dept, {"Critical": 0, "High": 0, "Medium": 0, "Low": 0})
        buckets[dept][cat] += 1

    cells = []
    for dept, counts in sorted(buckets.items()):
        for cat in ("Critical", "High", "Medium", "Low"):
            cells.append({
                "department": dept,
                "category": cat,
                "count": counts[cat],
            })

    return {
        "categories": ["Critical", "High", "Medium", "Low"],
        "departments": sorted(buckets.keys()),
        "cells": cells,
    }


# ──────────────────────────────────────────────────────────────────────
# Activity feed (FR-DASH-05) + Upcoming audits (FR-DASH-06)
# ──────────────────────────────────────────────────────────────────────
def recent_activity(*, limit: int = 20) -> list[dict[str, Any]]:
    """Last N audit-log entries, shaped for the dashboard timeline."""
    from iams.models import AuditLogEntry

    rows = (
        AuditLogEntry.objects.order_by("-timestamp")
        [:limit]
    )
    return [
        {
            "id": str(r.id),
            "actor": r.actor,
            "action": r.action,
            "target": r.target,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]


def upcoming_audits(*, limit: int = 10, department: str | None = None) -> list[dict[str, Any]]:
    """Upcoming audits sorted by start_date, future first."""
    from iams.models import Audit

    today = date.today()
    qs = Audit.objects.filter(start_date__gte=today).order_by("start_date")
    if department:
        qs = qs.filter(department=department)
    return [
        {
            "id": str(a.id),
            "title": a.title,
            "department": a.department,
            "startDate": a.start_date.isoformat() if a.start_date else None,
            "endDate": a.end_date.isoformat() if a.end_date else None,
            "status": a.status,
            "leadAuditor": a.lead_auditor,
            "priority": a.priority,
        }
        for a in qs[:limit]
    ]


# ──────────────────────────────────────────────────────────────────────
# Rating summaries (FR-DASH-09)
# ──────────────────────────────────────────────────────────────────────
def rating_summary(*, period: str | None = None) -> dict[str, Any]:
    """Aggregate rating outcomes across the IAMS surfaces that produce one.

    Three buckets:
      - QAIP assessment ratings (Satisfactory / Needs Improvement / Unsatisfactory)
      - ICFR test conclusions (Effective / Deficient / Not Tested)
      - CSA response weak-flags
    """
    from iams.models import (
        CSAResponse,
        ControlTest,
        QAIPAssessment,
    )

    qaip_qs = QAIPAssessment.objects.all()
    icfr_qs = ControlTest.objects.all()
    csa_qs = CSAResponse.objects.filter(status__in=["submitted", "under_review", "closed"])
    if period:
        qaip_qs = qaip_qs.filter(period=period)
        icfr_qs = icfr_qs.filter(period=period)

    return {
        "period": period,
        "qaip": list(qaip_qs.values("rating_overall").annotate(count=Count("id")).order_by("rating_overall")),
        "icfr": [
            {"conclusion": c, "count": icfr_qs.filter(auditor_assessment=c).count()}
            for c in ("effective", "deficient", "not_tested")
        ],
        "csa": {
            "weak": csa_qs.filter(is_weak=True).count(),
            "ok": csa_qs.filter(is_weak=False).count(),
            "averageScore": float(csa_qs.aggregate(avg=Avg("score_overall"))["avg"] or 0),
        },
    }


# ──────────────────────────────────────────────────────────────────────
# Role-specific bundles
# ──────────────────────────────────────────────────────────────────────
VALID_ROLES = {"executive", "manager", "auditor", "auditee"}


def role_bundle(*, role: str, user_email: str | None = None) -> dict[str, Any]:
    """Pre-composed dashboard for the four primary roles.

    Each bundle returns the panels that the FE renders for that role.
    Heavy aggregations are wrapped in their own cache keys so two
    roles asking for the same panel hit the same cache entry.
    """
    role = (role or "").lower()
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {sorted(VALID_ROLES)}; got {role!r}")

    if role == "executive":
        return {
            "role": role,
            "kpis": core_kpis(),
            "trends": trends(period="YoY"),
            "riskHeatmap": risk_heatmap_by_department(),
            "ratings": rating_summary(),
            "upcomingAudits": upcoming_audits(limit=5),
        }

    if role == "manager":
        return {
            "role": role,
            "kpis": core_kpis(),
            "trends": trends(period="YoY"),
            "ratings": rating_summary(),
            "upcomingAudits": upcoming_audits(limit=10),
            "recentActivity": recent_activity(limit=10),
        }

    if role == "auditor":
        # Auditor-scoped numbers: their own assigned audits / open findings.
        from iams.models import Audit, Finding
        my_audits = []
        my_findings = []
        if user_email:
            my_audits = list(
                Audit.objects.filter(lead_auditor__iexact=user_email)
                .order_by("-start_date").values("id", "title", "status", "start_date", "end_date")[:5]
            )
            my_findings = list(
                Finding.objects.filter(owner__iexact=user_email)
                .exclude(status="Closed")
                .order_by("due_date")
                .values("id", "title", "severity", "status", "due_date")[:10]
            )
        return {
            "role": role,
            "myAudits": my_audits,
            "myOpenFindings": my_findings,
            "upcomingAudits": upcoming_audits(limit=5),
            "recentActivity": recent_activity(limit=10),
        }

    # auditee
    from iams.models import CSAResponse, CorrectiveAction
    my_caps = []
    my_csa = []
    if user_email:
        my_caps = list(
            CorrectiveAction.objects.filter(owner__iexact=user_email)
            .exclude(status="Closed")
            .order_by("due_date")
            .values("id", "title", "status", "priority", "progress", "due_date")[:10]
        )
        my_csa = list(
            CSAResponse.objects.filter(responder__email__iexact=user_email)
            .order_by("-created_at")
            .values("id", "questionnaire__title", "status", "score_overall", "is_weak")[:5]
        )
    return {
        "role": role,
        "myOpenCAPs": my_caps,
        "myCSAResponses": my_csa,
        "recentActivity": recent_activity(limit=5),
    }


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _filter_by_period_year(qs, date_field: str, period: str | None):
    """Apply a period filter using a date field.

    Supports ``"YYYY"`` and ``"YYYY-Qn"`` shapes; leaves the queryset
    untouched for anything else (including ``None``).
    """
    if not period:
        return qs
    if len(period) == 4 and period.isdigit():
        return qs.filter(**{f"{date_field}__year": int(period)})
    if "-Q" in period:
        try:
            year_str, q_str = period.split("-Q", 1)
            year, q = int(year_str), int(q_str)
            if 1 <= q <= 4:
                start_month = (q - 1) * 3 + 1
                end_month = start_month + 2
                return qs.filter(**{
                    f"{date_field}__year": year,
                    f"{date_field}__month__gte": start_month,
                    f"{date_field}__month__lte": end_month,
                })
        except (TypeError, ValueError):
            pass
    return qs
