from collections import deque
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


MAX_RANGE_MILES = 500
MPG = 10
START_PRICE_RADIUS_MILES = 25
EPSILON = Decimal("0.000000001")


def number(value, label):
    try:
        if isinstance(value, bool):
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be a finite number.") from None


def rounded(value, places=2):
    return float(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def optimize_fuel_stops(
    candidate_stations,
    total_distance_miles,
    max_range=MAX_RANGE_MILES,
    mpg=MPG,
):
    """Minimize purchases on the supplied fixed route, starting with a full tank.

    At each station, buy just enough to reach the next strictly cheaper station.
    Otherwise fill up and advance to the cheapest reachable station, preferring
    the furthest equal-price option. Buy only enough to finish the final leg.
    Detour road mileage is not yet included in this fixed-route calculation.
    """
    distance = number(total_distance_miles, "Trip distance")
    vehicle_range = number(max_range, "Vehicle range")
    efficiency = number(mpg, "MPG")
    if distance < 0 or vehicle_range <= 0 or efficiency <= 0:
        raise ValueError("Trip distance must be nonnegative; vehicle range and MPG must be positive.")
    capacity = vehicle_range / efficiency

    # At the same sampled route position, only the cheapest station is useful.
    by_position = {}
    for station in candidate_stations:
        if not isinstance(station, dict):
            continue
        try:
            position = number(station.get("route_mile"), "Station route mile")
            price = number(station.get("price"), "Station price")
            detour = number(station.get("distance_from_route_miles", 0), "Station offset")
        except ValueError:
            continue
        if not (0 <= position <= distance) or price <= 0 or detour < 0:
            continue
        item = {
            "station": station, "position": position, "price": price, "detour": detour,
        }
        previous = by_position.get(position)
        if previous is None or (price, detour) < (previous["price"], previous["detour"]):
            by_position[position] = item

    all_stations = sorted(by_position.values(), key=lambda item: item["position"])
    references = [
        item for item in all_stations
        if item["position"] <= START_PRICE_RADIUS_MILES
    ]
    start = min(references, key=lambda item: (item["price"], item["detour"])) if references else None
    stations = [item for item in all_stations if 0 < item["position"] < distance]

    if not stations and distance > vehicle_range + EPSILON:
        raise ValueError("No fuel stations were found near the route.")

    # A missing station cannot be bridged by any fuel-purchasing strategy.
    previous_position = Decimal(0)
    for position in [item["position"] for item in stations] + [distance]:
        if position - previous_position > vehicle_range + EPSILON:
            raise ValueError(
                "Could not build a valid fuel plan. "
                f"No usable station found within {vehicle_range.normalize():f} miles "
                f"after mile {rounded(previous_position)}."
            )
        previous_position = position

    # A zero-price destination makes buying only enough to finish the last leg
    # part of the same rule. The monotonic stack finds next cheaper prices
    # in linear time after sorting.
    points = stations + [{"position": distance, "price": Decimal(0)}]
    next_cheaper = [None] * len(stations)
    stack = []
    for index in range(len(points) - 1, -1, -1):
        while stack and points[stack[-1]]["price"] >= points[index]["price"]:
            stack.pop()
        if index < len(stations) and stack:
            next_index = stack[-1]
            if points[next_index]["position"] - points[index]["position"] <= vehicle_range + EPSILON:
                next_cheaper[index] = next_index
        stack.append(index)

    # Cheapest stations in each forward range window, including the starting
    # tank's window. Equal prices favor the furthest station. A monotonic deque
    # computes every window in linear time; tiny equal-price purchases are
    # avoided by jumping between useful points rather than visiting every one.
    cheapest = []
    window = deque()
    right = 0
    for anchor in range(-1, len(stations)):
        while window and window[0] <= anchor:
            window.popleft()
        position = Decimal(0) if anchor == -1 else stations[anchor]["position"]
        while right < len(stations) and stations[right]["position"] <= position + vehicle_range + EPSILON:
            while window and stations[window[-1]]["price"] >= stations[right]["price"]:
                window.pop()
            window.append(right)
            right += 1
        cheapest.append(window[0] if window else None)

    fuel = capacity
    previous_position = Decimal(0)
    last_purchase_position = Decimal(0)
    purchased = Decimal(0)
    purchase_cost = Decimal(0)
    fuel_stops = []

    index = cheapest[0] if distance > vehicle_range + EPSILON else None
    while index is not None and index < len(stations):
        item = stations[index]
        fuel -= (item["position"] - previous_position) / efficiency
        if fuel < -EPSILON:
            raise ValueError("Fuel plan would run out of fuel before a station.")
        fuel = max(Decimal(0), fuel)
        previous_position = item["position"]

        next_index = next_cheaper[index]
        if next_index is not None:
            target = (points[next_index]["position"] - item["position"]) / efficiency
        else:
            target = capacity
            next_index = cheapest[index + 1]
            if next_index is None:
                raise ValueError("No reachable fuel station after the current stop.")
        target = min(capacity, target)
        gallons = max(Decimal(0), target - fuel)
        if gallons <= EPSILON:
            index = next_index
            continue

        arrival_fuel = fuel
        fuel += gallons
        cost = (gallons * item["price"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        purchased += gallons
        purchase_cost += cost
        station = item["station"]
        fuel_stops.append({
            "id": station.get("id"),
            "name": station["name"],
            "address": station["address"],
            "city": station["city"],
            "state": station["state"],
            "latitude": station["latitude"],
            "longitude": station["longitude"],
            "coordinate_quality": station.get("coordinate_quality", "unverified"),
            "coordinate_source": station.get("coordinate_source", ""),
            "route_mile": rounded(item["position"]),
            "leg_distance_miles": rounded(item["position"] - last_purchase_position),
            "distance_from_route_miles": rounded(item["detour"]),
            "price_per_gallon": rounded(item["price"], 5),
            "fuel_on_arrival_gallons": rounded(arrival_fuel, 6),
            "gallons_purchased": rounded(gallons, 6),
            "fuel_after_refueling_gallons": rounded(fuel, 6),
            "cost": float(cost),
        })
        last_purchase_position = item["position"]
        index = next_index

    fuel -= (distance - previous_position) / efficiency
    if fuel < -EPSILON:
        raise ValueError("Fuel plan would run out of fuel before the destination.")
    fuel = max(Decimal(0), fuel)

    consumed = distance / efficiency
    initial_used = min(capacity, consumed)
    initial_cost = (
        (initial_used * start["price"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if start else (Decimal(0) if initial_used == 0 else None)
    )
    reference = None
    if start:
        station = start["station"]
        reference = {
            "name": station["name"], "city": station["city"], "state": station["state"],
            "price_per_gallon": rounded(start["price"], 5),
            "route_mile": rounded(start["position"]),
            "coordinate_quality": station.get("coordinate_quality", "unverified"),
            "coordinate_source": station.get("coordinate_source", ""),
        }

    result = {
        "starting_fuel_reference": reference,
        "fuel_stops": fuel_stops,
        "number_of_fuel_stops": len(fuel_stops),
        "total_gallons": rounded(consumed),
        "total_gallons_purchased": rounded(purchased, 6),
        "total_refueling_cost": float(purchase_cost),
        "starting_fuel_gallons": rounded(capacity, 6),
        "initial_fuel_used_gallons": rounded(initial_used, 6),
        "starting_fuel_cost_estimate": float(initial_cost) if initial_cost is not None else None,
        "ending_fuel_gallons": rounded(fuel, 6),
        "total_fuel_cost": float(initial_cost + purchase_cost) if initial_cost is not None else None,
        "vehicle_range_miles": float(vehicle_range),
        "fuel_efficiency_mpg": float(efficiency),
        "cost_basis": (
            "Starts with a full tank. total_refueling_cost is money spent buying fuel "
            "during the trip. total_fuel_cost also includes the estimated value of "
            "starting fuel consumed, using a station price within 25 route miles of "
            "the start. Station detour road mileage is excluded."
        ),
    }
    if initial_cost is None:
        result["message"] = (
            "There is no fuel price within 25 route miles of the start. "
            "Total fuel cost cannot be estimated; total_refueling_cost covers "
            "fuel purchases during the trip. The plan assumes a full starting fuel tank."
        )
    return result
