from math import radians, sin, cos, sqrt, asin

from routing.models import FuelStation


US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE",
    "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC"
}


def haversine_miles(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two latitude/longitude
    points in miles.
    """

    earth_radius = 3958.8

    lat1 = radians(lat1)
    lon1 = radians(lon1)
    lat2 = radians(lat2)
    lon2 = radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    return 2 * earth_radius * asin(sqrt(a))


def build_route_samples(
    route_coordinates,
    interval_miles=5
):
    """
    Reduce thousands of route coordinates into
    points roughly every 5 miles.

    Also keep track of distance from start.
    """

    if not route_coordinates:
        return []

    first_lon, first_lat = route_coordinates[0]

    samples = [
        {
            "latitude": first_lat,
            "longitude": first_lon,
            "route_mile": 0.0,
        }
    ]

    total_distance = 0.0
    distance_since_sample = 0.0

    previous_lon = first_lon
    previous_lat = first_lat

    for longitude, latitude in route_coordinates[1:]:

        segment_distance = haversine_miles(
            previous_lat,
            previous_lon,
            latitude,
            longitude,
        )

        total_distance += segment_distance
        distance_since_sample += segment_distance

        if distance_since_sample >= interval_miles:

            samples.append(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "route_mile": total_distance,
                }
            )

            distance_since_sample = 0.0

        previous_lat = latitude
        previous_lon = longitude

    last_lon, last_lat = route_coordinates[-1]

    samples.append(
        {
            "latitude": last_lat,
            "longitude": last_lon,
            "route_mile": total_distance,
        }
    )

    return samples


def find_stations_near_route(
    route_geometry,
    corridor_miles=20
):
    """
    Find fuel stations close to the route.
    """

    route_coordinates = route_geometry["coordinates"]

    samples = build_route_samples(
        route_coordinates,
        interval_miles=5
    )

    # Route bounding box
    latitudes = [
        coordinate[1]
        for coordinate in route_coordinates
    ]

    longitudes = [
        coordinate[0]
        for coordinate in route_coordinates
    ]

    # Rough bounding-box margin.
    margin = 0.75

    stations = FuelStation.objects.filter(
        state__in=US_STATES,

        latitude__isnull=False,
        longitude__isnull=False,

        latitude__gte=min(latitudes) - margin,
        latitude__lte=max(latitudes) + margin,

        longitude__gte=min(longitudes) - margin,
        longitude__lte=max(longitudes) + margin,
    )

    candidates = []

    for station in stations:

        nearest_distance = None
        nearest_route_mile = None

        for sample in samples:

            distance = haversine_miles(
                station.latitude,
                station.longitude,
                sample["latitude"],
                sample["longitude"],
            )

            if (
                nearest_distance is None
                or distance < nearest_distance
            ):
                nearest_distance = distance

                nearest_route_mile = sample[
                    "route_mile"
                ]

        if nearest_distance <= corridor_miles:

            candidates.append(
                {
                    "id": station.id,

                    "name": station.truckstop_name,

                    "address": station.address,

                    "city": station.city,

                    "state": station.state,

                    "price": float(
                        station.retail_price
                    ),

                    "latitude": station.latitude,

                    "longitude": station.longitude,

                    "distance_from_route_miles": round(
                        nearest_distance,
                        2
                    ),

                    "route_mile": round(
                        nearest_route_mile,
                        2
                    ),
                }
            )

    # Sort stations from start → destination
    candidates.sort(
        key=lambda station: station["route_mile"]
    )

    return candidates