"""Conservative matching of a downloaded OSM fuel-station extract."""

from math import isfinite
import re

from .fuel_service import US_STATES, haversine_miles
from .station_geocoding import normalize


def brand_name(value):
    tokens = normalize(re.sub(r"#\s*\d+\b", "", str(value))).split()
    generic = {"the", "travel", "center", "centre", "truck", "stop", "plaza", "station"}
    return "".join(token for token in tokens if token not in generic)


def build_osm_index(elements):
    index = {}
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        if not isinstance(tags, dict) or tags.get("amenity") != "fuel":
            continue
        state = str(tags.get("addr:state", "")).upper()
        city = normalize(tags.get("addr:city", ""))
        country = str(tags.get("addr:country", "US")).upper()
        ref = str(tags.get("ref", "")).strip()
        if state not in US_STATES or not city or country not in {"US", "USA"}:
            continue
        if not re.fullmatch(r"\d+", ref):
            continue
        if element.get("type") == "node":
            coordinates = element
        elif element.get("type") in {"way", "relation"}:
            coordinates = element.get("center") or {}
        else:
            continue
        if not isinstance(coordinates, dict):
            continue
        try:
            if any(isinstance(coordinates.get(key), bool) for key in ("lat", "lon")):
                continue
            latitude, longitude = float(coordinates["lat"]), float(coordinates["lon"])
            osm_id = int(element["id"])
        except (KeyError, ValueError, TypeError):
            continue
        if not (isfinite(latitude) and isfinite(longitude)) or osm_id <= 0:
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        match = {
            "latitude": latitude, "longitude": longitude,
            "source": f"openstreetmap:{element['type']}/{osm_id}",
        }
        brands = {brand_name(tags.get(key, "")) for key in ("brand", "name", "operator")}
        for brand in brands - {""}:
            key = (state, city, brand, int(ref))
            index.setdefault(key, []).append(match)
    return index


def match_osm_station(station, index):
    # OPIS IDs identify CSV records, not chain branches. Compare the number
    # explicitly present in the business name with OSM's branch ref instead.
    branch = re.search(r"#\s*(\d+)\b", station.truckstop_name)
    if not branch:
        return None
    name = station.truckstop_name[:branch.start()]
    key = (station.state.upper(), normalize(station.city), brand_name(name), int(branch[1]))
    candidates = index.get(key, [])
    if not candidates:
        return None
    # Reject contradictory mapped locations for the same branch.
    best = candidates[0]
    for candidate in candidates[1:]:
        if haversine_miles(best["latitude"], best["longitude"],
                           candidate["latitude"], candidate["longitude"]) > 0.25:
            return None
    if station.latitude is not None and station.longitude is not None:
        if haversine_miles(station.latitude, station.longitude,
                           best["latitude"], best["longitude"]) > 25:
            return None
    return best
