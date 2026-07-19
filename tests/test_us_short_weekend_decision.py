# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline action decision (engine/us_short_weekend_decision.py) — batch4 slice 4d-ii-b.

Design authority: docs/us_short_system_design.md §5 / §6 / §6.1 / §9 / §8.1 / §18.2.

Covers the §6 priority chain → §9 final_action over real 4d-ii-a analysis evidence: holding clear/hold
(event veto / breach / hold), candidate reject / observe(data_restricted, price_not_executable) /
provisional 建仓, veto-precedence ordering, the PROVISIONAL nature of 建仓 (regime / forward do not block
here — deferred to sizing/basket), frozen-vocab triangulation (emitted subset ⊆ contract + action_group
compatible), and fail-closed evidence shapes.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_analysis as wa  # noqa: E402
import engine.us_short_weekend_decision as wd  # noqa: E402
from engine.us_short_action_rank import action_group  # noqa: E402

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


def _decide(rows, axes=None):
    return wd.decide_actions(wa.analyze_rows(rows, market_axis_regimes=axes if axes is not None else _AGG))


class DecideActionsTests(unittest.TestCase):
    # --- holdings ---
    def test_holding_clean_holds(self):
        row = _decide([_hold(close=110.5)])["rows"][0]
        self.assertEqual(row["final_action"], "持有")
        self.assertIsNone(row["observe_reason_type"])

    def test_holding_position_hard_veto_event_clear(self):
        row = _decide([_hold(signals={"delisted": True})])["rows"][0]
        self.assertEqual(row["final_action"], "清仓-事件")

    def test_holding_breached_stop_clear(self):
        row = _decide([_hold(close=101.5)])["rows"][0]  # close far below trailing stop → breached
        self.assertEqual(row["final_action"], "清仓-止损")

    def test_holding_veto_precedes_breach(self):
        # both a hard position veto AND a breach → event clear takes precedence (can't trade a delisted name)
        row = _decide([_hold(close=101.5, signals={"delisted": True})])["rows"][0]
        self.assertEqual(row["final_action"], "清仓-事件")

    # --- candidates ---
    def test_candidate_clean_provisional_build(self):
        row = _decide([_cand()])["rows"][0]
        self.assertEqual(row["final_action"], "建仓")
        self.assertIsNone(row["observe_reason_type"])

    def test_candidate_entry_hard_veto_rejected(self):
        row = _decide([_cand(signals={"delisted": True})])["rows"][0]
        self.assertEqual(row["final_action"], "否决/避开")

    def test_candidate_data_restricted_observed(self):
        row = _decide([_cand(event_sensitive_type="biotech")])["rows"][0]  # missing FDA → restricted
        self.assertEqual(row["final_action"], "观察")
        self.assertEqual(row["observe_reason_type"], "data_restricted")

    def test_candidate_price_not_executable_observed(self):
        row = _decide([_cand(price_input={"close": 101.5, "bars": []})])["rows"][0]  # no ATR → not executable
        self.assertEqual(row["final_action"], "观察")
        self.assertEqual(row["observe_reason_type"], "price_not_executable")

    def test_candidate_veto_precedes_price(self):
        # entry hard veto + a non-executable price → reject (veto outranks the price gate)
        row = _decide([_cand(signals={"delisted": True}, price_input={"close": 101.5, "bars": []})])["rows"][0]
        self.assertEqual(row["final_action"], "否决/避开")

    def test_candidate_data_restricted_precedes_price(self):
        # restricted sensitive data + non-executable price → data_restricted (don't trade the name regardless)
        row = _decide([_cand(event_sensitive_type="biotech", price_input={"close": 101.5, "bars": []})])["rows"][0]
        self.assertEqual(row["final_action"], "观察")
        self.assertEqual(row["observe_reason_type"], "data_restricted")

    # --- forward / reduce_caution do NOT block the provisional build (deferred to sizing) ---
    def test_candidate_forward_event_still_builds(self):
        row = _decide([_cand(forward_event={"event_type": "earnings", "days_to_event": 5})])["rows"][0]
        self.assertEqual(row["final_action"], "建仓")  # forward → sizing discount downstream, not a block here

    def test_candidate_reduce_caution_gap_still_builds(self):
        row = _decide([_cand(event_sensitive_type="recent_ipo")])["rows"][0]  # reduce_caution, not restricted
        self.assertEqual(row["final_action"], "建仓")

    def test_extreme_defensive_candidate_still_builds_provisionally(self):
        # 极度防御 caps new entry at 0, but that downgrade is the basket build-limit's job (4d-ii-d), NOT here
        out = _decide([_cand()], axes={})
        self.assertEqual(out["regime"]["market_risk_regime"], "极度防御")
        self.assertEqual(out["rows"][0]["final_action"], "建仓")

    # --- evidence carried through (additive) + regime carried ---
    def test_evidence_carried_through(self):
        row = _decide([_cand()])["rows"][0]
        for k in ("ticker", "row_source", "row_context", "veto", "price", "score", "sub_mode_resolved"):
            self.assertIn(k, row)

    def test_regime_carried(self):
        out = _decide([_cand()])
        self.assertEqual(out["regime"]["market_risk_regime"], "进攻")

    # --- frozen-vocab triangulation ---
    def test_emitted_vocab_within_frozen_contract(self):
        emitted = {wd._A_REJECT, wd._A_OBSERVE, wd._A_BUILD, wd._A_HOLD, wd._A_CLEAR_EVENT, wd._A_CLEAR_STOP}
        self.assertTrue(emitted <= set(wd.FINAL_ACTIONS))
        self.assertNotIn("加仓", emitted)
        self.assertTrue({wd._R_DATA_RESTRICTED, wd._R_PRICE_NOT_EXEC} <= set(wd.OBSERVE_REASONS))
        for a in emitted:
            action_group(a)  # every emitted final_action must be rank_actions-compatible (no ValueError)

    def test_all_emitted_actions_are_valid(self):
        dc = [_cand(), _cand(ticker="MSF", signals={"delisted": True}), _cand(ticker="BIOX", event_sensitive_type="biotech"),
              _hold(), _hold(ticker="NFLX", signals={"delisted": True}), _hold(ticker="TSLA", close=101.5)]
        for row in _decide(dc)["rows"]:
            self.assertIn(row["final_action"], wd.FINAL_ACTIONS)
            action_group(row["final_action"])
            if row["observe_reason_type"] is not None:
                self.assertIn(row["observe_reason_type"], wd.OBSERVE_REASONS)

    # --- fail-closed shapes ---
    def test_non_dict_analysis_result_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            wd.decide_actions(["not", "a", "result"])

    def test_missing_regime_or_rows_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            wd.decide_actions({"rows": []})
        with self.assertRaises(wd.WeekendDecisionError):
            wd.decide_actions({"regime": {}})

    def test_rows_not_list_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            wd.decide_actions({"regime": {}, "rows": {"ticker": "AAPL"}})

    def test_malformed_evidence_row_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            wd.decide_actions({"regime": {}, "rows": [{"ticker": "AAPL"}]})  # missing row_context/veto/price


