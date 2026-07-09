# -*- coding: utf-8 -*-
"""Tests for the US-short full-universe overextension producer (engine/us_short_overextension_producer.py).

Adversarial focus: the ENVELOPE fail-closed gate (a stray / duplicate / clock-mismatched packet series is a
forged / look-ahead packet and must RAISE — a future `as_of` is the load-bearing look-ahead guard) vs honest
per-ticker DATA dispositioning (an absent / thin eligible ticker → insufficient_data, never a raise).
"""
import sys
import unittest
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_overextension_producer as op  # noqa: E402

_PB = "2026-07-08"        # price_basis_date
_SESSION = "RTH"
_ADJ = "split_adjusted"
_PARA_CLOSES = [106 + i for i in range(24)] + [135]
_PARA_VOLS = [1_000_000.0] * 24 + [3_000_000.0]


def _series(closes, volumes=None, *, as_of=_PB, session=_SESSION, adjustment_mode=_ADJ, spread=0.5):
    """OHLCV series with ascending daily dates ENDING at as_of (so PIT keeps them all)."""
    end = _date.fromisoformat(as_of)
    n = len(closes)
    pts = []
    for i, c in enumerate(closes):
        d = (end - _timedelta(days=(n - 1 - i))).isoformat()
        p = {"date": d, "high": float(c) + spread, "low": float(c) - spread, "close": float(c)}
        if volumes is not None:
            p["volume"] = float(volumes[i])
        pts.append(p)
    return {"as_of": as_of, "session": session, "adjustment_mode": adjustment_mode, "points": pts}


class OverextensionProducerTests(unittest.TestCase):
    def _proj(self, series_by_ticker, eligible):
        return op.build_overextension_projection(
            series_by_ticker, eligible, price_basis_date=_PB, session=_SESSION, adjustment_mode=_ADJ)

    def test_projects_all_eligible_with_honest_dispositions(self):
        packet = {"AAPL": _series(_PARA_CLOSES, _PARA_VOLS),
                  "MSFT": _series([100, 101] * 13, [1_000_000.0] * 26)}
        out = self._proj(packet, ["AAPL", "MSFT", "JPM"])   # JPM eligible but ABSENT from the packet
        self.assertEqual(out["target_count"], 3)
        self.assertEqual(out["overextension_by_ticker"]["AAPL"]["overextension_state"], "chasing_extreme")
        self.assertTrue(out["overextension_by_ticker"]["AAPL"]["strips_theme_score"])
        self.assertEqual(out["overextension_by_ticker"]["MSFT"]["overextension_state"], "none")
        self.assertEqual(out["overextension_by_ticker"]["JPM"]["disposition"], "insufficient_data")
        self.assertEqual(out["disposition_counts"], {"scored": 2, "insufficient_data": 1})
        self.assertEqual(out["scored_count"], 2)

    def test_stray_ticker_not_eligible_raises(self):
        packet = {"AAPL": _series(_PARA_CLOSES, _PARA_VOLS), "TSLA": _series([100, 101] * 13)}
        with self.assertRaises(op.OverextensionProducerError):
            self._proj(packet, ["AAPL"])

    def test_duplicate_canonical_series_key_raises(self):
        # "aapl" and "AAPL" canonicalize to the SAME ticker → duplicate packet series key
        packet = {"AAPL": _series(_PARA_CLOSES, _PARA_VOLS), "aapl": _series([100, 101] * 13)}
        with self.assertRaises(op.OverextensionProducerError):
            self._proj(packet, ["AAPL"])

    def test_future_as_of_clock_mismatch_raises_look_ahead_guard(self):
        # a series carrying a FUTURE as_of (!= price_basis_date) would PIT-cut at a later date → look-ahead;
        # the envelope must reject it (the load-bearing forgery / look-ahead guard).
        packet = {"AAPL": _series(_PARA_CLOSES, _PARA_VOLS, as_of="2026-07-15")}
        with self.assertRaises(op.OverextensionProducerError):
            self._proj(packet, ["AAPL"])

    def test_session_or_adjustment_mismatch_raises(self):
        for bad in ({"session": "EXT"}, {"adjustment_mode": "raw"}):
            s = _series(_PARA_CLOSES, _PARA_VOLS)
            s.update(bad)
            with self.assertRaises(op.OverextensionProducerError):
                self._proj({"AAPL": s}, ["AAPL"])

    def test_present_but_malformed_series_raises(self):
        with self.assertRaises(op.OverextensionProducerError):
            self._proj({"AAPL": "not a dict"}, ["AAPL"])
        with self.assertRaises(op.OverextensionProducerError):
            self._proj({"AAPL": {"points": []}}, ["AAPL"])   # missing as_of → != price_basis → raise

    def test_non_canonical_or_duplicate_eligible_raises(self):
        with self.assertRaises(op.OverextensionProducerError):
            self._proj({}, ["AAPL", "aapl"])   # duplicate canonical eligible
        with self.assertRaises(op.OverextensionProducerError):
            self._proj({}, ["600519"])         # A-share code → not a canonicalizable US ticker

    def test_non_list_eligible_raises(self):
        with self.assertRaises(op.OverextensionProducerError):
            self._proj({}, "AAPL")

    def test_empty_eligible_is_empty_projection(self):
        out = self._proj({}, [])
        self.assertEqual(out["target_count"], 0)
        self.assertEqual(out["overextension_by_ticker"], {})
        self.assertEqual(out["disposition_counts"], {"scored": 0, "insufficient_data": 0})

    def test_non_dict_series_by_ticker_all_absent(self):
        out = self._proj(None, ["AAPL", "MSFT"])   # no packet → every eligible dispositions insufficient_data
        self.assertEqual(out["disposition_counts"], {"scored": 0, "insufficient_data": 2})


if __name__ == "__main__":
    unittest.main()
