"""Root URL configuration.

Layout:
    /admin/                    Django admin
    /health/, /ready/          Liveness & readiness probes (system)
    /metrics/                  Prometheus scrape endpoint
    /api/schema/               OpenAPI 3.1 schema (YAML/JSON)
    /api/docs/                 Swagger UI (interactive)
    /api/redoc/                ReDoc UI
    /api/auth/...              Auth endpoints (JWT)
    /api/...                   Resource endpoints (see iams.urls)
"""
from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView, TokenVerifyView

from iams.views import HealthView, MeView, ReadinessView, ThrottledTokenObtainPairView

urlpatterns = [
    path("admin/", admin.site.urls),
    # System
    path("health/", HealthView.as_view(), name="health"),
    path("ready/", ReadinessView.as_view(), name="ready"),
    path("", include("django_prometheus.urls")),  # /metrics/
    # OpenAPI schema & docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    # Auth
    path("api/auth/me/", MeView.as_view(), name="auth_me"),
    path("api/auth/token/", ThrottledTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    path("api/auth/token/blacklist/", TokenBlacklistView.as_view(), name="token_blacklist"),
    # Resource endpoints
    path("api/", include("iams.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
