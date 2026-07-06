"""DB-level immutability for RiskHistoryEntry.

Mirrors ``0041_auditableentityrevision_immutability_trigger`` for the
risk-rating history trail. The model already raises ``PermissionError`` on
``save()`` / ``delete()``, but that guard is Python-only —
``QuerySet.update()``, ``.delete()``, raw SQL, or an ORM-bypassing writer
could still mutate the history. For an enterprise audit trail the
immutability must be enforced by the database.

PostgreSQL gets a ``BEFORE UPDATE OR DELETE`` trigger that raises unless a
privileged session opts out via the ``iams.allow_audit_log_modification``
GUC. SQLite (test DB) and other vendors no-op — the Python guard remains the
only enforcement there.
"""
from __future__ import annotations

from django.db import migrations


TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION iams_riskhistoryentry_reject_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF current_setting('iams.allow_audit_log_modification', true) = 'on' THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    RAISE EXCEPTION 'iams_riskhistoryentry is append-only (operation=%, request_user=%)',
        TG_OP, current_user;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS iams_riskhistoryentry_immutable
    ON iams_riskhistoryentry;

CREATE TRIGGER iams_riskhistoryentry_immutable
BEFORE UPDATE OR DELETE ON iams_riskhistoryentry
FOR EACH ROW
EXECUTE FUNCTION iams_riskhistoryentry_reject_modification();
"""

TRIGGER_SQL_REVERSE = """
DROP TRIGGER IF EXISTS iams_riskhistoryentry_immutable
    ON iams_riskhistoryentry;
DROP FUNCTION IF EXISTS iams_riskhistoryentry_reject_modification();
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
        ("iams", "0043_riskhistoryentry_risk_hist_entity_date_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(apply_trigger, reverse_code=reverse_trigger),
    ]
