# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline sizing stage (engine/us_short_weekend_sizing.py) — batch4 slice 4d-ii-c.

Design authority: docs/us_short_system_design.md §8 (按风险定仓 + 削减叠法) / §9 / §18.2.

Covers the §8 削减叠法 over real analyze→decide→size chain output: a provisional 建仓 sized (base ×
regime cap × harshest discount, capped by single-ticker / liquidity), the single-ticker and liquidity
caps binding, the harshest discount applied, a below-min build downgrading to 观察 (极度防御 cap-0 →
capacity_or_budget_deferred, else cost_inefficient_min_size), non-建仓 rows carrying through with sizing=None, and fail-closed
value-validation of the injected sizing_context + each build row's price levels.

Deterministic chain numbers for _cand() in 进攻: valid_entry_high=101.5, stop_clear_price=99.42,
base=⌊100000×0.0075/2.08⌋=477, single_ticker_cap=⌊100000×0.10/101.5⌋=98.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_analysis as wa  # noqa: E402
import engine.us_short_weekend_decision as wd  # noqa: E402
import engine.us_short_weekend_sizing as ws  # noqa: E402

_AGG = {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"}


def _uptrend_bars(n=22):
    return [{"high": 100.0 + i * 0.5 + 0.5, "low": 100.0 + i * 0.5, "close": 100.0 + i * 0.5 + 0.3}
            for i in range(n)]


def _cand(ticker="AAPL", close=101.5, **over):
    r = {"ticker": ticker, "row_source": "top15_candidate", "signals": {},
         "price_input": {"close": close, "bars": _uptrend_bars()},
         "score_blocks": {"momentum": 70.0, "theme": 60.0, "catalyst": 50.0},
         "risk_downgrade": {"points": 0.0, "hard_veto": False, "components": {"history": 0.0, "current_event": 0.0, "analyst": 0.0}}}
    r.update(over)
    return r


def _hold(ticker="GOOG", close=110.5, **over):
    r = {"ticker": ticker, "row_source": "holding_in_top15", "signals": {},
         "price_input": {"close": close, "bars": _uptrend_bars()}}
    r.update(over)
    return r


def _sctx(bucket=100000.0, tickers=("AAPL",), discount=(1.0,), liquidity=100000):
    return {"short_bucket_dollars": bucket,
            "per_ticker": {t: {"discount_mults": list(discount), "liquidity_cap_shares": liquidity}
                           for t in tickers}}


def _size_real(rows, axes=_AGG, sctx=None):
    dec = wd.decide_actions(wa.analyze_rows(rows, market_axis_regimes=axes))
    if sctx is None:
        builds = [r["ticker"] for r in dec["rows"] if r["final_action"] == "建仓"] or ["AAPL"]
        sctx = _sctx(tickers=builds)
    return ws.size_rows(dec, sizing_context=sctx)


# --- direct decision_result builders for value-validation cases ---
def _build_row(ticker="AAPL", entry=101.5, stop=99.78, final="建仓", executable=True, row_context="candidate"):
    return {"ticker": ticker, "row_source": "top15_candidate", "row_context": row_context,
            "final_action": final, "observe_reason_type": None,
            "price": {"executable": executable, "trace": {}, "price_engine_used": "support_atr_engine",
                      "price_sub_mode": "pullback",
                      "action_fields": {"valid_entry_high": entry, "stop_clear_price": stop}},
            "veto": {"veto_tier": "none"}, "event_data_gap": None, "forward_event": None, "score": None}


def _decision(rows, position_cap=1.0):
    return {"regime": {"market_risk_regime": "进攻", "position_cap": position_cap}, "rows": rows}


class SizeRowsTests(unittest.TestCase):
    # --- sized build + caps ---
    def test_happy_build_sized_single_ticker_cap_binds(self):
        row = _size_real([_cand()])["rows"][0]
        self.assertEqual(row["final_action"], "建仓")
        s = row["sizing"]
        self.assertEqual(s["status"], "sized")
        self.assertEqual(s["base_shares"], 477)
        self.assertEqual(s["single_ticker_cap_shares"], 98)
        self.assertEqual(s["desired_model_shares"], 98)   # single-ticker cap binds (98 < base 477)

    def test_liquidity_cap_binds(self):
        row = _size_real([_cand()], sctx=_sctx(liquidity=50))["rows"][0]
        self.assertEqual(row["sizing"]["desired_model_shares"], 50)  # liquidity 50 < single-ticker 98

    def test_harshest_discount_applied_below_cap(self):
        row = _size_real([_cand()], sctx=_sctx(discount=(0.1, 0.8)))["rows"][0]  # harshest = 0.1
        self.assertEqual(row["final_action"], "建仓")
        self.assertEqual(row["sizing"]["desired_model_shares"], 47)  # ⌊477×1.0×0.1⌋=47, below the 98 cap

    def test_zero_discount_below_min_observes(self):
        row = _size_real([_cand()], sctx=_sctx(discount=(0.0,)))["rows"][0]
        self.assertEqual(row["final_action"], "观察")
        self.assertEqual(row["observe_reason_type"], "cost_inefficient_min_size")
        self.assertEqual(row["sizing"]["status"], "observe")
        self.assertEqual(row["sizing"]["desired_model_shares"], 0)

    def test_extreme_defensive_cap_zero_observes_capacity(self):
        row = _size_real([_cand()], axes={})["rows"][0]  # 极度防御 → position_cap 0 → 0 shares
        self.assertEqual(row["final_action"], "观察")
        # regime/position-cap zero is a CAPACITY/BUDGET deferral, NOT a cost/min-size inefficiency
        self.assertEqual(row["observe_reason_type"], "capacity_or_budget_deferred")
        self.assertEqual(row["sizing"]["regime_multiplier"], 0.0)

    # --- non-build rows carry through unsized ---
    def test_non_build_rows_carry_through_unsized(self):
        rows = _size_real([_cand("AAPL"), _cand("BIOX", event_sensitive_type="biotech"), _hold("GOOG")])["rows"]
        by = {r["ticker"]: r for r in rows}
        self.assertEqual(by["AAPL"]["final_action"], "建仓")
        self.assertIsNotNone(by["AAPL"]["sizing"])
        self.assertEqual(by["BIOX"]["final_action"], "观察")   # data_restricted observe — not sized
        self.assertIsNone(by["BIOX"]["sizing"])
        self.assertEqual(by["GOOG"]["final_action"], "持有")
        self.assertIsNone(by["GOOG"]["sizing"])

    def test_regime_carried(self):
        self.assertEqual(_size_real([_cand()])["regime"]["market_risk_regime"], "进攻")

    # --- fail-closed sizing_context value-validation ---
    def test_missing_per_ticker_entry_raises(self):
        dec = wd.decide_actions(wa.analyze_rows([_cand("AAPL")], market_axis_regimes=_AGG))
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(dec, sizing_context=_sctx(tickers=("OTHER",)))  # AAPL build has no sizing input

    def test_malformed_discount_mults_raises(self):
        for bad in ("not-a-list", [1.5], [-0.1], [float("nan")], [True]):
            with self.assertRaises(ws.WeekendSizingError):
                _size_real([_cand()], sctx={"short_bucket_dollars": 100000.0,
                                            "per_ticker": {"AAPL": {"discount_mults": bad,
                                                                    "liquidity_cap_shares": 100}}})

    def test_malformed_liquidity_cap_raises(self):
        for bad in (-1, 1.0, True, "100"):
            with self.assertRaises(ws.WeekendSizingError):
                _size_real([_cand()], sctx={"short_bucket_dollars": 100000.0,
                                            "per_ticker": {"AAPL": {"discount_mults": [1.0],
                                                                    "liquidity_cap_shares": bad}}})

    def test_per_ticker_entry_extra_key_raises(self):
        with self.assertRaises(ws.WeekendSizingError):
            _size_real([_cand()], sctx={"short_bucket_dollars": 100000.0,
                                        "per_ticker": {"AAPL": {"discount_mults": [1.0],
                                                                "liquidity_cap_shares": 100, "x": 1}}})

    def test_malformed_short_bucket_raises(self):
        for bad in (0.0, -100.0, float("inf"), "100k", True):
            with self.assertRaises(ws.WeekendSizingError):
                _size_real([_cand()], sctx={"short_bucket_dollars": bad,
                                            "per_ticker": {"AAPL": {"discount_mults": [1.0],
                                                                    "liquidity_cap_shares": 100}}})

    def test_sizing_context_wrong_top_keys_raises(self):
        with self.assertRaises(ws.WeekendSizingError):
            _size_real([_cand()], sctx={"short_bucket_dollars": 100000.0})  # missing per_ticker

    # --- decision_result / build-row validation (direct dicts) ---
    def test_invalid_build_levels_raise(self):
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(_decision([_build_row(entry=99.0, stop=100.0)]),  # entry <= stop
                         sizing_context=_sctx())

    def test_bad_position_cap_raises(self):
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(_decision([_build_row()], position_cap=1.5), sizing_context=_sctx())

    def test_malformed_decision_result_raises(self):
        for bad in ({"rows": []}, {"regime": {"position_cap": 1.0}}, {"regime": {"position_cap": 1.0}, "rows": {}}):
            with self.assertRaises(ws.WeekendSizingError):
                ws.size_rows(bad, sizing_context=_sctx())

    def test_malformed_decision_row_raises(self):
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(_decision([{"ticker": "AAPL", "final_action": "建仓"}]),  # missing price
                         sizing_context=_sctx())

    # --- decision-row VALUE contract + sizing-context coverage (Codex FAIL repair) ---
    def test_duplicate_build_ticker_raises(self):
        # same stock twice would each get its own capped size → bypasses the per-ticker cap
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(_decision([_build_row("AAPL"), _build_row("AAPL")]), sizing_context=_sctx(tickers=("AAPL",)))

    def test_stale_per_ticker_key_raises(self):
        sctx = {"short_bucket_dollars": 100000.0,
                "per_ticker": {"AAPL": {"discount_mults": [1.0], "liquidity_cap_shares": 100},
                               "STALE": {"discount_mults": [1.0], "liquidity_cap_shares": 100}}}
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(_decision([_build_row("AAPL")]), sizing_context=sctx)

    def test_unknown_final_action_raises(self):
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(_decision([_build_row(final="BANANA")]), sizing_context=_sctx())

    def test_non_executable_build_raises(self):
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(_decision([_build_row(executable=False)]), sizing_context=_sctx())

    def test_build_incompatible_row_context_raises(self):
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(_decision([_build_row(row_context="holding")]), sizing_context=_sctx())

    def test_non_canonical_ticker_raises(self):
        with self.assertRaises(ws.WeekendSizingError):
            ws.size_rows(_decision([_build_row("000001.SZ")]), sizing_context=_sctx(tickers=("000001.SZ",)))

    # --- every emitted ticker is canonical UPPERCASE (never echoed raw) ---
    def test_build_ticker_emitted_uppercase(self):
        out = ws.size_rows(_decision([_build_row("aapl")]), sizing_context=_sctx(tickers=("AAPL",)))
        self.assertEqual(out["rows"][0]["ticker"], "AAPL")   # lowercase input normalized on output
        self.assertEqual(out["rows"][0]["final_action"], "建仓")

    def test_non_build_ticker_emitted_canonical(self):
        out = ws.size_rows(_decision([_build_row(" goog ", final="持有", row_context="holding")]),
                           sizing_context={"short_bucket_dollars": 100000.0, "per_ticker": {}})
        self.assertEqual(out["rows"][0]["ticker"], "GOOG")   # whitespace + lowercase normalized on output


class SizeRowsOverextensionWarningTests(unittest.TestCase):
    # a large per-share risk (entry 101.5 − stop 90) makes the risk-budget BASE (65) bind below the single-ticker
    # cap (98), so the §4.3 warning reduce_size discount is visible in the final size. base = ⌊100000×0.0075/11.5⌋ = 65.
    def _row(self, state, *, reduce_size=True):
        row = _build_row(entry=101.5, stop=90.0)
        row["overextension"] = {
            "overextension_state": state, "strips_theme_score": state == "chasing_extreme",
            "execution_flags": ({"force_pullback": True, "reduce_size": reduce_size, "raise_rr_gate": True}
                                if state == "warning" else {})}
        return row

    def test_warning_reduce_size_shrinks_the_position(self):
        base = ws.size_rows(_decision([self._row("none")]), sizing_context=_sctx())["rows"][0]["sizing"]
        self.assertEqual(base["desired_model_shares"], 65)                      # un-reduced base binds
        warn = ws.size_rows(_decision([self._row("warning")]), sizing_context=_sctx())["rows"][0]
        self.assertEqual(warn["final_action"], "建仓")
        self.assertEqual(warn["sizing"]["desired_model_shares"], 32)            # 65 × 0.5 warning discount
        self.assertLess(warn["sizing"]["desired_model_shares"], base["desired_model_shares"])

    def test_chasing_and_absent_overextension_do_not_reduce(self):
        chasing = ws.size_rows(_decision([self._row("chasing_extreme")]), sizing_context=_sctx())["rows"][0]
        absent = ws.size_rows(_decision([_build_row(entry=101.5, stop=90.0)]), sizing_context=_sctx())["rows"][0]
        self.assertEqual(chasing["sizing"]["desired_model_shares"], 65)        # chasing carries NO reduce_size flag
        self.assertEqual(absent["sizing"]["desired_model_shares"], 65)         # no overextension field at all

    def test_warning_reduce_folds_into_harshest_not_multiplied(self):
        # an injected 0.3 discount is HARSHER than the 0.5 warning → harshest (0.3) wins, NOT 0.3×0.5.
        sized = ws.size_rows(_decision([self._row("warning")]), sizing_context=_sctx(discount=(0.3,)))["rows"][0]
        self.assertEqual(sized["sizing"]["desired_model_shares"], int(65 * 0.3))   # ⌊65×0.3⌋=19, not ⌊65×0.3×0.5⌋=9

    def test_malformed_present_overextension_fails_closed(self):
        for bad in ("warning", {"overextension_state": "bogus", "execution_flags": {}},
                    {"overextension_state": "warning", "execution_flags": "x"},
                    {"overextension_state": "warning", "strips_theme_score": True,
                     "execution_flags": {"force_pullback": True, "reduce_size": True, "raise_rr_gate": True}}):
            row = _build_row(entry=101.5, stop=90.0)
            row["overextension"] = bad
            with self.assertRaises(ws.WeekendSizingError):
                ws.size_rows(_decision([row]), sizing_context=_sctx())


if __name__ == "__main__":
    unittest.main()
