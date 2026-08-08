import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "plan_store.py"
SPEC = importlib.util.spec_from_file_location("plan_store", MODULE_PATH)
plan_store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan_store)


class PlanStoreTests(unittest.TestCase):
    def test_save_and_list_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "travel-data"
            source = Path(temp) / "plan.json"
            source.write_text(
                json.dumps({"destination": "洛阳", "days_count": 3}, ensure_ascii=False),
                encoding="utf-8",
            )
            saved = plan_store.save_plan(root, source)
            plans = plan_store.list_plans(root)
            self.assertTrue(Path(saved["path"]).exists())
            self.assertEqual(plans[0]["destination"], "洛阳")
            self.assertEqual(plans[0]["days_count"], 3)

    def test_sensitive_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "travel-data"
            source = Path(temp) / "unsafe.json"
            source.write_text(
                json.dumps({"destination": "测试城", "api_key": "YOUR_API_KEY_HERE"}),
                encoding="utf-8",
            )
            with self.assertRaises(plan_store.StoreError):
                plan_store.save_plan(root, source)

    def test_wishlist_add_update_and_remove(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "travel-data"
            first = plan_store.wishlist_add(root, "洛阳", "看石窟")
            second = plan_store.wishlist_add(root, "洛阳", "春天去")
            payload = plan_store.wishlist_list(root)
            removed = plan_store.wishlist_remove(root, "洛阳")
            self.assertEqual(first["action"], "added")
            self.assertEqual(second["action"], "updated")
            self.assertEqual(len(payload["items"]), 1)
            self.assertEqual(payload["items"][0]["note"], "春天去")
            self.assertEqual(removed["action"], "removed")
            self.assertEqual(plan_store.wishlist_list(root)["items"], [])

    def test_root_must_be_explicit(self):
        previous = plan_store.os.environ.pop("TRAVEL_PLANNER_DATA_DIR", None)
        try:
            with self.assertRaises(plan_store.StoreError):
                plan_store._resolve_root(None)
        finally:
            if previous is not None:
                plan_store.os.environ["TRAVEL_PLANNER_DATA_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
