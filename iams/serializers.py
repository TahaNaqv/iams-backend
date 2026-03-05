from django.contrib.auth import get_user_model
from rest_framework import serializers

from iams.models import Permission, Role, UserProfile

User = get_user_model()


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "key", "name", "description", "module"]
        read_only_fields = fields


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)
    permission_keys = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ["id", "name", "description", "is_super_admin", "permissions", "permission_keys"]

    def get_permission_keys(self, obj):
        if obj.is_super_admin:
            return list(Permission.objects.values_list("key", flat=True))
        return list(obj.permissions.values_list("key", flat=True))


class RoleWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "description", "is_super_admin"]


class RolePermissionsUpdateSerializer(serializers.Serializer):
    permission_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
    )


class UserProfileSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = ["id", "role", "department", "status"]


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    role = serializers.SerializerMethodField()
    role_id = serializers.SerializerMethodField()
    department = serializers.CharField(source="profile.department", read_only=True)
    status = serializers.CharField(source="profile.status", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "profile",
            "role",
            "role_id",
            "department",
            "status",
        ]
        read_only_fields = ["id", "username", "email", "first_name", "last_name", "profile"]

    def get_role(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and profile.role:
            return profile.role.name
        return None

    def get_role_id(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and profile.role:
            return str(profile.role.id)
        return None


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    role_id = serializers.UUIDField(write_only=True)
    department = serializers.CharField(allow_blank=True, default="")
    status = serializers.ChoiceField(
        choices=[("Active", "Active"), ("Inactive", "Inactive")],
        default="Active",
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "role_id",
            "department",
            "status",
        ]

    def create(self, validated_data):
        role_id = validated_data.pop("role_id")
        department = validated_data.pop("department", "")
        status = validated_data.pop("status", "Active")
        password = validated_data.pop("password")

        user = User.objects.create_user(
            username=validated_data.get("username"),
            email=validated_data.get("email", ""),
            password=password,
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
        )
        role = Role.objects.get(id=role_id)
        UserProfile.objects.create(
            user=user,
            role=role,
            department=department,
            status=status,
        )
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    role_id = serializers.UUIDField(write_only=True, required=False)
    department = serializers.CharField(allow_blank=True, required=False)
    status = serializers.ChoiceField(
        choices=[("Active", "Active"), ("Inactive", "Inactive")],
        required=False,
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "role_id", "department", "status"]

    def update(self, instance, validated_data):
        role_id = validated_data.pop("role_id", None)
        department = validated_data.pop("department", None)
        status = validated_data.pop("status", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        profile = getattr(instance, "profile", None)
        if profile is None:
            profile = UserProfile(user=instance)
        if role_id is not None:
            profile.role = Role.objects.get(id=role_id)
        if department is not None:
            profile.department = department
        if status is not None:
            profile.status = status
        profile.save()
        return instance


class MeSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    department = serializers.CharField(source="profile.department", read_only=True)
    status = serializers.CharField(source="profile.status", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "name", "role", "department", "status"]

    def get_name(self, obj):
        parts = [obj.first_name, obj.last_name]
        return " ".join(p for p in parts if p).strip() or obj.email

    def get_role(self, obj):
        profile = getattr(obj, "profile", None)
        if not profile or not profile.role:
            return None
        role = profile.role
        return {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
            "is_super_admin": role.is_super_admin,
            "permissions": list(
                Permission.objects.values_list("key", flat=True)
                if role.is_super_admin
                else role.permissions.values_list("key", flat=True)
            ),
        }
