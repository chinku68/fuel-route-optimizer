MAX_RANGE_MILES = 500
MPG = 10

# We prefer to refuel in the later part of the available range.
# This prevents unnecessary stops every 100-200 miles.
PREFERRED_RANGE_RATIO = 0.70

# Small penalty for stations far away from the route.
DETOUR_PRICE_PENALTY = 0.02


def optimize_fuel_stops(
    candidate_stations,
    total_distance_miles,
    max_range=MAX_RANGE_MILES,
    mpg=MPG,
):
    """
    Select cost-effective fuel stops while ensuring
    no leg exceeds the vehicle's maximum range.
    """

    stations = sorted(
        candidate_stations,
        key=lambda station: station["route_mile"],
    )

    if not stations:
        if total_distance_miles <= max_range:
            return {
                "fuel_stops": [],
                "total_gallons": round(total_distance_miles / mpg, 2),
                "total_fuel_cost": None,
                "message": (
                    "Destination is within one tank range, "
                    "but no fuel price was available near the route."
                ),
            }

        raise ValueError("No fuel stations were found near the route.")

    # -------------------------------------------------
    # Find a fuel-price reference near the start
    # -------------------------------------------------

    start_candidates = [
        station
        for station in stations
        if station["route_mile"] <= 25
    ]

    if not start_candidates:
        start_candidates = stations[:10]

    start_station = min(
        start_candidates,
        key=lambda station: (
            station["price"]
            + (
                station["distance_from_route_miles"]
                * DETOUR_PRICE_PENALTY
            )
        ),
    )

    # -------------------------------------------------
    # If destination is within one 500-mile tank
    # -------------------------------------------------

    if total_distance_miles <= max_range:
        gallons = total_distance_miles / mpg
        total_cost = gallons * start_station["price"]

        return {
            "starting_fuel_reference": {
                "name": start_station["name"],
                "city": start_station["city"],
                "state": start_station["state"],
                "price_per_gallon": start_station["price"],
            },
            "fuel_stops": [],
            "number_of_fuel_stops": 0,
            "total_gallons": round(gallons, 2),
            "total_fuel_cost": round(total_cost, 2),
            "vehicle_range_miles": max_range,
            "fuel_efficiency_mpg": mpg,
        }

    # -------------------------------------------------
    # Identify stations that can eventually reach
    # the destination using <= 500-mile legs.
    # -------------------------------------------------

    station_count = len(stations)

    can_reach_destination = [False] * station_count

    for i in range(
        station_count - 1,
        -1,
        -1,
    ):
        current_mile = stations[i]["route_mile"]

        # Can directly reach destination
        if total_distance_miles - current_mile <= max_range:
            can_reach_destination[i] = True
            continue

        # Otherwise check whether another viable
        # station is reachable within 500 miles.
        for j in range(
            i + 1,
            station_count,
        ):
            gap = stations[j]["route_mile"] - current_mile

            if gap > max_range:
                break

            if can_reach_destination[j]:
                can_reach_destination[i] = True
                break

    # -------------------------------------------------
    # Select fuel stops
    # -------------------------------------------------

    selected_stops = []
    current_mile = 0.0

    while total_distance_miles - current_mile > max_range:
        maximum_reachable = current_mile + max_range

        preferred_start = (
            current_mile
            + (max_range * PREFERRED_RANGE_RATIO)
        )

        reachable = []

        for index, station in enumerate(stations):
            station_mile = station["route_mile"]

            if station_mile <= current_mile + 5:
                continue

            if station_mile > maximum_reachable:
                break

            if can_reach_destination[index]:
                reachable.append(station)

        if not reachable:
            raise ValueError(
                (
                    "Could not build a valid fuel plan. "
                    f"No usable station found within "
                    f"{max_range} miles after mile "
                    f"{round(current_mile, 2)}."
                )
            )

        # Prefer stations in the last 30% of our
        # available range.
        preferred = [
            station
            for station in reachable
            if station["route_mile"] >= preferred_start
        ]

        selection_pool = preferred if preferred else reachable

        # Cheapest station while applying a small
        # penalty for detouring away from the route.
        best_station = min(
            selection_pool,
            key=lambda station: (
                station["price"]
                + (
                    station["distance_from_route_miles"]
                    * DETOUR_PRICE_PENALTY
                ),
                -station["route_mile"],
            ),
        )

        selected_stops.append(best_station)
        current_mile = best_station["route_mile"]

    # -------------------------------------------------
    # Calculate trip fuel cost
    # -------------------------------------------------

    fuel_stops = []
    total_cost = 0.0
    total_gallons = 0.0

    previous_mile = 0.0
    previous_price = start_station["price"]

    for stop in selected_stops:
        leg_distance = stop["route_mile"] - previous_mile
        gallons = leg_distance / mpg
        leg_cost = gallons * previous_price

        total_gallons += gallons
        total_cost += leg_cost

        fuel_stops.append(
            {
                "name": stop["name"],
                "address": stop["address"],
                "city": stop["city"],
                "state": stop["state"],
                "latitude": stop["latitude"],
                "longitude": stop["longitude"],
                "route_mile": round(stop["route_mile"], 2),
                "distance_from_route_miles": round(
                    stop["distance_from_route_miles"],
                    2,
                ),
                "price_per_gallon": round(stop["price"], 3),
            }
        )

        previous_mile = stop["route_mile"]
        previous_price = stop["price"]

    # Final leg: last stop -> destination
    final_leg_distance = total_distance_miles - previous_mile
    final_gallons = final_leg_distance / mpg
    final_cost = final_gallons * previous_price

    total_gallons += final_gallons
    total_cost += final_cost

    return {
        "starting_fuel_reference": {
            "name": start_station["name"],
            "city": start_station["city"],
            "state": start_station["state"],
            "price_per_gallon": round(
                start_station["price"],
                3,
            ),
        },
        "fuel_stops": fuel_stops,
        "number_of_fuel_stops": len(fuel_stops),
        "total_gallons": round(total_gallons, 2),
        "total_fuel_cost": round(total_cost, 2),
        "vehicle_range_miles": max_range,
        "fuel_efficiency_mpg": mpg,
    }
