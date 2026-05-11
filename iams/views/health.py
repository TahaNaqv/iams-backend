from django.db import connections
from django.db.utils import OperationalError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class ReadinessView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            connections["default"].cursor()
        except OperationalError:
            return Response({"status": "not_ready"}, status=503)
        return Response({"status": "ready"})
