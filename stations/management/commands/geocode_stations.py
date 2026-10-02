"""
One-time, resumable geocoding of stations by (city, state) using Nominatim (OpenStreetMap).
Why city-level: the file only has highway-exit style addresses ("I-44, EXIT 283 & US-69"), which
geocoders can't resolve reliably. ~4.2k unique cities at Nominatim's 1 req/sec limit is ~70 minutes,
run once; results are cached in data/geocode_cache.json so re-runs only fetch what's missing.
"""
import json
import time
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from stations.constants import STATE_NAMES, US_LAT_RANGE, US_LON_RANGE
from stations.models import Station

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

def _in_us(lat, lon):
    return US_LAT_RANGE[0] <= lat <= US_LAT_RANGE[1] and US_LON_RANGE[0] <= lon <= US_LON_RANGE[1]


def _key(city, state):
    return f"{city}|{state}"

def lookup(city, state, session, user_agent):
    """Return [lat, lon] or None. Raises requests.RequestException on network/HTTP errors."""
    resp = session.get(
        NOMINATIM_URL,
        params={"city": city, "state": STATE_NAMES[state], "country": "US", "format": "jsonv2", "limit": 1},
        headers={"User-Agent": user_agent},
        timeout=15,
    )
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        return None
    lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
    return [lat, lon] if _in_us(lat, lon) else None


class Command(BaseCommand):
    help = "Geocode stations by (city, state) via Nominatim, caching results to a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Max NEW lookups this run (for testing).")
        parser.add_argument("--delay", type=float, default=1.1, help="Seconds between requests (policy: >=1).")
        parser.add_argument("--apply-only", action="store_true", help="Skip network; just apply the cache to the DB.")

    def handle(self, *args, **opts):
        cache_path = Path(settings.GEOCODE_CACHE_PATH)
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

        if not opts["apply_only"]:
            self._fetch_missing(cache, cache_path, opts["limit"], opts["delay"])
        self._apply(cache)

    def _fetch_missing(self, cache, cache_path, limit, delay):
        pairs = (Station.objects.filter(lat__isnull=True)
                 .values_list("city", "state").distinct().order_by("state", "city"))
        todo = [(c, s) for c, s in pairs if _key(c, s) not in cache]
        if limit is not None:
            todo = todo[:limit]
        self.stdout.write(f"{len(todo)} cities to look up (cache has {len(cache)}).")

        session = requests.Session()
        for i, (city, state) in enumerate(todo, 1):
            try:
                cache[_key(city, state)] = lookup(city, state, session, settings.GEOCODER_USER_AGENT)
            except requests.RequestException as exc:
                # Don't cache failures; they'll be retried next run.
                self.stderr.write(f"  ! {city}, {state}: {exc}")
            if i % 25 == 0:
                cache_path.write_text(json.dumps(cache))
                self.stdout.write(f"  ...{i}/{len(todo)}")
            time.sleep(delay)
        cache_path.write_text(json.dumps(cache))

    def _apply(self, cache):
        updated = 0
        with transaction.atomic():
            for key, coords in cache.items():
                if not coords:
                    continue
                city, state = key.rsplit("|", 1)
                updated += Station.objects.filter(city=city, state=state, lat__isnull=True)\
                    .update(lat=coords[0], lon=coords[1])
        total = Station.objects.count()
        missing = Station.objects.filter(lat__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"Applied coords to {updated} stations. {total - missing}/{total} geocoded, {missing} still missing."))
