"""Unit tests for week filtering + YoY math. Synthetic inputs only (never shown on the site).

Run: python3 -m unittest discover -s tests
"""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from metrics import drop_incomplete, iso_key, organ_metrics, total_series  # noqa: E402


def weeks(start, counts):
    """Consecutive Sunday-start weeks beginning `start` with the given counts."""
    out = []
    for i, c in enumerate(counts):
        ws = start + timedelta(weeks=i)
        out.append({"week_start": ws.isoformat(), "week_end": (ws + timedelta(days=6)).isoformat(), "count": c})
    return out


class TestMetrics(unittest.TestCase):
    def setUp(self):
        # Prior year: weeks 1..10 of ISO 2025 (Sunday 2024-12-29 midpoint -> 2025-W01)
        self.prior = weeks(date(2024, 12, 29), [100] * 6 + [110, 120, 130, 140])
        # Current year: weeks 1..10 of ISO 2026 (Sunday 2025-12-28 -> 2026-W01)
        self.cur = weeks(date(2025, 12, 28), [105] * 6 + [100, 130, 150, 147])

    def test_iso_alignment(self):
        self.assertEqual(iso_key(self.prior[0]), (2025, 1))
        self.assertEqual(iso_key(self.cur[0]), (2026, 1))

    def test_drop_incomplete(self):
        rows = self.cur
        as_of = date.fromisoformat(rows[-1]["week_end"])  # pulled on the last week's final day
        kept, dropped = drop_incomplete(rows, as_of)
        self.assertEqual(len(dropped), 1)
        self.assertEqual(kept[-1], rows[-2])

    def test_yoy(self):
        m = organ_metrics(self.prior + self.cur)
        # latest week: 147 vs 140 -> +5.0%
        self.assertEqual(m["latest_week"]["yoy_pct"], 5.0)
        # trailing 4: 100+130+150+147=527 vs 110+120+130+140=500 -> +5.4%
        self.assertEqual(m["trailing_4wk"]["total"], 527)
        self.assertEqual(m["trailing_4wk"]["prior_year_total"], 500)
        self.assertEqual(m["trailing_4wk"]["yoy_pct"], 5.4)
        # YTD: 630+527=1157 vs 600+500=1100 -> +5.2%
        self.assertEqual(m["ytd"]["total"], 1157)
        self.assertEqual(m["ytd"]["prior_year_total"], 1100)
        self.assertEqual(m["ytd"]["yoy_pct"], 5.2)

    def test_missing_prior_week_gives_none(self):
        m = organ_metrics(self.prior[:-1] + self.cur)
        self.assertIsNone(m["trailing_4wk"]["yoy_pct"])
        self.assertIsNone(m["ytd"]["yoy_pct"])

    def test_total_series(self):
        t = total_series({"heart": self.cur, "liver": self.cur[:3]})
        self.assertEqual(len(t), 3)
        self.assertEqual(t[0]["count"], 210)


if __name__ == "__main__":
    unittest.main()
