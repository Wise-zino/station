"""Turn a TripPlan into the JSON-able dict returned by the API and embedded in the map page."""
import time
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse

from routing.simplify import simplify_indices


def build_payload(plan, start_text, finish_text, request, started_at):
    route = plan.route
    idx = route.display_idx if route.display_idx is not None else simplify_indices(route.lats, route.lons)
    coords = [[round(float(route.lons[i]), 5), round(float(route.lats[i]), 5)] for i in idx]

    stops = []
    for n, s in enumerate(plan.stops, 1):
        origin = s.kind == "origin"
        stops.append({
            "order": n, "kind": s.kind, "name": s.name, "address": s.address, "city": s.city, "state": s.state,
            "lat": route.start.lat if origin else s.lat, "lon": route.start.lon if origin else s.lon,
            "route_mile": s.route_mile, "miles_off_route": s.miles_off_route,
            "price_per_gallon": s.price_per_gallon, "gallons": s.gallons, "cost": s.cost,
        })

    map_url = request.build_absolute_uri(reverse("map")) + "?" + urlencode({"start": start_text, "finish": finish_text})
    timings = dict(plan.timings_ms)
    timings["total"] = round((time.perf_counter() - started_at) * 1000, 1)

    return {
        "start": {"query": start_text, "label": route.start.label, "lat": route.start.lat, "lon": route.start.lon},
        "finish": {"query": finish_text, "label": route.finish.label, "lat": route.finish.lat, "lon": route.finish.lon},
        "route": {
            "distance_miles": plan.total_miles,
            "duration_hours": round(route.duration_s / 3600, 2),
            "geometry": {"type": "LineString", "coordinates": coords},
        },
        "fuel_stops": stops,
        "summary": {
            "total_fuel_cost": plan.total_cost,
            "total_gallons": plan.total_gallons,
            "stops_count": len(stops),
            "vehicle_range_miles": settings.VEHICLE_RANGE_MILES,
            "mpg": settings.VEHICLE_MPG,
            "departure_price_per_gallon": plan.start_fuel_price,
            "departure_price_source": plan.start_price_source,
        },
        "map_url": map_url,
        "meta": {"external_api_calls": route.api_calls, "route_cached": route.cached, "timings_ms": timings},
    }
