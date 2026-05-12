"""Auth endpoints for IAMS.

Routes registered in ``config/urls.py``:

    GET   /api/auth/me/                       MeView — read current user
    PATCH /api/auth/me/                       MeView — update own profile
    POST  /api/auth/token/                    JWT login (throttled, scope='auth_burst')
    POST  /api/auth/token/refresh/            JWT refresh (from simplejwt)
    POST  /api/auth/token/verify/             JWT verify (from simplejwt)
    POST  /api/auth/token/blacklist/          JWT blacklist (logout)
    POST  /api/auth/password/change/          PasswordChangeView — authenticated
    POST  /api/auth/password/reset/           PasswordResetRequestView — anonymous
    POST  /api/auth/password/reset/confirm/   PasswordResetConfirmView — anonymous + token
"""
from __future__ import annotations

import logging

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from iams.serializers import (
    MeSerializer,
    MeUpdateSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
)
from iams.tasks import send_password_reset_email

logger = logging.getLogger(__name__)


def _frontend_base_url(request) -> str:
    """Resolve where the password-reset link should point.

    Priority:
      1. ``Origin`` request header (browser-injected; safe — matches CORS allowlist)
      2. ``settings.FRONTEND_BASE_URL`` (explicit env override)
      3. First entry in ``settings.CORS_ALLOWED_ORIGINS``
      4. Fallback to ``http://localhost:5173``
    """
    origin = request.META.get("HTTP_ORIGIN")
    if origin and origin in (settings.CORS_ALLOWED_ORIGINS or []):
        return origin
    if getattr(settings, "FRONTEND_BASE_URL", ""):
        return settings.FRONTEND_BASE_URL
    if settings.CORS_ALLOWED_ORIGINS:
        return settings.CORS_ALLOWED_ORIGINS[0]
    return "http://localhost:5173"


class MeView(APIView):
    """Return / update the current authenticated user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_me_read",
        tags=["auth"],
        responses=MeSerializer,
        summary="Get current user",
    )
    def get(self, request):
        return Response(MeSerializer(request.user).data)

    @extend_schema(
        operation_id="auth_me_update",
        tags=["auth"],
        request=MeUpdateSerializer,
        responses=MeSerializer,
        summary="Update own profile (name, email)",
    )
    def patch(self, request):
        serializer = MeUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MeSerializer(request.user).data)


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """JWT login with per-scope throttling to slow brute-force attempts."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_burst"


class PasswordChangeView(APIView):
    """Change the authenticated user's password."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_burst"

    @extend_schema(
        operation_id="auth_password_change",
        tags=["auth"],
        request=PasswordChangeSerializer,
        responses={204: OpenApiResponse(description="Password changed")},
        summary="Change own password",
    )
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info("password_changed", extra={"user_id": str(request.user.pk)})
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestView(APIView):
    """Initiate a password reset by sending a tokenized email link.

    Always returns 202 — never reveals whether the email is registered.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_burst"
    authentication_classes: list = []  # public endpoint, ignore token presence

    @extend_schema(
        operation_id="auth_password_reset_request",
        tags=["auth"],
        request=PasswordResetRequestSerializer,
        responses={
            202: OpenApiResponse(
                description=(
                    "Request accepted. If the email matches an active account, a reset "
                    "link will be delivered. (No information is revealed about whether "
                    "the email is registered.)"
                )
            )
        },
        summary="Request a password reset email",
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.find_user()
        if user is not None:
            send_password_reset_email.delay(
                user_id=str(user.pk),
                frontend_base_url=_frontend_base_url(request),
            )
            logger.info("password_reset_requested", extra={"user_id": str(user.pk)})
        else:
            logger.info(
                "password_reset_requested_unknown_email",
                extra={"email": serializer.validated_data["email"]},
            )
        return Response(status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(APIView):
    """Complete a password reset with a valid uid+token pair."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_burst"
    authentication_classes: list = []

    @extend_schema(
        operation_id="auth_password_reset_confirm",
        tags=["auth"],
        request=PasswordResetConfirmSerializer,
        responses={204: OpenApiResponse(description="Password reset")},
        summary="Confirm a password reset with token",
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        logger.info("password_reset_completed", extra={"user_id": str(user.pk)})
        return Response(status=status.HTTP_204_NO_CONTENT)
