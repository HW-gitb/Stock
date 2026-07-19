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
         "score_blocks": {"momentum": 70.0, "theme": 60.0, "catalyst": 50.0},
         "risk_downgrade": {"points": 0.0, "hard_veto": False, "components": {"history": 0.0, "current_event": 0.0, "analyst": 0.0}}}
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


class RiskDowngradeWiring(unittest.TestCase):
    """R-USSHORT-BATCH4-RISK-DOWNGRADE-WIRING-GAP: the §4.2 soft risk_downgrade is now SUBTRACTED in the weekend
    core_score; a scored candidate must carry the closed-world typed input (missing/malformed fails closed)."""

    def _rd(self, points, **comp):
        c = {"history": 0.0, "current_event": 0.0, "analyst": 0.0}
        c.update(comp)
        return {"points": points, "hard_veto": False, "components": c}

    def test_zero_penalty_leaves_core_score_unchanged(self):
        # blocks 70/60/50 @ balanced 40/35/25 → 61.5; zero penalty leaves it
        row = _run([_cand_row(risk_downgrade=self._rd(0.0))])["rows"][0]
        self.assertAlmostEqual(row["score"]["core_score"], 61.5, places=6)
        self.assertEqual(row["risk_downgrade"], {"points": 0.0, "hard_veto": False,
                         "components": {"history": 0.0, "current_event": 0.0, "analyst": 0.0}})

    def test_penalty_lowers_selection_priority(self):
        # the §4.2 penalty's §10 terminal is action_rank (group-2 builds order by selection_rank, set from
        # core_score). A candidate whose core_score is penalized below a competitor ranks AFTER it — proving the
        # terminal PRIORITY demonstrably changes (not just field-record metadata).
        from engine.us_short_weekend_pipeline import _select_top15
        clean = _run([_cand_row(ticker="AAA", risk_downgrade=self._rd(0.0))])["rows"][0]["score"]["core_score"]
        pen = _run([_cand_row(ticker="BBB", risk_downgrade=self._rd(15.0, history=15.0))])["rows"][0]["score"]["core_score"]
        self.assertLess(pen, clean)   # 46.5 < 61.5: the penalty lowered the action_rank-driving value
        per = {"AAA": {"core_score": clean, "theme_momentum_score": 0.0},
               "BBB": {"core_score": pen, "theme_momentum_score": 0.0}}
        si = {"theme_opportunity_state": "no_strong_theme",
              "theme_selection_contract": {"as_of": "20260615", "mode": "industry_heat_v1_cross_industry_disabled",
                  "cross_industry_provisional_enabled": False, "theme_opportunity_state": "no_strong_theme",
                  "per_ticker": {ticker: {"theme_id": f"industry:{ticker.lower()}", "theme_source": "industry_heat_v1",
                      "theme_lifecycle_state": "confirmed_active", "theme_leader_rs": 0.0,
                      "membership_origin": "automatic_discovery", "market_confirmed": True,
                      "individual_theme_gate_passed": True, "overextension_state": "none",
                      "macro_cluster": "unclassified_conservative"} for ticker in per}},
              "per_ticker": per}
        ranks = {d["ticker"]: d["selection_rank"] for d in _select_top15(["AAA", "BBB"], si, decision_date="20260615")["selection_details"]}
        self.assertLess(ranks["AAA"], ranks["BBB"])   # the penalized BBB ranks AFTER the clean AAA

    def test_nonzero_penalty_subtracted_from_core_score(self):
        base = _run([_cand_row(risk_downgrade=self._rd(0.0))])["rows"][0]["score"]["core_score"]
        pen = _run([_cand_row(risk_downgrade=self._rd(10.0, current_event=10.0))])["rows"][0]
        self.assertAlmostEqual(pen["score"]["core_score"], base - 10.0, places=6)   # 61.5 → 51.5
        self.assertEqual(pen["risk_downgrade"]["points"], 10.0)
        self.assertLess(pen["score"]["core_score"], base)                           # rank-affecting: lower score

    def test_scored_candidate_missing_risk_downgrade_fails_closed(self):
        bad = _cand_row()
        del bad["risk_downgrade"]
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([bad])

    def test_malformed_risk_downgrade_fails_closed(self):
        _C = {"history": 0.0, "current_event": 0.0, "analyst": 0.0}
        for rd in (None,
                   {"points": -1.0, "hard_veto": False, "components": _C},                       # negative
                   {"points": 5.0, "hard_veto": False, "components": {"history": 1.0, "current_event": 1.0, "analyst": 1.0}},  # points!=Σ
                   {"points": 0.0, "hard_veto": False, "components": {"history": 0.0}},           # bad component shape
                   {"points": "0", "hard_veto": False, "components": _C},                         # numeric string
                   {"points": 5.0, "hard_veto": True, "components": {"history": 5.0, "current_event": 0.0, "analyst": 0.0}},  # never hard veto
                   {"points": 0.0, "components": _C},                                             # MISSING hard_veto (closed-world)
                   {"points": 0.0, "hard_veto": False, "components": _C, "extra": 1}):            # EXTRA top-level key
            with self.assertRaises(wa.WeekendAnalysisError):
                _run([_cand_row(risk_downgrade=rd)])

    def test_same_run_reconciliation_uses_penalized_score(self):
        # a selection_record core_score must equal the PENALIZED analysis core_score (one core_score per run)
        rd = self._rd(10.0, current_event=10.0)
        sel = {"selection_rank": 1, "selection_bucket": "core_top", "core_score": 51.5, "theme_momentum_score": 0.0}
        ok = _run([_cand_row(risk_downgrade=rd, selection_record=sel)])["rows"][0]
        self.assertAlmostEqual(ok["score"]["core_score"], 51.5, places=6)
        bad_sel = {**sel, "core_score": 61.5}   # the UNPENALIZED score now forks → fail closed
        with self.assertRaises(wa.WeekendAnalysisError):
            _run([_cand_row(risk_downgrade=rd, selection_record=bad_sel)])

    def test_holding_has_no_risk_downgrade(self):
        row = _run([_hold_row()])["rows"][0]
        self.assertIsNone(row["risk_downgrade"])
        self.assertIsNone(row["score"])


