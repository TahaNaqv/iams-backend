"""Keycloak / OIDC single sign-on (Phase 6 Track 1).

Two surfaces:

  - :class:`IAMSOIDCAuthenticationBackend` — subclass of
    ``mozilla_django_oidc.auth.OIDCAuthenticationBackend`` that
    JIT-provisions a Django ``User`` + ``UserProfile`` on first SSO
    login, and re-syncs Keycloak group → IAMS role mapping on every
    sign-in so role changes take effect immediately.

  - Helper functions consumed by the SSO endpoints:
    :func:`sso_config_payload` (what the FE reads to decide whether to
    show the SSO button), :func:`build_sso_redirect_url` (the
    server-side redirect that hands off to Keycloak), and
    :func:`mint_jwt_pair` (after successful OIDC callback, we mint a
    standard SimpleJWT access/refresh pair so the rest of the IAMS
    code path is unchanged).

Design notes:

  - We **never** trust Keycloak's group claim to grant administrative
    privilege without an explicit ``KeycloakGroupRoleMap`` row. A user
    in a Keycloak group with no mapping defaults to
    ``IAMS_SSO_DEFAULT_ROLE`` ("Viewer"). Administrators must
    deliberately wire in the mapping.

  - SSO users keep ``UserProfile.status == "Active"`` exactly like
    password users — there's no separate "SSO-only" flag because the
    auth backend short-circuit handles which path applies.

  - The ``ModelBackend`` stays in the chain so service accounts can
    still password-auth; SSO is *additive*, not exclusive.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)

User = get_user_model()


# ──────────────────────────────────────────────────────────────────────
# Configuration helpers
# ──────────────────────────────────────────────────────────────────────
def sso_enabled() -> bool:
    """True iff SSO is configured *and* enabled by the operator."""
    if not getattr(settings, "IAMS_SSO_ENABLED", False):
        return False
    return all([
        getattr(settings, "OIDC_RP_CLIENT_ID", ""),
        getattr(settings, "OIDC_OP_AUTHORIZATION_ENDPOINT", ""),
        getattr(settings, "OIDC_OP_TOKEN_ENDPOINT", ""),
    ])


def sso_config_payload() -> dict[str, Any]:
    """Payload returned by ``GET /api/auth/sso/config/``.

    The FE login page calls this on mount; ``enabled=False`` hides the
    "Sign in with corporate account" button. The payload purposely
    omits client secrets — those are server-side only.
    """
    return {
        "enabled": sso_enabled(),
        "providerName": getattr(settings, "IAMS_SSO_PROVIDER_NAME", "Corporate SSO"),
        "loginUrl": "/api/auth/sso/login/" if sso_enabled() else None,
    }


def build_sso_redirect_url(*, redirect_uri: str, state: str) -> str:
    """Build the URL that browser-redirects to Keycloak's auth endpoint."""
    params = {
        "client_id": settings.OIDC_RP_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": getattr(settings, "OIDC_RP_SCOPES", "openid email profile"),
        "state": state,
    }
    return f"{settings.OIDC_OP_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def mint_jwt_pair(user) -> dict[str, str]:
    """Return ``{access, refresh}`` for a SimpleJWT user.

    The downstream API treats SSO-issued tokens identically to
    password-issued ones — same permissions, same throttles, same
    refresh path.
    """
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


# ──────────────────────────────────────────────────────────────────────
# Role resolution from Keycloak group claim
# ──────────────────────────────────────────────────────────────────────
def resolve_role_from_groups(groups: list[str]):
    """Pick the highest-precedence (lowest number) Role matching ``groups``.

    Returns the Django Role instance or ``None`` if no active mapping
    matches. Callers fall back to ``IAMS_SSO_DEFAULT_ROLE`` when None.
    """
    from iams.models import KeycloakGroupRoleMap

    if not groups:
        return None
    match = (
        KeycloakGroupRoleMap.objects
        .filter(is_active=True, group_name__in=groups)
        .select_related("role")
        .order_by("precedence", "group_name")
        .first()
    )
    return match.role if match else None


def get_or_create_default_role():
    """Return the role assigned to SSO users when no group mapping wins."""
    from iams.models import Role
    name = getattr(settings, "IAMS_SSO_DEFAULT_ROLE", "Viewer")
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={
            "description": "Default role for SSO-provisioned users with no group mapping.",
            "is_super_admin": False,
        },
    )
    return role


# ──────────────────────────────────────────────────────────────────────
# Custom OIDC backend — JIT provisioning + role sync
# ──────────────────────────────────────────────────────────────────────
try:
    from mozilla_django_oidc.auth import OIDCAuthenticationBackend
except ImportError:  # pragma: no cover — package always installed at runtime
    OIDCAuthenticationBackend = object  # type: ignore[misc,assignment]


class IAMSOIDCAuthenticationBackend(OIDCAuthenticationBackend):  # type: ignore[misc]
    """OIDC backend that creates/updates ``UserProfile`` from the token."""

    def create_user(self, claims: dict[str, Any]):
        """JIT provision a fresh user + profile."""
        from iams.models import UserProfile
        from django.utils import timezone

        email = claims.get("email") or ""
        username = claims.get("preferred_username") or email or claims.get("sub", "")
        if not username:
            raise ValueError("OIDC claims missing both email and preferred_username")
        first = claims.get("given_name", "")
        last = claims.get("family_name", "")

        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first,
            last_name=last,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])

        role = resolve_role_from_groups(claims.get("groups") or []) \
            or get_or_create_default_role()
        UserProfile.objects.create(
            user=user, role=role,
            department=claims.get("department", "") or "",
            status="Active",
            last_login_at=timezone.now(),
            last_activity_at=timezone.now(),
        )
        logger.info(
            "sso: provisioned user %s with role %s",
            username, role.name,
            extra={"username": username, "role": role.name},
        )
        return user

    def update_user(self, user, claims: dict[str, Any]):
        """Sync role + profile fields from each SSO sign-in."""
        from iams.models import UserProfile
        from django.utils import timezone

        first = claims.get("given_name") or user.first_name
        last = claims.get("family_name") or user.last_name
        if first != user.first_name or last != user.last_name:
            user.first_name, user.last_name = first, last
            user.save(update_fields=["first_name", "last_name"])

        role = resolve_role_from_groups(claims.get("groups") or [])
        profile, _ = UserProfile.objects.get_or_create(
            user=user, defaults={"status": "Active"},
        )
        update_fields = ["last_login_at", "last_activity_at"]
        profile.last_login_at = timezone.now()
        profile.last_activity_at = timezone.now()
        if role and (profile.role_id != role.pk):
            profile.role = role
            update_fields.append("role")
            logger.info(
                "sso: re-mapped %s → role %s via group claim",
                user.username, role.name,
                extra={"username": user.username, "role": role.name},
            )
        elif profile.role_id is None:
            profile.role = role or get_or_create_default_role()
            update_fields.append("role")
        profile.save(update_fields=update_fields)
        return user

    def filter_users_by_claims(self, claims: dict[str, Any]):
        """Match an incoming SSO claim back to an existing user.

        Priority: ``preferred_username`` → ``email`` (case-insensitive).
        Email is the safety net for IdPs that change usernames.
        """
        username = claims.get("preferred_username")
        if username:
            qs = User.objects.filter(username=username)
            if qs.exists():
                return qs
        email = claims.get("email") or ""
        if email:
            return User.objects.filter(email__iexact=email)
        return User.objects.none()
