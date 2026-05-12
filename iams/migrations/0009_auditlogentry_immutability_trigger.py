"""DB-level immutability for AuditLogEntry.

Phase 2 hardening: prevent UPDATE and DELETE on ``iams_auditlogentry`` at
the database level so application-layer bypasses (raw SQL, bulk_update,
ORM-bypassing migrations) cannot corrupt the audit trail.

PostgreSQL gets a ``BEFORE UPDATE OR DELETE`` trigger that raises an
exception with a clear message. The trigger is owned by the table owner
(typically the migrations user), and a privileged ``iams_audit_admin``
role can disable it temporarily when the scheduled retention task runs.

SQLite (used by the test suite) gets no DB-level enforcement — the
Python-level ``AuditLogEntry.save()`` / ``delete()`` overrides remain the
only guard. That's intentional: tests then validate the Python guard,
not the SQL one.

Other databases (MySQL, Oracle) silently no-op for now; add per-vendor
SQL if/when those backends are supported.
"""
from __future__ import annotations

from django.db import migrations


TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION iams_auditlogentry_reject_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF current_setting('iams.allow_audit_log_modification', true) = 'on' THEN
        -- Privileged retention worker sets this GUC for its session before
        -- expiring partitions. Default behavior outside that scope is reject.
        RETURN COALESCE(NEW, OLD);
    END IF;
    RAISE EXCEPTION 'iams_auditlogentry is append-only (operation=%, request_user=%)',
        TG_OP, current_user;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS iams_auditlogentry_immutable ON iams_auditlogentry;

CREATE TRIGGER iams_auditlogentry_immutable
BEFORE UPDATE OR DELETE ON iams_auditlogentry
FOR EACH ROW
EXECUTE FUNCTION iams_auditlogentry_reject_modification();
"""

TRIGGER_SQL_REVERSE = """
DROP TRIGGER IF EXISTS iams_auditlogentry_immutable ON iams_auditlogentry;
DROP FUNCTION IF EXISTS iams_auditlogentry_reject_modification();
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
        ("iams", "0008_auditlogentry_changes_auditlogentry_ip_address_and_more"),
    ]

    operations = [
        migrations.RunPython(apply_trigger, reverse_code=reverse_trigger),
    ]
