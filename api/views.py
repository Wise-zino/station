import time

from django.conf import settings
from django.shortcuts import render
from django.views import View
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from planner.service import plan_trip
from routing.exceptions import RoutingServiceError

from .payload import build_payload
from .serializers import ErrorSerializer, RouteRequestSerializer, RouteResponseSerializer

ERROR_RESPONSES = {
    400: ErrorSerializer,   # bad input / location not found or outside the USA
    422: ErrorSerializer,   # route exists but no valid fuel plan (e.g. >500 mile gap without stations)
    502: ErrorSerializer,   # routing provider failed or timed out
}


class RouteView(APIView):
    """Plan fuel stops for a trip. Accepts POST (JSON body) or GET (query string)."""
    authentication_classes = []
    permission_classes = []

    def _run(self, request, data):
        started = time.perf_counter()
        ser = RouteRequestSerializer(data=data)
        ser.is_valid(raise_exception=True)
        start, finish = ser.validated_data["start"].strip(), ser.validated_data["finish"].strip()
        plan = plan_trip(start, finish)
        return Response(build_payload(plan, start, finish, request, started))

    @extend_schema(
        request=RouteRequestSerializer, responses={200: RouteResponseSerializer, **ERROR_RESPONSES},
        examples=[OpenApiExample("Cross-country", value={"start": "New York, NY", "finish": "Los Angeles, CA"},
                                 request_only=True)],
    )
    def post(self, request):
        return self._run(request, request.data)

    @extend_schema(parameters=[RouteRequestSerializer], responses={200: RouteResponseSerializer, **ERROR_RESPONSES})
    def get(self, request):
        return self._run(request, request.query_params)


class MapView(View):
    """Interactive Leaflet map of the same result: /map/?start=...&finish=..."""

    def get(self, request):
        start = request.GET.get("start", "").strip()
        finish = request.GET.get("finish", "").strip()
        ctx = {"start": start, "finish": finish, "trip": None, "error": None,
               "tiles": {"url": settings.MAP_TILE_URL, "attribution": settings.MAP_TILE_ATTRIBUTION}}
        status = 200
        if start and finish:
            started = time.perf_counter()
            try:
                plan = plan_trip(start, finish)
                ctx["trip"] = build_payload(plan, start, finish, request, started)
            except RoutingServiceError as exc:
                ctx["error"], status = str(exc), exc.status_code
        elif start or finish:
            ctx["error"], status = "Please enter both a start and a finish location.", 400
        return render(request, "api/map.html", ctx, status=status)
