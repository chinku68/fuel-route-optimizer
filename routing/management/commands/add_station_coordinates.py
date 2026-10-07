import csv
from math import isfinite
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from routing.fuel_service import US_STATES
from routing.models import FuelStation


class Command(BaseCommand):
    help = "Add approximate city coordinates and label existing city-based USA station locations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cities-file", type=Path, default=settings.BASE_DIR / "data/us_cities.csv"
        )

    def handle(self, *args, **options):
        csv_path = options["cities_file"]
        if not csv_path.exists():
            raise CommandError(f"City-coordinate file not found: {csv_path}")
        city_coordinates = {}
        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            required = {"CITY", "STATE_CODE", "LATITUDE", "LONGITUDE"}
            if not required.issubset(reader.fieldnames or []):
                raise CommandError("City CSV is missing required coordinate columns.")
            for row in reader:
                try:
                    latitude = float(row["LATITUDE"])
                    longitude = float(row["LONGITUDE"])
                except (ValueError, TypeError):
                    continue
                if not (isfinite(latitude) and isfinite(longitude)):
                    continue
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    continue
                key = (row["CITY"].strip().casefold(), row["STATE_CODE"].strip().upper())
                city_coordinates[key] = (latitude, longitude)

        filled = labeled = 0
        updates = []
        stations = FuelStation.objects.filter(state__in=US_STATES).exclude(
            coordinate_quality__in=["address", "venue"]
        )
        for station in stations.iterator(chunk_size=1000):
            coordinates = city_coordinates.get((station.city.strip().casefold(), station.state))
            if not coordinates:
                continue
            missing = station.latitude is None or station.longitude is None
            is_city = (
                not missing
                and abs(station.latitude - coordinates[0]) < 0.000001
                and abs(station.longitude - coordinates[1]) < 0.000001
            )
            if missing:
                station.latitude, station.longitude = coordinates
                filled += 1
            elif not is_city:
                # Preserve independently geocoded coordinates as unverified.
                continue
            if not missing and station.coordinate_quality == "city" and station.coordinate_source == "local/us_cities.csv":
                continue
            station.coordinate_quality = "city"
            station.coordinate_source = "local/us_cities.csv"
            station.geocode_confidence = None
            updates.append(station)
            labeled += 1
            if len(updates) >= 1000:
                self.save_batch(updates)
                updates = []
        self.save_batch(updates)
        self.stdout.write(f"Filled missing USA coordinates: {filled}; labeled city locations: {labeled}.")
        for row in FuelStation.objects.filter(state__in=US_STATES).values(
            "coordinate_quality"
        ).annotate(count=Count("pk")).order_by("coordinate_quality"):
            self.stdout.write(f"{row['coordinate_quality']}: {row['count']}")

    def save_batch(self, stations):
        if stations:
            FuelStation.objects.bulk_update(stations, [
                "latitude", "longitude", "coordinate_quality",
                "coordinate_source", "geocode_confidence",
            ], batch_size=1000)
