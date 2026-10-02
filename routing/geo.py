import numpy as np

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles. Works on scalars or numpy arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def cumulative_miles(lats, lons):
    """Miles travelled along the polyline at each vertex (first vertex = 0)."""
    seg = haversine_miles(lats[:-1], lons[:-1], lats[1:], lons[1:])
    return np.concatenate(([0.0], np.cumsum(seg)))


def to_xyz(lats, lons):
    """Lat/lon -> 3D points on a sphere (miles). Euclidean distance between these points
    is the chord length, ~equal to the great-circle distance for short hops, with no
    longitude-scaling distortion. Lets a KD-tree do "within N miles" queries correctly."""
    lat, lon = np.radians(lats), np.radians(lons)
    c = np.cos(lat)
    return EARTH_RADIUS_MILES * np.column_stack((c * np.cos(lon), c * np.sin(lon), np.sin(lat)))


def chord_to_arc_miles(chord):
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.minimum(chord / (2 * EARTH_RADIUS_MILES), 1.0))
