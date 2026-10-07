from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIClient


class RouteFuelPlanTests(SimpleTestCase):
    """Exercise API responses without a database or external API requests."""

    def setUp(self):
        self.client = APIClient()
        self.route_geometry = {
            "type": "LineString",
            "coordinates": [[-96.8, 32.8], [-97.7, 30.3]],
        }
        self.geocode = self.mock_service("geocode_location")
        self.geocode.side_effect = [
            {"coordinates": [-96.8, 32.8], "label": "Dallas, TX, USA"},
            {"coordinates": [-97.7, 30.3], "label": "Austin, TX, USA"},
        ]
        self.get_route = self.mock_service("get_route")
        self.find_stations = self.mock_service("find_stations_near_route")
        self.find_stations.return_value = []

    def mock_service(self, name):
        patcher = patch(f"routing.views.{name}")
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def request_route(self, miles):
        self.get_route.return_value = {
            "features": [{
                "geometry": self.route_geometry,
                "properties": {
                    "summary": {"distance": miles * 1609.344, "duration": 3600},
                },
            }],
        }
        return self.client.post(
            "/api/route/",
            {"start": "Dallas, TX", "finish": "Austin, TX"},
            format="json",
        )

    def station(self, route_mile):
        return {
            "id": 1,
            "name": "Test fuel station",
            "address": "123 Main Street",
            "city": "Dallas",
            "state": "TX",
            "price": 3.0,
            "latitude": 32.8,
            "longitude": -96.8,
            "route_mile": route_mile,
            "distance_from_route_miles": 0.0,
        }

    def test_short_trip_without_stations_returns_route_and_unknown_cost(self):
        response = self.request_route(100)

        self.assertEqual(response.status_code, 200)
        summary = response.data["fuel_summary"]
        self.assertEqual(summary["candidate_station_count"], 0)
        self.assertEqual(summary["number_of_fuel_stops"], 0)
        self.assertEqual(summary["total_gallons"], 10.0)
        self.assertIsNone(summary["total_fuel_cost"])
        self.assertEqual(summary["total_refueling_cost"], 0.0)
        self.assertEqual(summary["ending_fuel_gallons"], 40.0)
        self.assertIn("no fuel price", summary["message"])
        self.assertIn("starting fuel", summary["message"])
        self.assertIsNone(response.data["starting_fuel_reference"])
        self.assertEqual(response.data["fuel_stops"], [])
        features = response.data["map"]["features"]
        self.assertEqual(
            [feature["properties"]["type"] for feature in features],
            ["route", "start", "finish"],
        )
        self.assertEqual(features[0]["geometry"], self.route_geometry)
        self.assertEqual(self.geocode.call_count, 2)
        self.get_route.assert_called_once()

    def test_exactly_one_tank_without_stations_succeeds(self):
        response = self.request_route(500)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["fuel_summary"]["total_gallons"], 50.0)
        self.assertIsNone(response.data["fuel_summary"]["total_fuel_cost"])

    def test_over_one_tank_without_stations_returns_clear_error(self):
        response = self.request_route(500.01)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["error"], "No fuel stations were found near the route."
        )

    def test_short_trip_with_station_still_returns_priced_plan(self):
        self.find_stations.return_value = [self.station(0)]
        response = self.request_route(100)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["fuel_summary"]["total_fuel_cost"], 30.0)
        self.assertEqual(response.data["fuel_summary"]["total_refueling_cost"], 0.0)
        self.assertEqual(response.data["fuel_stops"], [])
        self.assertNotIn("message", response.data["fuel_summary"])

    def test_long_trip_with_reachable_station_still_returns_plan(self):
        stop = self.station(400)
        stop["coordinate_quality"] = "city"
        stop["coordinate_source"] = "local/us_cities.csv"
        self.find_stations.return_value = [self.station(0), stop]
        response = self.request_route(600)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["fuel_summary"]["number_of_fuel_stops"], 1)
        self.assertEqual(response.data["fuel_summary"]["total_fuel_cost"], 180.0)
        self.assertEqual(response.data["fuel_summary"]["total_refueling_cost"], 30.0)
        self.assertEqual(response.data["fuel_stops"][0]["gallons_purchased"], 10.0)
        self.assertEqual(response.data["fuel_stops"][0]["coordinate_quality"], "city")
        marker = response.data["map"]["features"][2]
        self.assertEqual(marker["properties"]["coordinate_quality"], "city")
        self.assertEqual(marker["properties"]["gallons_purchased"], 10.0)
        self.assertEqual(marker["properties"]["cost"], 30.0)

    def test_long_trip_with_unreachable_destination_returns_clear_error(self):
        self.find_stations.return_value = [self.station(400)]
        response = self.request_route(1100)

        self.assertEqual(response.status_code, 400)
        self.assertIn("No usable station found within 500 miles", response.data["error"])

    def test_early_cheaper_station_is_selected_and_costs_are_reported(self):
        stations = [self.station(mile) for mile in (0, 200, 400, 700)]
        for station, price in zip(stations, (5, 1, 4, 4)):
            station["price"] = price
        self.find_stations.return_value = stations
        response = self.request_route(900)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([stop["route_mile"] for stop in response.data["fuel_stops"]], [200, 700])
        summary = response.data["fuel_summary"]
        self.assertEqual(summary["total_gallons"], 90.0)
        self.assertEqual(summary["total_gallons_purchased"], 40.0)
        self.assertEqual(summary["total_refueling_cost"], 100.0)
        self.assertEqual(summary["total_fuel_cost"], 350.0)
        self.assertEqual(self.geocode.call_count, 2)
        self.get_route.assert_called_once()
