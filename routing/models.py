from django.db import models


class FuelStation(models.Model):
    opis_truckstop_id = models.IntegerField(db_index=True)

    truckstop_name = models.CharField(max_length=255)

    address = models.CharField(max_length=500)

    city = models.CharField(max_length=100)

    state = models.CharField(max_length=2, db_index=True)

    rack_id = models.IntegerField(
        null=True,
        blank=True
    )

    retail_price = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        db_index=True
    )

    latitude = models.FloatField(
        null=True,
        blank=True
    )

    longitude = models.FloatField(
        null=True,
        blank=True
    )

    class CoordinateQuality(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        CITY = "city", "Approximate city location"
        ADDRESS = "address", "Address-level geocoder match"
        VENUE = "venue", "Station name/branch match"

    coordinate_quality = models.CharField(
        max_length=16, choices=CoordinateQuality.choices,
        default=CoordinateQuality.UNVERIFIED, db_index=True,
    )
    coordinate_source = models.CharField(max_length=64, blank=True)
    geocode_confidence = models.FloatField(null=True, blank=True)
    geocode_checked_at = models.DateTimeField(null=True, blank=True)
    geocode_error = models.TextField(blank=True)

    def __str__(self):
        return f"{self.truckstop_name} - {self.city}, {self.state}"


class StationGeocodeCache(models.Model):
    """Persist station search results so reruns do not repeat API requests."""

    query = models.CharField(max_length=1000, unique=True)
    features = models.JSONField(default=list)
    checked_at = models.DateTimeField(auto_now=True)
