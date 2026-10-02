"""Milestone 3 entry point: plan_trip(start, finish) -> TripPlan."""
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from django.conf import settings

from routing.service import get_route

from .corridor import find_candidates
from .exceptions import PlanningError
from .index import get_station_index
from .optimizer import plan_fuel_stops


@dataclass
class Stop:
    kind: str                    # "origin" (departure fill-up) or "station"
    name: str
    route_mile: float
    price_per_gallon: float
    gallons: float
    cost: float
    station_id: Optional[int] = None
    address: str = ""
    city: str = ""
    state: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    miles_off_route: float = 0.0


@dataclass
class TripPlan:
    route: object
    stops: list
    total_miles: float
    total_gallons: float
    total_cost: float
    start_fuel_price: float
    start_price_source: str
    timings_ms: dict = field(default_factory=dict)


def _ms(t0):
    return round((time.perf_counter() - t0) * 1000, 1)


def plan_trip(start_text, finish_text) -> TripPlan:
    t = time.perf_counter()
    route = get_route(start_text, finish_text)
    timings = {"route": _ms(t)}

    index = get_station_index()
    if len(index) == 0:
        raise PlanningError("No geocoded stations available. Run `manage.py geocode_stations` first.")

    t = time.perf_counter()
    cands = find_candidates(route, index, settings.CORRIDOR_MILES)
    timings["match"] = _ms(t)

    # Price of fuel bought at departure: the station nearest the origin, else the national average.
    if cands:
        near = min(c.mile for c in cands)
        first = min((c for c in cands if c.mile <= near + 1.0), key=lambda c: c.price)
        start_price, source = first.price, f"nearest station to origin ({index.names[first.index_pos]})"
    else:
        start_price, source = float(np.mean(index.price)), "national average (no stations near route)"

    t = time.perf_counter()
    fills = plan_fuel_stops(cands, route.total_miles, start_price,
                            settings.VEHICLE_RANGE_MILES, settings.VEHICLE_MPG)
    timings["optimize"] = _ms(t)

    stops = []
    for f in fills:
        gal, cost = round(f.gallons, 2), round(f.gallons * f.price, 2)
        if f.ref is None:
            stops.append(Stop("origin", "Departure fill-up (at origin)", round(f.mile, 1),
                              round(f.price, 4), gal, cost))
        else:
            i = f.ref.index_pos
            stops.append(Stop("station", index.names[i], round(f.mile, 1), round(f.price, 4), gal, cost,
                              station_id=index.ids[i], address=index.addresses[i], city=index.cities[i],
                              state=index.states[i], lat=float(index.lat[i]), lon=float(index.lon[i]),
                              miles_off_route=round(f.ref.off_route, 1)))

    return TripPlan(
        route=route, stops=stops,
        total_miles=round(route.total_miles, 1),
        total_gallons=round(route.total_miles / settings.VEHICLE_MPG, 2),
        total_cost=round(sum(s.cost for s in stops), 2),   # sum of the displayed per-stop costs
        start_fuel_price=round(start_price, 4), start_price_source=source,
        timings_ms=timings,
    )
