import os

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from iams.models import (
    Module,
    Permission,
    Role,
    RoleModuleAccess,
    UserProfile,
)
from iams.rbac_matrix import (
    LEGACY_PERMISSIONS,
    MODULES,
    ROLE_MATRIX,
    ROLE_META,
    derived_permission_keys,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Seed modules, permissions, the Role Access Matrix, and the Super Admin user"

    def add_arguments(self, parser):
        parser.add_argument(
            "--super-admin-email",
            default=os.environ.get("SUPER_ADMIN_EMAIL", "admin@company.com"),
            help="Email for Super Admin user",
        )
        parser.add_argument(
            "--super-admin-password",
            default=os.environ.get("SUPER_ADMIN_PASSWORD", "admin123"),
            help="Password for Super Admin user",
        )

    def handle(self, *args, **options):
        email = options["super_admin_email"]
        password = options["super_admin_password"]

        # 1. Modules (matrix columns)
        self.stdout.write("Creating modules...")
        module_map = {}
        for key, name, order in MODULES:
            module, _ = Module.objects.update_or_create(
                key=key, defaults={"name": name, "order": order}
            )
            module_map[key] = module
        self.stdout.write(self.style.SUCCESS(f"  {len(module_map)} modules"))

        # 2. Legacy permission catalogue (display-only, kept for transition)
        self.stdout.write("Creating permissions...")
        perm_map = {}
        for key, name, desc, mod in LEGACY_PERMISSIONS:
            perm, _ = Permission.objects.get_or_create(
                key=key, defaults={"name": name, "description": desc, "module": mod}
            )
            perm_map[key] = perm
        self.stdout.write(self.style.SUCCESS(f"  {len(perm_map)} permissions"))

        # 3. Roles + matrix cells
        self.stdout.write("Creating roles and matrix...")
        role_map = {}
        for name, (description, is_super_admin, requires_issuance_gate) in ROLE_META.items():
            role, _ = Role.objects.get_or_create(name=name)
            role.description = description
            role.is_super_admin = is_super_admin
            role.requires_issuance_gate = requires_issuance_gate
            role.save()
            role_map[name] = role

            cells = ROLE_MATRIX[name]
            for module_key, (level, scoped) in cells.items():
                module = module_map.get(module_key)
                if module is None:
                    continue
                # Preserve admin edits: only set defaults on first creation.
                RoleModuleAccess.objects.get_or_create(
                    role=role,
                    module=module,
                    defaults={"level": level, "scoped": scoped},
                )

            # Keep the legacy M2M in sync (display-only) so the existing
            # Permissions tab / RoleSerializer.permission_keys stay coherent.
            level_map = {mk: lvl for mk, (lvl, _s) in cells.items()}
            keys = derived_permission_keys(level_map)
            role.permissions.set([perm_map[k] for k in keys if k in perm_map])
        self.stdout.write(self.style.SUCCESS(f"  {len(role_map)} roles"))

        # 4. Super Admin user
        self.stdout.write("Creating Super Admin user...")
        admin_role = role_map["System administrator"]
        user, created = User.objects.get_or_create(
            username=email,
            defaults={"email": email, "first_name": "Admin", "last_name": "User"},
        )
        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"  Created user: {email}"))
        else:
            self.stdout.write(f"  User already exists: {email}")

        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={
                "role": admin_role,
                "department": "IT Administration",
                "status": "Active",
            },
        )
        if profile.role_id != admin_role.id:
            profile.role = admin_role
            profile.department = "IT Administration"
            profile.status = "Active"
            profile.save()
            self.stdout.write(self.style.SUCCESS("  Updated profile with admin role"))

        self.stdout.write(self.style.SUCCESS("RBAC seed complete."))
