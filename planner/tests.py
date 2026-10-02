import random
from dataclasses import dataclass
from unittest import mock

import numpy as np
from django.test import TestCase

from routing.geo import cumulative_miles
from routing.geocoding import Point
from routing.service import Route
from stations.models import Station

from .corridor import find_candidates
from .exceptions import PlanningError
from .index import get_station_index, reset_station_index
from .optimizer import plan_fuel_stops
from .service import plan_trip


@dataclass
class C:  # minimal candidate for pure optimizer tests
    mile: float
    price: float


def meridian_route(lat0=30.0, lat1=45.0, lon=-95.0, n=1501):
    lats = np.linspace(lat0, lat1, n)
    lons = np.full(n, lon)
    cum = cumulative_miles(lats, lons)
    return Route(Point(lat0, lon), Point(lat1, lon), lats, lons, cum, float(cum[-1]), 0.0)


def brute_force_cost(cands, total, start_price, rng, mpg):
    """Exhaustive DP on integer miles: min cost over every legal buying strategy."""
    nodes = [(0, start_price)] + [(int(c.mile), c.price) for c in cands] + [(int(total), 0.0)]
    INF = float("inf")
    dp = [[INF] * (rng + 1) for _ in nodes]
    dp[0][0] = 0.0
    for i in range(len(nodes) - 1):
        gap = nodes[i + 1][0] - nodes[i][0]
        for f in range(rng + 1):
            if dp[i][f] == INF:
                continue
            for buy in range(rng - f + 1):
                g = f + buy
                if g < gap:
                    continue
                c = dp[i][f] + buy / mpg * nodes[i][1]
                if c < dp[i + 1][g - gap]:
                    dp[i + 1][g - gap] = c
    return min(dp[-1])


class OptimizerTests(TestCase):
    def test_buys_just_enough_before_a_cheaper_station(self):
        fills = plan_fuel_stops([C(100, 3.0)], 300, start_price=3.5, range_miles=500, mpg=10)
        self.assertEqual([round(f.miles_bought) for f in fills], [100, 200])
        self.assertAlmostEqual(sum(f.cost for f in fills), 10 * 3.5 + 20 * 3.0)

    def test_short_trip_no_cheaper_station_buys_everything_at_origin(self):
        fills = plan_fuel_stops([C(100, 4.0)], 300, start_price=3.5, range_miles=500, mpg=10)
        self.assertEqual(len(fills), 1)
        self.assertIsNone(fills[0].ref)
        self.assertAlmostEqual(fills[0].gallons, 30.0)

    def test_fills_up_when_nothing_cheaper_in_range(self):
        # origin 3.0, stations get pricier; trip 700 mi, range 500 -> must stop once, filling the tank
        fills = plan_fuel_stops([C(400, 3.4), C(450, 3.6)], 700, 3.0, 500, 10)
        self.assertAlmostEqual(fills[0].miles_bought, 500)          # full tank at origin
        self.assertAlmostEqual(sum(f.gallons for f in fills), 70.0)  # exactly the fuel the trip needs

    def test_gap_larger_than_range_raises(self):
        with self.assertRaises(PlanningError):
            plan_fuel_stops([C(100, 3.0), C(700, 3.0)], 800, 3.0, 500, 10)

    def test_first_hop_beyond_range_raises(self):
        with self.assertRaises(PlanningError):
            plan_fuel_stops([C(600, 3.0)], 900, 3.0, 500, 10)

    def test_matches_brute_force_on_random_instances(self):
        rnd = random.Random(7)
        for _ in range(250):
            rng, mpg = 100, 10
            total = rnd.randint(40, 520)
            cands, m = [], 0
            while True:
                m += rnd.randint(1, 60)
                if m >= total:
                    break
                cands.append(C(m, round(rnd.uniform(3.0, 4.0), 2)))
            start = round(rnd.uniform(3.0, 4.0), 2)
            fills = plan_fuel_stops(cands, total, start, rng, mpg)
            got = sum(f.cost for f in fills)
            self.assertAlmostEqual(got, brute_force_cost(cands, total, start, rng, mpg), places=6)
            self.assertAlmostEqual(sum(f.gallons for f in fills), total / mpg, places=6)

    def test_tank_never_overflows_or_runs_dry(self):
        rnd = random.Random(11)
        for _ in range(100):
            rng = 100
            total = rnd.randint(150, 600)
            cands, m = [], 0
            while True:
                m += rnd.randint(5, 70)
                if m >= total:
                    break
                cands.append(C(m, round(rnd.uniform(3.0, 4.0), 2)))
            fills = plan_fuel_stops(cands, total, 3.5, rng, 10)
            fuel, pos = 0.0, 0.0
            for f in fills:
                fuel -= f.mile - pos
                pos = f.mile
                self.assertGreaterEqual(fuel, -1e-6)
                fuel += f.miles_bought
                self.assertLessEqual(fuel, rng + 1e-6)
            self.assertGreaterEqual(fuel - (total - pos), -1e-6)


