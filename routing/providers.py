"""Directions providers. Each makes exactly ONE HTTP call and returns the same shape."""
from dataclasses import dataclass

import requests
from django.conf import settings

from .exceptions import RoutingError

_session = requests.Session()  # keep-alive: avoids a fresh TLS handshake per request


@dataclass
class ProviderRoute:
    coordinates: list  # [[lon, lat], ...] full-resolution geometry
    distance_m: float
    duration_s: float


def _osrm(start, finish) -> ProviderRoute:
    url = f"{settings.OSRM_BASE_URL}/route/v1/driving/{start.lon},{start.lat};{finish.lon},{finish.lat}"
    resp = _session.get(url, params={"overview": "full", "geometries": "geojson"},
                        timeout=settings.ROUTING_TIMEOUT)
    if resp.status_code >= 500:
        raise RoutingError(f"Routing service error (HTTP {resp.status_code}).")
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(f"No drivable route found ({data.get('code', 'unknown')}).")
    r = data["routes"][0]
    return ProviderRoute(r["geometry"]["coordinates"], r["distance"], r["duration"])


def _ors(start, finish) -> ProviderRoute:
    if not settings.ORS_API_KEY:
        raise RoutingError("ORS_API_KEY is not configured.")
    resp = _session.post(
        f"{settings.ORS_BASE_URL}/v2/directions/driving-car/geojson",
        json={"coordinates": [[start.lon, start.lat], [finish.lon, finish.lat]]},
        headers={"Authorization": settings.ORS_API_KEY},
        timeout=settings.ROUTING_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RoutingError(f"No drivable route found (routing service HTTP {resp.status_code}).")
    feat = resp.json()["features"][0]
    summary = feat["properties"]["summary"]
    return ProviderRoute(feat["geometry"]["coordinates"], summary["distance"], summary["duration"])


PROVIDERS = {"osrm": _osrm, "ors": _ors}


def fetch_route(start, finish) -> ProviderRoute:
    try:
        impl = PROVIDERS[settings.ROUTING_PROVIDER]
    except KeyError:
        raise RoutingError(f"Unknown ROUTING_PROVIDER '{settings.ROUTING_PROVIDER}'.")
    try:
        return impl(start, finish)
    except requests.Timeout as exc:
        raise RoutingError("Routing service timed out.") from exc
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        raise RoutingError(f"Routing service failed: {exc}") from exc
