# Audit Universe v2 — derive business unit and owning department from the
# entity hierarchy.
#
# The v2 form asks only for a parent: the owning department is the nearest
# Department-type ancestor and the business unit is the nearest ancestor that
# has one. Both columns stay (they back existing filters and indexes) but are
# now populated rather than typed.
#
# This only fills blanks. Where a stored value disagrees with what the
# hierarchy implies, the row is logged and left alone — choosing between the
# two is a conversation with the audit team, not something a deploy decides.
# Run `manage.py backfill_audit_universe --only links --dry-run` beforehand to
# see the disagreements before they scroll past in a deploy log.
#
# Not reversible in a meaningful sense: the migration cannot tell a value it
# filled from one that was always there, and guessing would discard real data.

from django.db import migrations

from iams.backfills import derive_structural_links


def forwards(apps, schema_editor):
    Entity = apps.get_model("iams", "AuditableEntity")
    derive_structural_links(Entity)


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0050_backfill_entity_codes"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
