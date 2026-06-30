"""Canonical Role Access Matrix — single source of truth.

This module is intentionally dependency-free (plain data, no Django/model
imports) so it can be imported from migrations, the ``seed_rbac`` command,
permission classes, and tests without import-cycle or historical-model
hazards.

The matrix mirrors the client's spreadsheet exactly: 9 roles × 11 modules,
each cell a ``(level, scoped)`` pair where ``level`` is one of
"full" / "approve" / "edit" / "read" / "none" and ``scoped`` means the
access is limited to the user's own department / owned records.
"""

# Access-level string constants (mirror models.AccessLevelChoices values;
# duplicated here to keep this module import-free).
FULL = "full"
APPROVE = "approve"
EDIT = "edit"
READ = "read"
NONE = "none"

ACCESS_RANK = {FULL: 5, APPROVE: 4, EDIT: 3, READ: 2, NONE: 1}

# ── Modules (matrix columns), in display order ───────────────────────────
MODULES = [
    ("audit_plan", "Audit Plan", 1),
    ("audit_universe", "Audit Universe", 2),
    ("risk_assessment", "Risk Assessment", 3),
    ("engagements", "Engagements", 4),
    ("workpapers", "Workpapers", 5),
    ("findings", "Findings", 6),
    ("reports", "Reports", 7),
    ("follow_up", "Follow-up / Actions", 8),
    ("mgmt_responses", "Mgmt Responses", 9),
    ("users_roles", "Users & Roles", 10),
    ("dashboards", "Dashboards", 11),
]

MODULE_KEYS = [key for key, _name, _order in MODULES]

# ── Role metadata ────────────────────────────────────────────────────────
# name -> (description, is_super_admin, requires_issuance_gate)
ROLE_META = {
    "System administrator": (
        "Full system access; manages users, roles, config, and data retention",
        True,
        False,
    ),
    "Chief audit executive": (
        "Approves audit plan, risk assessments and reports; views all "
        "engagements; final sign-off authority",
        False,
        False,
    ),
    "Audit manager": (
        "Manages engagements end-to-end; owns risk assessment; assigns staff; "
        "reviews and escalates findings",
        False,
        False,
    ),
    "Senior auditor": (
        "Leads individual audits; edits risk assessments, workpapers, findings "
        "and follow-ups within engagement",
        False,
        False,
    ),
    "QA / quality reviewer": (
        "Reviews and annotates all modules for quality assurance; no edit "
        "rights (independence)",
        False,
        False,
    ),
    "Staff auditor": (
        "Executes assigned test steps; updates follow-up actions and task "
        "status within own scope",
        False,
        False,
    ),
    "Auditee / client manager": (
        "Submits management responses; views findings, reports and follow-up "
        "actions for own area only",
        False,
        True,  # only sees own-dept records AFTER formal issuance
    ),
    "Read-only stakeholder": (
        "Views issued reports, follow-up status and dashboards only; no "
        "interaction rights",
        False,
        False,
    ),
    "External auditor / regulator": (
        "Scoped, time-limited access to shared reports only",
        False,
        False,
    ),
}

# ── The matrix: role -> {module_key: (level, scoped)} ────────────────────
# Modules omitted for a role default to (NONE, False).
def _row(**cells):
    row = {key: (NONE, False) for key in MODULE_KEYS}
    row.update(cells)
    return row


