import requests

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import FuelStation
from .serializers import FuelStationSerializer
from .services import geocode_location, get_route
from .fuel_service import find_stations_near_route
from .fuel_optimizer import optimize_fuel_stops
from .map_service import build_map_geojson

@api_view(["GET"])
def health_check(request):
    return Response({
        "status": "success",
        "message": "Fuel Route Optimizer API is running"
    })


@api_view(["GET"])
def fuel_stations(request):
    state = request.GET.get("state")
    city = request.GET.get("city")
    limit = request.GET.get("limit", 20)

    try:
        limit = int(limit)
    except ValueError:
        limit = 20

    stations = FuelStation.objects.all()

    if state:
        stations = stations.filter(
            state__iexact=state
        )

    if city:
        stations = stations.filter(
            city__iexact=city
        )

    stations = stations.order_by(
        "retail_price"
    )[:limit]

    serializer = FuelStationSerializer(
        stations,
        many=True
    )

    return Response({
        "count": len(serializer.data),
        "stations": serializer.data
    })


@api_view(["POST"])
def route_preview(request):
    start = request.data.get("start")
    finish = request.data.get("finish")

    if not start or not finish:
        return Response(
            {
                "error": (
                    "Both start and finish locations "
                    "are required."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # API Call 1:
        # Convert start location into coordinates
        start_location = geocode_location(start)

        # API Call 2:
        # Convert finish location into coordinates
        finish_location = geocode_location(finish)

        # API Call 3:
        # Get actual driving route
        route_data = get_route(
            start_location["coordinates"],
            finish_location["coordinates"],
        )

        feature = route_data["features"][0]

        route_geometry = feature["geometry"]

        summary = feature["properties"]["summary"]

        distance_meters = summary["distance"]
        duration_seconds = summary["duration"]

        distance_miles = (
            distance_meters / 1609.344
        )

        duration_hours = (
            duration_seconds / 3600
        )

        # Find fuel stations near the route
        candidate_stations = find_stations_near_route(
            route_geometry
        )

        fuel_plan = optimize_fuel_stops(
            candidate_stations,
            distance_miles
        )

        map_data = build_map_geojson(
            route_geometry,
            start_location,
            finish_location,
            fuel_plan["fuel_stops"],
        )

        return Response(
            {
                "start": {
                    "input": start,
                    "location": start_location["label"],
                    "coordinates": start_location["coordinates"],
                },
                "finish": {
                    "input": finish,
                    "location": finish_location["label"],
                    "coordinates": finish_location["coordinates"],
                },
                "trip": {
                    "distance_miles": round(
                        distance_miles,
                        2,
                    ),
                    "duration_hours": round(
                        duration_hours,
                        2,
                    ),
                },
                "vehicle": {
                    "maximum_range_miles": 500,
                    "fuel_efficiency_mpg": 10,
                    "tank_capacity_gallons": 50,
                },
                "fuel_summary": {
                    "candidate_station_count": len(candidate_stations),
                    "number_of_fuel_stops": fuel_plan["number_of_fuel_stops"],
                    "total_gallons": fuel_plan["total_gallons"],
                    "total_fuel_cost": fuel_plan["total_fuel_cost"],
                },
                "starting_fuel_reference": fuel_plan["starting_fuel_reference"],
                "fuel_stops": fuel_plan["fuel_stops"],
                "map": map_data,
            }
        )

    except ValueError as error:
        return Response(
            {
                "error": str(error)
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    except requests.RequestException as error:
        return Response(
            {
                "error": "Routing service failed.",
                "details": str(error),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    except (
        KeyError,
        IndexError,
        TypeError
    ) as error:
        return Response(
            {
                "error": "Invalid routing response.",
                "details": str(error),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
