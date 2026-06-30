# Seed the 11 Role Access Matrix modules (matrix columns).
#
# Idempotent: get_or_create by ``key``. Reversible: deletes the seeded rows.

from django.db import migrations

from iams.rbac_matrix import MODULES


def seed_modules(apps, schema_editor):
    Module = apps.get_model("iams", "Module")
    for key, name, order in MODULES:
        Module.objects.update_or_create(
            key=key, defaults={"name": name, "order": order}
        )


def reverse(apps, schema_editor):
    Module = apps.get_model("iams", "Module")
    Module.objects.filter(key__in=[k for k, _n, _o in MODULES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0034_rbac_matrix_schema"),
    ]

    operations = [
        migrations.RunPython(seed_modules, reverse),
    ]
