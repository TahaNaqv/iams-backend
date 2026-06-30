# Backfill UserProfile.department_entity from the free-text ``department``
# string by case-insensitive name match against Department-type
# AuditableEntity rows.
#
# Prod-safe: only sets the FK when currently null; unmatched departments are
# skipped (never fails the migration). Reversible (nulls the FK).

from django.db import migrations


def backfill(apps, schema_editor):
    UserProfile = apps.get_model("iams", "UserProfile")
    AuditableEntity = apps.get_model("iams", "AuditableEntity")

    # Build a case-insensitive name -> department-entity lookup.
    dept_by_name = {}
    for ent in AuditableEntity.objects.filter(entity_type="Department"):
        dept_by_name.setdefault(ent.name.strip().lower(), ent)

    for profile in UserProfile.objects.filter(
        department_entity__isnull=True
    ).exclude(department=""):
        ent = dept_by_name.get(profile.department.strip().lower())
        if ent is not None:
            profile.department_entity = ent
            profile.save(update_fields=["department_entity"])


def reverse(apps, schema_editor):
    UserProfile = apps.get_model("iams", "UserProfile")
    UserProfile.objects.update(department_entity=None)


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0037_seed_matrix_defaults"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
