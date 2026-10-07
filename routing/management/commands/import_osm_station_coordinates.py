from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from routing.fuel_service import US_STATES
from routing.osm_coordinate_import import import_osm_matches, load_osm_extract


class Command(BaseCommand):
    help = "Match downloaded OSM fuel-station data by brand, branch number, city and state."

    def add_arguments(self, parser):
        parser.add_argument("--input", type=Path, required=True, help="Overpass JSON with tags and node coordinates/way centers.")
        parser.add_argument("--dry-run", action="store_true", help="Show matches without updating stations.")
        parser.add_argument("--limit", type=int, default=25, help="Maximum station records to update.")
        parser.add_argument("--state", help="Only import matches for this USA state code.")

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit must be positive.")
        state = options["state"].upper() if options["state"] else None
        if state and state not in US_STATES:
            raise CommandError("--state must be a valid USA state code.")

        def report_match(station, result):
            self.stdout.write(
                f"OPIS {station.opis_truckstop_id}: {station.truckstop_name}, "
                f"{station.city}, {station.state} -> {result['source']}"
            )

        try:
            matched = import_osm_matches(
                load_osm_extract(options["input"]), state=state, limit=options["limit"],
                dry_run=options["dry_run"], on_match=report_match,
            )
        except ValueError as error:
            raise CommandError(str(error)) from None
        action = "Would update" if options["dry_run"] else "Updated"
        self.stdout.write(f"{action}: {matched} station records. API calls: 0.")
