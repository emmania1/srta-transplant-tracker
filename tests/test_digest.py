"""Digest line assembly + estimated average distance. Synthetic inputs only."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_digest import MAX_LINES, assemble_digest, direction_word, flying_demand, organ_miles_change  # noqa: E402
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



class TestFlyingDemand(unittest.TestCase):
    def test_organ_miles_formula(self):
        self.assertEqual(organ_miles_change(10.0, -10.0), -1.0)       # 1.1 x 0.9 - 1
        self.assertEqual(organ_miles_change(4.43, -4.18), 0.1)          # this week's numbers
        self.assertIsNone(organ_miles_change(None, 1.0))

    def test_roughly_flat_wording(self):
        self.assertEqual(direction_word(0.1), "roughly flat")
        self.assertEqual(direction_word(-1.99), "roughly flat")
        self.assertEqual(direction_word(2.0), "up")
        self.assertEqual(direction_word(-2.5), "down")

    def test_combined_average_is_count_weighted(self):
        # pooling bands across organs = count-weighted average of the organ estimates
        heart = {"0–150": 100, "151–200": 0, "201–250": 0, "251–500": 0, "500+": 100}   # 387.5
        lung = {"0–150": 0, "151–200": 0, "201–250": 0, "251–500": 300, "500+": 0}      # 375
        pooled = {b: heart[b] + lung[b] for b in heart}
        self.assertEqual(est_avg_nm(pooled), round((387.5 * 200 + 375 * 300) / 500, 1))

    def test_flying_demand_end_to_end(self):
        bands = lambda a, b: {"0–150": a, "151–200": 0, "201–250": 0, "251–500": b, "500+": 0}  # noqa: E731
        organs = {o: {"2025": {"est_avg_nm": 300.0}, "2026": {"est_avg_nm": 300.0}} for o in ("heart", "liver", "lung")}
        dist = {"status": "ok", "period_end": "2026-01-14", "current_year": 2026, "prior_year": 2025, "organs": organs,
                "hll": {"2025": {"est_avg_nm": est_avg_nm(bands(50, 50))}, "2026": {"est_avg_nm": est_avg_nm(bands(60, 40))}}}
        rows = [{"yr": y, "week": w, "week_end": f"{y}-01-{7 * w:02d}", "count": c}
                for y, c in ((2025, 100), (2026, 110)) for w in (1, 2, 3)]  # week 3 of 2026 ends Jan 21 > period_end
        f = flying_demand(dist, {"status": "ok", "organs": {"hll": rows}})
        self.assertEqual((f["volume"]["current"], f["volume"]["prior"]), (220, 200))  # weeks 1-2 only, both years
        self.assertEqual(f["volume"]["change_pct"], 10.0)
        self.assertEqual(f["distance"]["change_pct"], -13.3)   # 195 vs 225 NM
        self.assertEqual(f["organ_miles_change_pct"], -4.7)     # 1.10 x (195/225) - 1 = -4.67%
        self.assertEqual(f["direction"], "down")


class TestBulletBudget(unittest.TestCase):
    def test_seven_bullets_fit_with_three_headlines_and_link(self):
        lines = assemble_digest(["title"], [f"• b{i}" for i in range(7)], [f"  – h{i}" for i in range(3)], EMPTY, DASH, MAX_LINES)
        self.assertEqual(len(lines), MAX_LINES)
        self.assertEqual(sum(l.startswith("  – ") for l in lines), 3)
        self.assertEqual(lines[-1], DASH)


if __name__ == "__main__":
    unittest.main()