_ABSENT = object()


def _ev(row_context="candidate", veto_tier="none", executable=True, breached=_ABSENT,
        gap_status=_ABSENT, veto_ctx=_ABSENT):
    """Hand-crafted 4d-ii-a evidence row (bypasses analyze_rows so VALUE-level malformation can be injected)."""
    trace = {} if breached is _ABSENT else {"breached": breached}
    veto = {"veto_tier": veto_tier, "reasons": [], "effect": None,
            "row_context": row_context if veto_ctx is _ABSENT else veto_ctx}
    return {
        "ticker": "AAPL",
        "row_source": "top15_candidate" if row_context == "candidate" else "holding_in_top15",
        "row_context": row_context, "veto": veto,
        "price": {"executable": executable, "trace": trace, "action_fields": {},
                  "reject_reason": None, "price_engine_used": "x", "price_sub_mode": None},
        "event_data_gap": None if gap_status is _ABSENT else {"status": gap_status},
        "forward_event": None, "score": None, "sub_mode_resolved": None, "sub_mode_downgraded": False,
    }


def _act(ev):
    return wd.decide_actions({"regime": {"market_risk_regime": "进攻"}, "rows": [ev]})["rows"][0]


class EvidenceValueValidationTests(unittest.TestCase):
    # --- positive controls (valid hand-crafted evidence still maps correctly) ---
    def test_valid_candidate_builds(self):
        self.assertEqual(_act(_ev())["final_action"], "建仓")

    def test_valid_holding_holds(self):
        self.assertEqual(_act(_ev("holding", executable=True, breached=False))["final_action"], "持有")

    def test_valid_holding_breached_clears(self):
        self.assertEqual(_act(_ev("holding", breached=True))["final_action"], "清仓-止损")

    def test_valid_holding_position_veto_event_clears(self):
        ev = _ev("holding", veto_tier="position_hard_veto", executable=True, breached=False)
        self.assertEqual(_act(ev)["final_action"], "清仓-事件")

    # --- NEW: a non-executable (data-degraded) holding is NOT a clean hold (§6) ---
    def test_holding_non_executable_observes(self):
        row = _act(_ev("holding", executable=False))  # no computable levels
        self.assertEqual(row["final_action"], "观察")
        self.assertEqual(row["observe_reason_type"], "price_not_executable")

    # --- malformed VALUE → fail closed (never a clean action) ---
    def test_invalid_veto_tier_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            _act(_ev(veto_tier="banana"))

    def test_none_veto_tier_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            _act(_ev(veto_tier=None))

    def test_missing_veto_tier_raises(self):
        ev = _ev()
        del ev["veto"]["veto_tier"]
        with self.assertRaises(wd.WeekendDecisionError):
            _act(ev)

    def test_candidate_position_hard_veto_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            _act(_ev("candidate", veto_tier="position_hard_veto"))  # context-incompatible tier

    def test_holding_entry_hard_veto_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            _act(_ev("holding", veto_tier="entry_hard_veto"))  # context-incompatible tier

    def test_veto_row_context_mismatch_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            _act(_ev("candidate", veto_ctx="holding"))

    def test_non_bool_executable_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            _act(_ev(executable="false"))

    def test_executable_holding_missing_breached_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            _act(_ev("holding", executable=True, breached=_ABSENT))

    def test_non_bool_breached_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            _act(_ev("holding", executable=True, breached="false"))  # truthy string must not pass as a breach

    def test_unknown_event_gap_status_raises(self):
        with self.assertRaises(wd.WeekendDecisionError):
            _act(_ev(gap_status="banana"))

    # --- vocab triangulation: the decision's accepted vocab covers what the source engines emit ---
    def test_veto_tier_vocab_covers_engine_outputs(self):
        from engine.us_short_hard_veto import classify_hard_veto
        cases = [{}, {"delisted": True}, {"high_si": True},
                 {"active_offering": {"recency": "recent", "status": "active", "materiality": None}},
                 {"semantic_audit": {"available": True, "adverse": True, "confidence": "high"}},
                 {"semantic_audit": {"available": False}}]
        for ctx in ("candidate", "holding"):
            for sig in cases:
                self.assertIn(classify_hard_veto(sig, ctx)["veto_tier"], wd._VALID_VETO_TIERS)

    def test_event_gap_status_vocab_covers_engine_outputs(self):
        from engine.us_short_forward_events import event_data_gap_status
        for est in (None, "biotech", "recent_ipo", "spac", "ordinary", "weird", 123):
            for has in (True, False, None, "x"):
                self.assertIn(event_data_gap_status(est, has)["status"], wd._EVENT_GAP_STATUSES)