ROLE_MATRIX = {
    "System administrator": {key: (FULL, False) for key in MODULE_KEYS},
    "Chief audit executive": _row(
        audit_plan=(APPROVE, False),
        audit_universe=(READ, False),
        risk_assessment=(APPROVE, False),
        engagements=(READ, False),
        workpapers=(READ, False),
        findings=(APPROVE, False),
        reports=(APPROVE, False),
        follow_up=(READ, False),
        mgmt_responses=(READ, False),
        users_roles=(NONE, False),
        dashboards=(READ, False),
    ),
    "Audit manager": _row(
        audit_plan=(EDIT, False),
        audit_universe=(EDIT, False),
        risk_assessment=(EDIT, False),
        engagements=(EDIT, False),
        workpapers=(EDIT, False),
        findings=(EDIT, False),
        reports=(EDIT, False),
        follow_up=(EDIT, False),
        mgmt_responses=(READ, False),
        users_roles=(NONE, False),
        dashboards=(READ, False),
    ),
    "Senior auditor": _row(
        audit_plan=(READ, False),
        audit_universe=(READ, False),
        risk_assessment=(EDIT, False),
        engagements=(EDIT, False),
        workpapers=(EDIT, False),
        findings=(EDIT, False),
        reports=(EDIT, False),
        follow_up=(EDIT, False),
        dashboards=(READ, True),  # Scoped: own-dept dashboard data
    ),
    "QA / quality reviewer": _row(
        audit_universe=(READ, False),
        risk_assessment=(READ, False),
        engagements=(READ, False),
        workpapers=(READ, False),
        findings=(READ, False),
        reports=(READ, False),
        follow_up=(READ, False),
    ),
    "Staff auditor": _row(
        engagements=(EDIT, True),
        workpapers=(EDIT, True),
        findings=(EDIT, True),
        follow_up=(EDIT, True),
        dashboards=(READ, True),
    ),
    "Auditee / client manager": _row(
        findings=(READ, True),
        reports=(READ, True),
        follow_up=(READ, True),
        # "Edit" in the matrix; scoped to own dept per the role's "own area
        # only" mandate. Issuance gate does NOT apply to responses (the
        # viewset sets scope_issued_filter=None).
        mgmt_responses=(EDIT, True),
    ),
    "Read-only stakeholder": _row(
        reports=(READ, False),
        follow_up=(READ, False),
        dashboards=(READ, False),
    ),
    "External auditor / regulator": _row(
        # Time-limited shared reports; phase-1 approximated as scoped read.
        reports=(READ, True),
    ),
}

# ── Legacy permission-key compatibility map ──────────────────────────────
# key -> (module_key, min_level). Lets the old HasPermission("key") checks
# and the frontend permissions[] array keep working off the matrix.
LEGACY_PERMISSION_MAP = {
    "view_audits": ("engagements", READ),
    "create_audits": ("engagements", EDIT),
    "edit_audits": ("engagements", EDIT),
    "delete_audits": ("engagements", FULL),
    "manage_findings": ("findings", EDIT),
    "manage_caps": ("follow_up", EDIT),
    "view_reports": ("reports", READ),
    "export_reports": ("reports", EDIT),
    "manage_users": ("users_roles", FULL),
    "manage_roles": ("users_roles", FULL),
    "manage_permissions": ("users_roles", FULL),
    "manage_settings": ("users_roles", FULL),
}

# Legacy Permission catalogue (kept display-only for the transition).
# (key, name, description, module)
LEGACY_PERMISSIONS = [
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

# ── Legacy 6-role -> new 9-role migration map ────────────────────────────
LEGACY_ROLE_MAP = {
    "Super Admin": "System administrator",
    "Audit Manager": "Audit manager",
    "Lead Auditor": "Senior auditor",
    "Auditor": "Staff auditor",
    "Department Head": "Auditee / client manager",
    "Executive": "Chief audit executive",
}


def derived_permission_keys(access_map):
    """Given {module_key: (level, scoped)} (or a callable matrix row), return
    the set of legacy permission keys the role effectively holds.

    ``access_map`` is a dict module_key -> level string (scoped ignored for
    key derivation). Used to compute the backward-compatible permissions[]
    array for /auth/me.
    """
    keys = []
    for key, (module, min_level) in LEGACY_PERMISSION_MAP.items():
        level = access_map.get(module, NONE)
        if ACCESS_RANK.get(level, 1) >= ACCESS_RANK.get(min_level, 1):
            keys.append(key)
    return keys
