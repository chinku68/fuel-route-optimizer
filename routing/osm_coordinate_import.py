"""Shared local import and validated downloads for preparation, outside route requests."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
from django.utils import timezone

from .fuel_service import US_STATES
from .models import FuelStation
from .osm_station_matching import build_osm_index, match_osm_station


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024


def validate_osm_extract(data):
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise ValueError("OSM JSON must contain an elements list.")
    if data.get("remark"):
        raise ValueError("OSM extract reports an error; use a complete successful download.")
    return data


def load_osm_extract(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("Cannot read valid OSM JSON from --input.") from None
    return validate_osm_extract(data)


def import_osm_matches(data, *, state=None, limit=10000, dry_run=False, on_match=None):
    if state is not None and state not in US_STATES:
        raise ValueError("State must be a valid USA state code.")
    if limit < 1:
        raise ValueError("Import limit must be positive.")
    index = build_osm_index(validate_osm_extract(data)["elements"])
    stations = FuelStation.objects.filter(state__in=US_STATES).exclude(
        coordinate_quality__in=["address", "venue"]
    )
    if state is not None:
        stations = stations.filter(state=state)
    matched = 0
    for station in stations.order_by("pk").iterator(chunk_size=1000):
        result = match_osm_station(station, index)
        if result is None:
            continue
        if not dry_run:
            station.latitude = result["latitude"]
            station.longitude = result["longitude"]
            station.coordinate_quality = "venue"
            station.coordinate_source = result["source"]
            station.geocode_confidence = None
            station.geocode_checked_at = timezone.now()
            station.geocode_error = ""
            station.save(update_fields=[
                "latitude", "longitude", "coordinate_quality", "coordinate_source",
                "geocode_confidence", "geocode_checked_at", "geocode_error",
            ])
        matched += 1
        if on_match is not None:
            on_match(station, result)
        if matched >= limit:
            break
    return matched


def state_query(state):
    if state not in US_STATES:
        raise ValueError("State must be a valid USA state code.")
    return (
        '[out:json][timeout:60][maxsize:67108864];\n'
        f'area["ISO3166-2"="US-{state}"]->.state;\n'
        'nwr["amenity"="fuel"](area.state);\n'
        'out center tags;'
    )


def download_state_extract(state, path):
    """One request, no automatic retries; invalid or partial data is never cached."""
    query = state_query(state)
    with requests.post(
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": "FuelRouteOptimizer/1.0 (station-coordinate-preparation)",
                 "Accept": "application/json"},
        timeout=(10, 75), stream=True,
    ) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            body.extend(chunk)
            if len(body) > MAX_DOWNLOAD_BYTES:
                raise ValueError("OSM download exceeded the 32 MB limit; no file was saved.")
    try:
        data = validate_osm_extract(json.loads(body))
    except (UnicodeError, ValueError) as error:
        raise ValueError(f"Invalid OSM download: {error}") from None

    # A complete JSON file is written atomically, so interruptions can be resumed.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=f".{state}-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return data
