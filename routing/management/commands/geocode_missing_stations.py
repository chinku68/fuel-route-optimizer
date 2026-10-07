import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from routing.fuel_service import US_STATES
from routing.models import FuelStation, StationGeocodeCache
from routing.station_geocoding import search_station, select_station_match, station_queries


class Command(BaseCommand):
    help = "Improve missing, city-based and unverified USA station coordinates in resumable batches."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25, help="Maximum stations to attempt.")
        parser.add_argument("--max-requests", type=int, default=50, help="Hard cap on external calls.")
        parser.add_argument("--state", help="Only process this USA state code.")
        parser.add_argument("--station-id", type=int, help="Only process this OPIS Truckstop ID.")
        parser.add_argument("--retry", action="store_true", help="Retry reviewed stations and refresh cached searches.")
        parser.add_argument("--dry-run", action="store_true", help="Show pending counts without calls or writes.")

    def handle(self, *args, **options):
        if options["limit"] < 1 or options["max_requests"] < 1:
            raise CommandError("--limit and --max-requests must be positive.")
        state = options["state"].upper() if options["state"] else None
        if state and state not in US_STATES:
            raise CommandError("--state must be a valid USA state code.")
        stations = FuelStation.objects.filter(state__in=US_STATES).exclude(
            coordinate_quality__in=["address", "venue"]
        )
        if state:
            stations = stations.filter(state=state)
        if options["station_id"] is not None:
            stations = stations.filter(opis_truckstop_id=options["station_id"])
        if not options["retry"]:
            stations = stations.filter(geocode_checked_at__isnull=True)
        self.stdout.write(f"Pending USA stations: {stations.count()}")
        if options["dry_run"]:
            self.stdout.write(
                f"Would attempt up to {options['limit']} stations; "
                f"external call cap: {options['max_requests']}."
            )
            return
        if not settings.ORS_API_KEY:
            raise CommandError("ORS_API_KEY is missing. Add it to your .env file.")

        calls = accepted = reviewed = 0
        last_request_at = None
        refreshed_queries = set()
        quota_exhausted = False
        for station in stations.order_by("pk")[:options["limit"]]:
            match = None
            message = ""
            for query in station_queries(station):
                key = " ".join(query.casefold().split())
                cached = StationGeocodeCache.objects.filter(query=key).first()
                if cached and (not options["retry"] or key in refreshed_queries):
                    features = cached.features
                else:
                    if calls >= options["max_requests"] or quota_exhausted:
                        self.stdout.write("Request cap or daily quota reached. Run again to resume.")
                        self.stdout.write(f"Accepted: {accepted}; reviewed: {reviewed}; API calls: {calls}.")
                        return
                    if last_request_at is not None:
                        time.sleep(max(0, 1.1 - (time.monotonic() - last_request_at)))
                    last_request_at = time.monotonic()
                    calls += 1
                    try:
                        features, quota = search_station(query)
                    except requests.RequestException as error:
                        code = error.response.status_code if error.response is not None else None
                        # Do not print exceptions: their URLs may include credentials.
                        reason = f"HTTP {code}" if code else "network error"
                        raise CommandError(
                            f"Geocoding stopped ({reason}). Previously accepted stations are saved. "
                            "Check the key, service availability or quota, then rerun."
                        ) from None
                    except ValueError:
                        raise CommandError("Invalid geocoding response; saved progress retained.") from None
                    StationGeocodeCache.objects.update_or_create(
                        query=key, defaults={"features": features}
                    )
                    refreshed_queries.add(key)
                    if quota.get("X-Ratelimit-Remaining") is not None:
                        self.stdout.write(f"Geocoding quota remaining: {quota['X-Ratelimit-Remaining']}")
                        quota_exhausted = str(quota["X-Ratelimit-Remaining"]) == "0"
                try:
                    match = select_station_match(station, features)
                    break
                except ValueError as error:
                    message = str(error)

            if match:
                station.latitude = match["latitude"]
                station.longitude = match["longitude"]
                station.coordinate_quality = match["quality"]
                station.coordinate_source = match["source"]
                station.geocode_confidence = match["confidence"]
                station.geocode_error = ""
                accepted += 1
            else:
                station.geocode_error = message
            station.geocode_checked_at = timezone.now()
            station.save(update_fields=[
                "latitude", "longitude", "coordinate_quality", "coordinate_source",
                "geocode_confidence", "geocode_checked_at", "geocode_error",
            ])
            reviewed += 1
            result = "accepted" if match else "manual review needed"
            self.stdout.write(f"Station {station.opis_truckstop_id}: {result}")

        self.stdout.write(f"Accepted: {accepted}; reviewed: {reviewed}; API calls: {calls}.")
