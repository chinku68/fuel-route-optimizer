def build_map_geojson(
    route_geometry,
    start_location,
    finish_location,
    fuel_stops,
):
    features = []

    # Route line
    features.append({
        "type": "Feature",
        "properties": {
            "type": "route"
        },
        "geometry": route_geometry,
    })

    # Start marker
    features.append({
        "type": "Feature",
        "properties": {
            "type": "start",
            "label": start_location["label"],
        },
        "geometry": {
            "type": "Point",
            "coordinates": start_location["coordinates"],
        },
    })

    # Fuel stop markers
    for index, stop in enumerate(fuel_stops, start=1):
        features.append({
            "type": "Feature",
            "properties": {
                "type": "fuel_stop",
                "stop_number": index,
                "name": stop["name"],
                "city": stop["city"],
                "state": stop["state"],
                "price_per_gallon": stop["price_per_gallon"],
                "route_mile": stop["route_mile"],
                "coordinate_quality": stop.get("coordinate_quality", "unverified"),
                "coordinate_source": stop.get("coordinate_source", ""),
                "gallons_purchased": stop["gallons_purchased"],
                "cost": stop["cost"],
            },
            "geometry": {
                "type": "Point",
                "coordinates": [
                    stop["longitude"],
                    stop["latitude"],
                ],
            },
        })

    # Destination marker
    features.append({
        "type": "Feature",
        "properties": {
            "type": "finish",
            "label": finish_location["label"],
        },
        "geometry": {
            "type": "Point",
            "coordinates": finish_location["coordinates"],
        },
    })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
