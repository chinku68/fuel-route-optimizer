from decimal import Decimal
from random import Random

from django.test import SimpleTestCase

from routing.fuel_optimizer import optimize_fuel_stops


def station(mile, price):
    return {
        "id": mile, "name": f"Station at {mile}", "address": "Test address",
        "city": "Test City", "state": "TX", "latitude": 32.8, "longitude": -96.8,
        "route_mile": mile, "price": price, "distance_from_route_miles": 0,
        "coordinate_quality": "city", "coordinate_source": "local/us_cities.csv",
    }


def exhaustive_purchase_cost(distance, capacity, prices):
    """Independent integer fuel-state DP: try every legal purchase quantity."""
    states = {capacity: 0}
    previous = 0
    for position, price in sorted(prices.items()) + [(distance, None)]:
        gap = position - previous
        arrivals = {}
        for fuel, cost in states.items():
            if fuel >= gap:
                remaining = fuel - gap
                arrivals[remaining] = min(arrivals.get(remaining, float("inf")), cost)
        if not arrivals:
            return None
        if price is None:
            return min(arrivals.values())
        states = {}
        for fuel, cost in arrivals.items():
            for purchase in range(capacity - fuel + 1):
                after = fuel + purchase
                total = cost + purchase * price
                states[after] = min(states.get(after, float("inf")), total)
        previous = position


