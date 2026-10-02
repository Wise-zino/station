from routing.exceptions import RoutingServiceError


class PlanningError(RoutingServiceError):
    """Route is fine, but no valid fuel plan exists (e.g. a >500 mile gap with no station)."""
    status_code = 422
