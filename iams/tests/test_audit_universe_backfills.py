"""Tests for the Audit Universe v2 data backfills (migrations 0050-0053).

The property that matters most is **idempotency**: in production each backfill
runs twice — once manually via ``manage.py backfill_audit_universe`` in the
maintenance window, then again when the migration lands. A second run must
change nothing.

The second property is that a backfill never overwrites a human's value. Where
a derived answer disagrees with a stored one the row is reported, not
corrected.
"""
from __future__ import annotations

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from iams.backfills import (
    MIGRATED_RISK_TITLE,
    backfill_entity_codes,
    derive_structural_links,
    migrate_inherent_risk_to_register,
    migrate_materiality_values,
)
from iams.models import (
    AuditableEntity,
    BusinessUnit,
    EntityMaterialityValue,
    EntityRisk,
    MaterialityMetricDefinition,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def metrics(db):
    """The two definitions migration 0049 seeds and 0052 depends on."""
    return {
        "headcount": MaterialityMetricDefinition.objects.create(
            code="headcount", label="Staff count", unit="fte", display_order=5,
        ),
        "annual_expenses": MaterialityMetricDefinition.objects.create(
            code="annual_expenses", label="Annual operating expenses",
            unit="currency", currency="USD", display_order=2,
        ),
    }


# ══════════════════════════════════════════════════════════════════════
# 0050 — entity codes
# ══════════════════════════════════════════════════════════════════════
def test_codes_use_the_category_prefix_and_sequence():
    AuditableEntity.objects.create(name="Claims", universe_category="Operations")
    AuditableEntity.objects.create(name="Payments", universe_category="Operations")
    AuditableEntity.objects.create(name="Board pack", universe_category="Governance")

    report = backfill_entity_codes(AuditableEntity)

    assert report["assigned"] == 3
    codes = dict(AuditableEntity.objects.values_list("name", "code"))
    assert codes["Claims"] == "OPS-0001"
    assert codes["Payments"] == "OPS-0002"
    assert codes["Board pack"] == "GOV-0001"


def test_code_prefix_falls_back_to_entity_type_then_generic():
    AuditableEntity.objects.create(name="Finance", entity_type="Department")
    AuditableEntity.objects.create(name="Odd one", entity_type="")

    backfill_entity_codes(AuditableEntity)

    codes = dict(AuditableEntity.objects.values_list("name", "code"))
    assert codes["Finance"].startswith("DEP-")
    assert codes["Odd one"].startswith("AE-")


def test_existing_codes_are_never_renumbered_and_reserve_their_number():
    AuditableEntity.objects.create(
        name="Hand-numbered", universe_category="Operations", code="OPS-0007",
    )
    AuditableEntity.objects.create(name="New", universe_category="Operations")

    backfill_entity_codes(AuditableEntity)

    codes = dict(AuditableEntity.objects.values_list("name", "code"))
    assert codes["Hand-numbered"] == "OPS-0007"
    # The sequence continues past the hand-written number rather than colliding.
    assert codes["New"] == "OPS-0008"


def test_a_free_form_code_is_left_alone():
    """An administrator's own scheme survives the backfill untouched."""
    AuditableEntity.objects.create(
        name="Legacy ref", universe_category="Operations", code="LEGACY/CLAIMS/1",
    )

    report = backfill_entity_codes(AuditableEntity)

    assert report["assigned"] == 0
    assert AuditableEntity.objects.get(name="Legacy ref").code == "LEGACY/CLAIMS/1"


def test_codes_are_assigned_to_archived_entities_too():
    """0055 makes the column required for every row, archived included."""
    archived = AuditableEntity.objects.create(
        name="Retired process", universe_category="Operations", status="Archived",
    )

    backfill_entity_codes(AuditableEntity)

    archived.refresh_from_db()
    assert archived.code.startswith("OPS-")


def test_codes_backfill_is_idempotent():
    for i in range(3):
        AuditableEntity.objects.create(name=f"E{i}", universe_category="Finance")

    first = backfill_entity_codes(AuditableEntity)
    before = dict(AuditableEntity.objects.values_list("name", "code"))
    second = backfill_entity_codes(AuditableEntity)

    assert first["assigned"] == 3
    assert second["assigned"] == 0
    assert dict(AuditableEntity.objects.values_list("name", "code")) == before


def test_dry_run_writes_nothing():
    AuditableEntity.objects.create(name="Claims", universe_category="Operations")

    report = backfill_entity_codes(AuditableEntity, dry_run=True)

    assert report["assigned"] == 1
    assert AuditableEntity.objects.get(name="Claims").code == ""


# ══════════════════════════════════════════════════════════════════════
# 0051 — structural links
# ══════════════════════════════════════════════════════════════════════
@pytest.fixture
def hierarchy(db):
    """BU > Department > Process > Sub-process, links deliberately left blank."""
    bu = BusinessUnit.objects.create(name="Insurance Operations")
    dept = AuditableEntity.objects.create(
        name="Claims department", entity_type="Department", business_unit=bu,
    )
    process = AuditableEntity.objects.create(
        name="Claims handling", entity_type="Process", parent=dept,
    )
    sub = AuditableEntity.objects.create(
        name="FNOL intake", entity_type="Process", parent=process,
    )
    return {"bu": bu, "dept": dept, "process": process, "sub": sub}


def test_links_derive_from_the_nearest_ancestors(hierarchy):
    report = derive_structural_links(AuditableEntity)

    process = AuditableEntity.objects.get(pk=hierarchy["process"].pk)
    sub = AuditableEntity.objects.get(pk=hierarchy["sub"].pk)

    assert process.department_entity_id == hierarchy["dept"].pk
    assert process.business_unit_id == hierarchy["bu"].pk
    # Two levels down still resolves to the same department and BU.
    assert sub.department_entity_id == hierarchy["dept"].pk
    assert sub.business_unit_id == hierarchy["bu"].pk
    assert report["department_filled"] == 2
    assert report["business_unit_filled"] == 2


def test_a_disagreeing_stored_value_is_reported_not_overwritten(hierarchy):
    """Picking a winner is a conversation, not a deploy-time decision."""
    other_dept = AuditableEntity.objects.create(
        name="Finance department", entity_type="Department",
    )
    process = hierarchy["process"]
    process.department_entity = other_dept
    process.save()

    report = derive_structural_links(AuditableEntity)

    process.refresh_from_db()
    assert process.department_entity_id == other_dept.pk
    mismatches = {row["entity"] for row in report["department_mismatches"]}
    assert str(process.pk) in mismatches


def test_roots_are_left_alone(hierarchy):
    """A top-level entity has nothing to inherit; its own values stand."""
    root = AuditableEntity.objects.create(name="Group risk", entity_type="Division")

    derive_structural_links(AuditableEntity)

    root.refresh_from_db()
    assert root.department_entity_id is None
    assert root.business_unit_id is None


def test_parent_cycle_terminates(db):
    """A corrupted parent loop must not hang the deploy."""
    a = AuditableEntity.objects.create(name="A", entity_type="Process")
    b = AuditableEntity.objects.create(name="B", entity_type="Process", parent=a)
    AuditableEntity.all_objects.filter(pk=a.pk).update(parent=b)

    report = derive_structural_links(AuditableEntity)

    assert report["scanned"] == 2


def test_links_backfill_is_idempotent(hierarchy):
    derive_structural_links(AuditableEntity)
    second = derive_structural_links(AuditableEntity)

    assert second["department_filled"] == 0
    assert second["business_unit_filled"] == 0
    assert second["department_mismatches"] == []


# ══════════════════════════════════════════════════════════════════════
# 0052 — materiality values
# ══════════════════════════════════════════════════════════════════════
def test_legacy_columns_become_metric_values(metrics):
    entity = AuditableEntity.objects.create(
        name="Claims", headcount=42, operating_budget=Decimal("1250000.00"),
    )

    report = migrate_materiality_values(
        AuditableEntity, MaterialityMetricDefinition, EntityMaterialityValue,
    )

    assert report["created"] == 2
    values = {
        v.definition.code: v
        for v in EntityMaterialityValue.objects.filter(entity=entity).select_related("definition")
    }
    assert values["headcount"].value == Decimal("42.00")
    assert values["annual_expenses"].value == Decimal("1250000.00")
    # The source must not let anyone mistake the migration date for a period.
    assert "period not recorded" in values["headcount"].source


def test_entities_without_legacy_values_are_skipped(metrics):
    AuditableEntity.objects.create(name="Empty")

    report = migrate_materiality_values(
        AuditableEntity, MaterialityMetricDefinition, EntityMaterialityValue,
    )

    assert report["created"] == 0


def test_materiality_backfill_is_idempotent_across_days(metrics):
    """Guarding on (entity, metric) rather than period is what makes this work.

    Guarding on the period instead would create a fresh duplicate row every
    day the backfill was re-run.
    """
    from datetime import date

    AuditableEntity.objects.create(name="Claims", headcount=42)

    first = migrate_materiality_values(
        AuditableEntity, MaterialityMetricDefinition, EntityMaterialityValue,
        as_of=date(2026, 9, 16),
    )
    second = migrate_materiality_values(
        AuditableEntity, MaterialityMetricDefinition, EntityMaterialityValue,
        as_of=date(2026, 9, 17),
    )

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["skipped_existing"] == 1
    assert EntityMaterialityValue.objects.count() == 1


def test_missing_metric_definitions_are_reported_not_invented(db):
    """An administrator deleted the definitions; do not silently re-create them."""
    AuditableEntity.objects.create(name="Claims", headcount=42)

    report = migrate_materiality_values(
        AuditableEntity, MaterialityMetricDefinition, EntityMaterialityValue,
    )

    assert report["created"] == 0
    assert report["missing_definitions"] == ["annual_expenses", "headcount"]


# ══════════════════════════════════════════════════════════════════════
# 0053 — inherent assessment into the register
# ══════════════════════════════════════════════════════════════════════
def test_bare_inherent_pair_becomes_a_risk_row():
    entity = AuditableEntity.objects.create(
        name="Claims", inherent_likelihood=4, inherent_impact=5,
    )

    report = migrate_inherent_risk_to_register(AuditableEntity, EntityRisk)

    assert report["created"] == 1
    risk = EntityRisk.objects.get(entity=entity)
    assert risk.title == MIGRATED_RISK_TITLE
    assert (risk.inherent_likelihood, risk.inherent_impact) == (4, 5)
    # No post-control position is claimed, because none was ever assessed.
    assert risk.residual_likelihood is None
    assert risk.residual_impact is None
    assert risk.control_effectiveness == "Not Assessed"


def test_entities_that_already_have_risks_are_left_alone():
    entity = AuditableEntity.objects.create(
        name="Claims", inherent_likelihood=4, inherent_impact=5,
    )
    EntityRisk.objects.create(
        entity=entity, title="Real risk", inherent_likelihood=2, inherent_impact=2,
    )

    report = migrate_inherent_risk_to_register(AuditableEntity, EntityRisk)

    assert report["created"] == 0
    assert report["skipped_has_risks"] == 1
    assert EntityRisk.objects.filter(entity=entity).count() == 1


def test_a_half_filled_pair_is_not_migrated():
    """One of the two values alone is not an assessment."""
    AuditableEntity.objects.create(name="Claims", inherent_likelihood=4)

    report = migrate_inherent_risk_to_register(AuditableEntity, EntityRisk)

    assert report["created"] == 0


def test_migration_does_not_change_the_entitys_rating():
    """bulk_create skips post_save, so the roll-up does not fire.

    A backfill whose purpose is to preserve the current position must not
    change ratings on its way past — otherwise entities silently re-band
    during a deploy and nobody can explain why.
    """
    entity = AuditableEntity.objects.create(
        name="Claims", inherent_likelihood=1, inherent_impact=1,
        risk_rating="Critical",
    )

    migrate_inherent_risk_to_register(AuditableEntity, EntityRisk)

    entity.refresh_from_db()
    assert entity.risk_rating == "Critical"
    assert entity.residual_likelihood is None


def test_inherent_backfill_is_idempotent():
    AuditableEntity.objects.create(
        name="Claims", inherent_likelihood=4, inherent_impact=5,
    )

    first = migrate_inherent_risk_to_register(AuditableEntity, EntityRisk)
    second = migrate_inherent_risk_to_register(AuditableEntity, EntityRisk)

    assert first["created"] == 1
    assert second["created"] == 0
    assert EntityRisk.objects.count() == 1


# ══════════════════════════════════════════════════════════════════════
# The management command
# ══════════════════════════════════════════════════════════════════════
def test_command_dry_run_reports_without_writing(metrics, hierarchy):
    AuditableEntity.objects.create(
        name="Claims", universe_category="Operations", headcount=42,
        inherent_likelihood=3, inherent_impact=3,
    )
    out = StringIO()

    call_command("backfill_audit_universe", "--dry-run", stdout=out)

    output = out.getvalue()
    assert "Dry run" in output
    assert "Entity codes" in output
    # Nothing was written by any of the four steps.
    assert AuditableEntity.objects.filter(code="").count() == AuditableEntity.objects.count()
    assert EntityMaterialityValue.objects.count() == 0
    assert EntityRisk.objects.count() == 0


def test_command_only_runs_the_requested_step(metrics):
    AuditableEntity.objects.create(
        name="Claims", universe_category="Operations", headcount=42,
    )
    out = StringIO()

    call_command("backfill_audit_universe", "--only", "codes", stdout=out)

    assert AuditableEntity.objects.get(name="Claims").code == "OPS-0001"
    # The materiality step did not run.
    assert EntityMaterialityValue.objects.count() == 0
    assert "Materiality values" not in out.getvalue()


def test_command_surfaces_structural_disagreements(hierarchy):
    other_dept = AuditableEntity.objects.create(
        name="Finance department", entity_type="Department",
    )
    process = hierarchy["process"]
    process.department_entity = other_dept
    process.save()
    out = StringIO()

    call_command("backfill_audit_universe", "--only", "links", "--dry-run", stdout=out)

    output = out.getvalue()
    assert "disagrees with" in output
    assert str(process.pk) in output


def test_command_writes_when_not_a_dry_run(metrics):
    AuditableEntity.objects.create(
        name="Claims", universe_category="Operations", headcount=42,
        inherent_likelihood=3, inherent_impact=3,
    )
    out = StringIO()

    call_command("backfill_audit_universe", stdout=out)

    entity = AuditableEntity.objects.get(name="Claims")
    assert entity.code == "OPS-0001"
    assert entity.materiality_cache == {"headcount": 42.0}
    assert EntityRisk.objects.filter(entity=entity).count() == 1
    assert "Backfill complete" in out.getvalue()
