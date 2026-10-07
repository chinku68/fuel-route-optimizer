import requests
from django.conf import settings


GEOCODE_URL = "https://api.heigit.org/pelias/v1/search"

DIRECTIONS_URL = (
    "https://api.heigit.org/openrouteservice/v2/"
    "directions/driving-car/geojson"
)


def geocode_location(location):
    response = requests.get(
        GEOCODE_URL,
        params={
            "text": location,
            "boundary.country": "US",
            "size": 1,
        },
        headers={
            "Authorization": settings.ORS_API_KEY
        },
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("features"):
        raise ValueError(f"Location not found: {location}")

    feature = data["features"][0]

    return {
        "coordinates": feature["geometry"]["coordinates"],
        "label": feature["properties"].get(
            "label",
            location
        ),
    }


def get_route(start_coordinates, finish_coordinates):
    response = requests.post(
        DIRECTIONS_URL,
        headers={
            "Authorization": settings.ORS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/geo+json",
        },
        json={
            "coordinates": [
                start_coordinates,
                finish_coordinates,
            ]
        },
        timeout=30,
    )

    response.raise_for_status()

    return response.json()