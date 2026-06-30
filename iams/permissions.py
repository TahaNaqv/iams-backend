from django.db.models import Q
from rest_framework.permissions import BasePermission

from iams.rbac_matrix import LEGACY_PERMISSION_MAP


def _role_for(request):
    """Return the authenticated user's Role, or None."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    if not profile or not profile.role:
        return None
    return profile.role


class HasPermission(BasePermission):
    """Legacy permission gate, now resolved through the Role Access Matrix.

    Historically this checked a flat ``Role.permissions`` M2M by key. It now
    maps each legacy key to a (module, min_level) pair via
    ``LEGACY_PERMISSION_MAP`` and delegates to ``Role.has_access`` so the
    matrix is the single source of truth. The ~55 existing call sites keep
    working unchanged. Super Admin bypasses all checks.
    """

    def __init__(self, permission_key):
        self.permission_key = permission_key

    def __call__(self):
        """Allow DRF to instantiate: permission_classes = [HasPermission('key')]."""
        return self

    def has_permission(self, request, view):
        role = _role_for(request)
        if role is None:
            return False
        if role.is_super_admin:
            return True
        mapping = LEGACY_PERMISSION_MAP.get(self.permission_key)
        if mapping is None:
            return False
        module_key, min_level = mapping
        return role.has_access(module_key, min_level)


def has_permission(permission_key):
    """Factory to create HasPermission with the given key."""
    return HasPermission(permission_key)


class ModuleAccess(BasePermission):
    """Matrix-native permission: require >= ``min_level`` on ``module_key``.

    Usage:
        permission_classes = [ModuleAccess("findings", "edit")]
    or per-action in get_permissions(). Super Admin bypasses.
    """

    def __init__(self, module_key, min_level="read"):
        self.module_key = module_key
        self.min_level = min_level

    def __call__(self):
        return self

    def has_permission(self, request, view):
        role = _role_for(request)
        if role is None:
            return False
        if role.is_super_admin:
            return True
        return role.has_access(self.module_key, self.min_level)


def module_access(module_key, min_level="read"):
    """Factory mirroring ``has_permission`` for ModuleAccess."""
    return ModuleAccess(module_key, min_level)


class ModuleGatedMixin:
    """Gate a ViewSet on a single matrix module, choosing the required level
    by action. Set ``module`` and (optionally) tune the action buckets.

        class FindingViewSet(ModuleGatedMixin, ...):
            module = "findings"

    Defaults: list/retrieve -> read, destroy -> full, everything else
    (create/update/partial_update/custom @actions) -> edit. Use
    ``read_actions`` / ``approve_actions`` / ``action_levels`` to override
    (e.g. add a custom read-only @action to ``read_actions``).
    """

    module = None
    read_actions = ("list", "retrieve")
    delete_actions = ("destroy",)
    approve_actions = ()
    action_levels: dict = {}

    def _level_for_action(self):
        action = self.action
        if action in self.action_levels:
            return self.action_levels[action]
        if action in self.read_actions:
            return "read"
        if action in self.delete_actions:
            return "full"
        if action in self.approve_actions:
            return "approve"
        return "edit"

    def get_permissions(self):
        if self.module is None:
            return super().get_permissions()
        return [ModuleAccess(self.module, self._level_for_action())]


class DepartmentScopedQuerysetMixin:
    """Restrict a ModelViewSet to the acting user's department/owned records
    when that user's role has a *scoped* cell for ``scope_module``.

    Configure per viewset:
        scope_module            = "findings"        # matrix module key
        scope_department_field  = "department"       # dotted path to dept str
        scope_owner_fields      = ("owner_ref",)     # FK(s) to the user
        scope_dept_entity_field = None               # dotted path to dept FK
        scope_issued_filter     = Q(is_issued=True)  # applied for issuance-gated roles

    Responsibilities: (a) filter ``get_queryset``; (b) enforce
    ``has_object_permission`` for detail/update/delete. Non-scoped roles
    (and Super Admin) are unaffected.
    """

    scope_module = None
    scope_department_field = "department"
    scope_owner_fields = ("owner_ref",)
    scope_dept_entity_field = None
    scope_issued_filter = None
    # Direct, writable department field stamped on create/update for scoped
    # users so they cannot create/move records into another department. Set to
    # None for models whose department is reached via a relation (e.g. working
    # papers via audit, follow-ups via finding) — those have no own dept column.
    scope_create_stamp_field = "department"
    # When True, the issued filter applies to EVERY scoped user (e.g. reports:
    # never expose drafts to auditees/externals). When False (default), it
    # applies only to issuance-gated roles (Auditee on findings/follow-up).
    scope_issued_always = False

    # ── helpers ──────────────────────────────────────────────────────
    def _scope_profile(self):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return None
        return getattr(user, "profile", None)

    def _is_scoped(self):
        profile = self._scope_profile()
        if not profile or not profile.role:
            return False
        role = profile.role
        if role.is_super_admin or self.scope_module is None:
            return False
        acc = role.access_for(self.scope_module)
        return bool(acc and acc.scoped)

    def _scope_q(self):
        """Build the OR of department + ownership filters for the user."""
        profile = self._scope_profile()
        user = self.request.user
        q = Q()
        has_clause = False
        if self.scope_department_field and profile and profile.department:
            q |= Q(**{self.scope_department_field: profile.department})
            has_clause = True
        if (
            self.scope_dept_entity_field
            and profile
            and profile.department_entity_id
        ):
            q |= Q(**{self.scope_dept_entity_field: profile.department_entity_id})
            has_clause = True
        for field in self.scope_owner_fields:
            q |= Q(**{field: user})
            has_clause = True
        # No identifiable scope → return an always-false filter so scoped
        # users never see the whole table by accident.
        if not has_clause:
            return Q(pk__in=[])
        return q

    def _needs_issuance_gate(self):
        profile = self._scope_profile()
        return bool(
            profile
            and profile.role
            and getattr(profile.role, "requires_issuance_gate", False)
        )

    # ── DRF hooks ────────────────────────────────────────────────────
    def _apply_issued(self):
        return self.scope_issued_filter is not None and (
            self.scope_issued_always or self._needs_issuance_gate()
        )

    def get_queryset(self):
        qs = super().get_queryset()
        if not self._is_scoped():
            return qs
        qs = qs.filter(self._scope_q())
        if self._apply_issued():
            qs = qs.filter(self.scope_issued_filter)
        return qs

    def _object_in_scope(self, obj):
        # Reuse the same queryset filter for object-level enforcement so the
        # list and detail rules can never diverge.
        model = obj.__class__
        in_scope = model._default_manager.filter(pk=obj.pk).filter(self._scope_q())
        if self._apply_issued():
            in_scope = in_scope.filter(self.scope_issued_filter)
        return in_scope.exists()

    def has_object_permission(self, request, view, obj):
        if not self._is_scoped():
            return True
        return self._object_in_scope(obj)

    # ── create/update scope enforcement ──────────────────────────────
    def _stamp_department(self, serializer):
        """Force the record's department to the scoped user's own department
        on write, so a scoped user can neither create nor move a record into
        another department. Returns True if it handled the save."""
        if not self._is_scoped() or not self.scope_create_stamp_field:
            return False
        profile = self._scope_profile()
        if not profile or not profile.department:
            return False
        serializer.save(**{self.scope_create_stamp_field: profile.department})
        return True

    def perform_create(self, serializer):
        if not self._stamp_department(serializer):
            super().perform_create(serializer)

    def perform_update(self, serializer):
        if not self._stamp_department(serializer):
            super().perform_update(serializer)
