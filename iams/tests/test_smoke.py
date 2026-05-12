"""Smoke tests — confirm the test harness, fixtures, and OpenAPI schema work."""
from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_endpoint(api_client):
    response = api_client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_ready_endpoint(api_client):
    response = api_client.get("/ready/")
    assert response.status_code in (200, 503)  # DB might not be ready


@pytest.mark.django_db
def test_openapi_schema_renders(api_client):
    """Schema endpoint should return valid OpenAPI 3.x."""
    response = api_client.get(reverse("schema"), HTTP_ACCEPT="application/json")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("openapi", "").startswith("3.")
    assert "paths" in payload
    assert "components" in payload


@pytest.mark.django_db
def test_authed_client_factory(authed_client, super_admin):
    """Sanity-check the authed_client fixture wires JWT correctly."""
    client = authed_client(super_admin)
    response = client.get("/api/auth/me/")
    assert response.status_code == 200
    body = response.json()
    # CamelCase rendering enabled
    assert "email" in body
    assert body["email"] == "sa@iams.test"


@pytest.mark.django_db
def test_unauthed_request_is_rejected(api_client):
    response = api_client.get("/api/audits/")
    assert response.status_code == 401
