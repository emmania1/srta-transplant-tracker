"""health.py step-outcome messages (no network, no files)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from health import step_issues  # noqa: E402


class TestStepIssues(unittest.TestCase):
    def test_playwright_failure_explained_once(self):
        issues = step_issues({"Playwright install": "failure", "OPTN weekly": "skipped", "News": "success"})
        self.assertEqual(len(issues), 1)
        self.assertIn("OPTN weekly fetch was skipped", issues[0])

    def test_other_failures_listed(self):
        issues = step_issues({"Prices": "failure", "Ingest": "failure", "CDC": "success"})
        self.assertEqual(issues, ["Prices step failed in the latest run; showing the last good data.",
                                  "Ingest step failed in the latest run; showing the last good data."])

    def test_all_good(self):
        self.assertEqual(step_issues({"Tests": "success", "Playwright install": "success", "OPTN weekly": "success"}), [])


if __name__ == "__main__":
    unittest.main()
