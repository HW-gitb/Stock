# -*- coding: utf-8 -*-
"""Tests for US-short §12.1 deterministic paper fill (engine/us_short_paper_fill.py).

Covers: Step 0 (open in band); Step 1 (pullback low<=limit; breakout high>=breakout, fill = clamp(max(open,
breakout), high=valid_entry_high)); same-day conservative exit (stop priority over tp); reproducibility (same
order+bar → same result); frozen order_type single-source; order geometry (a long's stop<fill<tp brackets the
actual fill + a pullback limit in-band — inverted / equal / out-of-band refused for both order types before any
booking); and the whole malformed-input class (order/bar shape, non-finite/negative prices, OHLC sanity, missing
type-specific price). Pure/offline; no provider/live; no A-share.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_fill as pf  # noqa: E402

ORDER_TYPES = json.loads((ROOT / "presets" / "us_short_action_table_contract_20260620.json").read_text(encoding="utf-8"))["design_locked_enums"]["order_type"]


def _pullback(**o):
    d = {"order_type": "pullback_limit", "order_expiry": "first_regular_session_only",
         "valid_entry_low": 95.0, "valid_entry_high": 105.0,
         "limit_order_price": 98.0, "stop_clear_price": 92.0, "take_profit_exit_price": 115.0}
    d.update(o)
    return d


def _breakout(**o):
    d = {"order_type": "breakout_stop_limit", "order_expiry": "first_regular_session_only",
         "valid_entry_low": 95.0, "valid_entry_high": 105.0,
         "breakout_entry_price": 102.0, "stop_clear_price": 92.0, "take_profit_exit_price": 115.0}
    d.update(o)
    return d


def _bar(open=100.0, high=103.0, low=97.0, close=101.0):
    return {"open": open, "high": high, "low": low, "close": close}


class Step0Band(unittest.TestCase):
    def test_open_above_band_not_filled(self):
        r = pf.simulate_fill(_pullback(), _bar(open=110.0, high=111.0, low=109.0, close=110.0))
        self.assertEqual(r["status"], "not_filled")
        self.assertEqual(r["reason"], "open_out_of_band")

    def test_open_below_band_not_filled(self):
        r = pf.simulate_fill(_pullback(), _bar(open=90.0, high=94.0, low=89.0, close=93.0))
        self.assertEqual(r["status"], "not_filled")


class OrderGeometry(unittest.TestCase):
    """§12.1 (R-USSHORT-BATCH3-PAPER-FILL-ORDER-GEOMETRY-GAP): a long's passive levels must bracket the actual fill
    (stop < fill < tp) and a pullback limit must sit inside the valid entry band; impossible geometry fails closed
    BEFORE any same-day stop/tp/held output can be booked."""
    _FILLBAR = {"open": 100.0, "high": 103.0, "low": 97.0, "close": 101.0}  # fills pullback limit 98 / breakout 102

    def test_pullback_stop_at_or_above_fill_refused(self):
        for stop in (105.0, 98.0):  # stop >= fill 98 (Codex probe 1 + equality) — would book a "stop" as a gain
            with self.assertRaises(pf.PaperFillError):
                pf.simulate_fill(_pullback(stop_clear_price=stop, take_profit_exit_price=115.0), self._FILLBAR)

    def test_pullback_tp_at_or_below_fill_refused(self):
        for tp in (95.0, 98.0):  # tp <= fill 98 (Codex probe 2 + equality) — would book a "take-profit" as a loss
            with self.assertRaises(pf.PaperFillError):
                pf.simulate_fill(_pullback(stop_clear_price=90.0, take_profit_exit_price=tp), self._FILLBAR)

    def test_pullback_limit_outside_band_refused(self):
        for limit in (120.0, 90.0):  # above valid_entry_high 105 (Codex probe 3) / below valid_entry_low 95 (probe 4)
            with self.assertRaises(pf.PaperFillError):
                pf.simulate_fill(_pullback(limit_order_price=limit), self._FILLBAR)

    def test_breakout_fill_not_bracketed_refused(self):
        # breakout fills @102 (min(max(open,102),105)); stop 104 >= fill → not bracketed → refused (same rule, both types)
        with self.assertRaises(pf.PaperFillError):
            pf.simulate_fill(_breakout(stop_clear_price=104.0, take_profit_exit_price=115.0), self._FILLBAR)

    def test_valid_geometry_still_books(self):  # positive control: valid bracket + in-band limit still books a same-day exit
        r = pf.simulate_fill(_pullback(stop_clear_price=92.0, take_profit_exit_price=115.0),
                             {"open": 100.0, "high": 103.0, "low": 91.0, "close": 95.0})  # low 91 <= stop 92 → stopped @ 92
        self.assertEqual((r["status"], r["exit_price"]), ("filled_stopped", 92.0))


class Step1Pullback(unittest.TestCase):
    def test_fill_at_limit_when_low_reaches(self):
        r = pf.simulate_fill(_pullback(), _bar(open=100.0, high=103.0, low=97.0, close=101.0))  # low 97 <= limit 98
        self.assertEqual(r["status"], "filled_held")
        self.assertEqual(r["fill_price"], 98.0)

    def test_not_filled_when_low_above_limit(self):
        r = pf.simulate_fill(_pullback(), _bar(open=100.0, high=103.0, low=99.0, close=101.0))  # low 99 > limit 98
        self.assertEqual(r["status"], "not_filled")
        self.assertEqual(r["reason"], "pullback_not_reached")


class Step1Breakout(unittest.TestCase):
    def test_fill_at_breakout_when_high_reaches(self):
        r = pf.simulate_fill(_breakout(), _bar(open=100.0, high=103.0, low=99.0, close=102.0))  # high 103 >= 102
        self.assertEqual(r["status"], "filled_held")
        self.assertEqual(r["fill_price"], 102.0)  # min(max(100,102),105) = 102

    def test_fill_at_open_when_gapped_above_breakout(self):
        r = pf.simulate_fill(_breakout(), _bar(open=104.0, high=106.0, low=103.0, close=104.5))
        self.assertEqual(r["fill_price"], 104.0)  # min(max(104,102),105) = 104 (can't fill below open)

    def test_fill_capped_at_valid_entry_high(self):
        r = pf.simulate_fill(_breakout(breakout_entry_price=110.0), _bar(open=100.0, high=111.0, low=99.0, close=104.0))
        self.assertEqual(r["fill_price"], 105.0)  # min(max(100,110),105) = 105 (never chase above band)

    def test_not_filled_when_high_below_breakout(self):
        r = pf.simulate_fill(_breakout(), _bar(open=100.0, high=101.0, low=99.0, close=100.5))  # high 101 < 102
        self.assertEqual(r["status"], "not_filled")
        self.assertEqual(r["reason"], "breakout_not_reached")


class SameDayConservativeExit(unittest.TestCase):
    def test_same_day_stop(self):
        r = pf.simulate_fill(_pullback(), _bar(open=100.0, high=103.0, low=90.0, close=93.0))  # low 90 <= stop 92
        self.assertEqual(r["status"], "filled_stopped")
        self.assertEqual(r["fill_price"], 98.0)
        self.assertEqual(r["exit_price"], 92.0)
        self.assertEqual(r["exit_reason"], "same_day_stop")

    def test_same_day_tp_exit(self):
        r = pf.simulate_fill(_pullback(), _bar(open=100.0, high=116.0, low=97.0, close=114.0))  # high 116 >= tp 115, low 97 > stop
        self.assertEqual(r["status"], "filled_tp_exit")
        self.assertEqual(r["exit_price"], 115.0)

    def test_stop_takes_priority_over_tp(self):  # §12.1 ②: both trigger same day → stop wins
        r = pf.simulate_fill(_pullback(), _bar(open=100.0, high=116.0, low=90.0, close=100.0))  # low<=stop AND high>=tp
        self.assertEqual(r["status"], "filled_stopped")

    def test_held_when_neither_triggers(self):
        r = pf.simulate_fill(_pullback(), _bar(open=100.0, high=103.0, low=97.0, close=101.0))
        self.assertEqual(r["status"], "filled_held")
        self.assertIsNone(r["exit_price"])


class Reproducible(unittest.TestCase):
    def test_same_inputs_same_result(self):
        o, b = _pullback(), _bar(open=100.0, high=116.0, low=90.0, close=100.0)
        self.assertEqual(pf.simulate_fill(o, b), pf.simulate_fill(o, b))

    def test_order_types_from_frozen_contract(self):
        self.assertEqual(pf._order_types(), ORDER_TYPES)


class MalformedFailsClosed(unittest.TestCase):
    def test_bad_order_refused(self):
        for bad in (None, "x", 5, []):
            with self.assertRaises(pf.PaperFillError, msg=repr(bad)):
                pf.simulate_fill(bad, _bar())

    def test_unknown_order_type_refused(self):
        with self.assertRaises(pf.PaperFillError):
            pf.simulate_fill(_pullback(order_type="market"), _bar())

    def test_bad_prices_refused(self):
        for key in ("valid_entry_low", "valid_entry_high", "stop_clear_price", "take_profit_exit_price", "limit_order_price"):
            for bad in (None, 0, -1.0, "98", True, float("nan"), float("inf")):
                with self.assertRaises(pf.PaperFillError, msg="%s=%r" % (key, bad)):
                    pf.simulate_fill(_pullback(**{key: bad}), _bar())

    def test_band_inverted_refused(self):
        with self.assertRaises(pf.PaperFillError):
            pf.simulate_fill(_pullback(valid_entry_low=105.0, valid_entry_high=95.0), _bar())

    def test_missing_type_specific_price_refused(self):
        o = _pullback(); del o["limit_order_price"]
        with self.assertRaises(pf.PaperFillError):
            pf.simulate_fill(o, _bar())
        o2 = _breakout(); del o2["breakout_entry_price"]
        with self.assertRaises(pf.PaperFillError):
            pf.simulate_fill(o2, _bar())

    def test_bad_bar_refused(self):
        for bad in (None, "x", {"open": 100.0}):  # non-dict / incomplete
            with self.assertRaises(pf.PaperFillError, msg=repr(bad)):
                pf.simulate_fill(_pullback(), bad)

    def test_ohlc_inconsistent_refused(self):
        for bar in (_bar(low=104.0), _bar(high=96.0), _bar(open=110.0, high=103.0, low=97.0), {"open": 100.0, "high": 90.0, "low": 95.0, "close": 92.0}):
            with self.assertRaises(pf.PaperFillError, msg=repr(bar)):
                pf.simulate_fill(_pullback(), bar)


class OrderExpiryV1Contract(unittest.TestCase):
    """R-USSHORT-BATCH3-PAPER-FILL-EXPIRY-GATE-GAP: §12.1 locks paper-fill v1 to
    order_expiry=first_regular_session_only; a missing / non-string / GTC / unknown expiry fails closed
    (PaperFillError) BEFORE any fill result is emitted."""

    def test_missing_expiry_refused(self):
        o = _pullback(); del o["order_expiry"]
        with self.assertRaises(pf.PaperFillError):
            pf.simulate_fill(o, _bar())

    def test_non_v1_expiry_refused(self):
        for bad in ("multi_day_gtc", "gtc", "", None, 5, "FIRST_REGULAR_SESSION_ONLY"):
            with self.assertRaises(pf.PaperFillError, msg=repr(bad)):
                pf.simulate_fill(_pullback(order_expiry=bad), _bar())

    def test_valid_expiry_fills(self):  # positive control: the one v1 value still simulates
        self.assertEqual(pf.simulate_fill(_pullback(), _bar())["status"], "filled_held")

    def test_order_expiries_from_frozen_contract(self):
        self.assertEqual(pf._order_expiries(), ["first_regular_session_only"])


if __name__ == "__main__":
    unittest.main()
