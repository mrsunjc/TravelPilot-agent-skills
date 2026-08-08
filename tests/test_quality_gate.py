import importlib.util
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_ROOT = REPO_ROOT / "travel-planner" / "scripts"
TOOLS_ROOT = REPO_ROOT / "tools"
for path in (QUALITY_ROOT, TOOLS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from eval_fixture import mutate, valid_plan
from travel_quality.quality_gate import validate_final_plan


SCHEMA = json.loads((REPO_ROOT / "travel-planner" / "schemas" / "final-plan.schema.json").read_text(encoding="utf-8"))
POLICY = json.loads((REPO_ROOT / "travel-planner" / "schemas" / "quality-policy.json").read_text(encoding="utf-8"))


class QualityGateTests(unittest.TestCase):
    def report(self, mutation):
        return validate_final_plan(mutate(valid_plan(), mutation), SCHEMA, POLICY)

    def test_valid_fixture_passes_with_perfect_score(self):
        report = self.report("valid")
        self.assertTrue(report["passed"], report["findings"])
        self.assertEqual(report["score"], 100)

    def test_core_failures_are_detected(self):
        expectations = {
            "missing_evidence": "EVIDENCE_REQUIRED",
            "budget_mismatch": "BUDGET_TOTAL_MISMATCH",
            "excluded_scheduled": "CONSTRAINT_EXCLUDED_SCHEDULED",
            "overlap": "SCHEDULE_OVERLAP",
            "reservation_unknown": "RESERVATION_STATUS_UNKNOWN",
            "route_missing": "ROUTE_LEG_MISSING",
            "community_authority": "EVIDENCE_SOURCE_AUTHORITY_LOW",
            "stale_closure": "EVIDENCE_STALE",
            "sensitive_field": "SECURITY_SENSITIVE_FIELD",
            "return_buffer": "RETURN_BUFFER_LOW",
        }
        for mutation, expected in expectations.items():
            with self.subTest(mutation=mutation):
                report = self.report(mutation)
                codes = {item["code"] for item in report["findings"]}
                self.assertFalse(report["passed"])
                self.assertIn(expected, codes)


if __name__ == "__main__":
    unittest.main()
