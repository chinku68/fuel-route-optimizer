import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from routing.models import FuelStation
from routing.osm_station_matching import build_osm_index, match_osm_station


def osm_element(**tags):
    base = {
        "amenity": "fuel", "brand": "Kwik Trip", "name": "Kwik Trip",
        "ref": "796", "addr:city": "Tomah", "addr:state": "WI",
    }
    base.update(tags)
    return {
        "type": "way", "id": 1204194481,
        "center": {"lat": 44.0188755, "lon": -90.5025615}, "tags": base,
    }


class OsmStationMatchTests(SimpleTestCase):
    def setUp(self):
        self.station = SimpleNamespace(
            truckstop_name="KWIK TRIP #796", city="Tomah", state="WI",
            latitude=43.994833, longitude=-90.491704,
        )

    def test_brand_branch_city_state_match_has_known_osm_source(self):
        result = match_osm_station(self.station, build_osm_index([osm_element()]))
        self.assertEqual(result["source"], "openstreetmap:way/1204194481")
        self.assertEqual(result["latitude"], 44.0188755)

    def test_wrong_branch_brand_city_state_or_country_is_not_used(self):
        for change in (
            {"ref": "718"}, {"brand": "Shell", "name": "Shell"},
            {"addr:city": "Madison"}, {"addr:state": "MN"},
            {"addr:country": "CA"}, {"amenity": "parking"}, {"ref": ""},
        ):
            with self.subTest(change=change):
                self.assertIsNone(match_osm_station(
                    self.station, build_osm_index([osm_element(**change)])
                ))

    def test_same_chain_without_explicit_csv_branch_is_not_guessed(self):
        self.station.truckstop_name = "Kwik Trip"
        self.assertIsNone(match_osm_station(self.station, build_osm_index([osm_element()])))

    def test_conflicting_branch_locations_are_rejected(self):
        other = osm_element()
        other["center"]["lat"] = 44.1
        self.assertIsNone(match_osm_station(
            self.station, build_osm_index([osm_element(), other])
        ))

    def test_match_too_far_from_city_is_rejected(self):
        other = osm_element()
        other["center"]["lat"] = 45.1
        self.assertIsNone(match_osm_station(self.station, build_osm_index([other])))

    def test_chain_name_normalization_preserves_brand_numbers(self):
        self.station.truckstop_name = "7-ELEVEN #34709"
        result = match_osm_station(self.station, build_osm_index([
            osm_element(brand="7-Eleven", name="7-Eleven", ref="34709"),
        ]))
        self.assertIsNotNone(result)


class OsmCoordinateImportTests(TestCase):
    def setUp(self):
        self.station = FuelStation.objects.create(
            opis_truckstop_id=9, truckstop_name="KWIK TRIP #796",
            address="I-94, EXIT 143 & US-12 & SR-21", city="Tomah", state="WI",
            retail_price="3.28733", latitude=43.994833, longitude=-90.491704,
            coordinate_quality="city", geocode_error="Manual review needed",
        )
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "sample.json"
        self.path.write_text(json.dumps({"elements": [osm_element()]}))
        self.output = StringIO()

    def run_import(self, **options):
        call_command("import_osm_station_coordinates", input=self.path, stdout=self.output, **options)

    def test_import_changes_location_only_and_is_idempotent(self):
        self.run_import()
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "venue")
        self.assertEqual(self.station.coordinate_source, "openstreetmap:way/1204194481")
        self.assertIsNone(self.station.geocode_confidence)
        self.assertEqual(self.station.geocode_error, "")
        self.assertEqual(str(self.station.retail_price), "3.28733")
        self.assertEqual(self.station.address, "I-94, EXIT 143 & US-12 & SR-21")
        self.assertEqual(FuelStation.objects.count(), 1)
        checked_at = self.station.geocode_checked_at
        self.run_import()
        self.station.refresh_from_db()
        self.assertEqual(self.station.geocode_checked_at, checked_at)

    def test_dry_run_does_not_update_database(self):
        self.run_import(dry_run=True)
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "city")
        self.assertEqual(self.station.latitude, 43.994833)
        self.assertIn("Would update: 1", self.output.getvalue())

    def test_existing_better_location_is_preserved(self):
        self.station.coordinate_quality = "address"
        self.station.save()
        self.run_import()
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "address")
        self.assertEqual(self.station.latitude, 43.994833)

    def test_partial_overpass_response_is_rejected(self):
        self.path.write_text(json.dumps({
            "remark": "runtime error: timeout", "elements": [osm_element()],
        }))
        with self.assertRaisesMessage(CommandError, "complete successful download"):
            self.run_import()
        self.station.refresh_from_db()
        self.assertEqual(self.station.coordinate_quality, "city")
