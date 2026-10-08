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


if __name__ == "__main__":
    unittest.main()
