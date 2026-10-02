"""Cost-minimising fuel plan. Pure Python: no Django, no I/O, easy to test.

Model
-----
* Tank holds `range_miles` of fuel and starts EMPTY at the origin. The origin acts as a virtual
  station priced at `start_price`, so every gallon burned on the trip is paid for.
* The destination is a virtual station with price 0, so the last stop buys only what's needed.

Greedy rule (optimal for this "gas station problem"; verified against a DP in tests):
  from the current stop, look at every stop reachable on a full tank.
    - if a CHEAPER one exists: drive to the nearest cheaper one, buying only enough to reach it
    - else: fill the tank, then drive to the cheapest reachable one
"""
from bisect import bisect_right
from dataclasses import dataclass

from .exceptions import PlanningError

EPS = 1e-9


@dataclass
class Fill:
    ref: object          # the Candidate, or None for the origin
    mile: float
    price: float
    miles_bought: float  # miles of range purchased here
    gallons: float
    cost: float


def plan_fuel_stops(candidates, total_miles, start_price, range_miles=500.0, mpg=10.0):
    """candidates: objects with .mile and .price, sorted by (mile, price). Returns list[Fill]."""
    nodes = [(c.mile, c.price, c) for c in candidates if c.mile < total_miles + EPS]
    nodes.append((total_miles, 0.0, "DEST"))
    miles = [n[0] for n in nodes]
    last = len(nodes) - 1

    cur, pos, price, fuel = -1, 0.0, float(start_price), 0.0   # cur=-1 -> origin
    fills = []

    while cur != last:
        lo = cur + 1
        hi = bisect_right(miles, pos + range_miles + EPS)
        if lo >= hi:
            raise PlanningError(
                f"No fuel station within {range_miles:.0f} miles after mile {pos:,.0f} of the route."
            )
        window = range(lo, hi)
        nxt = next((i for i in window if nodes[i][1] < price - EPS), None)
        if nxt is not None:                                   # cheaper stop ahead: buy just enough
            buy = max(0.0, (nodes[nxt][0] - pos) - fuel)
        else:                                                 # nothing cheaper in range: fill up
            nxt = min(window, key=lambda i: nodes[i][1])
            buy = range_miles - fuel

        if buy > EPS:
            gallons = buy / mpg
            fills.append(Fill(nodes[cur][2] if cur >= 0 else None, pos, price, buy, gallons, gallons * price))
        fuel += buy - (nodes[nxt][0] - pos)
        cur, pos, price = nxt, nodes[nxt][0], nodes[nxt][1]

    return fills
