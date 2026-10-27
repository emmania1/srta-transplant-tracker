"""Digest line assembly + estimated average distance. Synthetic inputs only."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_digest import MAX_LINES, assemble_digest  # noqa: E402
from ingest_national import est_avg_nm  # noqa: E402

DASH = "Dashboard: https://example"
EMPTY = "*Top headlines:* No major news this week."


class TestAssembleDigest(unittest.TestCase):
    def test_dashboard_kept_when_too_many_headlines(self):
        top, bullets = ["title"], [f"• b{i}" for i in range(7)]
        heads = [f"  – h{i}" for i in range(5)]
        lines = assemble_digest(top, bullets, heads, EMPTY, DASH, MAX_LINES)
        self.assertEqual(lines[-1], DASH)
        self.assertLessEqual(len(lines), MAX_LINES)
        self.assertEqual(lines[:8], top + bullets)          # all bullets survive
        self.assertEqual(lines[9:-1], heads[:MAX_LINES - 10])  # headlines trimmed instead

    def test_dashboard_kept_even_if_bullets_overflow(self):
        lines = assemble_digest(["title", "⚠️ issue"], [f"• b{i}" for i in range(20)], ["  – h"], EMPTY, DASH, 13)
        self.assertEqual(len(lines), 13)
        self.assertEqual(lines[-1], DASH)

    def test_no_headlines_line(self):
        lines = assemble_digest(["title"], ["• b"], [], EMPTY, DASH, 13)
        self.assertEqual(lines, ["title", "• b", EMPTY, DASH])

    def test_headline_cap_is_three(self):
        cfg = json.loads((ROOT / "config" / "keywords.json").read_text())
        self.assertEqual(cfg["digest"]["max_items"], 3)


class TestEstAvgDistance(unittest.TestCase):
    def test_midpoint_weighted_average(self):
        # hand check: heart 2026 YTD bands -> 1,091,625 / 3,432 = 318.07
        bands = {"0–150": 864, "151–200": 313, "201–250": 299, "251–500": 1429, "500+": 527}
        self.assertEqual(est_avg_nm(bands), 318.1)

    def test_empty(self):
        self.assertIsNone(est_avg_nm({"0–150": 0, "151–200": 0, "201–250": 0, "251–500": 0, "500+": 0}))


if __name__ == "__main__":
    unittest.main()
