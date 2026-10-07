import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from routing.models import FuelStation
from routing.osm_coordinate_import import download_state_extract, state_query
from routing.test_osm_station_matching import osm_element


class OsmDownloadTests(SimpleTestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "cache" / "WI.json"

    def response(self, data):
        response = MagicMock()
        response.iter_content.return_value = [json.dumps(data).encode()]
        return response

    def test_validated_download_is_cached_atomically_without_ors_credentials(self):
        data = {"elements": [osm_element()], "osm3s": {"timestamp_osm_base": "2026-10-07T00:00:00Z"}}
        with patch("routing.osm_coordinate_import.requests.post") as post:
            post.return_value.__enter__.return_value = self.response(data)
            self.assertEqual(download_state_extract("WI", self.path), data)
        self.assertEqual(json.loads(self.path.read_text()), data)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])
        self.assertIn('"US-WI"', post.call_args.kwargs["data"]["data"])
        post.assert_called_once()

    def test_partial_or_invalid_response_is_not_cached(self):
        for data in ({"remark": "timeout", "elements": []}, {"features": []}):
            with self.subTest(data=data), patch("routing.osm_coordinate_import.requests.post") as post:
                post.return_value.__enter__.return_value = self.response(data)
                with self.assertRaises(ValueError):
                    download_state_extract("WI", self.path)
                self.assertFalse(self.path.exists())

    def test_oversized_download_is_not_cached(self):
        with patch("routing.osm_coordinate_import.requests.post") as post, patch("routing.osm_coordinate_import.MAX_DOWNLOAD_BYTES", 3):
            post.return_value.__enter__.return_value = self.response({"elements": []})
            with self.assertRaisesMessage(ValueError, "32 MB limit"):
                download_state_extract("WI", self.path)
            self.assertFalse(self.path.exists())

    def test_query_rejects_non_us_or_injected_state(self):
        for state in ("BC", 'WI"];out;'):
            with self.assertRaises(ValueError):
                state_query(state)


class OsmPreparationTests(TestCase):
    def setUp(self):
        self.station = FuelStation.objects.create(
            opis_truckstop_id=9, truckstop_name="KWIK TRIP #796",
            address="I-94, EXIT 143 & US-12 & SR-21", city="Tomah", state="WI",
            retail_price="3.28733", latitude=43.994833, longitude=-90.491704,
            coordinate_quality="city",
        )
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.cache = Path(self.folder.name) / "cache"
        self.output = StringIO()

    def cached(self, state="WI", data=None):
        self.cache.mkdir(exist_ok=True)
        (self.cache / f"{state}.json").write_text(json.dumps(data or {"elements": [osm_element()]}))

    def run_command(self, **options):
        call_command("prepare_osm_coordinates", cache_dir=self.cache, stdout=self.output, **options)

    def test_cached_import_and_repeat_make_zero_external_calls(self):
        self.cached()
        with patch("routing.osm_coordinate_import.requests.post") as post:
            self.run_command(states=["WI"], max_requests=0)
            self.station.refresh_from_db()
            self.assertEqual(self.station.coordinate_quality, "venue")
            self.assertEqual(str(self.station.retail_price), "3.28733")
            checked = self.station.geocode_checked_at
            self.run_command(states=["WI"], max_requests=0)
            self.station.refresh_from_db()
            self.assertEqual(self.station.geocode_checked_at, checked)
            post.assert_not_called()
        self.assertIn("updated 0 stations", self.output.getvalue())

    def test_dry_run_previews_matches_and_missing_files_without_writes(self):
        self.cached()
        with patch("routing.osm_coordinate_import.requests.post") as post:
            self.run_command(states=["WI", "MN"], dry_run=True)
            post.assert_not_called()
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "city")
        self.assertFalse((self.cache / "MN.json").exists())
        self.assertIn("would update 1 stations", self.output.getvalue())
        self.assertIn("MN: download pending", self.output.getvalue())

    def test_dry_run_does_not_create_cache_directory(self):
        with patch("routing.osm_coordinate_import.requests.post") as post:
            self.run_command(states=["WI"], dry_run=True)
            post.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_request_cap_downloads_once_and_reports_remaining_state(self):
        with patch("routing.osm_coordinate_import.requests.post") as post:
            response = MagicMock()
            response.iter_content.return_value = [json.dumps({"elements": [osm_element()]}).encode()]
            post.return_value.__enter__.return_value = response
            self.run_command(states=["WI", "MN"], max_requests=1)
            post.assert_called_once()
        self.assertTrue((self.cache / "WI.json").exists())
        self.assertFalse((self.cache / "MN.json").exists())
        self.assertIn("Downloads pending: MN", self.output.getvalue())
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "venue")

    def test_download_failure_preserves_earlier_imports(self):
        self.cached()
        response = requests.Response()
        response.status_code = 429
        with patch("routing.osm_coordinate_import.requests.post", side_effect=requests.HTTPError(response=response)) as post:
            with self.assertRaisesMessage(CommandError, "HTTP 429"):
                self.run_command(states=["WI", "MN"], max_requests=1)
            post.assert_called_once()
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "venue")
        self.assertFalse((self.cache / "MN.json").exists())

    def test_invalid_cached_extract_stops_without_import_or_download(self):
        self.cached(data={"elements": [osm_element()], "remark": "timeout"})
        with patch("routing.osm_coordinate_import.requests.post") as post:
            with self.assertRaisesMessage(CommandError, "complete successful download"):
                self.run_command(states=["WI"])
            post.assert_not_called()
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "city")

    def test_state_filter_does_not_import_other_states_in_extract(self):
        self.cached(state="MN")
        self.run_command(states=["MN"], max_requests=0)
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "city")

    def test_existing_user_download_is_reused(self):
        base = Path(self.folder.name)
        (base / "data").mkdir()
        (base / "data" / "osm_virginia.json").write_text(json.dumps({"elements": []}))
        with override_settings(BASE_DIR=base), patch("routing.osm_coordinate_import.requests.post") as post:
            call_command("prepare_osm_coordinates", states=["VA"], max_requests=0, stdout=self.output)
            post.assert_not_called()
        self.assertIn("VA: cached", self.output.getvalue())
        self.assertFalse((base / "data" / "osm_cache").exists())

    def test_zero_budget_reports_missing_download_without_making_requests(self):
        with patch("routing.osm_coordinate_import.requests.post") as post:
            self.run_command(states=["WI"], max_requests=0)
            post.assert_not_called()
        self.assertIn("WI: download pending", self.output.getvalue())
        self.assertFalse(self.cache.exists())

    def test_default_states_exclude_non_us_station_records(self):
        FuelStation.objects.create(opis_truckstop_id=99, truckstop_name="Foreign", address="x",
                                   city="Vancouver", state="BC", retail_price="3.0")
        self.run_command(max_requests=0, dry_run=True)
        self.assertIn("WI: download pending", self.output.getvalue())
        self.assertNotIn("BC:", self.output.getvalue())

    def test_invalid_arguments_make_no_requests(self):
        for options in ({"states": ["BC"]}, {"max_requests": -1},
                        {"pause_seconds": float("nan")}, {"pause_seconds": 4}):
            with self.subTest(options=options), patch("routing.osm_coordinate_import.requests.post") as post:
                with self.assertRaises(CommandError):
                    self.run_command(**options)
                post.assert_not_called()
