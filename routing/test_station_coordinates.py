import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from routing.fuel_service import find_stations_near_route
from routing.models import FuelStation, StationGeocodeCache
from routing.station_geocoding import select_station_match


def feature(**properties):
    base = {
        "country_a": "USA", "region_a": "TX", "locality": "Dallas",
        "confidence": 0.95, "layer": "address",
        "housenumber": "100", "street": "Main Street",
        "name": "100 Main Street",
    }
    base.update(properties)
    return {
        "geometry": {"type": "Point", "coordinates": [-96.8, 32.8]},
        "properties": base,
    }


class StationMatchTests(SimpleTestCase):
    def setUp(self):
        self.station = SimpleNamespace(
            truckstop_name="Test Truck Stop #123", address="100 Main Street",
            city="Dallas", state="TX", latitude=32.81, longitude=-96.81,
        )

    def test_matching_address_is_accepted(self):
        match = select_station_match(self.station, [feature()])
        self.assertEqual(match["quality"], "address")
        self.assertEqual(match["latitude"], 32.8)

    def test_matching_station_name_is_accepted(self):
        match = select_station_match(self.station, [
            feature(layer="venue", name="Test Truck Stop #123"),
        ])
        self.assertEqual(match["quality"], "venue")

    def test_street_abbreviations_match_expanded_geocoder_names(self):
        self.station.address = "504 N CREGO RD"
        match = select_station_match(self.station, [
            feature(housenumber="504", street="North Crego Road"),
        ])
        self.assertEqual(match["quality"], "address")

    def test_wrong_country_state_city_or_low_confidence_is_rejected(self):
        for changes in (
            {"country_a": "CAN"}, {"region_a": "OK"}, {"locality": "Austin"},
            {"confidence": 0.5}, {"confidence": float("nan")},
            {"confidence": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                select_station_match(self.station, [feature(**changes)])

    def test_city_and_street_results_are_not_station_matches(self):
        for layer in ("locality", "street", "region"):
            with self.subTest(layer=layer), self.assertRaises(ValueError):
                select_station_match(self.station, [feature(layer=layer, confidence=1)])

    def test_other_chain_branch_is_rejected(self):
        with self.assertRaises(ValueError):
            select_station_match(self.station, [
                feature(layer="venue", name="Test Truck Stop #456"),
            ])

    def test_wrong_house_number_or_street_is_rejected(self):
        for changes in ({"housenumber": "200"}, {"street": "Oak Avenue"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                select_station_match(self.station, [feature(**changes)])

    def test_invalid_coordinates_are_rejected(self):
        for coordinates in ([float("nan"), 32.8], [181, 32.8], [True, 32.8], [1]):
            bad = feature()
            bad["geometry"]["coordinates"] = coordinates
            with self.subTest(coordinates=coordinates), self.assertRaises(ValueError):
                select_station_match(self.station, [bad])

    def test_conflicting_results_require_manual_review(self):
        other = feature()
        other["geometry"]["coordinates"] = [-96.9, 32.8]
        with self.assertRaisesMessage(ValueError, "Multiple station matches"):
            select_station_match(self.station, [feature(), other])

    def test_highway_exit_does_not_pass_as_house_number(self):
        self.station.address = "I-44, EXIT 283 & US-69"
        self.station.city = "Big Cabin"
        self.station.state = "OK"
        with self.assertRaises(ValueError):
            select_station_match(self.station, [
                feature(layer="street", name="US 283", locality="Sayre", region_a="OK", confidence=1),
            ])


@override_settings(ORS_API_KEY="test-only-key")
class CoordinatePreparationTests(TestCase):
    def setUp(self):
        self.station = FuelStation.objects.create(
            opis_truckstop_id=123, truckstop_name="Test Truck Stop #123",
            address="100 Main Street", city="Dallas", state="TX",
            retail_price="3.0", latitude=32.81, longitude=-96.81,
            coordinate_quality="city",
        )
        self.output = StringIO()
        self.sleep_patcher = patch(
            "routing.management.commands.geocode_missing_stations.time.sleep"
        )
        self.sleep_patcher.start()
        self.addCleanup(self.sleep_patcher.stop)

    def geocode(self, **options):
        call_command("geocode_missing_stations", stdout=self.output, **options)

    @patch("routing.management.commands.geocode_missing_stations.search_station")
    def test_city_location_is_replaced_and_saved_immediately(self, search):
        search.return_value = ([feature()], {"X-Ratelimit-Remaining": "100"})
        self.geocode(limit=1)
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "address")
        self.assertEqual(self.station.latitude, 32.8)
        self.assertEqual(self.station.coordinate_source, "openrouteservice/pelias")
        self.assertIsNotNone(self.station.geocode_checked_at)
        self.assertEqual(StationGeocodeCache.objects.count(), 1)
        self.geocode(limit=1)
        search.assert_called_once()

    @patch("routing.management.commands.geocode_missing_stations.search_station")
    def test_rejected_result_preserves_city_coordinates_and_is_not_repeated(self, search):
        search.return_value = ([feature(layer="locality")], {})
        self.geocode(limit=1)
        self.station.refresh_from_db()
        self.assertEqual(self.station.latitude, 32.81)
        self.assertEqual(self.station.coordinate_quality, "city")
        self.assertIn("manual review", self.station.geocode_error)
        self.assertEqual(search.call_count, 2)
        self.geocode(limit=1)
        self.assertEqual(search.call_count, 2)

    @patch("routing.management.commands.geocode_missing_stations.search_station")
    def test_cached_result_is_reused_for_duplicate_records(self, search):
        search.return_value = ([feature()], {})
        self.geocode(limit=1)
        self.station.pk = None
        self.station.geocode_checked_at = None
        self.station.coordinate_quality = "city"
        self.station.save()
        self.geocode(limit=1)
        self.assertEqual(search.call_count, 1)
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "address")

    @patch("routing.management.commands.geocode_missing_stations.search_station")
    def test_call_cap_and_resume_use_persistent_cache(self, search):
        search.return_value = ([], {})
        self.geocode(limit=1, max_requests=1)
        self.station.refresh_from_db()
        self.assertIsNone(self.station.geocode_checked_at)
        self.assertEqual(search.call_count, 1)
        search.return_value = ([feature()], {})
        self.geocode(limit=1, max_requests=1)
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "address")
        self.assertEqual(search.call_count, 2)

    @patch("routing.management.commands.geocode_missing_stations.search_station")
    def test_zero_quota_stops_before_another_call(self, search):
        search.return_value = ([], {"X-Ratelimit-Remaining": "0"})
        self.geocode(limit=1)
        self.assertEqual(search.call_count, 1)
        self.assertIn("daily quota", self.output.getvalue())

    @patch("routing.management.commands.geocode_missing_stations.search_station")
    def test_quota_error_stops_and_keeps_previous_station(self, search):
        second = FuelStation.objects.create(
            opis_truckstop_id=456, truckstop_name="Second Truck Stop",
            address="200 Main Street", city="Dallas", state="TX",
            retail_price="3.0",
        )
        response = requests.Response()
        response.status_code = 403
        search.side_effect = [
            ([feature()], {}),
            requests.HTTPError("secret-test-url", response=response),
        ]
        with self.assertRaisesMessage(CommandError, "HTTP 403") as error:
            self.geocode(limit=2)
        self.assertNotIn("secret-test-url", str(error.exception))
        self.station.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "address")
        self.assertIsNone(second.geocode_checked_at)

    @patch("routing.management.commands.geocode_missing_stations.search_station")
    def test_dry_run_makes_no_calls_or_database_changes(self, search):
        self.geocode(dry_run=True)
        search.assert_not_called()
        self.station.refresh_from_db()
        self.assertIsNone(self.station.geocode_checked_at)
        self.assertEqual(StationGeocodeCache.objects.count(), 0)

    @patch("routing.management.commands.geocode_missing_stations.search_station")
    def test_non_usa_and_already_matched_stations_are_skipped(self, search):
        self.station.coordinate_quality = "venue"
        self.station.save()
        FuelStation.objects.create(
            opis_truckstop_id=789, truckstop_name="Canadian station",
            address="100 Main Street", city="Toronto", state="ON", retail_price="3.0",
        )
        self.geocode()
        search.assert_not_called()

    def test_city_command_labels_city_points_and_preserves_better_locations(self):
        matched = FuelStation.objects.create(
            opis_truckstop_id=456, truckstop_name="Matched",
            address="200 Main Street", city="Dallas", state="TX",
            retail_price="3.0", latitude=32.8, longitude=-96.8,
            coordinate_quality="address", coordinate_source="openrouteservice/pelias",
        )
        unknown = FuelStation.objects.create(
            opis_truckstop_id=789, truckstop_name="Unknown",
            address="300 Main Street", city="Dallas", state="TX",
            retail_price="3.0", latitude=32.7, longitude=-96.7,
        )
        self.station.coordinate_quality = "unverified"
        self.station.save()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "cities.csv"
            with path.open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["CITY", "STATE_CODE", "LATITUDE", "LONGITUDE"])
                writer.writerow(["Dallas", "TX", 32.81, -96.81])
            call_command("add_station_coordinates", cities_file=path, stdout=self.output)
            call_command("add_station_coordinates", cities_file=path, stdout=self.output)
        self.station.refresh_from_db()
        matched.refresh_from_db()
        unknown.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "city")
        self.assertEqual(matched.coordinate_quality, "address")
        self.assertEqual(matched.latitude, 32.8)
        self.assertEqual(unknown.coordinate_quality, "unverified")
        self.assertEqual(unknown.latitude, 32.7)

    def test_station_api_and_route_candidates_expose_location_quality(self):
        response = APIClient().get("/api/stations/?state=TX")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["stations"][0]["coordinate_quality"], "city")
        candidates = find_stations_near_route({
            "type": "LineString", "coordinates": [[-96.81, 32.81], [-96.8, 32.8]],
        })
        self.assertEqual(candidates[0]["coordinate_quality"], "city")
