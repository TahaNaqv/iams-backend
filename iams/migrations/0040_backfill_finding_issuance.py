# Backfill Finding.is_issued for findings whose audit already has a finalized
# ("Final") report, so existing Auditee users immediately see historically
# issued findings. Idempotent; reverse clears the flags.

from django.db import migrations


def backfill(apps, schema_editor):
    Finding = apps.get_model("iams", "Finding")
    AuditReport = apps.get_model("iams", "AuditReport")

    final_audit_ids = set(
        AuditReport.objects.filter(status="Final").values_list("audit_id", flat=True)
    )
    if not final_audit_ids:
        return
    # Use the audit's last-modified report time is overkill; stamp "now" is not
    # available in a stable way here, so leave issued_at null on backfill and
    # only set the flag. New issuances (post-deploy) get a real timestamp.
    Finding.objects.filter(
        audit_id__in=final_audit_ids, is_issued=False
    ).update(is_issued=True)


def reverse(apps, schema_editor):
    Finding = apps.get_model("iams", "Finding")
    Finding.objects.update(is_issued=False, issued_at=None)


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0039_finding_issuance_and_mgmt_response"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
