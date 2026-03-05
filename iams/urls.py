from django.urls import path, include
from rest_framework.routers import DefaultRouter

from iams.views import UserViewSet, RoleViewSet, PermissionViewSet, RolePermissionsView

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("roles", RoleViewSet, basename="role")
router.register("permissions", PermissionViewSet, basename="permission")

urlpatterns = [
    path("", include(router.urls)),
    path("roles/<uuid:pk>/permissions/", RolePermissionsView.as_view(), name="role-permissions"),
]
