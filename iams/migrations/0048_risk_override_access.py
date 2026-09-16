# Audit Universe v2 — raise "Audit manager" to Approve on risk_assessment.
#
# The rating-override action (POST /api/auditable-entities/{id}/override-rating/)
# is gated at ModuleAccess("risk_assessment", "approve"). Before this migration
# the Approve level on risk_assessment was held only by Chief audit executive
# and gated nothing, while Edit was shared by Audit manager and Senior auditor.
# Overriding a risk rating is a sign-off act that feeds the board-facing plan,
# so it belongs above the level an auditor needs to *enter* factor scores.
#
# 0037_seed_matrix_defaults uses get_or_create and therefore never updates an
# existing cell, so the change is applied explicitly here.
#
# APPROVE outranks EDIT in ACCESS_RANK, so this only widens what the role can
# do; nothing an Audit manager could do before is withdrawn.
#
# Reversible: puts the cell back to Edit.

from django.db import migrations

_ROLE = "Audit manager"
_MODULE = "risk_assessment"


def _set_level(apps, level):
    Role = apps.get_model("iams", "Role")
    Module = apps.get_model("iams", "Module")
    RoleModuleAccess = apps.get_model("iams", "RoleModuleAccess")

    role = Role.objects.filter(name=_ROLE).first()
    module = Module.objects.filter(key=_MODULE).first()
    if role is None or module is None:
        # Fresh install where the RBAC seed has not run yet; 0037 will seed
        # the cell from ROLE_MATRIX, which already carries the new level.
        return
    RoleModuleAccess.objects.update_or_create(
        role=role,
        module=module,
        defaults={"level": level, "scoped": False},
    )


def forwards(apps, schema_editor):
    _set_level(apps, "approve")


def backwards(apps, schema_editor):
    _set_level(apps, "edit")


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0047_audit_universe_v2_schema"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
