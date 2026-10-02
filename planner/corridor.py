"""Find stations near the route and the mile marker where each one sits."""
import math
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from routing.geo import chord_to_arc_miles, to_xyz


@dataclass(frozen=True)
class Candidate:
    index_pos: int      # position in StationIndex arrays
    mile: float         # miles from start, at the route vertex nearest the station
    price: float        # $/gallon
    off_route: float    # straight-line miles from the route


def find_candidates(route, index, corridor_miles):
    """Stations within `corridor_miles` of the route, sorted by (mile, price).

    1. numpy bounding-box prefilter drops most of the country,
    2. a KD-tree over the route's vertices answers "nearest route point" for every survivor at once.
    """
    if len(index) == 0 or len(route.lats) == 0:
        return []

    lat_margin = corridor_miles / 69.0
    lat_lo, lat_hi = route.lats.min() - lat_margin, route.lats.max() + lat_margin
    widest_lat = min(89.0, max(abs(lat_lo), abs(lat_hi)))
    lon_margin = corridor_miles / (69.17 * math.cos(math.radians(widest_lat)))
    lon_lo, lon_hi = route.lons.min() - lon_margin, route.lons.max() + lon_margin

    sel = np.nonzero((index.lat >= lat_lo) & (index.lat <= lat_hi) &
                     (index.lon >= lon_lo) & (index.lon <= lon_hi))[0]
    if sel.size == 0:
        return []

    tree = cKDTree(to_xyz(route.lats, route.lons))
    chord, vertex = tree.query(index.xyz[sel], k=1, distance_upper_bound=corridor_miles, workers=-1)
    hit = np.isfinite(chord)
    if not hit.any():
        return []

    sel, vertex, chord = sel[hit], vertex[hit], chord[hit]
    miles = route.cum_miles[vertex]
    off = chord_to_arc_miles(chord)
    out = [Candidate(int(i), float(m), float(index.price[i]), float(o))
           for i, m, o in zip(sel, miles, off)]
    out.sort(key=lambda c: (c.mile, c.price))
    return out
