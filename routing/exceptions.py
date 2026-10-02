class RoutingServiceError(Exception):
    """Base error class"""
    status_code = 502


class LocationError(RoutingServiceError):
    """The start/finish input couldn't be understood or isn't in the USA."""
    status_code = 400


class RoutingError(RoutingServiceError):
    """The routing provider failed, timed out, or found no drivable route."""
    status_code = 502
