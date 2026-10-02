from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from routing.exceptions import RoutingServiceError


def api_exception_handler(exc, context):
    """Every error is {"error": {"type", "message", ["details"]}} with a meaningful status code."""
    if isinstance(exc, RoutingServiceError):
        return Response({"error": {"type": type(exc).__name__, "message": str(exc)}}, status=exc.status_code)

    response = drf_exception_handler(exc, context)
    if response is not None:
        details = response.data
        message = "Invalid request." if response.status_code == 400 else str(details.get("detail", "Error."))
        body = {"type": type(exc).__name__, "message": message}
        if response.status_code == 400:
            body["details"] = details
        response.data = {"error": body}
    return response
