"""DB-level immutability for AuditableEntityRevision.

Mirrors ``0009_auditlogentry_immutability_trigger`` for the audit-universe
revision trail. The model already raises ``PermissionError`` on
``save()`` / ``delete()`` (see ``AuditableEntityRevision``), but that guard
is Python-only — ``QuerySet.update()``, ``.delete()``, ``bulk_create`` of a
tombstone, raw SQL, or an ORM-bypassing migration could still mutate the
history. For an enterprise audit trail the immutability must be enforced by
the database.

PostgreSQL gets a ``BEFORE UPDATE OR DELETE`` trigger that raises unless a
privileged session opts out via the ``iams.allow_audit_log_modification``
GUC (the same escape hatch the retention worker uses for
``iams_auditlogentry``). SQLite (test DB) and other vendors no-op — the
Python guard remains the only enforcement there, which is what the test
suite validates.
"""
from __future__ import annotations

from django.db import migrations


TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION iams_auditableentityrevision_reject_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF current_setting('iams.allow_audit_log_modification', true) = 'on' THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    RAISE EXCEPTION 'iams_auditableentityrevision is append-only (operation=%, request_user=%)',
        TG_OP, current_user;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS iams_auditableentityrevision_immutable
    ON iams_auditableentityrevision;

CREATE TRIGGER iams_auditableentityrevision_immutable
BEFORE UPDATE OR DELETE ON iams_auditableentityrevision
FOR EACH ROW
EXECUTE FUNCTION iams_auditableentityrevision_reject_modification();
"""

TRIGGER_SQL_REVERSE = """
DROP TRIGGER IF EXISTS iams_auditableentityrevision_immutable
    ON iams_auditableentityrevision;
DROP FUNCTION IF EXISTS iams_auditableentityrevision_reject_modification();
"""


def apply_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute(TRIGGER_SQL)


def reverse_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute(TRIGGER_SQL_REVERSE)


class Migration(migrations.Migration):
    dependencies = [
        ("iams", "0040_backfill_finding_issuance"),
    ]

    operations = [
        migrations.RunPython(apply_trigger, reverse_code=reverse_trigger),
    ]
