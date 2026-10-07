"""Station-specific validation; a confidence score alone is insufficient."""

from difflib import SequenceMatcher
from math import isfinite
import re

import requests
from django.conf import settings

from .fuel_service import haversine_miles
from .services import GEOCODE_URL


def normalize(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


def normalize_street(value):
    abbreviations = {
        "n": "north", "s": "south", "e": "east", "w": "west",
        "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
        "st": "street", "rd": "road", "ave": "avenue", "av": "avenue",
        "blvd": "boulevard", "hwy": "highway", "dr": "drive", "ln": "lane",
        "ct": "court", "pkwy": "parkway", "trl": "trail", "cir": "circle",
        "expy": "expressway", "fwy": "freeway", "pl": "place", "ter": "terrace",
    }
    return " ".join(abbreviations.get(token, token) for token in normalize(value).split())


def station_queries(station):
    place = f"{station.city}, {station.state}, USA"
    # Highway exits can be mistaken for street numbers. Search the business
    # name first, then the supplied address separately.
    return [f"{station.truckstop_name}, {place}", f"{station.address}, {place}"]


def search_station(query):
    response = requests.get(
        GEOCODE_URL,
        params={"text": query, "boundary.country": "US", "size": 5},
        headers={"Authorization": settings.ORS_API_KEY},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise ValueError("Geocoder returned an invalid feature collection.")
    # Only cache public geometry and place metadata, never auth headers.
    features = [
        {"geometry": f.get("geometry"), "properties": f.get("properties", {})}
        for f in data["features"] if isinstance(f, dict)
    ]
    quota = {name: response.headers.get(name) for name in (
        "X-Ratelimit-Limit", "X-Ratelimit-Remaining", "X-Ratelimit-Reset",
    )}
    return features, quota


def select_station_match(station, features):
    matches = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        coordinates = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(coordinates, (list, tuple)):
            continue
        try:
            if len(coordinates) != 2 or any(isinstance(n, bool) for n in coordinates):
                continue
            longitude, latitude = map(float, coordinates)
            confidence = float(properties.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if not all(isfinite(n) for n in (longitude, latitude, confidence)):
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        if confidence < 0.8 or confidence > 1:
            continue
        if str(properties.get("country_a", "")).upper() not in {"US", "USA"}:
            continue
        if str(properties.get("region_a", "")).upper() != station.state.upper():
            continue
        cities = [properties.get("locality", ""), properties.get("localadmin", "")]
        if normalize(station.city) not in {normalize(city) for city in cities}:
            continue
        if station.latitude is not None and station.longitude is not None:
            if haversine_miles(station.latitude, station.longitude, latitude, longitude) > 25:
                continue

        if properties.get("layer") == "venue":
            expected = normalize(station.truckstop_name)
            actual = normalize(properties.get("name", ""))
            if not actual or SequenceMatcher(None, expected, actual).ratio() < 0.85:
                continue
            expected_numbers = re.findall(r"\d+", expected)
            if expected_numbers and expected_numbers != re.findall(r"\d+", actual):
                continue
            quality = "venue"
        elif properties.get("layer") == "address":
            house = normalize(properties.get("housenumber", ""))
            street = normalize_street(properties.get("street", ""))
            expected_address = normalize(station.address)
            if not house or not street or not expected_address.startswith(house + " "):
                continue
            expected_street = normalize_street(expected_address[len(house):].strip())
            if SequenceMatcher(None, expected_street, street).ratio() < 0.8:
                continue
            quality = "address"
        else:
            # Reject city and street centroids, including interstate exits.
            continue

        matches.append({
            "latitude": latitude, "longitude": longitude,
            "quality": quality, "confidence": confidence,
            "source": "openrouteservice/pelias",
        })

    if not matches:
        raise ValueError(
            "No confident station/address match in the expected city and state; "
            "existing coordinates retained for manual review."
        )
    matches.sort(key=lambda match: match["confidence"], reverse=True)
    best = matches[0]
    for other in matches[1:]:
        if haversine_miles(best["latitude"], best["longitude"],
                           other["latitude"], other["longitude"]) > 0.25:
            raise ValueError("Multiple station matches disagree; manual review required.")
    return best