class FuelPurchaseTests(SimpleTestCase):
    def assert_tank_and_cost_balance(self, plan, distance):
        fuel = 50.0
        previous_mile = 0.0
        total_cost = Decimal(0)
        for stop in plan["fuel_stops"]:
            fuel -= (stop["route_mile"] - previous_mile) / 10
            self.assertGreaterEqual(fuel, -0.000001)
            self.assertAlmostEqual(fuel, stop["fuel_on_arrival_gallons"], places=6)
            self.assertGreater(stop["gallons_purchased"], 0)
            fuel += stop["gallons_purchased"]
            self.assertLessEqual(fuel, 50.000001)
            self.assertAlmostEqual(fuel, stop["fuel_after_refueling_gallons"], places=6)
            total_cost += Decimal(str(stop["cost"]))
            previous_mile = stop["route_mile"]
        fuel -= (distance - previous_mile) / 10
        self.assertGreaterEqual(fuel, -0.000001)
        self.assertAlmostEqual(fuel, plan["ending_fuel_gallons"], places=6)
        self.assertEqual(float(total_cost), plan["total_refueling_cost"])
        self.assertAlmostEqual(
            50 + plan["total_gallons_purchased"] - distance / 10,
            plan["ending_fuel_gallons"], places=6,
        )

    def test_early_cheap_fuel_is_carried_past_expensive_station(self):
        plan = optimize_fuel_stops([
            station(0, 5), station(200, 1), station(400, 4), station(700, 4),
        ], 900)
        self.assertEqual([stop["route_mile"] for stop in plan["fuel_stops"]], [200, 700])
        self.assertEqual([stop["gallons_purchased"] for stop in plan["fuel_stops"]], [20, 20])
        self.assertEqual(plan["total_refueling_cost"], 100)
        self.assertEqual(plan["starting_fuel_cost_estimate"], 250)
        self.assertEqual(plan["total_fuel_cost"], 350)
        self.assert_tank_and_cost_balance(plan, 900)

    def test_partial_purchase_reaches_cheaper_station_without_filling(self):
        plan = optimize_fuel_stops([
            station(0, 5), station(400, 5), station(600, 2),
        ], 900)
        self.assertEqual([stop["gallons_purchased"] for stop in plan["fuel_stops"]], [10, 30])
        self.assertEqual(plan["fuel_stops"][0]["fuel_after_refueling_gallons"], 20)
        self.assertEqual(plan["total_refueling_cost"], 110)
        self.assert_tank_and_cost_balance(plan, 900)

    def test_co_located_stations_use_cheapest_price(self):
        plan = optimize_fuel_stops([
            station(400, 5), station(0, 3), station(400, 1),
        ], 600)
        self.assertEqual(len(plan["fuel_stops"]), 1)
        self.assertEqual(plan["fuel_stops"][0]["price_per_gallon"], 1)
        self.assertEqual(plan["total_refueling_cost"], 10)
        self.assert_tank_and_cost_balance(plan, 600)

    def test_full_tank_short_trip_consumes_fuel_without_purchases(self):
        plan = optimize_fuel_stops([station(0, 3), station(50, 1)], 100)
        self.assertEqual(plan["fuel_stops"], [])
        self.assertEqual(plan["total_gallons"], 10)
        self.assertEqual(plan["ending_fuel_gallons"], 40)
        self.assertEqual(plan["total_refueling_cost"], 0)
        self.assertEqual(plan["total_fuel_cost"], 30)
        self.assert_tank_and_cost_balance(plan, 100)

    def test_missing_start_price_is_not_replaced_by_far_away_station(self):
        plan = optimize_fuel_stops([station(400, 3)], 600)
        self.assertIsNone(plan["starting_fuel_reference"])
        self.assertIsNone(plan["starting_fuel_cost_estimate"])
        self.assertIsNone(plan["total_fuel_cost"])
        self.assertEqual(plan["total_refueling_cost"], 30)
        self.assertEqual(plan["total_gallons_purchased"], 10)
        self.assert_tank_and_cost_balance(plan, 600)

    def test_exact_500_mile_legs_are_feasible(self):
        plan = optimize_fuel_stops([station(0, 3), station(500, 3)], 1000)
        self.assertEqual(plan["fuel_stops"][0]["gallons_purchased"], 50)
        self.assert_tank_and_cost_balance(plan, 1000)

    def test_over_range_gap_returns_clear_error(self):
        with self.assertRaisesMessage(ValueError, "No usable station found within 500 miles"):
            optimize_fuel_stops([station(0, 3), station(500, 3)], 1000.01)

    def test_station_within_first_five_miles_can_bridge_a_long_trip(self):
        plan = optimize_fuel_stops([
            station(0, 5), station(0.5, 1), station(500.5, 4),
        ], 1000.5)
        self.assertEqual(plan["fuel_stops"][0]["route_mile"], 0.5)
        self.assertEqual(plan["fuel_stops"][0]["gallons_purchased"], 0.05)
        self.assert_tank_and_cost_balance(plan, 1000.5)

    def test_invalid_station_prices_and_out_of_route_positions_are_skipped(self):
        plan = optimize_fuel_stops([
            station(-1, 1), station(1000, 1), station(400, 0),
            station(400, float("nan")), station(400, 3),
        ], 600)
        self.assertEqual(plan["total_refueling_cost"], 30)
        self.assert_tank_and_cost_balance(plan, 600)

    def test_retail_price_precision_and_cent_rounding_are_preserved(self):
        plan = optimize_fuel_stops([station(0, 3), station(500, 3.28733)], 501)
        self.assertEqual(plan["fuel_stops"][0]["price_per_gallon"], 3.28733)
        self.assertEqual(plan["fuel_stops"][0]["cost"], 0.33)
        self.assertEqual(plan["total_fuel_cost"], 150.33)
        self.assert_tank_and_cost_balance(plan, 501)

    def test_equal_price_dense_stations_do_not_create_tiny_repeated_purchases(self):
        plan = optimize_fuel_stops([station(mile, 3) for mile in range(1, 1500)], 1500)
        self.assertEqual([stop["route_mile"] for stop in plan["fuel_stops"]], [500, 1000])
        self.assertEqual(plan["total_refueling_cost"], 300)
        self.assert_tank_and_cost_balance(plan, 1500)

    def test_zero_length_trip_needs_no_fuel_and_has_zero_cost(self):
        plan = optimize_fuel_stops([], 0)
        self.assertEqual(plan["total_gallons"], 0)
        self.assertEqual(plan["total_refueling_cost"], 0)
        self.assertEqual(plan["total_fuel_cost"], 0)
        self.assertEqual(plan["ending_fuel_gallons"], 50)

    def test_invalid_vehicle_or_distance_values_are_rejected(self):
        for options in (
            {"total_distance_miles": -1}, {"total_distance_miles": float("nan")},
            {"total_distance_miles": True}, {"total_distance_miles": 100, "mpg": 0},
            {"total_distance_miles": 100, "max_range": -1},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                optimize_fuel_stops([], **options)

    def test_matches_exhaustive_minimum_for_seeded_small_routes(self):
        random = Random(42)
        feasible = impossible = 0
        for scenario in range(200):
            distance = random.randint(5, 12)
            capacity = random.randint(2, 5)
            prices = {
                mile: random.randint(1, 7)
                for mile in range(distance) if random.random() < 0.65
            }
            expected = exhaustive_purchase_cost(distance, capacity, prices)
            candidates = [station(mile, price) for mile, price in prices.items()]
            with self.subTest(scenario=scenario, distance=distance, capacity=capacity):
                if expected is None:
                    impossible += 1
                    with self.assertRaises(ValueError):
                        optimize_fuel_stops(candidates, distance, max_range=capacity, mpg=1)
                else:
                    feasible += 1
                    plan = optimize_fuel_stops(candidates, distance, max_range=capacity, mpg=1)
                    self.assertEqual(plan["total_refueling_cost"], expected)
                    self.assertGreaterEqual(plan["ending_fuel_gallons"], 0)
                    for stop in plan["fuel_stops"]:
                        self.assertLessEqual(stop["fuel_after_refueling_gallons"], capacity)
        self.assertGreater(feasible, 0)
        self.assertGreater(impossible, 0)
