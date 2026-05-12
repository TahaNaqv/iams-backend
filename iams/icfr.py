"""ICFR (Internal Control over Financial Reporting) service helpers.

The two side-effecting verbs:

  - ``record_test_result(test, by_user, role, conclusion, notes)`` —
    writes management or auditor assessment, advances status, and
    auto-creates a draft DeficiencyReport on a ``deficient`` outcome.

  - ``classify_and_open_deficiency(test, classification, narrative, ...)`` —
    promotes an auto-created draft deficiency into Open status with
    final classification.

Plus a ``build_icfr_summary(period)`` aggregator used by both the API
``/api/icfr/summary/`` endpoint and the (Phase 4) WeasyPrint PDF.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from iams.models import (
    Control,
    ControlException,
    ControlTest,
    DeficiencyReport,
)

logger = logging.getLogger(__name__)
User = get_user_model()


class ICFRError(Exception):
    """Domain error from the ICFR workflow."""


ROLE_MANAGEMENT = "management"
ROLE_AUDITOR = "auditor"
_ASSESSMENT_ROLES = {ROLE_MANAGEMENT, ROLE_AUDITOR}


@transaction.atomic
def record_test_result(
    test: ControlTest,
    *,
    by_user: User,
    role: str,
    conclusion: str,
    notes: str = "",
) -> ControlTest:
    """Record the management or auditor conclusion on a control test.

    Args:
        role: ``"management"`` or ``"auditor"`` (segregation per FR-ICFR-04).
        conclusion: one of the ``ControlTest.CONCLUSION_*`` constants.
        notes: optional free-form rationale shown in the matrix tooltip.

    Side effects:
        - Writes the corresponding ``*_assessment`` + ``*_notes`` fields.
        - Bumps status from Planned → In Progress (first write) and to
          Completed when both sides have signed off (or when only the
          auditor has, since IA takes precedence).
        - On a ``deficient`` auditor conclusion, ensures a DeficiencyReport
          exists for this test (auto-created in ``draft`` state — the
          downstream auditor explicitly classifies + opens it).
    """
    if not by_user or not by_user.is_authenticated:
        raise ICFRError("Recording a result requires an authenticated user.")
    if role not in _ASSESSMENT_ROLES:
        raise ICFRError(f"role must be one of {sorted(_ASSESSMENT_ROLES)}.")
    valid_conclusions = {c[0] for c in ControlTest.CONCLUSION_CHOICES}
    if conclusion not in valid_conclusions:
        raise ICFRError(f"conclusion must be one of {sorted(valid_conclusions)}.")

    if role == ROLE_MANAGEMENT:
        test.management_assessment = conclusion
        test.management_assessment_notes = notes
        update_fields = ["management_assessment", "management_assessment_notes"]
    else:
        test.auditor_assessment = conclusion
        test.auditor_assessment_notes = notes
        test.reviewer = by_user
        update_fields = ["auditor_assessment", "auditor_assessment_notes", "reviewer"]

    # First non-not_tested write bumps status off Planned.
    if conclusion != ControlTest.CONCLUSION_NOT_TESTED and test.status == ControlTest.STATUS_PLANNED:
        test.status = ControlTest.STATUS_IN_PROGRESS
        update_fields.append("status")
        if test.started_at is None:
            test.started_at = timezone.now().date()
            update_fields.append("started_at")

    # When the auditor has reached a verdict, the official conclusion is
    # set — mark the test Completed. Management-only assessments don't
    # complete the test because IA still has to weigh in.
    if (
        role == ROLE_AUDITOR
        and conclusion != ControlTest.CONCLUSION_NOT_TESTED
    ):
        test.status = ControlTest.STATUS_COMPLETED
        if "status" not in update_fields:
            update_fields.append("status")
        test.completed_at = timezone.now().date()
        update_fields.append("completed_at")

    update_fields.append("updated_at")
    test.save(update_fields=update_fields)

    # Auto-create deficiency on deficient auditor conclusion.
    if role == ROLE_AUDITOR and conclusion == ControlTest.CONCLUSION_DEFICIENT:
        _ensure_draft_deficiency(test)

    return test


def _ensure_draft_deficiency(test: ControlTest) -> DeficiencyReport:
    """Create a draft deficiency for this test if none exists.

    Default classification is the most conservative (``control_deficiency``)
    so the auditor must explicitly promote it to significant / material.
    """
    existing = DeficiencyReport.objects.filter(test=test).first()
    if existing is not None:
        return existing
    return DeficiencyReport.objects.create(
        test=test,
        classification=DeficiencyReport.CLASSIFICATION_CONTROL,
        status=DeficiencyReport.STATUS_DRAFT,
        identified_date=timezone.now().date(),
        narrative=(
            f"Auto-created from {test.control.control_id} "
            f"({test.test_type}, period {test.period}). "
            "Auditor please classify and open."
        ),
    )


@transaction.atomic
def open_deficiency(
    deficiency: DeficiencyReport,
    *,
    by_user: User,
    classification: str,
    narrative: str = "",
    recommendation: str = "",
    target_resolution_date=None,
    owner: str = "",
) -> DeficiencyReport:
    """Promote a draft deficiency to Open with the auditor's final classification."""
    if deficiency.status not in (
        DeficiencyReport.STATUS_DRAFT,
        DeficiencyReport.STATUS_OPEN,
    ):
        raise ICFRError(
            f"Cannot open a deficiency in status '{deficiency.status}'."
        )
    valid = {c[0] for c in DeficiencyReport.CLASSIFICATION_CHOICES}
    if classification not in valid:
        raise ICFRError(f"classification must be one of {sorted(valid)}.")

    deficiency.classification = classification
    if narrative:
        deficiency.narrative = narrative
    if recommendation:
        deficiency.recommendation = recommendation
    if target_resolution_date is not None:
        deficiency.target_resolution_date = target_resolution_date
    if owner:
        deficiency.owner = owner
    deficiency.status = DeficiencyReport.STATUS_OPEN
    deficiency.save(update_fields=[
        "classification", "narrative", "recommendation",
        "target_resolution_date", "owner", "status", "updated_at",
    ])
    return deficiency


