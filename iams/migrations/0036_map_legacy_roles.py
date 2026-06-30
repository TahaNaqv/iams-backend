# Map the legacy 6-role taxonomy onto the new 9-role matrix taxonomy and
# reassign every UserProfile so prod users keep working with zero access loss.
#
# Ordering matters: UserProfile.role is on_delete=PROTECT, so we reassign
# profiles BEFORE deleting the now-empty legacy roles. Idempotent and
# best-effort reversible.

from django.db import migrations

from iams.rbac_matrix import LEGACY_ROLE_MAP, ROLE_META


def map_roles(apps, schema_editor):
    Role = apps.get_model("iams", "Role")
    UserProfile = apps.get_model("iams", "UserProfile")

    # 1. Ensure all 9 canonical roles exist with correct metadata.
    canonical = {}
    for name, (description, is_super_admin, requires_issuance_gate) in ROLE_META.items():
        role, _ = Role.objects.get_or_create(name=name)
        role.description = description
        role.is_super_admin = is_super_admin
        role.requires_issuance_gate = requires_issuance_gate
        role.save()
        canonical[name] = role

    # 2. Reassign profiles from each legacy role to its canonical successor,
    #    then delete the empty legacy role (guard against PROTECT).
    for legacy_name, new_name in LEGACY_ROLE_MAP.items():
        if legacy_name == new_name:
            continue
        legacy = Role.objects.filter(name=legacy_name).first()
        if legacy is None:
            continue
        new_role = canonical[new_name]
        UserProfile.objects.filter(role=legacy).update(role=new_role)
        if not UserProfile.objects.filter(role=legacy).exists():
            legacy.delete()


def reverse(apps, schema_editor):
    # Best-effort: recreate the legacy roles and re-point profiles back.
    Role = apps.get_model("iams", "Role")
    UserProfile = apps.get_model("iams", "UserProfile")
    for legacy_name, new_name in LEGACY_ROLE_MAP.items():
        if legacy_name == new_name:
            continue
        new_role = Role.objects.filter(name=new_name).first()
        if new_role is None:
            continue
        legacy, _ = Role.objects.get_or_create(
            name=legacy_name,
            defaults={"is_super_admin": new_role.is_super_admin},
        )
        UserProfile.objects.filter(role=new_role).update(role=legacy)


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0035_seed_modules"),
    ]

    operations = [
        migrations.RunPython(map_roles, reverse),
    ]
