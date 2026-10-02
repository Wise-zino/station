"""In-memory snapshot of geocoded stations, loaded once per process.

6-7k rows is tiny, so we pay one DB query on first use and every request after that is pure numpy.
Call reset_station_index() after re-loading/geocoding data (or just restart the server).
"""
import threading
from dataclasses import dataclass

import numpy as np

from routing.geo import to_xyz
from stations.models import Station


@dataclass
class StationIndex:
    ids: list
    names: list
    addresses: list
    cities: list
    states: list
    price: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    xyz: np.ndarray

    def __len__(self):
        return len(self.ids)


_lock = threading.Lock()
_index = None


def _load() -> StationIndex:
    rows = list(Station.objects.filter(lat__isnull=False, lon__isnull=False)
                .values_list("id", "name", "address", "city", "state", "price", "lat", "lon"))
    lat = np.array([r[6] for r in rows], dtype=float)
    lon = np.array([r[7] for r in rows], dtype=float)
    return StationIndex(
        ids=[r[0] for r in rows], names=[r[1] for r in rows], addresses=[r[2] for r in rows],
        cities=[r[3] for r in rows], states=[r[4] for r in rows],
        price=np.array([float(r[5]) for r in rows], dtype=float),
        lat=lat, lon=lon,
        xyz=to_xyz(lat, lon) if len(rows) else np.empty((0, 3)),
    )


def get_station_index() -> StationIndex:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = _load()
    return _index


def reset_station_index():
    global _index
    with _lock:
        _index = None
