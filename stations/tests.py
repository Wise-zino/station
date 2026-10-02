import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from .loader import clean_stations
from .models import Station

CSV = """OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price
1,PILOT TRAVEL CENTER #1,"I-8,  EXIT 119",Gila Bend   ,AZ,930,3.000
1,PILOT #1,"I-8, EXIT 119",Gila Bend,AZ,930,4.000
2,TA SAGINAW,I-75 EXIT 144,Bridgeport,MI,260,3.200
3,PETRO-CANADA,HWY 1,Calgary,AB,1,1.900
4,BAD ROW,US-1,Nowhere,TX,1,not-a-price
"""


def write_csv(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    f.write(text)
    f.close()
    return f.name


class CleanStationsTests(TestCase):
    def test_drops_canada_bad_rows_and_merges_duplicates(self):
        rows, stats = clean_stations(write_csv(CSV))
        self.assertEqual([r["opis_id"] for r in rows], [1, 2])
        self.assertEqual(stats["non_us_dropped"], 1)
        self.assertEqual(stats["bad_rows_dropped"], 1)
        self.assertEqual(stats["duplicate_rows_merged"], 1)

    def test_whitespace_is_normalised(self):
        rows, _ = clean_stations(write_csv(CSV))
        self.assertEqual(rows[0]["city"], "Gila Bend")
        self.assertEqual(rows[0]["address"], "I-8, EXIT 119")

    def test_price_strategies(self):
        path = write_csv(CSV)
        self.assertEqual(clean_stations(path, "mean")[0][0]["price"], Decimal("3.5000"))
        self.assertEqual(clean_stations(path, "min")[0][0]["price"], Decimal("3.0000"))
        self.assertEqual(clean_stations(path, "median")[0][0]["price"], Decimal("3.5000"))

    def test_unknown_strategy_rejected(self):
        with self.assertRaises(ValueError):
            clean_stations(write_csv(CSV), "max")


class LoadCommandTests(TestCase):
    def test_load_is_idempotent_and_keeps_coordinates(self):
        path = write_csv(CSV)
        call_command("load_stations", csv=path, stdout=mock.MagicMock())
        Station.objects.filter(opis_id=1).update(lat=32.9, lon=-112.7)
        call_command("load_stations", csv=path, stdout=mock.MagicMock())
        self.assertEqual(Station.objects.count(), 2)
        s = Station.objects.get(opis_id=1)
        self.assertEqual((s.lat, s.lon), (32.9, -112.7))


class GeocodeCommandTests(TestCase):
    def setUp(self):
        call_command("load_stations", csv=write_csv(CSV), stdout=mock.MagicMock())
        self.cache = Path(tempfile.mkdtemp()) / "cache.json"

    def _resp(self, payload):
        r = mock.MagicMock()
        r.json.return_value = payload
        r.raise_for_status.return_value = None
        return r

    def test_geocodes_once_per_city_and_applies(self):
        hits = {"Gila Bend": [{"lat": "32.9484", "lon": "-112.7168"}],
                "Bridgeport": [{"lat": "43.3573", "lon": "-83.8686"}]}

        def fake_get(url, params, **kw):
            return self._resp(hits[params["city"]])

        with override_settings(GEOCODE_CACHE_PATH=self.cache), \
             mock.patch("stations.management.commands.geocode_stations.requests.Session.get", side_effect=fake_get) as g:
            call_command("geocode_stations", delay=0, stdout=mock.MagicMock())
            self.assertEqual(g.call_count, 2)
            # second run: fully cached, no network
            call_command("geocode_stations", delay=0, stdout=mock.MagicMock())
            self.assertEqual(g.call_count, 2)

        self.assertEqual(Station.objects.filter(lat__isnull=True).count(), 0)
        self.assertIn("Gila Bend|AZ", json.loads(self.cache.read_text()))

    def test_out_of_us_hits_are_rejected(self):
        with override_settings(GEOCODE_CACHE_PATH=self.cache), \
             mock.patch("stations.management.commands.geocode_stations.requests.Session.get",
                        return_value=self._resp([{"lat": "51.5", "lon": "-0.12"}])):  # London
            call_command("geocode_stations", delay=0, stdout=mock.MagicMock())
        self.assertEqual(Station.objects.filter(lat__isnull=False).count(), 0)
