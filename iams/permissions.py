from rest_framework.permissions import BasePermission


class HasPermission(BasePermission):
    """
    DRF permission that checks if the user's role has the given permission.
    Super Admin bypasses all checks.
    """

    def __init__(self, permission_key):
        self.permission_key = permission_key

    def __call__(self):
        """Allow DRF to instantiate: permission_classes = [HasPermission('key')]."""
        return self

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        if not profile or not profile.role:
            return False
        role = profile.role
        if role.is_super_admin:
            return True
        return role.permissions.filter(key=self.permission_key).exists()


def has_permission(permission_key):
    """Factory to create HasPermission with the given key."""
    return HasPermission(permission_key)