class ActionPriceContractTests(unittest.TestCase):
    """R-USSHORT-BATCH4-ACTION-PRICE-MAPPING-GAP: the §9 action↔price 一一对应 matrix is single-source
    (ACTION_REQUIRED_PRICE_FIELDS / action_price_error), covers ALL 9 frozen actions (incl. the v1-deferred
    加仓/减仓/清仓-止盈 so a later activation cannot bypass the gate), lands only on real §11.3 columns, and
    rejects a priced action whose required price is missing / non-positive / non-finite / wrong-type."""

    # --- triangulation: exactly the frozen vocab + only real §11.3 columns (no third drift surface) ---
    def test_matrix_keys_are_exactly_the_frozen_actions(self):
        self.assertEqual(set(wd.ACTION_REQUIRED_PRICE_FIELDS), set(wd.FINAL_ACTIONS))

    def test_required_fields_are_frozen_action_table_columns(self):
        from engine.us_short_action_table_renderer import action_table_columns
        cols = set(action_table_columns())
        for action, fields in wd.ACTION_REQUIRED_PRICE_FIELDS.items():
            for f in fields:
                self.assertIn(f, cols, f"{action} required price {f} must be a frozen §11.3 column")

    def test_na_actions_require_no_price(self):
        for a in ("持有", "观察", "否决/避开"):
            self.assertEqual(wd.ACTION_REQUIRED_PRICE_FIELDS[a], ())
            self.assertIsNone(wd.action_price_error(a, {}))
            self.assertIsNone(wd.action_price_error(a, None))   # N/A: action_fields irrelevant

    # --- per priced action: one positive + the missing / non-positive / non-finite / wrong-type reverse set ---
    def test_every_priced_action_positive_and_reverse(self):
        priced = {a: f for a, f in wd.ACTION_REQUIRED_PRICE_FIELDS.items() if f}
        self.assertEqual(set(priced), {"建仓", "加仓", "减仓", "清仓-止损", "清仓-止盈", "清仓-事件"})
        for action, fields in priced.items():
            good = {f: 10.0 for f in fields}
            self.assertIsNone(wd.action_price_error(action, good), f"{action} positive must pass")
            self.assertIsNotNone(wd.action_price_error(action, None), f"{action} non-dict action_fields rejected")
            for f in fields:
                for bad in (None, 0.0, -1.0, float("nan"), float("inf"), "10.0", True):
                    self.assertIsNotNone(wd.action_price_error(action, {**good, f: bad}),
                                         f"{action} with {f}={bad!r} must be rejected")

    def test_event_clear_requires_event_reference_price(self):
        self.assertIsNone(wd.action_price_error("清仓-事件", {"event_clear_reference_price": 8.0}))
        self.assertIsNotNone(wd.action_price_error("清仓-事件", {"event_clear_reference_price": None}))
        self.assertIsNotNone(wd.action_price_error("清仓-事件", {}))


if __name__ == "__main__":
    unittest.main()
