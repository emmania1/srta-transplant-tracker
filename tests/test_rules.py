"""Tests for rule-based labels and news filters. Synthetic inputs only."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_digest import classify  # noqa: E402
import fetch_news  # noqa: E402

CFG = json.loads((ROOT / "config" / "keywords.json").read_text())
LABELS = {"up": "up", "flat": "flat", "down": "down"}


class TestSignals(unittest.TestCase):
    def test_flat_band_inclusive(self):
        self.assertEqual(classify(2.0, 2.0, LABELS), "flat")
        self.assertEqual(classify(-2.0, 2.0, LABELS), "flat")
        self.assertEqual(classify(2.1, 2.0, LABELS), "up")
        self.assertEqual(classify(-2.1, 2.0, LABELS), "down")
        self.assertIsNone(classify(None, 2.0, LABELS))


class TestNewsFilters(unittest.TestCase):
    def keep(self, headline, source="Test"):
        return fetch_news.make_filter(CFG)({"source": source, "headline": headline, "tags": ["competitors"]})

    def test_zacks_template_dropped(self):
        self.assertFalse(self.keep("Strata Critical Medical, Inc. (SRTA) Upgraded to Buy: What Does It Mean for the Stock?"))
        self.assertFalse(self.keep("TransMedics (TMDX) Downgraded to Strong Sell"))

    def test_broker_actions_kept(self):
        self.assertTrue(self.keep("Needham reiterates Buy on TransMedics stock, names new CFO"))
        self.assertTrue(self.keep("Weekly Recap: TMDX CFO appointment and TD Cowen $120 target"))

    def test_other_company_analyst_dropped(self):
        self.assertFalse(self.keep("Danske Bank cuts target price for Xvivo Perfusion"))

    def test_digest_angle_word_start(self):
        angle = [re.compile(r"\b" + re.escape(a), re.I) for a in CFG["digest"]["angle_terms"]]
        self.assertFalse(any(a.search("Egypt death-row organ proposal sparks debate") for a in angle))
        self.assertTrue(any(a.search("OPO decertified by CMS") for a in angle))


class TestDigestHeadlines(unittest.TestCase):
    def pick(self, items, sec=None):
        from datetime import datetime, timezone
        from build_digest import news_block
        now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
        news = {"items": items, "groups": [{"id": "strata", "label": "Strata"}, {"id": "competitors", "label": "Comp"}]}
        return news_block(news, now, sec)

    def item(self, h, d, tags=("competitors",)):
        return {"headline": h, "source": "Test", "date": f"{d}T12:00:00+00:00", "url": f"u/{h}", "tags": list(tags)}

    def test_none_when_fewer_than_two(self):
        r = self.pick([self.item("TransMedics expands transplant logistics", "2026-10-08")])
        self.assertEqual(r["top_headlines"], [])
        self.assertEqual(r["none_text"], "No major news this week")

    def test_housekeeping_opinion_and_stale_results_skipped(self):
        sec = {"filings": [{"form": "8-K", "items": "2.02,9.01", "filed": "2026-08-04"}]}
        items = [self.item("Nomination Committee of XVIVO Perfusion AB", "2026-10-08"),
                 self.item("Opinion: OPO reform is overdue", "2026-10-08", ("competitors", "opinion")),
                 self.item("Strata Critical Medical Q2 Results: revenue rises 60%", "2026-09-28", ("strata",)),
                 self.item("TransMedics expands transplant logistics", "2026-10-08"),
                 self.item("Paragonix wins FDA clearance for perfusion device", "2026-10-07")]
        heads = [h["headline"] for h in self.pick(items, sec)["top_headlines"]]
        self.assertEqual(heads, ["TransMedics expands transplant logistics", "Paragonix wins FDA clearance for perfusion device"])


if __name__ == "__main__":
    unittest.main()
