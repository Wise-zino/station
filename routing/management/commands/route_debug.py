import time

from django.core.management.base import BaseCommand

from routing.exceptions import RoutingServiceError
from routing.service import get_route


class Command(BaseCommand):
    help = 'Smoke-test routing: manage.py route_debug "Chicago, IL" "Dallas, TX"  (or "41.88,-87.63" "32.78,-96.8")'

    def add_arguments(self, parser):
        parser.add_argument("start")
        parser.add_argument("finish")

    def handle(self, *args, **opts):
        for attempt in ("cold", "warm"):
            t0 = time.perf_counter()
            try:
                r = get_route(opts["start"], opts["finish"])
            except RoutingServiceError as exc:
                self.stderr.write(f"{type(exc).__name__}: {exc}")
                return
            ms = (time.perf_counter() - t0) * 1000
            self.stdout.write(
                f"[{attempt}] {r.total_miles:,.1f} mi | {r.duration_s / 3600:.1f} h | {len(r.lats):,} vertices | "
                f"{r.api_calls} external call(s) | cached={r.cached} | {ms:.0f} ms"
            )
