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

    def __str__(self):
        return f"{self.truckstop_name} - {self.city}, {self.state}"