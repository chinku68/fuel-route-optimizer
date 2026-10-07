import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand

from routing.models import FuelStation


class Command(BaseCommand):
    help = "Import fuel station prices from CSV"

    def handle(self, *args, **options):
        csv_path = Path("data/fuel_prices.csv")

        if not csv_path.exists():
            self.stdout.write(
                self.style.ERROR(
                    "CSV file not found at data/fuel_prices.csv"
                )
            )
            return

        stations = []
        skipped = 0

        with open(csv_path, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)

            for row in reader:
                try:
                    retail_price = Decimal(row["Retail Price"].strip())

                    rack_id_value = row["Rack ID"].strip()

                    rack_id = (
                        int(rack_id_value)
                        if rack_id_value
                        else None
                    )

                    station = FuelStation(
                        opis_truckstop_id=int(
                            row["OPIS Truckstop ID"].strip()
                        ),
                        truckstop_name=row[
                            "Truckstop Name"
                        ].strip(),
                        address=row["Address"].strip(),
                        city=row["City"].strip(),
                        state=row["State"].strip(),
                        rack_id=rack_id,
                        retail_price=retail_price,
                    )

                    stations.append(station)

                except (
                    ValueError,
                    InvalidOperation,
                    KeyError,
                    AttributeError,
                ):
                    skipped += 1

        FuelStation.objects.bulk_create(
            stations,
            batch_size=1000
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(stations)} fuel stations"
            )
        )

        if skipped:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {skipped} invalid rows"
                )
            )