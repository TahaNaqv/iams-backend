"""Tests for the Audit Universe v2 API surface.

Covers the pieces added in PR 1 (see docs/AUDIT-UNIVERSE-FORM-SPEC.md):

  - the new v2 columns round-trip through the entity API
  - StrategicObjective / KeySystem lookups, with objective coverage counts
  - the configurable materiality metric registry and its applies_to narrowing
  - materiality values, and the denormalised sort cache they maintain
  - assurance coverage, including the reliance-needs-a-rationale rule at both
    the serializer and the database level
  - derived helpers: total effort, months since last audit, suggested frequency
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from rest_framework import status

from iams.materiality import build_materiality_cache, refresh_materiality_cache
from iams.models import (
    AssuranceCoverage,
    AuditableEntity,
    AuditFrequencyChoices,
    EntityMaterialityValue,
    KeySystem,
    MaterialityMetricDefinition,
    RiskRatingChoices,
    StrategicObjective,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sa_client(super_admin, authed_client):
    return authed_client(super_admin)


@pytest.fixture
def entity(db) -> AuditableEntity:
    return AuditableEntity.objects.create(
        name="Claims handling",
        entity_type="Process",
        universe_category="Operations",
        status="Active",
    )


@pytest.fixture
def revenue_metric(db) -> MaterialityMetricDefinition:
    return MaterialityMetricDefinition.objects.create(
        code="annual_revenue", label="Annual revenue", unit="currency",
        currency="USD", display_order=1,
    )


# ══════════════════════════════════════════════════════════════════════
# New columns on the entity
# ══════════════════════════════════════════════════════════════════════
def test_v2_mandate_fields_round_trip(sa_client, entity):
    """Objectives, scope and resources persist and come back out.

    These three are what the IIA practice guide asks to be "clearly defined"
    for every auditable unit, so a silent drop here is the whole point of the
    v2 work going missing.
    """
    resp = sa_client.patch(
        f"/api/auditable-entities/{entity.id}/",
        {
            "version": entity.version,
            "code": "OPS-0042",
            "universeCategory": "Operations",
            "auditObjectives": "Establish that claims are settled within policy terms.",
            "scopeInclusions": "First-notification-of-loss through settlement.",
            "scopeExclusions": "Reinsurance recoveries.",
            "frequencySource": "Mandated",
            "mandateReference": "Insurance Ordinance s.42",
            "estimatedIaDays": "18.00",
            "estimatedCosourceDays": "4.50",
            "requiredSkills": ["actuarial", "data_analytics"],
            "applicableFrameworks": ["IFRS 17", "AML/CFT"],
            "isFraudRiskRelevant": True,
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.data

    entity.refresh_from_db()
    assert entity.code == "OPS-0042"
    assert entity.audit_objectives.startswith("Establish that claims")
    assert entity.scope_exclusions == "Reinsurance recoveries."
    assert entity.frequency_source == "Mandated"
    assert entity.mandate_reference == "Insurance Ordinance s.42"
    assert entity.required_skills == ["actuarial", "data_analytics"]
    assert entity.applicable_frameworks == ["IFRS 17", "AML/CFT"]
    assert entity.is_fraud_risk_relevant is True


def test_total_estimated_days_sums_the_split(entity):
    """Total effort is IA + co-source once either is set."""
    entity.estimated_ia_days = Decimal("18.00")
    entity.estimated_cosource_days = Decimal("4.50")
    assert entity.total_estimated_days == Decimal("22.50")


def test_total_estimated_days_falls_back_to_the_legacy_column(entity):
    """Entities not yet migrated to the split keep reporting their old figure.

    ``estimated_man_days`` stays populated for one release; without this
    fallback every pre-v2 entity would report no effort at all and drop out of
    capacity-based planning.
    """
    entity.estimated_man_days = Decimal("12.00")
    assert entity.total_estimated_days == Decimal("12.00")


def test_months_since_last_audit(entity):
    assert entity.months_since_last_audit is None
    entity.last_audit_date = date.today() - timedelta(days=400)
    assert entity.months_since_last_audit == 13


@pytest.mark.parametrize(
    "rating,expected",
    [
        (RiskRatingChoices.CRITICAL, AuditFrequencyChoices.ANNUAL),
        (RiskRatingChoices.HIGH, AuditFrequencyChoices.ANNUAL),
        (RiskRatingChoices.MEDIUM, AuditFrequencyChoices.BIENNIAL),
        (RiskRatingChoices.LOW, AuditFrequencyChoices.TRIENNIAL),
    ],
)
def test_suggested_frequency_follows_the_iia_bands(entity, rating, expected):
    """High risk at least annually, moderate 19-24 months, low 25-36 months."""
    entity.risk_rating = rating
    assert entity.suggested_audit_frequency() == expected


# ══════════════════════════════════════════════════════════════════════
# Lookups
# ══════════════════════════════════════════════════════════════════════
def test_strategic_objective_reports_coverage_count(sa_client, entity):
    """entityCount is how an uncovered objective becomes visible."""
    covered = StrategicObjective.objects.create(code="OBJ-1", title="Grow retail book")
    StrategicObjective.objects.create(code="OBJ-2", title="Exit legacy lines")
    entity.strategic_objectives.add(covered)

    resp = sa_client.get("/api/strategic-objectives/")
    assert resp.status_code == status.HTTP_200_OK
    by_code = {row["code"]: row for row in resp.data["results"]}
    assert by_code["OBJ-1"]["entityCount"] == 1
    assert by_code["OBJ-2"]["entityCount"] == 0


def test_key_system_active_only_filter(sa_client):
    KeySystem.objects.create(name="Guidewire ClaimCenter", criticality="Critical")
    KeySystem.objects.create(name="Retired mainframe", is_active=False)

    resp = sa_client.get("/api/key-systems/?activeOnly=true")
    names = [row["name"] for row in resp.data["results"]]
    assert names == ["Guidewire ClaimCenter"]


# ══════════════════════════════════════════════════════════════════════
# Materiality registry
# ══════════════════════════════════════════════════════════════════════
def test_metric_registry_applies_to_narrowing(sa_client, revenue_metric):
    """A scoped metric is offered only where it belongs; unscoped ones always.

    ``applies_to`` is an opt-in narrowing — an empty list means "offer this
    everywhere" — so a filtered request must still return the general metrics.
    """
    MaterialityMetricDefinition.objects.create(
        code="gross_written_premium", label="Gross written premium",
        unit="currency", currency="USD",
        applies_to=["Underwriting"], display_order=10,
    )

    resp = sa_client.get("/api/materiality-metrics/?universeCategory=Operations")
    codes = {row["code"] for row in resp.data["results"]}
    assert "annual_revenue" in codes
    assert "gross_written_premium" not in codes

    resp = sa_client.get("/api/materiality-metrics/?universeCategory=Underwriting")
    codes = {row["code"] for row in resp.data["results"]}
    assert {"annual_revenue", "gross_written_premium"} <= codes


def test_currency_metric_requires_a_currency(sa_client):
    """An amount without a currency is an ambiguous figure."""
    resp = sa_client.post(
        "/api/materiality-metrics/",
        {"code": "loose_amount", "label": "Loose amount", "unit": "currency"},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "currency" in resp.data


def test_metric_registry_writes_need_administration_rights(auditor_user, authed_client, revenue_metric):
    """Reading the registry is part of the job; changing it is configuration.

    Editing a definition changes what every entity in the organization is
    asked for, so it sits behind the administration gate rather than
    audit_universe edit.
    """
    client = authed_client(auditor_user)

    assert client.get("/api/materiality-metrics/").status_code == status.HTTP_200_OK

    resp = client.patch(
        f"/api/materiality-metrics/{revenue_metric.id}/",
        {"label": "Turnover"},
        format="json",
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ══════════════════════════════════════════════════════════════════════
# Materiality values + sort cache
# ══════════════════════════════════════════════════════════════════════
def test_posting_a_value_refreshes_the_sort_cache(sa_client, entity, revenue_metric):
    resp = sa_client.post(
        "/api/entity-materiality/",
        {
            "entityId": str(entity.id),
            "definitionId": str(revenue_metric.id),
            "value": "4100000.00",
            "asOf": "2026-03-31",
            "source": "GL extract FY26",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.data

    entity.refresh_from_db()
    assert entity.materiality_cache == {"annual_revenue": 4100000.0}


def test_cache_takes_the_most_recent_period(entity, revenue_metric):
    """Two periods for one metric: the newest wins in the cache."""
    EntityMaterialityValue.objects.create(
        entity=entity, definition=revenue_metric,
        value=Decimal("3000000"), as_of=date(2025, 3, 31),
    )
    EntityMaterialityValue.objects.create(
        entity=entity, definition=revenue_metric,
        value=Decimal("4100000"), as_of=date(2026, 3, 31),
    )
    assert build_materiality_cache(entity) == {"annual_revenue": 4100000.0}


def test_cache_refresh_does_not_bump_version(entity, revenue_metric):
    """Refreshing a derived cache is not a user edit.

    If it bumped ``version`` it would make a concurrent PATCH fail its
    optimistic-locking check with a 409 that the user did nothing to earn.
    """
    before = entity.version
    EntityMaterialityValue.objects.create(
        entity=entity, definition=revenue_metric,
        value=Decimal("1"), as_of=date(2026, 3, 31),
    )
    refresh_materiality_cache(entity)

    entity.refresh_from_db()
    assert entity.version == before
    assert entity.materiality_cache == {"annual_revenue": 1.0}


def test_one_value_per_metric_per_period(entity, revenue_metric):
    EntityMaterialityValue.objects.create(
        entity=entity, definition=revenue_metric,
        value=Decimal("1"), as_of=date(2026, 3, 31),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        EntityMaterialityValue.objects.create(
            entity=entity, definition=revenue_metric,
            value=Decimal("2"), as_of=date(2026, 3, 31),
        )


# ══════════════════════════════════════════════════════════════════════
# Assurance coverage (Standard 9.5)
# ══════════════════════════════════════════════════════════════════════
def test_reliance_without_rationale_is_rejected(sa_client, entity):
    resp = sa_client.post(
        "/api/assurance-coverage/",
        {
            "entityId": str(entity.id),
            "providerName": "Group Compliance",
            "providerType": "second_line",
            "relianceLevel": "partial",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "relianceRationale" in resp.data


def test_reliance_with_rationale_is_accepted(sa_client, entity):
    resp = sa_client.post(
        "/api/assurance-coverage/",
        {
            "entityId": str(entity.id),
            "providerName": "Group Compliance",
            "providerType": "second_line",
            "scope": "Sanctions screening controls",
            "lastReviewDate": "2026-02-10",
            "relianceLevel": "partial",
            "relianceRationale": "Methodology reviewed by IA in Q4 2025; testing re-performed on a sample.",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.data
    assert AssuranceCoverage.objects.filter(entity=entity).count() == 1


def test_future_last_review_date_is_rejected(sa_client, entity):
    """A future 'last review' would feed the recency factor a false signal."""
    resp = sa_client.post(
        "/api/assurance-coverage/",
        {
            "entityId": str(entity.id),
            "providerName": "External audit",
            "providerType": "external_audit",
            "lastReviewDate": str(date.today() + timedelta(days=30)),
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "lastReviewDate" in resp.data


def test_reliance_rule_is_enforced_by_the_database_too(entity):
    """The serializer is not the only writer — admin and imports write here."""
    with pytest.raises(IntegrityError), transaction.atomic():
        AssuranceCoverage.objects.create(
            entity=entity,
            provider_name="Regulator",
            provider_type="regulator",
            reliance_level="full",
            reliance_rationale="",
        )


# ══════════════════════════════════════════════════════════════════════
# Filters
# ══════════════════════════════════════════════════════════════════════
def test_framework_and_skill_filters(sa_client, entity):
    """JSON-list columns filter correctly on both Postgres and SQLite."""
    entity.applicable_frameworks = ["IFRS 17", "AML/CFT"]
    entity.required_skills = ["actuarial"]
    entity.save()
    AuditableEntity.objects.create(
        name="IT general controls", entity_type="Process",
        applicable_frameworks=["SOX"], required_skills=["it_general_controls"],
    )

    resp = sa_client.get("/api/auditable-entities/?applicableFramework=IFRS 17")
    assert [r["name"] for r in resp.data["results"]] == ["Claims handling"]

    resp = sa_client.get("/api/auditable-entities/?requiredSkill=it_general_controls")
    assert [r["name"] for r in resp.data["results"]] == ["IT general controls"]


def test_coverage_gap_filters(sa_client, entity):
    """The tiles that tell a team what to finish before planning season."""
    complete = AuditableEntity.objects.create(
        name="Underwriting", entity_type="Process",
        audit_objectives="Establish pricing discipline.",
        scope_inclusions="Quote through bind.",
        estimated_ia_days=Decimal("10"),
    )

    resp = sa_client.get("/api/auditable-entities/?withoutObjectives=true")
    names = {r["name"] for r in resp.data["results"]}
    assert entity.name in names and complete.name not in names

    resp = sa_client.get("/api/auditable-entities/?withoutEffortEstimate=true")
    names = {r["name"] for r in resp.data["results"]}
    assert entity.name in names and complete.name not in names


def test_legacy_man_days_counts_as_an_effort_estimate(sa_client, entity):
    """A pre-v2 entity is not reported as missing an estimate it already has."""
    entity.estimated_man_days = Decimal("8")
    entity.save()

    resp = sa_client.get("/api/auditable-entities/?withoutEffortEstimate=true")
    assert entity.name not in {r["name"] for r in resp.data["results"]}


def test_universe_category_filter_accepts_a_csv(sa_client, entity):
    AuditableEntity.objects.create(
        name="Board reporting", entity_type="Process", universe_category="Governance",
    )
    AuditableEntity.objects.create(
        name="Payroll", entity_type="Process", universe_category="Support",
    )

    resp = sa_client.get("/api/auditable-entities/?universeCategory=Operations,Governance")
    assert {r["name"] for r in resp.data["results"]} == {"Claims handling", "Board reporting"}


# ══════════════════════════════════════════════════════════════════════
# Audit trail
# ══════════════════════════════════════════════════════════════════════
def test_v2_field_changes_land_in_the_revision_diff(sa_client, entity):
    """Objectives and effort are exactly what a QA reviewer asks about."""
    from iams.models import AuditableEntityRevision

    sa_client.patch(
        f"/api/auditable-entities/{entity.id}/",
        {
            "version": entity.version,
            "auditObjectives": "Establish that claims are settled within policy terms.",
            "estimatedIaDays": "18.00",
        },
        format="json",
    )

    revision = AuditableEntityRevision.objects.filter(entity=entity).order_by("-version").first()
    assert revision is not None
    assert "audit_objectives" in revision.changes
    assert revision.changes["audit_objectives"]["to"].startswith("Establish that claims")
    assert "estimated_ia_days" in revision.changes
