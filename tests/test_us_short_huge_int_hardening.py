# -*- coding: utf-8 -*-
"""US-short huge-int OverflowError containment — whole-class regression (cc_r1 finding).

The raw-provider-facing finite guards must treat an over-large Python int (e.g. 10**400, which
float()/math.isfinite() reject with OverflowError) as non-finite / malformed and NEVER let a bare
OverflowError escape. These are the raw-provider-facing subset the project's earlier per-engine
surgical scope miscategorised as 0-100-value-consuming; the genuinely 0-100-consuming copies
(core_score / risk_downgrade / theme_heat / theme_opportunity / macro_cluster / orthogonalize /
position_sizing / ship_gate_sizing / forward_events / portfolio_guard) are intentionally left — a raw
huge int is unreachable there (their inputs are upstream-clamped engine outputs).
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_catalyst as cat
from engine import us_short_eligibility_gate as eg
from engine import us_short_massive_financials as mf
from engine import us_short_massive_news_catalyst as mnc
from engine import us_short_numeric_catalyst_entitlement as nce
from engine import us_short_regime as rg
from runners import us_short_universe_fetch as uf

BIG = 10 ** 400   # a legit Python int; float()/math.isfinite() reject it with OverflowError


class HugeIntContainment(unittest.TestCase):
    def test_sanity_big_overflows_math_isfinite(self):
        # proves BIG is exactly the hostile shape these guards must contain (not a synthetic assertion).
        with self.assertRaises(OverflowError):
            math.isfinite(BIG)

    def test_eligibility_gate_contains(self):
        self.assertIs(eg._is_finite_number(BIG), False)   # Pass1 universe gate: one bad row can't crash the whole narrowing

    def test_massive_financials_contains(self):
        self.assertIs(mf._is_finite_number(BIG), False)

    def test_catalyst_contains(self):
        self.assertIs(cat._is_finite_number(BIG), False)
        self.assertIsNone(cat._finite(BIG))

    def test_numeric_entitlement_raises_valueerror_not_overflow(self):
        # must raise ValueError (caught by the caller's malformed-200 neutral fallback), NOT a leaked OverflowError.
        with self.assertRaises(ValueError):
            nce._finite_number(BIG, field="earnings_surprise_pct")

    def test_news_catalyst_block_raises_typed_not_overflow(self):
        with self.assertRaises(mnc.MassiveNewsCatalystSeamError):
            mnc._finite_block_value(BIG, name="x")

    def test_regime_classify_vix_unknown_not_crash(self):
        self.assertEqual(rg.classify_vix(BIG), rg.UNKNOWN)

    def test_universe_fetch_contains_raw_provider_numeric(self):
        self.assertIs(uf._is_finite(BIG), False)


if __name__ == "__main__":
    unittest.main()
