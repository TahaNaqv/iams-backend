# Audit Universe v2 — move the legacy size columns into the metric registry.
#
# headcount -> the "headcount" metric, operating_budget -> "annual_expenses".
# The columns stay readable for one more release (0055 drops them); this makes
# the registry the place the figures actually live, and refreshes the
# denormalised sort cache so the register keeps sorting correctly.
#
# Idempotent by (entity, metric): an entity that already has a value for a
# metric is left alone, so a second run creates nothing.

from django.db import migrations

from iams.backfills import migrate_materiality_values


def forwards(apps, schema_editor):
    Entity = apps.get_model("iams", "AuditableEntity")
    MetricDef = apps.get_model("iams", "MaterialityMetricDefinition")
    MaterialityValue = apps.get_model("iams", "EntityMaterialityValue")
    report = migrate_materiality_values(Entity, MetricDef, MaterialityValue)

    if not report["created"]:
        return
    # Rebuild the sort cache for the entities we just gave values to. Done
    # inline with historical models rather than by calling iams.materiality,
    # which builds its queries against the real ones.
    rows = (
        MaterialityValue.objects
        .select_related("definition")
        .order_by("entity_id", "definition__code", "-as_of")
    )
    caches: dict = {}
    for row in rows:
        per_entity = caches.setdefault(row.entity_id, {})
        if row.definition.code in per_entity or row.value is None:
            continue
        per_entity[row.definition.code] = float(row.value)
    for entity_id, cache in caches.items():
        Entity.objects.filter(pk=entity_id).update(materiality_cache=cache)


def backwards(apps, schema_editor):
    MaterialityValue = apps.get_model("iams", "EntityMaterialityValue")
    Entity = apps.get_model("iams", "AuditableEntity")
    MaterialityValue.objects.filter(source__startswith="Migrated from legacy ").delete()
    Entity.objects.update(materiality_cache={})


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0051_derive_structural_links"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
