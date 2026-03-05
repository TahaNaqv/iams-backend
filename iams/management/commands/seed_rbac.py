from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from decouple import config

from iams.models import Permission, Role, UserProfile

User = get_user_model()

PERMISSIONS = [
    ("view_audits", "View Audits", "View audit plans and details", "Audits"),
    ("create_audits", "Create Audits", "Create new audit plans", "Audits"),
    ("edit_audits", "Edit Audits", "Edit existing audit plans", "Audits"),
    ("delete_audits", "Delete Audits", "Delete audit plans", "Audits"),
    ("manage_findings", "Manage Findings", "Create, edit, and resolve findings", "Findings"),
    ("manage_caps", "Manage CAPs", "Create and manage corrective actions", "CAPs"),
    ("view_reports", "View Reports", "View report dashboards", "Reports"),
    ("export_reports", "Export Reports", "Export reports to PDF/Excel", "Reports"),
    ("manage_users", "Manage Users", "Add, edit, and remove users", "Administration"),
    ("manage_roles", "Manage Roles", "Create and edit roles", "Administration"),
    ("manage_permissions", "Manage Permissions", "Assign permissions to roles", "Administration"),
    ("manage_settings", "Manage Settings", "Configure system settings", "Administration"),
]

ROLES = [
    (
        "Super Admin",
        "Full system access with user and role management",
        True,
        [],  # All permissions - handled separately
    ),
    (
        "Audit Manager",
        "Manages audit plans, teams, findings, and reports",
        False,
        [
            "view_audits", "create_audits", "edit_audits", "delete_audits",
            "manage_findings", "manage_caps", "view_reports", "export_reports",
            "manage_settings",
        ],
    ),
    (
        "Lead Auditor",
        "Leads audit execution and manages findings",
        False,
        [
            "view_audits", "create_audits", "edit_audits",
            "manage_findings", "manage_caps", "view_reports", "export_reports",
        ],
    ),
    (
        "Auditor",
        "Executes audit procedures and documents findings",
        False,
        ["view_audits", "manage_findings", "view_reports"],
    ),
    (
        "Department Head",
        "Reviews findings and manages corrective actions for their department",
        False,
        ["view_audits", "manage_findings", "manage_caps", "view_reports"],
    ),
    (
        "Executive",
        "Views high-level reports and audit status",
        False,
        ["view_audits", "manage_findings", "view_reports", "export_reports"],
    ),
]


class Command(BaseCommand):
    help = "Seed permissions, roles, and Super Admin user"

    def add_arguments(self, parser):
        parser.add_argument(
            "--super-admin-email",
            default=config("SUPER_ADMIN_EMAIL", default="admin@company.com"),
            help="Email for Super Admin user",
        )
        parser.add_argument(
            "--super-admin-password",
            default=config("SUPER_ADMIN_PASSWORD", default="admin123"),
            help="Password for Super Admin user",
        )

    def handle(self, *args, **options):
        email = options["super_admin_email"]
        password = options["super_admin_password"]

        # 1. Create permissions
        self.stdout.write("Creating permissions...")
        perm_map = {}
        for key, name, desc, module in PERMISSIONS:
            perm, _ = Permission.objects.get_or_create(
                key=key,
                defaults={"name": name, "description": desc, "module": module},
            )
            perm_map[key] = perm
        self.stdout.write(self.style.SUCCESS(f"  {len(perm_map)} permissions"))

        # 2. Create roles
        self.stdout.write("Creating roles...")
        role_map = {}
        all_perms = list(Permission.objects.all())
        for name, desc, is_super_admin, perm_keys in ROLES:
            role, _ = Role.objects.get_or_create(
                name=name,
                defaults={"description": desc, "is_super_admin": is_super_admin},
            )
            role_map[name] = role
            if is_super_admin:
                role.permissions.set(all_perms)
            else:
                perms = [perm_map[k] for k in perm_keys if k in perm_map]
                role.permissions.set(perms)
        self.stdout.write(self.style.SUCCESS(f"  {len(role_map)} roles"))

        # 3. Create Super Admin user
        self.stdout.write("Creating Super Admin user...")
        super_admin_role = role_map["Super Admin"]
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

        # Ensure profile exists and has Super Admin role
        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={"role": super_admin_role, "department": "IT Administration", "status": "Active"},
        )
        if profile.role != super_admin_role:
            profile.role = super_admin_role
            profile.department = "IT Administration"
            profile.status = "Active"
            profile.save()
            self.stdout.write(self.style.SUCCESS(f"  Updated profile with Super Admin role"))

        self.stdout.write(self.style.SUCCESS("RBAC seed complete."))
