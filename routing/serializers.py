from rest_framework import serializers
from .models import FuelStation


class FuelStationSerializer(serializers.ModelSerializer):
    class Meta:
        model = FuelStation
        fields = [
            "id",
            "opis_truckstop_id",
            "truckstop_name",
            "address",
            "city",
            "state",
            "rack_id",
            "retail_price",
            "latitude",
            "longitude",
            "coordinate_quality",
            "coordinate_source",
            "geocode_confidence",
            "geocode_checked_at",
            "geocode_error",
        ]
