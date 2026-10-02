from django.core.management.base import BaseCommand

from planner.service import plan_trip
from routing.exceptions import RoutingServiceError


class Command(BaseCommand):
    help = 'End-to-end smoke test: manage.py plan_debug "New York, NY" "Los Angeles, CA"'

    def add_arguments(self, parser):
        parser.add_argument("start")
        parser.add_argument("finish")

    def handle(self, *args, **opts):
        try:
            p = plan_trip(opts["start"], opts["finish"])
        except RoutingServiceError as exc:
            self.stderr.write(f"{type(exc).__name__}: {exc}")
            return
        w = self.stdout.write
        w(f"{p.total_miles:,.1f} mi | {p.total_gallons:,.1f} gal | ${p.total_cost:,.2f} total | "
          f"{len(p.stops)} fill-ups | route calls={p.route.api_calls} cached={p.route.cached}")
        w(f"start price ${p.start_fuel_price} <- {p.start_price_source}")
        for s in p.stops:
            w(f"  mile {s.route_mile:>7,.1f}  ${s.price_per_gallon:.3f}  {s.gallons:>6.2f} gal  ${s.cost:>8.2f}  "
              f"{s.name}" + (f" ({s.city}, {s.state}, {s.miles_off_route} mi off route)" if s.kind == 'station' else ""))
        w(f"timings ms: {p.timings_ms}")
