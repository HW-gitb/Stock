from __future__ import annotations

import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_price_engine as pe  # noqa: E402
from engine.us_short_canonical_asof import resolve_canonical_asof  # noqa: E402


class CanonicalNowEtSelfGuard(unittest.TestCase):
    """D8 P3: the PURE canonical resolver now rejects a tz-aware / non-datetime now_et itself (was silently accepted,
    relying on every caller to guard) — fail-closed at the function's own contract, before touching sessions."""

    def test_tz_aware_now_et_rejected(self):
        with self.assertRaises(ValueError):
            resolve_canonical_asof(datetime(2026, 7, 9, 8, 0, 0, tzinfo=timezone.utc), [])

    def test_non_datetime_now_et_rejected(self):
        with self.assertRaises(ValueError):
            resolve_canonical_asof("2026-07-09", [])


class AtrNonFiniteGuard(unittest.TestCase):
    """D8 P3: atr() returns None (not a non-finite value that slips the downstream `a is None or a <= 0` guard)
    on a hostile non-finite bar — a single-source fix that protects every consumer."""

    def _bars(self, high, low, close):
        return [{"high": high, "low": low, "close": close} for _ in range(pe.ATR_WINDOW + 1)]

    def test_atr_none_on_nonfinite_bar(self):
        self.assertIsNone(pe.atr(self._bars(float("inf"), 1.0, 1.0)))
        self.assertIsNone(pe.atr(self._bars(1.0, float("-inf"), 1.0)))

    def test_atr_finite_on_normal_bars(self):
        a = pe.atr(self._bars(2.0, 1.0, 1.5))
        self.assertIsNotNone(a)
        self.assertGreater(a, 0)


class FinitePositivePriceGuard(unittest.TestCase):
    """D8 P3: a non-positive / non-finite price (e.g. a hostile negative close) is rejected by both price engines via
    _finite_positive, so it can never fabricate a false trailing-stop breach or entry geometry."""

    def test_accepts_only_finite_positive(self):
        self.assertTrue(pe._finite_positive(1.0))
        self.assertTrue(pe._finite_positive(0.01))
        for bad in (None, 0, 0.0, -1.0, float("nan"), float("inf"), float("-inf"), True, False, "1", [], {}):
            self.assertFalse(pe._finite_positive(bad), repr(bad))


class ProducerDefaultDateConsistency(unittest.TestCase):
    """D8 P3: each full-universe producer's data-path DEFAULT_* constants share ONE date (were drifted:
    candidate 06 vs series/output 07/09/02) — a stale-CLI-default consistency check that catches future drift."""

    def _date(self, p):
        m = re.search(r"(\d{8})", Path(p).name)
        return m.group(1) if m else None

    def test_each_producer_data_defaults_share_one_date(self):
        from runners import us_short_batch5_full_universe_momentum_producer as mom
        from runners import us_short_batch5_full_universe_overextension_producer as oe
        from runners import us_short_batch5_full_universe_theme_producer as th
        self.assertEqual(1, len({self._date(mom.DEFAULT_CANDIDATE_ARTIFACT_PATH),
                                 self._date(mom.DEFAULT_SERIES_PACKET_PATH),
                                 self._date(mom.DEFAULT_OUTPUT_PROJECTION_PATH)}))
        self.assertEqual(1, len({self._date(oe.DEFAULT_CANDIDATE_ARTIFACT_PATH),
                                 self._date(oe.DEFAULT_SERIES_PACKET_PATH),
                                 self._date(oe.DEFAULT_OUTPUT_PROJECTION_PATH)}))
        self.assertEqual(1, len({self._date(th.DEFAULT_CANDIDATE_ARTIFACT_PATH),
                                 self._date(th.DEFAULT_SERIES_PACKET_PATH),
                                 self._date(th.DEFAULT_CLASSIFICATION_PACKET_PATH),
                                 self._date(th.DEFAULT_OUTPUT_PROJECTION_PATH)}))


if __name__ == "__main__":
    unittest.main()
