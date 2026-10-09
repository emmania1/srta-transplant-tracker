"""Calendar-quarter proration tests (synthetic data)."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from quarters import q_bounds, quarter_metrics, span_total, daily  # noqa: E402


def optn_weeks(year, counts):
    """OPTN-style weeks for one year: week N starts Jan 1 + 7(N-1); week 52 runs to Dec 31."""
    rows = []
    for i, c in enumerate(counts, start=1):
        s = date(year, 1, 1) + timedelta(days=7 * (i - 1))
        e = date(year, 12, 31) if i == 52 else s + timedelta(days=6)
        rows.append({"yr": year, "week": i, "week_start": s.isoformat(), "week_end": e.isoformat(), "count": c})
    return rows


class TestQuarters(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(q_bounds(2026, 3), (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(q_bounds(2026, 4), (date(2026, 10, 1), date(2026, 12, 31)))

    def test_boundary_week_prorated_by_days(self):
        # 70 per week = 10 per day; week 26 (Jun 25-Jul 1) has 1 day in Q3
        rows = optn_weeks(2026, [70] * 52)
        self.assertAlmostEqual(span_total(daily(rows), date(2026, 7, 1), date(2026, 7, 1)), 10.0)
        # Q3 = 92 days x 10
        self.assertAlmostEqual(span_total(daily(rows), *q_bounds(2026, 3)), 920.0)

    def test_metrics_yoy_seq_typical(self):
        rows = []
        for y, per_day in [(2023, 10), (2024, 10), (2025, 10), (2026, 11)]:
            rows += optn_weeks(y, [per_day * 7] * 51 + [per_day * 9 if y != 2024 else per_day * 9])
        m = quarter_metrics(rows, date(2026, 9, 30))
        self.assertEqual(m["quarter"], "Q3 2026")
        self.assertEqual(m["yoy_pct"], 10.0)        # 11/day vs 10/day
        self.assertEqual(m["seq_pct"], round(100 * (92 / 91 - 1), 1))  # Q3 has 92 days, Q2 has 91
        self.assertFalse(m["qtd"]["shown"])

    def test_incomplete_quarter_uses_previous(self):
        rows = optn_weeks(2026, [70] * 39)  # data through Sep 30 -> Q3 complete
        self.assertEqual(quarter_metrics(rows, date(2026, 9, 30))["quarter"], "Q3 2026")
        self.assertEqual(quarter_metrics(rows[:38], date(2026, 9, 23))["quarter"], "Q2 2026")


if __name__ == "__main__":
    unittest.main()
