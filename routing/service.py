from dataclasses import dataclass, replace

import numpy as np
from django.conf import settings
from django.core.cache import cache

from .exceptions import RoutingError
from .geo import METERS_PER_MILE, cumulative_miles
from .geocoding import Point, resolve_location
from .providers import fetch_route
from .simplify import simplify_indices


@dataclass
class Route:
    start: Point
    finish: Point
    lats: np.ndarray
    lons: np.ndarray
    cum_miles: np.ndarray   # miles from start at each vertex; cum_miles[-1] == total_miles
    total_miles: float
    duration_s: float
    api_calls: int = 0      # external HTTP calls made for THIS request
    cached: bool = False    # True if the directions result came from cache
    display_idx: np.ndarray = None  # vertex indices kept for the simplified geometry sent to clients


def _build(start: Point, finish: Point, pr) -> Route:
    pts = np.asarray(pr.coordinates, dtype=float)
    if pts.ndim != 2 or len(pts) < 2:
        raise RoutingError("Routing service returned an empty route.")
    lons, lats = pts[:, 0], pts[:, 1]
    cum = cumulative_miles(lats, lons)
    total = pr.distance_m / METERS_PER_MILE
    if cum[-1] > 0:
        cum *= total / cum[-1]  # make mile markers agree with the provider's road distance
    return Route(start, finish, lats, lons, cum, float(total), float(pr.duration_s),
                 display_idx=simplify_indices(lats, lons))


def _route_key(start: Point, finish: Point) -> str:
    return (f"route:{settings.ROUTING_PROVIDER}:"
            f"{start.lat:.4f},{start.lon:.4f}:{finish.lat:.4f},{finish.lon:.4f}")


def get_route(start_text: str, finish_text: str) -> Route:
    start, c1 = resolve_location(start_text)
    finish, c2 = resolve_location(finish_text)
    geocode_calls = c1 + c2

    key = _route_key(start, finish)
    hit = cache.get(key)
    if hit is not None:
        return replace(hit, start=start, finish=finish, api_calls=geocode_calls, cached=True)

    route = _build(start, finish, fetch_route(start, finish))
    cache.set(key, route, settings.ROUTE_CACHE_SECONDS)
    return replace(route, api_calls=geocode_calls + 1, cached=False)