_OX_WARNING = {"overextension_state": "warning", "strips_theme_score": False,
               "execution_flags": {"force_pullback": True, "reduce_size": True, "raise_rr_gate": True},
               "conditions_met": 0, "condition_names": []}
_OX_CHASING = {"overextension_state": "chasing_extreme", "strips_theme_score": True, "execution_flags": {},
               "conditions_met": 3, "condition_names": ["vertical_run", "volume_climax", "far_above_all_mas"]}
_OX_NONE = {"overextension_state": "none", "strips_theme_score": False, "execution_flags": {},
            "conditions_met": 0, "condition_names": []}


class OverextensionWiring(unittest.TestCase):
    """cut 2c: the §4.3 overextension EXECUTION lever — `warning` forces pullback entry (no breakout chase), and
    the tier result rides onto the evidence row for the §11.3 column (cut 2d). chasing_extreme's effect is the
    SELECTION theme-strip (Slice B), NOT here — it carries no execution_flags, so no execution effect at this stage."""

    def test_warning_forces_pullback_over_breakout(self):
        # aggressive regime normally honors breakout; the §4.3 warning must force pullback (不追突破).
        row = _run([_cand_row(sub_mode="breakout", overextension=_OX_WARNING)])["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "pullback")
        self.assertTrue(row["overextension_forced_pullback"])
        self.assertEqual(row["price"]["action_fields"]["price_sub_mode"], "pullback")

    def test_warning_on_pullback_request_is_noop(self):
        row = _run([_cand_row(sub_mode="pullback", overextension=_OX_WARNING)])["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "pullback")
        self.assertFalse(row["overextension_forced_pullback"])   # already pullback → nothing to force

    def test_chasing_extreme_has_no_execution_effect_here(self):
        # chasing_extreme carries NO execution_flags (its theme-strip is Slice B) → a breakout is NOT forced down.
        row = _run([_cand_row(sub_mode="breakout", overextension=_OX_CHASING)])["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "breakout")
        self.assertFalse(row["overextension_forced_pullback"])

    def test_none_state_has_no_effect(self):
        row = _run([_cand_row(sub_mode="breakout", overextension=_OX_NONE)])["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "breakout")
        self.assertFalse(row["overextension_forced_pullback"])

    def test_state_rides_onto_candidate_row(self):
        row = _run([_cand_row(overextension=_OX_WARNING)])["rows"][0]
        self.assertEqual(row["overextension"], _OX_WARNING)

    def test_state_rides_onto_holding_row_no_submode_effect(self):
        row = _run([_hold_row(overextension=_OX_WARNING)])["rows"][0]
        self.assertEqual(row["overextension"], _OX_WARNING)
        self.assertIsNone(row["sub_mode_resolved"])              # holdings have no new-entry sub_mode
        self.assertFalse(row["overextension_forced_pullback"])

    def test_absent_overextension_is_none_noop(self):
        row = _run([_cand_row(sub_mode="breakout")])["rows"][0]   # no overextension injected
        self.assertIsNone(row["overextension"])
        self.assertFalse(row["overextension_forced_pullback"])
        self.assertEqual(row["sub_mode_resolved"], "breakout")

    def test_warning_composes_with_defensive_downgrade(self):
        # §8 defensive already downgrades breakout→pullback; the overextension warning is then a no-op force
        # (both only ever force breakout→pullback — no conflict). Outcome: pullback, downgraded by §8.
        row = _run([_cand_row(sub_mode="breakout", overextension=_OX_WARNING)], axes=_DEFENSIVE)["rows"][0]
        self.assertEqual(row["sub_mode_resolved"], "pullback")
        self.assertTrue(row["sub_mode_downgraded"])              # §8 defensive did the downgrade
        self.assertFalse(row["overextension_forced_pullback"])  # already pullback before the overext check

    def test_malformed_overextension_fails_closed(self):
        for bad in ("not-a-dict", 42,
                    {"overextension_state": "bogus", "execution_flags": {}},          # illegal state
                    {"overextension_state": "warning", "execution_flags": "nope"},    # execution_flags not a dict
                    {"execution_flags": {}},                                           # missing state
                    {**_OX_WARNING, "strips_theme_score": True},                       # warning must never strip
                    {**_OX_NONE, "execution_flags": dict(_OX_WARNING["execution_flags"])}):  # none must be inert
            with self.assertRaises(wa.WeekendAnalysisError):
                _run([_cand_row(overextension=bad)])

    def test_warning_raises_the_rr_gate_via_the_price_engine(self):
        # a §4.3 `warning` tier → _analyze_one passes raise_rr_gate to the §6 price engine → a borderline RR (1.636)
        # that PASSES the base 进攻 floor 1.5 now OBSERVES (fails the raised floor 2.0); a `none`/absent tier does not.
        ind = {"effective_support": 98.0, "support_quality": "strong", "effective_resistance": 109.0,
               "resistance_quality": "strong", "atr": 2.0}
        px = {"close": 100.0, "indicators": ind}
        out = {r["ticker"]: r for r in _run([
            _cand_row(ticker="AAPL", overextension=_OX_WARNING, price_input=px),
            _cand_row(ticker="MSFT", price_input=px)])["rows"]}
        self.assertFalse(out["AAPL"]["price"]["executable"])            # warning raised the RR gate → observe
        self.assertEqual(out["AAPL"]["price"]["action_fields"]["min_rr_gate_status"], "fail_below_floor")
        self.assertTrue(out["MSFT"]["price"]["executable"])            # none/absent → base floor → executable


if __name__ == "__main__":
    unittest.main()
