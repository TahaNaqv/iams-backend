# Audit Universe v2 — give every entity a human-readable register reference.
#
# Codes look like OPS-0042: a prefix from the universe category (falling back
# to the entity type, then AE) plus a per-prefix sequence. Migration 0055
# makes the column unique and required, so every existing row needs one first.
#
# The work lives in iams/backfills.py so the same implementation can be run
# ahead of the deploy via `manage.py backfill_audit_universe --only codes`, in
# a maintenance window, against a large universe. Running it there first makes
# this migration a fast no-op; running only this migration is equally correct.
#
# Idempotent: rows that already have a code are skipped and their numbers are
# reserved, so hand-written codes are never renumbered.
#
# Reverse: clears only codes matching the generated pattern, leaving any code
# an administrator typed themselves intact.

from django.db import migrations

from iams.backfills import CODE_PATTERN, backfill_entity_codes


def forwards(apps, schema_editor):
    Entity = apps.get_model("iams", "AuditableEntity")
    backfill_entity_codes(Entity)


def backwards(apps, schema_editor):
    # Historical models carry a plain manager, so this sees archived rows too.
    # The real model's default manager would not -- see _entity_manager in
    # iams/backfills.py.
    Entity = apps.get_model("iams", "AuditableEntity")
    generated = [
        e.pk
        for e in Entity.objects.exclude(code="").only("id", "code")
        if CODE_PATTERN.match(e.code)
    ]
    if generated:
        Entity.objects.filter(pk__in=generated).update(code="")


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0049_seed_risk_factor_library"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
