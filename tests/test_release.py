import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_release(name):
    path = REPO_ROOT / "release" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_release = load_release("check_release.py")
build_release = load_release("build_release.py")


class ReleaseTests(unittest.TestCase):
    def test_source_release_is_consistent(self):
        report = check_release.check_release(REPO_ROOT)
        self.assertTrue(report["passed"], report["findings"])

    def test_archive_matches_runtime_source(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "travel-planner.zip"
            result = build_release.build(REPO_ROOT, archive)
            self.assertEqual(result["version"], "2.1.0")
            self.assertTrue(archive.is_file())
            report = check_release.check_release(REPO_ROOT, archive=archive)
            self.assertTrue(report["passed"], report["findings"])


if __name__ == "__main__":
    unittest.main()
