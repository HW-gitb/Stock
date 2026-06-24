# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline analysis stage (engine/us_short_weekend_analysis.py) — batch4 slice 4d-ii-a.

Design authority: docs/us_short_system_design.md §5 / §6 / §7 / §8 / §8.1 / §4.2 / §18.2.

Covers the per-row analysis EVIDENCE: §7 market regime computed once and attached; §6 priority routing
(support_atr_engine for candidates / holding_exit_engine for holdings); §8 防御-档 breakout→pullback
sub_mode guard + its caller-asserted probe exception; §5 veto evidence (not suppressed here); §8.1
forward-event effect + event_sensitive data gap; §4.2 score; canonical one-identity-per-stock; and
fail-closed row/ticker/row_source/profile/forward_event shapes.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_analysis as wa  # noqa: E402

_AGGRESSIVE = {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"}
_DEFENSIVE = {"vix": "防御", "market_trend": "防御", "breadth": "防御"}
_EXTREME = {"vix": "极度防御", "market_trend": "极度防御", "breadth": "极度防御"}


def _uptrend_bars(n=22):
    """Smooth low-volatility uptrend (no spikes → strong de-spiked structure): support 101.0 /
    resistance 111.0 / ATR 0.7 over the last 20/14 bars."""
    return [{"high": 100.0 + i * 0.5 + 0.5, "low": 100.0 + i * 0.5, "close": 100.0 + i * 0.5 + 0.3}
            for i in range(n)]


def _cand_row(ticker="AAPL", close=101.5, **over):
    r = {"ticker": ticker, "row_source": "top15_candidate", "signals": {},
         "price_input": {"close": close, "bars": _uptrend_bars()},
         "score_blocks": {"momentum": 70.0, "theme": 60.0, "catalyst": 50.0}}
    r.update(over)
    return r


def _hold_row(ticker="GOOG", close=110.5, **over):
    r = {"ticker": ticker, "row_source": "holding_in_top15", "signals": {},
         "price_input": {"close": close, "bars": _uptrend_bars()}}
    r.update(over)
    return r


def _run(rows, axes=None, **kw):
    return wa.analyze_rows(rows, market_axis_regimes=axes if axes is not None else _AGGRESSIVE, **kw)


class AnalyzeRowsTests(unittest.TestCase):
    # --- regime computed once + attached ---
    def test_regime_computed_once_and_attached(self):
        out = _run([_cand_row(), _hold_row()])
        self.assertEqual(out["regime"]["market_risk_regime"], "进攻")
        self.assertEqual(out["regime"]["position_cap"], 1.0)
        self.assertTrue(out["regime"]["new_entry_permitted"])
        self.assertEqual(len(out["rows"]), 2)

    def test_regime_degradation_missing_axis(self):
        out = _run([_cand_row()], axes={"vix": "进攻", "market_trend": "进攻"})  # breadth missing → +1 tier
        self.assertEqual(out["regime"]["market_risk_regime"], "震荡")
        self.assertEqual(out["regime"]["position_cap"], 0.8)

    def test_regime_restricted_no_axes(self):
        out = _run([_cand_row()], axes={})
        self.assertTrue(out["regime"]["restricted"])
        self.assertEqual(out["regime"]["market_risk_regime"], "极度防御")
        self.assertEqual(out["regime"]["position_cap"], 0.0)

    # --- §6 routing + price evidence ---
    def test_happy_candidate_executable(self):
        row = _run([_cand_row()])["rows"][0]
        self.assertEqual(row["row_context"], "candidate")
        self.assertEqual(row["price"]["price_engine_used"], "support_atr_engine")
        self.assertTrue(row["price"]["executable"])
        af = row["price"]["action_fields"]
        self.assertLess(af["stop_clear_price"], af["valid_entry_high"])
        self.assertGreater(af["take_profit_reduce_price"], af["valid_entry_high"])
        self.assertEqual(row["veto"]["veto_tier"], "none")

    def test_happy_holding_levels(self):
        row = _run([_hold_row(close=110.5)])["rows"][0]
        self.assertEqual(row["row_context"], "holding")
        self.assertEqual(row["price"]["price_engine_used"], "holding_exit_engine")
        self.assertTrue(row["price"]["executable"])
        self.assertFalse(row["price"]["trace"].get("breached"))
        self.assertIsNotNone(row["price"]["action_fields"]["stop_clear_price"])

    def test_holding_breached_surfaced(self):
        row = _run([_hold_row(close=101.5)])["rows"][0]  # close far below the trailing stop
        self.assertTrue(row["price"]["executable"])
        self.assertTrue(row["price"]["trace"]["breached"])

    # --- §5 veto evidence (NOT suppressed in this stage) ---
    def test_candidate_entry_hard_veto_is_evidence_only(self):
        row = _run([_cand_row(signals={"delisted": True})])["rows"][0]
        self.assertEqual(row["veto"]["veto_tier"], "entry_hard_veto")
        self.assertIn("price", row)  # price plan still computed as evidence; gating is 4d-ii-b

    def test_holding_position_hard_veto(self):
        row = _run([_hold_row(signals={"delisted": True})])["rows"][0]
        self.assertEqual(row["veto"]["veto_tier"], "position_hard_veto")

    def test_malformed_signals_fail_closed_soft_tag(self):
        row = _run([_cand_row(signals="not-a-dict")])["rows"][0]
        self.assertEqual(row["veto"]["veto_tier"], "soft_risk_tag")

    # --- §8 防御 sub_mode guard ---
    def test_submode_breakout_honored_aggressive(self):
        row = _run([_cand_row(sub_mode="breakout")])["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "breakout")
        self.assertFalse(row["sub_mode_downgraded"])
        self.assertEqual(row["price"]["action_fields"]["price_sub_mode"], "breakout")

    def test_submode_breakout_downgraded_defensive(self):
        row = _run([_cand_row(sub_mode="breakout")], axes=_DEFENSIVE)["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "pullback")
        self.assertTrue(row["sub_mode_downgraded"])
        self.assertEqual(row["price"]["action_fields"]["price_sub_mode"], "pullback")

    def test_submode_defensive_breakout_probe_allowed(self):
        row = _run([_cand_row(sub_mode="breakout", defensive_breakout_probe_allowed=True)],
                   axes=_DEFENSIVE)["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "breakout")
        self.assertFalse(row["sub_mode_downgraded"])

    def test_submode_extreme_defensive_never_breakout(self):
        row = _run([_cand_row(sub_mode="breakout", defensive_breakout_probe_allowed=True)],
                   axes=_EXTREME)["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "pullback")  # 极度防御 caps at 0 → never a new breakout
        self.assertTrue(row["sub_mode_downgraded"])

    def test_submode_absent_defaults_pullback(self):
        row = _run([_cand_row()])["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "pullback")
        self.assertFalse(row["sub_mode_downgraded"])

    def test_holding_submode_none(self):
        row = _run([_hold_row()])["rows"][0]
        self.assertIsNone(row["sub_mode_resolved"])
        self.assertFalse(row["sub_mode_downgraded"])

    def test_explicit_pullback_honored(self):
        row = _run([_cand_row(sub_mode="pullback")])["rows"][0]  # explicit valid pullback (positive control)
        self.assertEqual(row["sub_mode_resolved"], "pullback")
        self.assertFalse(row["sub_mode_downgraded"])

    def test_invalid_sub_mode_string_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(sub_mode="banana")])  # invalid mode must NOT silently become pullback

    def test_non_string_sub_mode_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(sub_mode=42)])

    def test_explicit_none_sub_mode_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(sub_mode=None)])  # present-but-None is malformed (omit the key to default pullback)

    def test_non_bool_probe_flag_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(sub_mode="breakout", defensive_breakout_probe_allowed="true")], axes=_DEFENSIVE)

    def test_holding_ignores_submode_fields(self):
        # sub_mode / probe are candidate-only — a holding row carrying junk values is NOT rejected for them
        row = _run([_hold_row(sub_mode="banana", defensive_breakout_probe_allowed="true")])["rows"][0]
        self.assertIsNone(row["sub_mode_resolved"])
        self.assertEqual(row["price"]["price_engine_used"], "holding_exit_engine")

    # --- §8.1 forward event + event-sensitive data gap ---
    def test_forward_event_in_window(self):
        row = _run([_cand_row(forward_event={"event_type": "earnings", "days_to_event": 5})])["rows"][0]
        self.assertTrue(row["forward_event"]["in_window"])
        self.assertEqual(row["forward_event"]["direction"], "reduce_or_observe")

    def test_forward_event_out_of_window(self):
        row = _run([_cand_row(forward_event={"event_type": "earnings", "days_to_event": 999})])["rows"][0]
        self.assertFalse(row["forward_event"]["in_window"])
        self.assertEqual(row["forward_event"]["direction"], "none")

    def test_forward_event_absent_none(self):
        self.assertIsNone(_run([_cand_row()])["rows"][0]["forward_event"])

    def test_forward_event_malformed_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(forward_event="not-a-dict")])

    def test_event_gap_biotech_restricted(self):
        row = _run([_cand_row(event_sensitive_type="biotech")])["rows"][0]  # has_event_data absent → missing
        self.assertEqual(row["event_data_gap"]["status"], "restricted")

    def test_event_gap_ordinary_tag(self):
        row = _run([_cand_row(event_sensitive_type="ordinary")])["rows"][0]
        self.assertEqual(row["event_data_gap"]["status"], "tag")

    def test_event_gap_has_data_ok(self):
        row = _run([_cand_row(event_sensitive_type="biotech", has_event_data=True)])["rows"][0]
        self.assertEqual(row["event_data_gap"]["status"], "ok")

    def test_event_gap_absent_none(self):
        self.assertIsNone(_run([_cand_row()])["rows"][0]["event_data_gap"])

    # --- §4.2 score ---
    def test_score_present(self):
        row = _run([_cand_row()])["rows"][0]
        self.assertGreater(row["score"]["core_score"], 0.0)
        self.assertEqual(row["score"]["profile"], "balanced")

    def test_score_absent_none(self):
        row = _cand_row()
        del row["score_blocks"]
        self.assertIsNone(_run([row])["rows"][0]["score"])

    def test_score_unknown_profile_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(scoring_profile="bogus_profile")])

    # --- canonical identity (one per stock) ---
    def test_ticker_canonicalized(self):
        row = _run([_cand_row(ticker=" aapl ")])["rows"][0]
        self.assertEqual(row["ticker"], "AAPL")

    def test_ticker_class_share_preserved(self):
        row = _run([_cand_row(ticker="BRK.B")])["rows"][0]
        self.assertEqual(row["ticker"], "BRK.B")

    def test_ticker_a_share_code_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(ticker="000001.SZ")])

    def test_duplicate_ticker_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(ticker="AAPL"), _hold_row(ticker="aapl")])  # same stock, two spellings

    # --- fail-closed container / row / row_source shapes ---
    def test_unknown_row_source_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(row_source="bogus_source")])

    def test_rows_not_list_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            wa.analyze_rows({"ticker": "AAPL"}, market_axis_regimes=_AGGRESSIVE)

    def test_row_not_dict_raises(self):
        with self.assertRaises(wa.WeekendAnalysisError):
            _run(["not-a-row"])

    def test_missing_ticker_raises(self):
        row = _cand_row()
        del row["ticker"]  # absent ticker → canonical_us_ticker(None) → None → fail closed (no AttributeError)
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([row])

    def test_malformed_price_input_degrades_to_observe(self):
        row = _run([_cand_row(price_input="not-a-dict")])["rows"][0]
        self.assertFalse(row["price"]["executable"])  # engine fail-closes to observe, no crash


if __name__ == "__main__":
    unittest.main()
