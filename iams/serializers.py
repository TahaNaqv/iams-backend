from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers

from iams.models import KeycloakGroupRoleMap, Permission, Role, UserProfile

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

    def validate_role_id(self, value):
        if not Role.objects.filter(id=value).exists():
            raise serializers.ValidationError("Invalid role_id.")
        return value

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
        role = Role.objects.filter(id=role_id).first()
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

    def validate_role_id(self, value):
        if value and not Role.objects.filter(id=value).exists():
            raise serializers.ValidationError("Invalid role_id.")
        return value

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
            profile.role = Role.objects.filter(id=role_id).first()
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
    # Phase 6 Track 3 — UI language preference; FE bootstrap reads this
    # to set the initial locale + document direction.
    language = serializers.CharField(source="profile.language", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "name", "role", "department", "status", "language"]

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


# ───────────────────────────────────────────────────────────────────────
# Auth — profile self-edit, password change, password reset
# ───────────────────────────────────────────────────────────────────────


class MeUpdateSerializer(serializers.ModelSerializer):
    """PATCH /auth/me/ payload — users editing their own profile.

    Users can update their name, email, and UI language preference,
    but **never** their role or status (those require manage_users).
    Email change does not currently re-verify; re-verification is
    queued behind the SSO work in Phase 6.
    """

    # Phase 6 Track 3 — surface language on update too. Not a model
    # field on User itself; we apply it to ``user.profile.language``
    # in ``update()`` below.
    language = serializers.ChoiceField(
        choices=UserProfile.LANGUAGE_CHOICES,
        required=False, allow_blank=False, write_only=True,
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "language"]

    def validate_email(self, value: str) -> str:
        if not value:
            raise serializers.ValidationError("Email is required.")
        # Prevent collision with another user's email
        qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def update(self, instance, validated_data):
        language = validated_data.pop("language", None)
        user = super().update(instance, validated_data)
        if language is not None:
            UserProfile.objects.filter(user=user).update(language=language)
        return user


class PasswordChangeSerializer(serializers.Serializer):
    """POST /auth/password/change/ — authenticated user changing own password."""

    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value: str) -> str:
        user = self.context["request"].user
        password_validation.validate_password(value, user=user)
        return value

    def save(self) -> User:
        from iams.security import record_password_change

        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        record_password_change(user=user, new_hash=user.password)
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    """POST /auth/password/reset/ — anonymous request initiating reset.

    Always returns successfully (whether or not the email exists) to prevent
    enumeration. The view-layer dispatches the Celery task only if a matching
    active user exists.
    """

    email = serializers.EmailField()

    def find_user(self) -> User | None:
        try:
            return User.objects.get(email__iexact=self.validated_data["email"], is_active=True)
        except User.DoesNotExist:
            return None


class PasswordResetConfirmSerializer(serializers.Serializer):
    """POST /auth/password/reset/confirm/ — completes the reset with token."""

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs: dict) -> dict:
        # Decode UID
        try:
            user_pk = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist) as exc:
            raise serializers.ValidationError({"uid": "Invalid reset link."}) from exc

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError(
                {"token": "Reset link is invalid or has expired."}
            )

        # Validate password complexity
        password_validation.validate_password(attrs["new_password"], user=user)

        attrs["user"] = user
        return attrs

    def save(self) -> User:
        from iams.security import record_password_change

        user: User = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        record_password_change(user=user, new_hash=user.password)
        return user


# ──────────────────────────────────────────────────────────────────────
# Phase 6 Track 1 — Keycloak group → role mapping
# ──────────────────────────────────────────────────────────────────────
class KeycloakGroupRoleMapSerializer(serializers.ModelSerializer):
    groupName = serializers.CharField(source="group_name")
    roleId = serializers.PrimaryKeyRelatedField(
        source="role", queryset=Role.objects.all(),
    )
    roleName = serializers.CharField(source="role.name", read_only=True)
    isActive = serializers.BooleanField(source="is_active")

    class Meta:
        model = KeycloakGroupRoleMap
        fields = ["id", "groupName", "roleId", "roleName", "precedence", "isActive"]
