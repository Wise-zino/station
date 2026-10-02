import csv
import statistics
from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_UP

from .constants import US_STATES

PRICE_STRATEGIES = {
    "min": min,
    "mean": lambda xs: sum(xs) / len(xs),
    "median": statistics.median,
}
_CENT4 = Decimal("0.0001")


def _norm(value: str) -> str:
    return " ".join((value or "").split())


def clean_stations(path, price_strategy="mean"):
    """Return (stations, stats). `stations` is a list of dicts, one per OPIS truckstop ID."""
    if price_strategy not in PRICE_STRATEGIES:
        raise ValueError(f"price_strategy must be one of {sorted(PRICE_STRATEGIES)}")
    combine = PRICE_STRATEGIES[price_strategy]

    stats = {"rows": 0, "non_us_dropped": 0, "bad_rows_dropped": 0, "duplicate_rows_merged": 0}
    grouped = OrderedDict()

    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            stats["rows"] += 1
            state = _norm(row.get("State")).upper()
            if state not in US_STATES:
                stats["non_us_dropped"] += 1
                continue
            try:
                opis_id = int(row["OPIS Truckstop ID"])
                price = Decimal(_norm(row["Retail Price"]))
            except (KeyError, ValueError, ArithmeticError):
                stats["bad_rows_dropped"] += 1
                continue
            if price <= 0:
                stats["bad_rows_dropped"] += 1
                continue

            if opis_id in grouped:
                stats["duplicate_rows_merged"] += 1
                grouped[opis_id]["_prices"].append(price)
            else:
                grouped[opis_id] = {
                    "opis_id": opis_id,
                    "name": _norm(row.get("Truckstop Name")),
                    "address": _norm(row.get("Address")),
                    "city": _norm(row.get("City")),
                    "state": state,
                    "_prices": [price],
                }

    stations = []
    for rec in grouped.values():
        prices = rec.pop("_prices")
        rec["price"] = Decimal(combine(prices)).quantize(_CENT4, rounding=ROUND_HALF_UP)
        stations.append(rec)

    stats["stations"] = len(stations)
    stats["unique_cities"] = len({(s["city"], s["state"]) for s in stations})
    return stations, stats
