"""Douglas-Peucker line simplification for the geometry we SEND to clients.

The full-resolution route (often 50k+ vertices cross-country) is kept for station matching;
only the display copy is simplified, so accuracy of the fuel plan is unaffected.
"""
import numpy as np


def simplify_indices(lats, lons, tolerance_miles=0.1):
    """Indices of the vertices to keep (always includes first and last)."""
    n = len(lats)
    if n <= 2:
        return np.arange(n)

    # Local equirectangular projection (miles). One cos(lat) for the whole route is plenty
    # accurate for a *display* tolerance of a fraction of a mile.
    x = np.asarray(lons, float) * np.cos(np.radians(np.mean(lats))) * 69.17
    y = np.asarray(lats, float) * 69.09

    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        dx, dy = x[b] - x[a], y[b] - y[a]
        px, py = x[a + 1:b] - x[a], y[a + 1:b] - y[a]
        seg = np.hypot(dx, dy)
        dist = np.hypot(px, py) if seg == 0 else np.abs(dx * py - dy * px) / seg
        i = int(np.argmax(dist))
        if dist[i] > tolerance_miles:
            k = a + 1 + i
            keep[k] = True
            stack.append((a, k))
            stack.append((k, b))
    return np.nonzero(keep)[0]
