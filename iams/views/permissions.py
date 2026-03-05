from rest_framework import viewsets

from iams.models import Permission
from iams.serializers import PermissionSerializer
from iams.permissions import HasPermission


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [HasPermission("manage_permissions")]
