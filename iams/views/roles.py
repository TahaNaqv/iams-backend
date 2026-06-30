from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from iams.audit import AuditedViewSetMixin
from iams.models import KeycloakGroupRoleMap, Module, Role, RoleModuleAccess
from iams.serializers import (
    KeycloakGroupRoleMapSerializer,
    ModuleSerializer,
    RoleAccessBulkUpdateSerializer,
    RoleSerializer,
    RoleWriteSerializer,
    RolePermissionsUpdateSerializer,
)
from iams.permissions import HasPermission, ModuleAccess


class ModuleViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only registry of the 11 matrix modules (the matrix columns)."""

    queryset = Module.objects.all()
    serializer_class = ModuleSerializer
    permission_classes = [ModuleAccess("users_roles", "read")]


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.prefetch_related("permissions", "module_access__module").all()
    permission_classes = [HasPermission("manage_roles")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return RoleWriteSerializer
        return RoleSerializer

    def perform_create(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_super_admin:
            return Response(
                {"detail": "Cannot delete Super Admin role."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=True,
        methods=["get", "put"],
        url_path="access",
        permission_classes=[ModuleAccess("users_roles", "full")],
    )
    def access(self, request, pk=None):
        """GET → the role's 11-module access map. PUT → bulk-upsert cells.

        Editing the matrix is an administration action (users_roles=full).
        The Super Admin role is always Full and cannot be downgraded.
        """
        role = self.get_object()
        if request.method == "GET":
            return Response(role.full_access_map())

        if role.is_super_admin:
            return Response(
                {"detail": "The Super Admin role is always Full and cannot be edited."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = RoleAccessBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        modules = {m.key: m for m in Module.objects.all()}
        for cell in serializer.validated_data["access"]:
            module = modules.get(cell["module"])
            if module is None:
                return Response(
                    {"detail": f"Unknown module '{cell['module']}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            RoleModuleAccess.objects.update_or_create(
                role=role,
                module=module,
                defaults={"level": cell["level"], "scoped": cell.get("scoped", False)},
            )
        role.refresh_from_db()
        role.__dict__.pop("_access_map_cache", None)
        return Response(role.full_access_map())


class KeycloakGroupRoleMapViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """CRUD for Keycloak group → IAMS role mappings.

    Read access is gated by ``manage_roles``; mutations by
    ``manage_settings`` since changing the mapping table effectively
    grants/revokes role across the IAMS user base on the next SSO sign-in.
    """
    queryset = KeycloakGroupRoleMap.objects.select_related("role").all()
    serializer_class = KeycloakGroupRoleMapSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [HasPermission("manage_roles")]
        return [HasPermission("manage_settings")]


class RolePermissionsView(APIView):
    """Assign/unassign permissions to a role."""

    permission_classes = [IsAuthenticated, HasPermission("manage_permissions")]

    def patch(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        serializer = RolePermissionsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        permission_ids = serializer.validated_data["permission_ids"]
        from iams.models import Permission

        role.permissions.set(Permission.objects.filter(id__in=permission_ids))
        return Response(RoleSerializer(role).data)
