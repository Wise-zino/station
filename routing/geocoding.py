"""Turn user input into coordinates. Accepts "lat,lon" (zero API calls) or free text (one call)."""
import hashlib
import re
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from stations.constants import US_LAT_RANGE, US_LON_RANGE

from .exceptions import LocationError

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GEOCODE_CACHE_SECONDS = 60 * 60 * 24 * 30
_COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_session = requests.Session()


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float
    label: str = ""


def _validate_us(point: Point, original: str) -> Point:
    if not (US_LAT_RANGE[0] <= point.lat <= US_LAT_RANGE[1] and US_LON_RANGE[0] <= point.lon <= US_LON_RANGE[1]):
        raise LocationError(
            f"'{original}' is outside the USA. Coordinates must be 'lat,lon' (e.g. 34.05,-118.24)."
        )
    return point


def parse_coordinates(text: str):
    m = _COORDS.match(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return _validate_us(Point(lat, lon, f"{lat:.5f},{lon:.5f}"), text)


def resolve_location(text: str):
    """Return (Point, external_calls_made)."""
    text = (text or "").strip()
    if not text:
        raise LocationError("Location is required.")

    point = parse_coordinates(text)
    if point:
        return point, 0

    key = "geocode:" + hashlib.sha1(" ".join(text.lower().split()).encode()).hexdigest()
    hit = cache.get(key)
    if hit:
        return hit, 0

    try:
        resp = _session.get(
            NOMINATIM_URL,
            params={"q": text, "countrycodes": "us", "format": "jsonv2", "limit": 1},
            headers={"User-Agent": settings.GEOCODER_USER_AGENT},
            timeout=settings.GEOCODE_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise LocationError(f"Could not look up '{text}' right now: {exc}") from exc

    if not results:
        raise LocationError(f"Could not find '{text}' in the USA.")

    point = _validate_us(
        Point(float(results[0]["lat"]), float(results[0]["lon"]), results[0].get("display_name", text)), text
    )
    cache.set(key, point, GEOCODE_CACHE_SECONDS)
    return point, 1
