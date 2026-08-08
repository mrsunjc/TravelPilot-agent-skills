import importlib.util
import base64
import json
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "travel_visualizer.py"
SPEC = importlib.util.spec_from_file_location("travel_visualizer", MODULE_PATH)
visualizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(visualizer)


class TravelVisualizerTests(unittest.TestCase):
    def fixture(self):
        return {
            "destination": "评测城",
            "trip": {"days": 1, "intensity": "normal", "party": {"size": 2}},
            "itinerary": [
                {
                    "day": 1,
                    "date": "2026-08-10",
                    "zone_focus": ["城中"],
                    "stops": [
                        {"id": "hotel", "name": "城中住宿区", "kind": "hotel", "zone": "城中", "arrival_time": "08:30", "departure_time": "09:00"},
                        {"id": "museum", "name": "评测博物馆", "kind": "attraction", "zone": "城中", "arrival_time": "09:20", "departure_time": "11:20"},
                    ],
                    "legs": [{"from": "hotel", "to": "museum", "mode": "地铁", "minutes": 20, "distance_km": 5, "verified": True}],
                }
            ],
            "attractions": [{"name": "评测博物馆", "priority": "must"}],
            "lodging_recommendations": [{"area": "城中地铁沿线"}],
            "budget": {"currency": "CNY", "travelers": 2, "total": {"min": 737, "max": 1012}},
            "weather": [],
            "claims": [{"status": "estimated"}, {"status": "unverified"}],
        }

    def test_render_contains_destination_schedule_and_budget(self):
        rendered = visualizer.render_svg(self.fixture())
        self.assertTrue(rendered.startswith('<?xml version="1.0"'))
        self.assertIn("评测城", rendered)
        self.assertIn("评测博物馆", rendered)
        self.assertIn("CNY 737–1012", rendered)
        self.assertIn("Day 1", rendered)

    def test_untrusted_text_is_xml_escaped(self):
        plan = self.fixture()
        plan["destination"] = "测试<script>alert(1)</script>"
        rendered = visualizer.render_svg(plan)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_cli_writes_svg_and_host_neutral_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / "plan.json"
            fixture.write_text(json.dumps(self.fixture(), ensure_ascii=False), encoding="utf-8")
            output = Path(temp) / "trip.svg"
            prompt = Path(temp) / "cover.txt"
            code = visualizer.main([str(fixture), "--output", str(output), "--prompt-output", str(prompt)])
            self.assertEqual(code, 0)
            self.assertTrue(output.is_file())
            self.assertIn("no text", prompt.read_text(encoding="utf-8"))
            self.assertIn("不得虚构官方标志", prompt.read_text(encoding="utf-8"))

    def test_png_cover_can_be_embedded_without_external_dependency(self):
        one_pixel_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        with tempfile.TemporaryDirectory() as temp:
            cover = Path(temp) / "cover.png"
            cover.write_bytes(one_pixel_png)
            rendered = visualizer.render_svg(self.fixture(), cover_image=cover)
            self.assertIn("data:image/png;base64,", rendered)
            self.assertIn("clip-path=\"url(#heroClip)\"", rendered)


if __name__ == "__main__":
    unittest.main()
