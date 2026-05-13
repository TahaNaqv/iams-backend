"""Integration endpoints (Phase 6 Track 2).

Three surfaces:

  - **Webhook ingest** at ``/api/integrations/webhooks/<id>/<resource>/``
    is public-but-HMAC-signed. External systems POST a JSON payload
    with ``X-IAMS-Signature: sha256=<hex>`` (computed against
    ``source.inbound_secret``). Mismatch → 401.

  - **Admin REST** at ``/api/integrations/{sources,events}/`` is
    super-admin gated (``manage_settings``).

  - The signed-secret webhook **bypasses** the normal IsAuthenticated
    permission. We make the trust boundary explicit by declaring
    ``permission_classes = [AllowAny]`` + ``authentication_classes = []``
    on those views.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from iams.audit import AuditedViewSetMixin
from iams.integrations import (
    IngestError,
    SIGNATURE_HEADER,
    ingest_auditable_entity,
    ingest_finding,
    verify_signature,
)
from iams.models import IntegrationEvent, IntegrationSource
from iams.permissions import HasPermission

WEBHOOK_RESOURCES = {
    "auditable-entities": ingest_auditable_entity,
    "findings": ingest_finding,
}


class IntegrationWebhookView(APIView):
    """Accept signed inbound webhook deliveries from external systems."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        operation_id="integrations_webhook",
        tags=["integrations"],
        summary="Receive an inbound integration webhook (HMAC-signed)",
        responses={
            201: OpenApiResponse(description="Accepted"),
            400: OpenApiResponse(description="Bad payload"),
            401: OpenApiResponse(description="Bad signature"),
            404: OpenApiResponse(description="Unknown source or resource"),
        },
    )
    def post(self, request, source_id, resource):
        importer = WEBHOOK_RESOURCES.get(resource)
        if importer is None:
            return Response(
                {"detail": f"Unknown resource '{resource}'.",
                 "supported": sorted(WEBHOOK_RESOURCES.keys())},
                status=status.HTTP_404_NOT_FOUND,
            )

        source = get_object_or_404(
            IntegrationSource, pk=source_id,
            inbound_enabled=True,
            status=IntegrationSource.STATUS_ACTIVE,
        )

        signature = request.headers.get(SIGNATURE_HEADER, "")
        if not verify_signature(
            secret=source.inbound_secret,
            body=request.body,
            header_value=signature,
        ):
            return Response(
                {"detail": "Signature mismatch.",
                 "code": "signature_invalid"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            payload = request.data
            obj, created = importer(source, payload)
        except IngestError as exc:
            return Response(
                {"detail": str(exc), "code": "payload_invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "id": str(obj.pk),
                "externalId": payload.get("external_id"),
                "created": created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


# ──────────────────────────────────────────────────────────────────────
# Admin REST surface
# ──────────────────────────────────────────────────────────────────────
from rest_framework import serializers


class IntegrationSourceSerializer(serializers.ModelSerializer):
    inboundEnabled = serializers.BooleanField(source="inbound_enabled")
    outboundEnabled = serializers.BooleanField(source="outbound_enabled")
    outboundUrl = serializers.URLField(source="outbound_url", required=False, allow_blank=True)
    outboundPushesUsers = serializers.BooleanField(source="outbound_pushes_users")
    lastInboundAt = serializers.DateTimeField(source="last_inbound_at", read_only=True, allow_null=True)
    lastOutboundAt = serializers.DateTimeField(source="last_outbound_at", read_only=True, allow_null=True)
    lastError = serializers.CharField(source="last_error", read_only=True)

    class Meta:
        model = IntegrationSource
        fields = [
            "id", "name", "kind", "status",
            "inboundEnabled", "outboundEnabled",
            "outboundUrl", "outboundPushesUsers",
            "lastInboundAt", "lastOutboundAt", "lastError",
        ]
        extra_kwargs = {
            # Secrets are write-only — never echoed back to the FE.
            "inbound_secret": {"write_only": True, "required": False},
            "outbound_token": {"write_only": True, "required": False},
        }


class IntegrationEventSerializer(serializers.ModelSerializer):
    sourceId = serializers.UUIDField(source="source_id", read_only=True)
    sourceName = serializers.CharField(source="source.name", read_only=True)
    resourceType = serializers.CharField(source="resource_type")
    externalId = serializers.CharField(source="external_id")

    class Meta:
        model = IntegrationEvent
        fields = [
            "id", "sourceId", "sourceName", "direction", "resourceType",
            "externalId", "status", "error", "payload", "timestamp",
        ]
        read_only_fields = fields


class IntegrationSourceViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """CRUD for IntegrationSource. Settings-grade — super-admin only."""
    queryset = IntegrationSource.objects.all()
    serializer_class = IntegrationSourceSerializer
    permission_classes = [HasPermission("manage_settings")]


class IntegrationEventViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only ledger of inbound + outbound deliveries."""
    queryset = IntegrationEvent.objects.select_related("source").all()
    serializer_class = IntegrationEventSerializer
    permission_classes = [HasPermission("manage_settings")]

    def get_queryset(self):
        qs = super().get_queryset()
        source_id = self.request.query_params.get("source_id")
        direction = self.request.query_params.get("direction")
        status_filter = self.request.query_params.get("status")
        if source_id:
            qs = qs.filter(source_id=source_id)
        if direction in ("inbound", "outbound"):
            qs = qs.filter(direction=direction)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs
