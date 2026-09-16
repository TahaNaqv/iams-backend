# Audit Universe v2 — preserve entity-level inherent likelihood/impact as a
# risk-register entry before those fields stop being form inputs.
#
# In v2 an assessment is entered as EntityRisk line items carrying controls and
# a residual position, and the entity's own inherent_likelihood /
# inherent_impact become roll-up outputs. Any entity that carries a bare
# inherent pair today and has no risks at all would otherwise be left with a
# judgement stranded on a field nobody edits any more.
#
# Only entities with ZERO risks are touched: where a register already exists
# the roll-up is already the authority, and adding a synthetic row would
# distort it.
#
# Written with bulk_create, which does not fire post_save. That is deliberate —
# the EntityRisk signal re-rolls the owning entity's position, and a backfill
# whose whole purpose is to preserve the current position must not change
# ratings on its way past.

from django.db import migrations

from iams.backfills import MIGRATED_RISK_TITLE, migrate_inherent_risk_to_register


def forwards(apps, schema_editor):
    Entity = apps.get_model("iams", "AuditableEntity")
    EntityRisk = apps.get_model("iams", "EntityRisk")
    migrate_inherent_risk_to_register(Entity, EntityRisk)


def backwards(apps, schema_editor):
    EntityRisk = apps.get_model("iams", "EntityRisk")
    EntityRisk.objects.filter(title=MIGRATED_RISK_TITLE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0052_migrate_materiality_values"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
