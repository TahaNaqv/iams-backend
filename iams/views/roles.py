from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from iams.models import Role
from iams.serializers import RoleSerializer, RoleWriteSerializer, RolePermissionsUpdateSerializer
from iams.permissions import HasPermission


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.prefetch_related("permissions").all()
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


class RolePermissionsView(APIView):
    """Assign/unassign permissions to a role."""

    permission_classes = [IsAuthenticated, HasPermission("manage_permissions")]

    def patch(self, request, pk):
        role = Role.objects.get(pk=pk)
        serializer = RolePermissionsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        permission_ids = serializer.validated_data["permission_ids"]
        from iams.models import Permission

        role.permissions.set(Permission.objects.filter(id__in=permission_ids))
        return Response(RoleSerializer(role).data)
