import importlib.util
import json
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "route_optimizer.py"
SPEC = importlib.util.spec_from_file_location("route_optimizer", MODULE_PATH)
route_optimizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(route_optimizer)


def attraction(item_id, name, lat, lon, zone, **overrides):
    item = {
        "id": item_id,
        "name": name,
        "lat": lat,
        "lon": lon,
        "zone": zone,
        "priority": "recommended",
        "duration_minutes": 90,
        "time_preference": "any",
    }
    item.update(overrides)
    return item


class RouteOptimizerTests(unittest.TestCase):
    def test_groups_nearby_stops_and_puts_night_stop_last(self):
        payload = {
            "destination": "测试城",
            "days": 2,
            "intensity": "normal",
            "attractions": [
                attraction("north-a", "北区甲", 34.80, 112.40, "城北", priority="must"),
                attraction("north-b", "北区乙", 34.81, 112.41, "城北"),
                attraction("old-a", "老城甲", 34.60, 112.50, "老城", priority="must"),
                attraction(
                    "old-night",
                    "老城夜景",
                    34.61,
                    112.51,
                    "老城",
                    night=True,
                    time_preference="evening",
                ),
            ],
        }
        result = route_optimizer.optimize_trip(payload)
        grouped = {
            stop["id"]: day["day"]
            for day in result["days"]
            for stop in day["stops"]
        }
        self.assertEqual(grouped["north-a"], grouped["north-b"])
        self.assertEqual(grouped["old-a"], grouped["old-night"])
        old_day = next(day for day in result["days"] if grouped["old-a"] == day["day"])
        self.assertEqual(old_day["stops"][-1]["id"], "old-night")
        self.assertTrue(result["audit"]["passed"])

    def test_excluded_stop_is_never_scheduled(self):
        payload = {
            "destination": "测试城",
            "days": 1,
            "attractions": [
                attraction("must", "必去", 30.0, 120.0, "中心", priority="must"),
                attraction("skip", "不想去", 30.01, 120.01, "中心", excluded=True),
            ],
        }
        result = route_optimizer.optimize_trip(payload)
        scheduled = [stop["id"] for stop in result["days"][0]["stops"]]
        self.assertEqual(scheduled, ["must"])
        self.assertEqual(result["unscheduled"][0]["reason"], "user_excluded")

    def test_provided_travel_data_is_reported_as_verified(self):
        payload = {
            "destination": "测试城",
            "days": 1,
            "lodging": {"id": "hotel", "name": "住宿区", "lat": 30.0, "lon": 120.0, "zone": "中心"},
            "attractions": [
                attraction("a", "景点甲", 30.01, 120.01, "中心", priority="must"),
                attraction("b", "景点乙", 30.02, 120.02, "中心"),
            ],
            "travel_times": [
                {"from": "hotel", "to": "a", "minutes": 12, "distance_km": 3, "mode": "metro", "source": "map"},
                {"from": "a", "to": "b", "minutes": 8, "distance_km": 1.2, "mode": "walk", "source": "map"},
                {"from": "b", "to": "hotel", "minutes": 15, "distance_km": 4, "mode": "metro", "source": "map"},
            ],
        }
        result = route_optimizer.optimize_trip(payload)
        self.assertEqual(result["data_quality"]["estimated_legs"], 0)
        self.assertEqual(result["data_quality"]["verified_legs"], 3)

    def test_duplicate_ids_are_rejected(self):
        item = attraction("same", "重复", 30.0, 120.0, "中心")
        with self.assertRaises(route_optimizer.InputError):
            route_optimizer.optimize_trip(
                {"destination": "测试城", "days": 1, "attractions": [item, dict(item)]}
            )

    def test_luoyang_fixture_runs_as_a_three_day_plan(self):
        fixture = SKILL_ROOT / "tests" / "fixtures" / "luoyang-three-days.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        result = route_optimizer.optimize_trip(payload)
        self.assertEqual(result["destination"], "洛阳")
        self.assertEqual(len(result["days"]), 3)
        self.assertTrue(result["audit"]["passed"])
        scheduled = [stop for day in result["days"] for stop in day["stops"]]
        self.assertGreaterEqual(len(scheduled), 6)
        self.assertTrue(any(day["zone_focus"] == ["老城"] for day in result["days"]))


if __name__ == "__main__":
    unittest.main()
