from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from stations.loader import PRICE_STRATEGIES, clean_stations
from stations.models import Station


class Command(BaseCommand):
    help = "Clean the OPIS fuel price CSV and upsert it into the Station table (keeps existing lat/lon)."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=str(settings.FUEL_CSV_PATH))
        parser.add_argument("--price-strategy", choices=sorted(PRICE_STRATEGIES), default="mean",
                            help="How to combine multiple prices for the same OPIS ID (default: mean).")

    def handle(self, *args, **opts):
        rows, stats = clean_stations(opts["csv"], opts["price_strategy"])
        objs = [Station(**r) for r in rows]
        with transaction.atomic():
            # update_fields excludes lat/lon so re-loading never wipes geocoding work.
            Station.objects.bulk_create(
                objs, batch_size=500, update_conflicts=True,
                unique_fields=["opis_id"],
                update_fields=["name", "address", "city", "state", "price"],
            )
        self.stdout.write(self.style.SUCCESS(
            f"{stats['rows']} rows read -> {stats['stations']} US stations "
            f"({stats['non_us_dropped']} non-US dropped, {stats['duplicate_rows_merged']} duplicate rows merged, "
            f"{stats['bad_rows_dropped']} bad rows dropped). {stats['unique_cities']} unique cities to geocode."
        ))
