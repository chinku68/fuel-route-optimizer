import requests

from django.core.management.base import BaseCommand

from routing.models import FuelStation
from routing.services import geocode_location


US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE",
    "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC"
}


class Command(BaseCommand):
    help = "Geocode USA fuel stations missing coordinates"

    def handle(self, *args, **options):

        stations = FuelStation.objects.filter(
            state__in=US_STATES,
            latitude__isnull=True
        )

        self.stdout.write(
            f"Missing USA stations: {stations.count()}"
        )

        updated = []
        failed = []

        # Prevent duplicate API calls
        cache = {}

        for station in stations:

            location_text = (
                f"{station.address}, "
                f"{station.city}, "
                f"{station.state}, USA"
            )

            cache_key = location_text.lower()

            try:

                if cache_key in cache:
                    result = cache[cache_key]
                else:
                    result = geocode_location(location_text)
                    cache[cache_key] = result

                longitude, latitude = result["coordinates"]

                station.latitude = latitude
                station.longitude = longitude

                updated.append(station)

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Matched: {station.truckstop_name} "
                        f"- {station.city}, {station.state}"
                    )
                )

            except (
                ValueError,
                requests.RequestException
            ) as error:

                failed.append(station)

                self.stdout.write(
                    self.style.WARNING(
                        f"Failed: {station.truckstop_name} "
                        f"- {station.city}, {station.state} "
                        f"({error})"
                    )
                )

        FuelStation.objects.bulk_update(
            updated,
            [
                "latitude",
                "longitude"
            ],
            batch_size=100
        )

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully updated: {len(updated)}"
            )
        )

        self.stdout.write(
            self.style.WARNING(
                f"Still missing: {len(failed)}"
            )
        )