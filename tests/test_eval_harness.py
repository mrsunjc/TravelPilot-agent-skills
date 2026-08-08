import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "run_evals.py"
SPEC = importlib.util.spec_from_file_location("run_evals", MODULE_PATH)
run_evals = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_evals)


class EvalHarnessTests(unittest.TestCase):
    def test_gold_suite_meets_all_expectations(self):
        report = run_evals.run_suite(REPO_ROOT / "evals" / "gold" / "cases.json")
        self.assertTrue(report["passed"], report["results"])

    def test_heldout_suite_meets_all_expectations(self):
        report = run_evals.run_suite(REPO_ROOT / "evals" / "heldout" / "cases.json")
        self.assertTrue(report["passed"], report["results"])


if __name__ == "__main__":
    unittest.main()