class CorridorTests(TestCase):
    def setUp(self):
        reset_station_index()
        # ~69.09 mi per degree of latitude along the meridian; lon -95 is the route
        Station.objects.bulk_create([
            Station(opis_id=1, name="ON ROUTE", city="A", state="KS", price="3.50", lat=35.0, lon=-95.0),
            Station(opis_id=2, name="NEAR 5MI", city="B", state="KS", price="3.40", lat=36.0, lon=-94.9),
            Station(opis_id=3, name="FAR 17MI", city="C", state="KS", price="2.00", lat=37.0, lon=-94.7),
            Station(opis_id=4, name="NO COORDS", city="D", state="KS", price="2.00"),
            Station(opis_id=5, name="NOWHERE NEAR", city="E", state="CA", price="2.00", lat=34.0, lon=-118.0),
        ])
        self.addCleanup(reset_station_index)

    def test_index_skips_stations_without_coordinates(self):
        self.assertEqual(len(get_station_index()), 4)

    def test_candidates_within_corridor_with_mile_markers(self):
        route = meridian_route()
        names = {}
        idx = get_station_index()
        for c in find_candidates(route, idx, corridor_miles=10):
            names[idx.names[c.index_pos]] = c
        self.assertEqual(set(names), {"ON ROUTE", "NEAR 5MI"})
        self.assertAlmostEqual(names["ON ROUTE"].mile, 5 * 69.093, delta=0.5)
        self.assertAlmostEqual(names["NEAR 5MI"].mile, 6 * 69.093, delta=0.5)
        self.assertAlmostEqual(names["ON ROUTE"].off_route, 0.0, places=2)
        self.assertAlmostEqual(names["NEAR 5MI"].off_route, 0.1 * 69.17 * np.cos(np.radians(36)), delta=0.3)

    def test_wider_corridor_includes_far_station_and_results_are_sorted(self):
        idx = get_station_index()
        cands = find_candidates(meridian_route(), idx, corridor_miles=20)
        self.assertEqual(len(cands), 3)
        self.assertEqual([c.mile for c in cands], sorted(c.mile for c in cands))


class PlanTripTests(TestCase):
    def setUp(self):
        reset_station_index()
        self.addCleanup(reset_station_index)
        Station.objects.bulk_create([
            Station(opis_id=1, name="S31", city="A", state="KS", price="3.50", lat=31.0, lon=-95.0),
            Station(opis_id=2, name="S36", city="B", state="KS", price="3.00", lat=36.0, lon=-95.0),
            Station(opis_id=3, name="S41", city="C", state="KS", price="3.80", lat=41.0, lon=-95.0),
            Station(opis_id=4, name="S44", city="D", state="KS", price="3.20", lat=44.0, lon=-95.0),
            Station(opis_id=5, name="CHEAP BUT OFF ROUTE", city="E", state="KS", price="1.00", lat=38.0, lon=-94.5),
        ])
        self.route = meridian_route()

    def plan(self):
        with mock.patch("planner.service.get_route", return_value=self.route):
            return plan_trip("a", "b")

    def test_full_plan(self):
        p = self.plan()
        self.assertAlmostEqual(p.total_miles, 15 * 69.093, delta=1)
        self.assertEqual([s.name for s in p.stops],
                         ["Departure fill-up (at origin)", "S36", "S41", "S44"])
        self.assertEqual(p.stops[0].kind, "origin")
        self.assertIn("S31", p.start_price_source)
        self.assertAlmostEqual(p.start_fuel_price, 3.50)
        # all fuel burned is paid for, nothing more
        self.assertAlmostEqual(sum(s.gallons for s in p.stops), p.total_gallons, delta=0.05)
        self.assertAlmostEqual(p.total_cost, sum(s.cost for s in p.stops), places=2)
        self.assertNotIn("CHEAP BUT OFF ROUTE", [s.name for s in p.stops])
        # origin buys just enough to reach the cheaper S36 (~mile 415); S36 then fills the whole tank
        self.assertAlmostEqual(p.stops[0].gallons * 10, 6 * 69.093, delta=1)
        self.assertAlmostEqual(p.stops[1].gallons, 50.0, delta=0.05)

    def test_no_geocoded_stations_gives_clear_error(self):
        Station.objects.all().delete()
        reset_station_index()
        with self.assertRaisesMessage(PlanningError, "geocode_stations"):
            self.plan()

    def test_short_trip_with_no_nearby_station_uses_national_average(self):
        short = meridian_route(lat0=30.0, lat1=30.5, n=51)   # ~35 mi, no stations within 10 mi
        with mock.patch("planner.service.get_route", return_value=short):
            p = plan_trip("a", "b")
        self.assertIn("national average", p.start_price_source)
        self.assertEqual(len(p.stops), 1)
        self.assertGreater(p.total_cost, 0)
