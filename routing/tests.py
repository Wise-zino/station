from unittest import mock

import numpy as np
from django.core.cache import cache
from django.test import TestCase, override_settings

from .exceptions import LocationError, RoutingError
from .geo import cumulative_miles, haversine_miles
from .geocoding import parse_coordinates
from .service import get_route

# NYC -> Chicago -> LA (rough), reported as 2,800 mi by the "provider"
COORDS = [[-74.0, 40.7], [-87.6, 41.9], [-118.2, 34.0]]
DIST_M = 2800 * 1609.344


def resp(payload, status=200):
    r = mock.MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


OSRM_OK = {"code": "Ok", "routes": [{"distance": DIST_M, "duration": 144000,
                                     "geometry": {"type": "LineString", "coordinates": COORDS}}]}
NOMINATIM = {"new york": [{"lat": "40.7128", "lon": "-74.0060", "display_name": "New York, USA"}],
             "los angeles": [{"lat": "34.0522", "lon": "-118.2437", "display_name": "Los Angeles, USA"}],
             "chicago": [{"lat": "41.8781", "lon": "-87.6298", "display_name": "Chicago, USA"}]}


class FakeNetwork:
    """Patches Session.get/post and records every external call."""

    def __init__(self, osrm=None):
        self.calls = []
        self.osrm = osrm or OSRM_OK

    def get(self, url, **kw):
        self.calls.append(url)
        if "nominatim" in url:
            return resp(NOMINATIM.get(kw["params"]["q"].lower().split(",")[0], []))
        return resp(self.osrm)

    def __enter__(self):
        self.p = mock.patch("requests.Session.get", side_effect=self.get)
        self.p.start()
        return self

    def __exit__(self, *a):
        self.p.stop()


class GeoTests(TestCase):
    def test_haversine_nyc_to_la(self):
        d = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        self.assertAlmostEqual(float(d), 2445, delta=15)

    def test_cumulative_miles_monotonic_starts_at_zero(self):
        c = cumulative_miles(np.array([40.0, 41.0, 42.0]), np.array([-90.0, -90.0, -90.0]))
        self.assertEqual(c[0], 0.0)
        self.assertTrue(np.all(np.diff(c) > 0))
        self.assertAlmostEqual(c[-1], 138, delta=2)  # 2 degrees of latitude


class ParseTests(TestCase):
    def test_parses_coordinates(self):
        p = parse_coordinates(" 34.05 , -118.24 ")
        self.assertEqual((p.lat, p.lon), (34.05, -118.24))

    def test_free_text_returns_none(self):
        self.assertIsNone(parse_coordinates("Los Angeles, CA"))

    def test_swapped_or_non_us_coordinates_rejected(self):
        with self.assertRaises(LocationError):
            parse_coordinates("-118.24,34.05")   # lon,lat swapped
        with self.assertRaises(LocationError):
            parse_coordinates("51.5,-0.12")      # London


class GetRouteTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_coordinate_inputs_use_one_call_then_zero(self):
        with FakeNetwork() as net:
            r1 = get_route("40.71,-74.00", "34.05,-118.24")
            r2 = get_route("40.71,-74.00", "34.05,-118.24")
        self.assertEqual(len(net.calls), 1)
        self.assertEqual((r1.api_calls, r1.cached), (1, False))
        self.assertEqual((r2.api_calls, r2.cached), (0, True))

    def test_free_text_uses_three_calls_cold_then_zero(self):
        with FakeNetwork() as net:
            r1 = get_route("New York, NY", "Los Angeles, CA")
            r2 = get_route("new york,  ny", "LOS ANGELES, ca")
        self.assertEqual(r1.api_calls, 3)
        self.assertEqual(len(net.calls), 3)
        self.assertEqual(r2.api_calls, 0)

    def test_geocodes_are_reused_across_different_routes(self):
        with FakeNetwork() as net:
            get_route("New York, NY", "Los Angeles, CA")
            r = get_route("New York, NY", "Chicago, IL")   # only Chicago + directions are new
        self.assertEqual(r.api_calls, 2)
        self.assertEqual(len(net.calls), 5)

    def test_mile_markers_match_provider_distance(self):
        with FakeNetwork():
            r = get_route("40.71,-74.00", "34.05,-118.24")
        self.assertAlmostEqual(r.total_miles, 2800, places=3)
        self.assertAlmostEqual(float(r.cum_miles[-1]), 2800, places=3)
        self.assertEqual(float(r.cum_miles[0]), 0.0)
        self.assertTrue(np.all(np.diff(r.cum_miles) >= 0))
        self.assertEqual(len(r.lats), len(r.lons)); self.assertEqual(len(r.lats), 3)

    def test_unknown_place(self):
        with FakeNetwork():
            with self.assertRaises(LocationError):
                get_route("Atlantis", "34.05,-118.24")

    def test_no_route(self):
        with FakeNetwork(osrm={"code": "NoRoute"}):
            with self.assertRaises(RoutingError):
                get_route("40.71,-74.00", "34.05,-118.24")

    def test_failed_routes_are_not_cached(self):
        with FakeNetwork(osrm={"code": "NoRoute"}):
            with self.assertRaises(RoutingError):
                get_route("40.71,-74.00", "34.05,-118.24")
        with FakeNetwork() as net:
            r = get_route("40.71,-74.00", "34.05,-118.24")
        self.assertEqual(len(net.calls), 1)
        self.assertFalse(r.cached)

    def test_timeout_becomes_routing_error(self):
        import requests
        with mock.patch("requests.Session.get", side_effect=requests.Timeout()):
            with self.assertRaises(RoutingError):
                get_route("40.71,-74.00", "34.05,-118.24")

    @override_settings(ROUTING_PROVIDER="ors", ORS_API_KEY="k")
    def test_ors_provider_parses_geojson(self):
        ors = {"features": [{"geometry": {"coordinates": COORDS},
                             "properties": {"summary": {"distance": DIST_M, "duration": 144000}}}]}
        with mock.patch("requests.Session.post", return_value=resp(ors)) as post:
            r = get_route("40.71,-74.00", "34.05,-118.24")
        self.assertEqual(post.call_count, 1)
        self.assertAlmostEqual(r.total_miles, 2800, places=3)

    @override_settings(ROUTING_PROVIDER="ors", ORS_API_KEY="")
    def test_ors_without_key_fails_cleanly(self):
        with self.assertRaises(RoutingError):
            get_route("40.71,-74.00", "34.05,-118.24")
