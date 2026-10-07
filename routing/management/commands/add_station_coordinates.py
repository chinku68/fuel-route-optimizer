import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from routing.models import FuelStation


class Command(BaseCommand):
    help = "Add latitude and longitude to fuel stations"

    def handle(self, *args, **options):

        csv_path = Path("data/us_cities.csv")

        if not csv_path.exists():
            self.stdout.write(
                self.style.ERROR(
                    "data/us_cities.csv not found"
                )
            )
            return

        city_coordinates = {}

        with open(
            csv_path,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:

                city = row["CITY"].strip().lower()
                state = row["STATE_CODE"].strip().upper()

                try:
                    latitude = float(row["LATITUDE"])
                    longitude = float(row["LONGITUDE"])
                except (ValueError, TypeError):
                    continue

                key = (city, state)

                city_coordinates[key] = (
                    latitude,
                    longitude
                )

        stations = FuelStation.objects.filter(
            latitude__isnull=True
        )

        updated = []
        not_found = 0

        for station in stations:

            key = (
                station.city.strip().lower(),
                station.state.strip().upper()
            )

            coordinates = city_coordinates.get(key)

            if coordinates:

                station.latitude = coordinates[0]
                station.longitude = coordinates[1]

                updated.append(station)

            else:
                not_found += 1

        FuelStation.objects.bulk_update(
            updated,
            ["latitude", "longitude"],
            batch_size=1000
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {len(updated)} stations"
            )
        )

        self.stdout.write(
            self.style.WARNING(
                f"Could not match {not_found} stations"
            )
        )