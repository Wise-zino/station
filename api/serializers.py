from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=200, help_text='Start location in the USA: "Chicago, IL" or "41.88,-87.63" (lat,lon).')
    finish = serializers.CharField(
        max_length=200, help_text='Finish location in the USA: "Dallas, TX" or "32.78,-96.80" (lat,lon).')


class LocationSerializer(serializers.Serializer):
    query = serializers.CharField()
    label = serializers.CharField()
    lat = serializers.FloatField()
    lon = serializers.FloatField()


class RouteSerializer(serializers.Serializer):
    distance_miles = serializers.FloatField()
    duration_hours = serializers.FloatField()
    geometry = serializers.DictField(help_text="GeoJSON LineString ([lon, lat] pairs), simplified for display.")


class FuelStopSerializer(serializers.Serializer):
    order = serializers.IntegerField()
    kind = serializers.ChoiceField(
        choices=["origin", "station"],
        help_text='"origin" = the departure fill-up at the start; "station" = a stop along the route.')
    name = serializers.CharField()
    address = serializers.CharField(allow_blank=True)
    city = serializers.CharField(allow_blank=True)
    state = serializers.CharField(allow_blank=True)
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    route_mile = serializers.FloatField(help_text="Miles from the start.")
    miles_off_route = serializers.FloatField(help_text="Straight-line distance from the route.")
    price_per_gallon = serializers.FloatField()
    gallons = serializers.FloatField(help_text="Gallons bought at this stop.")
    cost = serializers.FloatField(help_text="USD spent at this stop.")


class SummarySerializer(serializers.Serializer):
    total_fuel_cost = serializers.FloatField()
    total_gallons = serializers.FloatField()
    stops_count = serializers.IntegerField(help_text="Number of fill-ups, including the departure fill-up.")
    vehicle_range_miles = serializers.IntegerField()
    mpg = serializers.FloatField()
    departure_price_per_gallon = serializers.FloatField()
    departure_price_source = serializers.CharField()


class MetaSerializer(serializers.Serializer):
    external_api_calls = serializers.IntegerField(help_text="Map/routing API calls made for this request.")
    route_cached = serializers.BooleanField()
    timings_ms = serializers.DictField(child=serializers.FloatField())


class RouteResponseSerializer(serializers.Serializer):
    start = LocationSerializer()
    finish = LocationSerializer()
    route = RouteSerializer()
    fuel_stops = FuelStopSerializer(many=True)
    summary = SummarySerializer()
    map_url = serializers.URLField(help_text="Open in a browser for an interactive map of this result.")
    meta = MetaSerializer()


class ErrorBodySerializer(serializers.Serializer):
    type = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField(required=False)


class ErrorSerializer(serializers.Serializer):
    error = ErrorBodySerializer()