@transaction.atomic
def close_deficiency(
    deficiency: DeficiencyReport,
    *,
    by_user: User,
    management_response: str = "",
) -> DeficiencyReport:
    if deficiency.status == DeficiencyReport.STATUS_CLOSED:
        raise ICFRError("Already closed.")
    if deficiency.status == DeficiencyReport.STATUS_DRAFT:
        raise ICFRError("Cannot close a draft — open it first.")
    deficiency.status = DeficiencyReport.STATUS_CLOSED
    deficiency.actual_resolution_date = timezone.now().date()
    if management_response:
        deficiency.management_response = management_response
    deficiency.save(update_fields=[
        "status", "actual_resolution_date", "management_response", "updated_at",
    ])
    return deficiency


# ──────────────────────────────────────────────────────────────────────
# Aggregator: ICFR summary for the FE dashboard + Phase 4 PDF
# ──────────────────────────────────────────────────────────────────────
def build_icfr_summary(*, period: str | None = None) -> dict[str, Any]:
    """Build an aggregate view across controls, tests, exceptions, deficiencies.

    When ``period`` is supplied, test/exception/deficiency counts are
    scoped to that period; control catalog totals stay global.
    """
    controls = Control.objects.all()
    controls_by_framework = list(
        controls.values("framework").annotate(count=__import__("django.db.models", fromlist=["Count"]).Count("id")).order_by("framework")
    )
    controls_by_status = list(
        controls.values("status").annotate(count=__import__("django.db.models", fromlist=["Count"]).Count("id")).order_by("status")
    )

    tests = ControlTest.objects.all()
    if period:
        tests = tests.filter(period=period)
    tests_by_status = list(
        tests.values("status").annotate(count=__import__("django.db.models", fromlist=["Count"]).Count("id")).order_by("status")
    )
    tests_by_conclusion = Counter()
    for t in tests.only("auditor_assessment", "management_assessment"):
        tests_by_conclusion[t.conclusion] += 1
    conclusion_payload = [
        {"conclusion": k, "count": v} for k, v in sorted(tests_by_conclusion.items())
    ]

    exception_qs = ControlException.objects.all()
    if period:
        exception_qs = exception_qs.filter(test__period=period)
    exceptions_by_severity = list(
        exception_qs.values("severity").annotate(count=__import__("django.db.models", fromlist=["Count"]).Count("id")).order_by("severity")
    )

    deficiency_qs = DeficiencyReport.objects.all()
    if period:
        deficiency_qs = deficiency_qs.filter(test__period=period)
    deficiencies_by_classification = list(
        deficiency_qs.values("classification").annotate(count=__import__("django.db.models", fromlist=["Count"]).Count("id")).order_by("classification")
    )
    deficiencies_by_status = list(
        deficiency_qs.values("status").annotate(count=__import__("django.db.models", fromlist=["Count"]).Count("id")).order_by("status")
    )
    open_material_weaknesses = deficiency_qs.filter(
        classification=DeficiencyReport.CLASSIFICATION_MATERIAL,
    ).exclude(status=DeficiencyReport.STATUS_CLOSED).count()

    return {
        "period": period,
        "controlsByFramework": controls_by_framework,
        "controlsByStatus": controls_by_status,
        "testsByStatus": tests_by_status,
        "testsByConclusion": conclusion_payload,
        "exceptionsBySeverity": exceptions_by_severity,
        "deficienciesByClassification": deficiencies_by_classification,
        "deficienciesByStatus": deficiencies_by_status,
        "openMaterialWeaknesses": open_material_weaknesses,
        "totalControls": controls.count(),
        "totalTests": tests.count(),
        "totalExceptions": exception_qs.count(),
        "totalDeficiencies": deficiency_qs.count(),
    }
