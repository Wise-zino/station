import json
import re
from unittest import mock

import numpy as np
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from planner.exceptions import PlanningError
from planner.index import reset_station_index
from planner.tests import meridian_route
from routing.exceptions import LocationError, RoutingError
from routing.simplify import simplify_indices
from stations.models import Station


class ApiTestBase(TestCase):
    def setUp(self):
        cache.clear()
        reset_station_index()
        self.addCleanup(reset_station_index)
        Station.objects.bulk_create([
            Station(opis_id=1, name="S31", city="A", state="KS", price="3.50", lat=31.0, lon=-95.0),
            Station(opis_id=2, name="S36", city="B", state="KS", price="3.00", lat=36.0, lon=-95.0),
            Station(opis_id=3, name="S41", city="C", state="KS", price="3.80", lat=41.0, lon=-95.0),
            Station(opis_id=4, name="S44 <b>x</b>", city="D", state="KS", price="3.20", lat=44.0, lon=-95.0),
        ])
        self.route = meridian_route()
        p = mock.patch("planner.service.get_route", return_value=self.route)
        p.start()
        self.addCleanup(p.stop)
        self.client = APIClient()


class RouteEndpointTests(ApiTestBase):
    def check_payload(self, data):
        self.assertEqual(set(data), {"start", "finish", "route", "fuel_stops", "summary", "map_url", "meta"})
        stops = data["fuel_stops"]
        self.assertEqual([s["order"] for s in stops], [1, 2, 3, 4])
        self.assertEqual(stops[0]["kind"], "origin")
        self.assertEqual((stops[0]["lat"], stops[0]["lon"]), (data["start"]["lat"], data["start"]["lon"]))
        self.assertTrue(all(s["kind"] == "station" for s in stops[1:]))
        # money adds up and fuel needed = miles / mpg
        self.assertAlmostEqual(data["summary"]["total_fuel_cost"], sum(s["cost"] for s in stops), places=2)
        self.assertAlmostEqual(data["summary"]["total_gallons"], data["route"]["distance_miles"] / 10, places=1)
        self.assertEqual(data["summary"]["stops_count"], 4)
        self.assertIn("/map/?start=", data["map_url"])
        self.assertIn("total", data["meta"]["timings_ms"])
        geom = data["route"]["geometry"]
        self.assertEqual(geom["type"], "LineString")
        return geom

    def test_post(self):
        r = self.client.post("/api/route/", {"start": "a", "finish": "b"}, format="json")
        self.assertEqual(r.status_code, 200)
        geom = self.check_payload(r.json())
        # a straight meridian simplifies to its two endpoints (full route has 1,501 vertices)
        self.assertEqual(len(geom["coordinates"]), 2)

    def test_get_matches_post(self):
        post = self.client.post("/api/route/", {"start": "a", "finish": "b"}, format="json").json()
        get = self.client.get("/api/route/", {"start": "a", "finish": "b"})
        self.assertEqual(get.status_code, 200)
        self.assertEqual(get.json()["summary"], post["summary"])
        self.assertEqual(get.json()["fuel_stops"], post["fuel_stops"])

    def test_validation_errors(self):
        r = self.client.post("/api/route/", {"start": "a"}, format="json")
        self.assertEqual(r.status_code, 400)
        err = r.json()["error"]
        self.assertEqual(err["type"], "ValidationError")
        self.assertIn("finish", err["details"])
        self.assertEqual(self.client.get("/api/route/").status_code, 400)
        self.assertEqual(self.client.post("/api/route/", {"start": "a", "finish": " "}, format="json").status_code, 400)

    def test_domain_errors_map_to_status_codes(self):
        cases = [(LocationError("Could not find 'x' in the USA."), 400),
                 (PlanningError("No fuel station within 500 miles after mile 100."), 422),
                 (RoutingError("Routing service timed out."), 502)]
        for exc, code in cases:
            with mock.patch("api.views.plan_trip", side_effect=exc):
                r = self.client.post("/api/route/", {"start": "a", "finish": "b"}, format="json")
            self.assertEqual(r.status_code, code)
            self.assertEqual(r.json()["error"], {"type": type(exc).__name__, "message": str(exc)})

    def test_method_not_allowed_uses_error_shape(self):
        r = self.client.put("/api/route/", {}, format="json")
        self.assertEqual(r.status_code, 405)
        self.assertIn("error", r.json())

    def test_swagger_and_schema(self):
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)
        schema = self.client.get("/api/schema/", {"format": "json"}).json()
        self.assertIn("/api/route/", schema["paths"])
        self.assertIn("post", schema["paths"]["/api/route/"])
        self.assertIn("get", schema["paths"]["/api/route/"])
        self.assertIn("RouteResponse", schema["components"]["schemas"])


class MapPageTests(ApiTestBase):
    def test_empty_form(self):
        r = self.client.get("/map/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Plan route")
        self.assertNotContains(r, "trip-data")

    def test_map_embeds_trip_json(self):
        r = self.client.get("/map/", {"start": "a", "finish": "b"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "leaflet")
        m = re.search(r'<script id="trip-data" type="application/json">(.*?)</script>', r.content.decode(), re.S)
        trip = json.loads(m.group(1))
        self.assertEqual(len(trip["fuel_stops"]), 4)
        # hostile station names are escaped inside the JSON script block, never raw HTML
        self.assertNotIn("<b>x</b>", r.content.decode())

    def test_map_shows_errors_with_status(self):
        with mock.patch("api.views.plan_trip", side_effect=LocationError("Could not find 'zzz' in the USA.")):
            r = self.client.get("/map/", {"start": "zzz", "finish": "b"})
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "Could not find", status_code=400)

    def test_map_requires_both_fields(self):
        r = self.client.get("/map/", {"start": "a"})
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "both a start and a finish", status_code=400)

    def test_root_redirects_to_docs(self):
        self.assertEqual(self.client.get("/").status_code, 302)


class SimplifyTests(TestCase):
    def test_straight_line_collapses_to_endpoints(self):
        lats = np.linspace(30, 40, 500)
        self.assertEqual(list(simplify_indices(lats, np.full(500, -95.0))), [0, 499])

    def test_corner_is_kept(self):
        lats = np.concatenate([np.linspace(30, 35, 100), np.full(100, 35.0)])
        lons = np.concatenate([np.full(100, -95.0), np.linspace(-95, -90, 100)])
        idx = simplify_indices(lats, lons)
        self.assertIn(99, idx)
        self.assertLessEqual(len(idx), 4)

    def test_deviation_never_exceeds_tolerance(self):
        rng = np.random.default_rng(5)
        t = np.linspace(0, 1, 3000)
        lats = 35 + 2 * np.sin(12 * t) + rng.normal(0, 0.0005, t.size)
        lons = -100 + 6 * t
        idx = simplify_indices(lats, lons, tolerance_miles=0.1)
        self.assertLess(len(idx), 3000 // 4)
        x = lons * np.cos(np.radians(lats.mean())) * 69.17
        y = lats * 69.09
        for a, b in zip(idx[:-1], idx[1:]):
            dx, dy = x[b] - x[a], y[b] - y[a]
            seg = np.hypot(dx, dy)
            for k in range(a + 1, b):
                d = abs(dx * (y[k] - y[a]) - dy * (x[k] - x[a])) / seg
                self.assertLessEqual(d, 0.1 + 1e-9)
