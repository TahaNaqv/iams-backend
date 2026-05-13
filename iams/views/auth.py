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

from iams.audit import record_audit_event
from iams.models import AuditLogEntry
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
    """JWT login with throttling, lockout enforcement, MFA gating, and
    attempt logging (FR-UAM-04, FR-UAM-07).

    The flow:

      1. Throttle (per IP) — slow brute-force attempts.
      2. Resolve the user by ``username``. Missing user → log
         ``user_not_found`` and return 401.
      3. Check for an active lockout — if present, log
         ``account_locked`` and return 423 with ``locked_until``.
      4. Check inactive flag — log ``user_inactive``, return 401.
      5. Validate credentials (delegate to ``TokenObtainPairSerializer``).
         On failure: ``register_failure`` increments counter and may
         open a lockout. Return 401 (or 423 if just locked).
      6. **MFA gate**: if the user must enroll/use MFA and didn't
         provide a valid ``otp_token`` in the payload, return 401 with
         ``code=mfa_required`` (FE shows the OTP prompt). If they did
         and it's valid, proceed.
      7. Issue tokens, log ``success``, stamp ``last_login_at``.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_burst"

    def post(self, request, *args, **kwargs):
        from django.contrib.auth import get_user_model
        from iams.models import LoginAttempt, MFADevice
        from iams.security import (
            get_active_lockout,
            mfa_enforcement_required,
            record_login_attempt,
            register_failure,
        )
        from iams.mfa import verify_totp_token

        User = get_user_model()
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        otp_token = (request.data.get("otp_token") or "").strip()

        if not username or not password:
            record_login_attempt(
                username=username, outcome=LoginAttempt.OUTCOME_INVALID_CREDENTIALS,
                request=request,
            )
            return Response(
                {"detail": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            record_login_attempt(
                username=username, outcome=LoginAttempt.OUTCOME_USER_NOT_FOUND,
                request=request,
            )
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        active_lock = get_active_lockout(user)
        if active_lock is not None:
            record_login_attempt(
                username=username, user=user,
                outcome=LoginAttempt.OUTCOME_ACCOUNT_LOCKED, request=request,
            )
            return Response(
                {
                    "detail": "Account is locked. Contact an administrator.",
                    "code": "account_locked",
                    "lockedUntil": (
                        active_lock.locked_until.isoformat()
                        if active_lock.locked_until else None
                    ),
                },
                status=423,  # 423 Locked
            )

        if not user.is_active:
            record_login_attempt(
                username=username, user=user,
                outcome=LoginAttempt.OUTCOME_USER_INACTIVE, request=request,
            )
            return Response(
                {"detail": "Account is inactive."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.check_password(password):
            lock, just_locked = register_failure(user=user, request=request)
            if just_locked:
                return Response(
                    {
                        "detail": "Account locked due to failed attempts.",
                        "code": "account_locked",
                        "lockedUntil": (
                            lock.locked_until.isoformat()
                            if lock and lock.locked_until else None
                        ),
                    },
                    status=423,
                )
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # MFA gate — two paths:
        #   - User has a confirmed TOTP device → MUST present otp_token.
        #   - User has no confirmed device but enrollment is required by
        #     policy (role / grace expired) → block with mfa_required so
        #     the FE prompts enrollment.
        totp = MFADevice.objects.filter(
            user=user, kind=MFADevice.KIND_TOTP, confirmed=True,
        ).first()
        enforce = mfa_enforcement_required(user) or totp is not None
        if enforce:
            if totp is None or not otp_token:
                record_login_attempt(
                    username=username, user=user,
                    outcome=LoginAttempt.OUTCOME_MFA_REQUIRED, request=request,
                    details={"has_confirmed_totp": totp is not None},
                )
                return Response(
                    {
                        "detail": "MFA token required.",
                        "code": "mfa_required",
                        "mfaEnrolled": totp is not None,
                    },
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            if not verify_totp_token(device=totp, token=otp_token):
                record_login_attempt(
                    username=username, user=user,
                    outcome=LoginAttempt.OUTCOME_MFA_FAILED, request=request,
                )
                # Repeated MFA failures count toward lockout too.
                register_failure(
                    user=user, request=request,
                    outcome=LoginAttempt.OUTCOME_MFA_FAILED,
                )
                return Response(
                    {"detail": "Invalid MFA token.", "code": "mfa_invalid"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        # Credentials + MFA OK — delegate token issuance to simplejwt.
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            from django.utils import timezone

            record_login_attempt(
                username=username, user=user,
                outcome=LoginAttempt.OUTCOME_SUCCESS, request=request,
            )
            # Stamp profile + bump activity. Skip if user has no profile.
            from iams.models import UserProfile

            UserProfile.objects.filter(user=user).update(
                last_login_at=timezone.now(),
                last_activity_at=timezone.now(),
            )
        return response


class AccountUnlockView(APIView):
    """Admin-only: clear an active lockout for a given user.

    POST /api/auth/lockouts/<user_id>/unlock/
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_account_unlock",
        tags=["auth"],
        request=None,
        responses={
            204: OpenApiResponse(description="Lockout cleared"),
            404: OpenApiResponse(description="No active lockout"),
            403: OpenApiResponse(description="Caller lacks manage_users"),
        },
        summary="Admin: clear a user's lockout",
    )
    def post(self, request, user_id):
        from django.contrib.auth import get_user_model

        from iams.permissions import HasPermission
        from iams.security import clear_lockout

        # Permission inline (using HasPermission as a class returns
        # a permission instance — we want to check now, not via the
        # framework's gate, because we want to allow super_admin too).
        perm = HasPermission("manage_users")()
        if not perm.has_permission(request, self):
            return Response(
                {"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN
            )

        User = get_user_model()
        try:
            target = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND
            )
        cleared = clear_lockout(
            user=target, cleared_by=request.user,
            note=f"Cleared by {request.user.username}",
        )
        if not cleared:
            return Response(
                {"detail": "No active lockout."}, status=status.HTTP_404_NOT_FOUND
            )
        record_audit_event(
            action="account_unlock",
            actor=request.user,
            target=target,
            details={"by": request.user.username},
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        record_audit_event(
            action=AuditLogEntry.ACTION_PASSWORD_CHANGE,
            actor=request.user,
            target=request.user,
            request=request,
        )
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


class MFAStatusView(APIView):
    """GET current user's MFA enrollment state."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="auth_mfa_status",
        tags=["auth"],
        summary="Get current user's MFA state",
        responses={200: OpenApiResponse(description="MFA status snapshot")},
    )
    def get(self, request):
        from iams.mfa import get_mfa_status
        return Response(get_mfa_status(request.user))


class MFATOTPEnrollView(APIView):
    """POST to begin TOTP enrollment (returns provisioning URI)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_burst"

    @extend_schema(
        operation_id="auth_mfa_totp_enroll",
        tags=["auth"],
        request=None,
        responses={
            201: OpenApiResponse(description="Enrollment started"),
            409: OpenApiResponse(description="TOTP already confirmed"),
        },
        summary="Start TOTP enrollment",
    )
    def post(self, request):
        from iams.mfa import begin_totp_enrollment
        from iams.models import MFADevice

        existing = MFADevice.objects.filter(
            user=request.user, kind=MFADevice.KIND_TOTP, confirmed=True,
        ).exists()
        if existing:
            return Response(
                {"detail": "TOTP already enrolled; remove the existing device first.",
                 "code": "totp_already_confirmed"},
                status=status.HTTP_409_CONFLICT,
            )
        device, uri = begin_totp_enrollment(request.user)
        return Response(
            {
                "deviceId": str(device.pk),
                "provisioningUri": uri,
                "secret": device.secret,
            },
            status=status.HTTP_201_CREATED,
        )


class MFATOTPConfirmView(APIView):
    """POST {token} — confirm TOTP enrollment by validating one token."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_burst"

    @extend_schema(
        operation_id="auth_mfa_totp_confirm",
        tags=["auth"],
        responses={
            204: OpenApiResponse(description="Confirmed"),
            400: OpenApiResponse(description="Invalid token"),
        },
        summary="Confirm TOTP enrollment",
    )
    def post(self, request):
        from iams.mfa import confirm_totp_enrollment

        token = (request.data.get("token") or "").strip()
        if not token:
            return Response(
                {"detail": "token is required.",
                 "code": "token_required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not confirm_totp_enrollment(request.user, token):
            return Response(
                {"detail": "Invalid token.",
                 "code": "totp_invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit_event(
            action="mfa_totp_confirmed",
            actor=request.user, target=request.user,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MFATOTPDisableView(APIView):
    """POST {password} — disable TOTP (re-verifies password before removal)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_burst"

    @extend_schema(
        operation_id="auth_mfa_totp_disable",
        tags=["auth"],
        responses={
            204: OpenApiResponse(description="Disabled"),
            400: OpenApiResponse(description="Bad password"),
        },
        summary="Disable TOTP",
    )
    def post(self, request):
        from iams.models import MFADevice

        password = request.data.get("password") or ""
        if not request.user.check_password(password):
            return Response(
                {"detail": "Password is incorrect.",
                 "code": "password_incorrect"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        MFADevice.objects.filter(
            user=request.user, kind=MFADevice.KIND_TOTP,
        ).delete()
        record_audit_event(
            action="mfa_totp_disabled",
            actor=request.user, target=request.user,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MFABackupCodesRegenerateView(APIView):
    """POST — generate a fresh batch of backup codes (replaces any prior set)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_burst"

    @extend_schema(
        operation_id="auth_mfa_backup_codes_regenerate",
        tags=["auth"],
        request=None,
        responses={201: OpenApiResponse(description="Codes generated (show once)")},
        summary="Regenerate backup codes",
    )
    def post(self, request):
        from iams.mfa import generate_backup_codes

        codes = generate_backup_codes(request.user)
        record_audit_event(
            action="mfa_backup_codes_regenerated",
            actor=request.user, target=request.user,
            request=request,
        )
        return Response({"codes": codes}, status=status.HTTP_201_CREATED)


# ──────────────────────────────────────────────────────────────────────
# Phase 6 Track 1 — Keycloak SSO endpoints
# ──────────────────────────────────────────────────────────────────────
class SSOConfigView(APIView):
    """Public endpoint that the FE login page queries on mount.

    Returns ``{enabled, providerName, loginUrl}``. Used to decide
    whether to show the "Sign in with corporate account" button.
    """
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        operation_id="auth_sso_config",
        tags=["auth"],
        responses={200: OpenApiResponse(description="SSO config payload")},
        summary="Get SSO configuration for the login UI",
    )
    def get(self, request):
        from iams.sso import sso_config_payload
        return Response(sso_config_payload())


class SSOLoginView(APIView):
    """Server-side 302 → Keycloak authorization endpoint.

    The browser hits ``/api/auth/sso/login/?return_to=/dashboard`` and
    we redirect to Keycloak with the ``state`` containing the
    return-to path. After the user authenticates, Keycloak posts back
    to ``SSOCallbackView``.
    """
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        operation_id="auth_sso_login",
        tags=["auth"],
        responses={
            302: OpenApiResponse(description="Redirect to IdP"),
            503: OpenApiResponse(description="SSO disabled"),
        },
        summary="Begin an SSO login flow",
    )
    def get(self, request):
        from django.http import HttpResponseRedirect
        from secrets import token_urlsafe

        from iams.sso import build_sso_redirect_url, sso_enabled

        if not sso_enabled():
            return Response(
                {"detail": "SSO is not enabled.", "code": "sso_disabled"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        state = token_urlsafe(32)
        return_to = request.query_params.get("return_to", "/")
        request.session["sso_state"] = state
        request.session["sso_return_to"] = return_to
        # Build the callback URL with the current host so dev and prod
        # both work without hard-coding the origin.
        callback = request.build_absolute_uri("/api/auth/sso/callback/")
        return HttpResponseRedirect(
            build_sso_redirect_url(redirect_uri=callback, state=state)
        )


class SSOCallbackView(APIView):
    """IdP callback — completes the OIDC code exchange and mints JWTs.

    Keycloak redirects here with ``?code=…&state=…``. We delegate the
    code-exchange + user-resolution to mozilla-django-oidc's backend,
    then mint a SimpleJWT access/refresh pair and redirect the browser
    to the FE with the tokens in the fragment (so they don't appear
    in server access logs).
    """
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        operation_id="auth_sso_callback",
        tags=["auth"],
        responses={
            302: OpenApiResponse(description="Redirect back to FE with tokens"),
            400: OpenApiResponse(description="Bad state / code"),
            503: OpenApiResponse(description="SSO disabled"),
        },
        summary="OIDC callback — exchange code, mint JWTs, redirect to FE",
    )
    def get(self, request):
        from django.http import HttpResponseRedirect
        from urllib.parse import urlencode

        from iams.sso import (
            IAMSOIDCAuthenticationBackend,
            mint_jwt_pair,
            sso_enabled,
        )

        if not sso_enabled():
            return Response(
                {"detail": "SSO is not enabled.", "code": "sso_disabled"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            return Response(
                {"detail": "Missing code/state.", "code": "sso_invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if state != request.session.get("sso_state"):
            return Response(
                {"detail": "State mismatch.", "code": "sso_state_mismatch"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        backend = IAMSOIDCAuthenticationBackend()
        user = backend.authenticate(request=request, code=code)
        if user is None:
            return Response(
                {"detail": "SSO authentication failed.", "code": "sso_failed"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        tokens = mint_jwt_pair(user)
        record_audit_event(
            action="sso_login",
            actor=user, target=user,
            details={"provider": "keycloak"},
            request=request,
        )
        # Send the browser back to the FE with the tokens in the URL
        # fragment so they're not in server access logs / referrer.
        return_to = request.session.pop("sso_return_to", "/")
        request.session.pop("sso_state", None)
        fe_url = _frontend_base_url(request)
        params = urlencode({"access": tokens["access"], "refresh": tokens["refresh"]})
        return HttpResponseRedirect(f"{fe_url}/login/sso/callback#{params}&return_to={return_to}")


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
        record_audit_event(
            action=AuditLogEntry.ACTION_PASSWORD_RESET,
            actor=user,
            target=user,
            details={"via": "reset_token"},
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
