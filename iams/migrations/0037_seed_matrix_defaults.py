# Seed the default Role Access Matrix cells (RoleModuleAccess) for the 9
# canonical roles. Only sets a cell on first creation so later admin edits in
# the Settings UI survive re-runs / re-seeds.
#
# Reversible: deletes the seeded cells for the canonical roles.

from django.db import migrations

from iams.rbac_matrix import ROLE_MATRIX


def seed_matrix(apps, schema_editor):
    Role = apps.get_model("iams", "Role")
    Module = apps.get_model("iams", "Module")
    RoleModuleAccess = apps.get_model("iams", "RoleModuleAccess")

    modules = {m.key: m for m in Module.objects.all()}

    for role_name, cells in ROLE_MATRIX.items():
        role = Role.objects.filter(name=role_name).first()
        if role is None:
            continue
        for module_key, (level, scoped) in cells.items():
            module = modules.get(module_key)
            if module is None:
                continue
            RoleModuleAccess.objects.get_or_create(
                role=role,
                module=module,
                defaults={"level": level, "scoped": scoped},
            )


def reverse(apps, schema_editor):
    Role = apps.get_model("iams", "Role")
    RoleModuleAccess = apps.get_model("iams", "RoleModuleAccess")
    role_ids = Role.objects.filter(name__in=ROLE_MATRIX.keys()).values_list(
        "pk", flat=True
    )
    RoleModuleAccess.objects.filter(role_id__in=list(role_ids)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0036_map_legacy_roles"),
    ]

    operations = [
        migrations.RunPython(seed_matrix, reverse),
    ]
