import math
import time
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from routing.fuel_service import US_STATES
from routing.models import FuelStation
from routing.osm_coordinate_import import (
    download_state_extract, import_osm_matches, load_osm_extract,
)


LEGACY_FILES = {"VA": "osm_virginia.json", "TN": "osm_tennessee.json", "TX": "osm_texas.json"}


class Command(BaseCommand):
    help = "Download and import OSM station locations in cached, resumable USA state batches."

    def add_arguments(self, parser):
        parser.add_argument("--states", nargs="+", help="State codes, e.g. VA TN TX. Default: USA states in the CSV database.")
        parser.add_argument("--max-requests", type=int, default=3, help="Maximum new downloads per run; 0 uses only cached files.")
        parser.add_argument("--cache-dir", type=Path, help="Download directory. Default: data/osm_cache/.")
        parser.add_argument("--pause-seconds", type=float, default=10, help="Delay between downloads, minimum 5 seconds.")
        parser.add_argument("--dry-run", action="store_true", help="Preview cached matches and missing downloads; no calls or writes.")

    def handle(self, *args, **options):
        if options["max_requests"] < 0:
            raise CommandError("--max-requests must be zero or positive.")
        pause = options["pause_seconds"]
        if not math.isfinite(pause) or not 5 <= pause <= 60:
            raise CommandError("--pause-seconds must be between 5 and 60.")
        if options["states"]:
            states = list(dict.fromkeys(state.upper() for state in options["states"]))
            if any(state not in US_STATES for state in states):
                raise CommandError("--states must contain valid USA state codes.")
        else:
            states = sorted(FuelStation.objects.filter(state__in=US_STATES).values_list("state", flat=True).distinct())
        custom_cache = options["cache_dir"] is not None
        cache_dir = options["cache_dir"] or settings.BASE_DIR / "data" / "osm_cache"
        calls = updated = cached = 0
        waiting = []
        last_request_at = None
        failure = None

        for state in states:
            path = cache_dir / f"{state}.json"
            if not custom_cache and not path.exists() and state in LEGACY_FILES:
                legacy = settings.BASE_DIR / "data" / LEGACY_FILES[state]
                if legacy.exists():
                    path = legacy
            try:
                if path.exists():
                    data = load_osm_extract(path)
                    cached += 1
                    label = "cached"
                elif options["dry_run"] or calls >= options["max_requests"]:
                    waiting.append(state)
                    self.stdout.write(f"{state}: download pending")
                    continue
                else:
                    if last_request_at is not None:
                        time.sleep(max(0, pause - (time.monotonic() - last_request_at)))
                    calls += 1
                    last_request_at = time.monotonic()
                    self.stdout.write(f"{state}: downloading ({calls}/{options['max_requests']})", ending="\n")
                    self.stdout.flush()
                    data = download_state_extract(state, path)
                    label = "downloaded"
                matched = import_osm_matches(
                    data, state=state, limit=10000, dry_run=options["dry_run"],
                )
                updated += matched
                action = "would update" if options["dry_run"] else "updated"
                self.stdout.write(f"{state}: {label}; {action} {matched} stations")
            except requests.RequestException as error:
                code = error.response.status_code if error.response is not None else None
                reason = f"HTTP {code}" if code else "network error"
                failure = f"{state}: download stopped ({reason}). Rerun later to resume; saved progress is retained."
                break
            except (OSError, ValueError) as error:
                failure = f"{state}: {error} Saved progress is retained."
                break

        action = "Would update" if options["dry_run"] else "Updated"
        self.stdout.write(f"{action}: {updated} stations; cached files: {cached}; external calls: {calls}.")
        stations = FuelStation.objects.filter(state__in=US_STATES)
        matched_total = stations.filter(coordinate_quality__in=["address", "venue"]).count()
        self.stdout.write(
            f"USA location coverage: {matched_total}/{stations.count()} matched; "
            f"{stations.exclude(coordinate_quality__in=['address', 'venue']).count()} still approximate or unverified."
        )
        if waiting:
            self.stdout.write(f"Downloads pending: {', '.join(waiting)}. Rerun this command to continue.")
        self.stdout.write("Mapped station locations still need road access checks. This command adds no route-request API calls.")
        if failure:
            raise CommandError(failure)
