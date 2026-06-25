# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline theme_probe cost floor (engine/us_short_weekend_cost_floor.py) — batch4 slice 4d-ii-h.

Design authority: docs/us_short_system_design.md §8 (line 232 最小仓成本地板, 真拦单) / §9 / §18.2.

Covers: a promoted theme_probe that clears the cost floor stays 建仓; one whose min-size profit-to-盈一 ≤
round-trip cost × safety multiple is downgraded to 观察(cost_inefficient_min_size) with build_count
recomputed and theme_probe / sizing / selection_rank kept as trace; base builds + non-建仓 rows carry
through untouched; degenerate geometry (tp1 ≤ entry) and malformed cost values fail closed to 观察;
canonical-unique ticker identity (non-canonical / duplicate rejected, lowercase canonicalized) + promoted-probe
trace VALUE validation (risk_tag / entry_mode_constraint) + the entry-mode⟺engine triangulation; and
fail-closed basket_result / row / §9 action-reason / cost_inputs-coverage validation.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_cost_floor as cf  # noqa: E402
import engine.us_short_theme_probe as tp_engine  # noqa: E402
from engine.us_short_position_sizing import MIN_EXECUTABLE_SHARES  # noqa: E402


def _probe(ticker, *, shares=1, entry=100.0, tp1=110.0, rank=2):
    return {"ticker": ticker, "final_action": "建仓", "observe_reason_type": None, "selection_rank": rank,
            "price": {"executable": True,
                      "action_fields": {"valid_entry_high": entry, "take_profit_reduce_price": tp1}},
            "sizing": {"desired_model_shares": shares, "status": "sized",
                       "reason": "theme_probe_forced_min", "pre_probe_risk_shares": 50},
            "theme_probe": {"risk_tag": "theme_probe_min_size", "entry_mode_constraint": "pullback_only"}}


def _base(ticker, rank=1):
    return {"ticker": ticker, "final_action": "建仓", "observe_reason_type": None, "selection_rank": rank,
            "sizing": {"desired_model_shares": 50, "status": "sized"}}


def _obs(ticker):
    return {"ticker": ticker, "final_action": "观察", "observe_reason_type": "capacity_or_budget_deferred",
            "selection_rank": 9}


def _result(rows, regime="防御"):
    return {"regime": {"market_risk_regime": regime, "position_cap": 0.5}, "rows": rows,
            "weekly_build_limit": 1, "build_count": sum(1 for r in rows if r["final_action"] == "建仓")}


def _ci(commission=1.0, slippage=0.5, spread=0.5):
    return {"commission_round_trip": commission, "slippage_dollars": slippage, "spread_dollars": spread}


def _by(out):
    return {r["ticker"]: r for r in out["rows"]}


class ApplyProbeCostFloorTests(unittest.TestCase):
    # --- probe clears / fails the cost floor ---
    def test_probe_clears_cost_floor_stays_build(self):
        # profit = 1 * (110 - 100) = 10; cost = 2; 10 > 2 * 3 = 6 → cleared.
        out = cf.apply_probe_cost_floor(_result([_base("AAA"), _probe("BBB")]), cost_inputs={"BBB": _ci()})
        by = _by(out)
        self.assertEqual(by["BBB"]["final_action"], "建仓")
        self.assertIsNone(by["BBB"]["observe_reason_type"])
        self.assertEqual(out["build_count"], 2)

    def test_probe_below_cost_floor_downgraded_to_observe(self):
        # profit = 10; cost = 4; 10 <= 4 * 3 = 12 → blocked → 观察(cost_inefficient_min_size).
        out = cf.apply_probe_cost_floor(_result([_base("AAA"), _probe("BBB")]),
                                        cost_inputs={"BBB": _ci(2.0, 1.0, 1.0)})
        by = _by(out)
        self.assertEqual(by["BBB"]["final_action"], "观察")
        self.assertEqual(by["BBB"]["observe_reason_type"], "cost_inefficient_min_size")
        self.assertEqual(out["build_count"], 1)   # recomputed: only the base build remains

    def test_cost_floored_probe_keeps_trace(self):
        out = cf.apply_probe_cost_floor(_result([_probe("BBB")]), cost_inputs={"BBB": _ci(2.0, 1.0, 1.0)})
        probe = _by(out)["BBB"]
        self.assertEqual(probe["final_action"], "观察")
        self.assertIn("theme_probe", probe)                       # theme_probe metadata kept as trace
        self.assertEqual(probe["sizing"]["desired_model_shares"], 1)   # forced-min sizing kept
        self.assertEqual(probe["selection_rank"], 2)              # rank kept

    def test_multiple_probes_mixed(self):
        rows = [_base("AAA"), _probe("BBB", entry=100.0, tp1=130.0), _probe("CCC", entry=100.0, tp1=101.0)]
        # BBB profit 30 > 6 cleared; CCC profit 1 <= 6 blocked.
        out = cf.apply_probe_cost_floor(_result(rows), cost_inputs={"BBB": _ci(), "CCC": _ci()})
        by = _by(out)
        self.assertEqual(by["BBB"]["final_action"], "建仓")
        self.assertEqual(by["CCC"]["final_action"], "观察")
        self.assertEqual(by["CCC"]["observe_reason_type"], "cost_inefficient_min_size")
        self.assertEqual(out["build_count"], 2)   # AAA base + BBB probe

    # --- carry-through: base builds + non-建仓 rows are untouched ---
    def test_base_build_not_cost_floored(self):
        # a base build (no theme_probe) carries through even with a tiny notional — the floor is probe-only.
        out = cf.apply_probe_cost_floor(_result([_base("AAA")]), cost_inputs={})
        self.assertEqual(_by(out)["AAA"]["final_action"], "建仓")
        self.assertEqual(out["build_count"], 1)

    def test_non_build_rows_carry_through(self):
        out = cf.apply_probe_cost_floor(_result([_obs("OBS"), _probe("BBB")]), cost_inputs={"BBB": _ci()})
        by = _by(out)
        self.assertEqual(by["OBS"]["final_action"], "观察")
        self.assertEqual(by["OBS"]["observe_reason_type"], "capacity_or_budget_deferred")   # unchanged

    def test_no_probes_empty_cost_inputs(self):
        out = cf.apply_probe_cost_floor(_result([_base("AAA"), _obs("OBS")]), cost_inputs={})
        self.assertEqual(out["build_count"], 1)

    # --- conservative fail-closed geometry / cost ---
    def test_degenerate_geometry_blocks(self):
        # tp1 <= entry (110 <= 110) → apply_cost_floor unverifiable → 观察 (conservative).
        out = cf.apply_probe_cost_floor(_result([_probe("BBB", entry=110.0, tp1=110.0)]),
                                        cost_inputs={"BBB": _ci()})
        self.assertEqual(_by(out)["BBB"]["observe_reason_type"], "cost_inefficient_min_size")

    def test_malformed_cost_value_blocks(self):
        # a negative / non-finite cost component → apply_cost_floor blocks → 观察 (never a clean build).
        out = cf.apply_probe_cost_floor(_result([_probe("BBB")]),
                                        cost_inputs={"BBB": _ci(commission=-1.0)})
        self.assertEqual(_by(out)["BBB"]["final_action"], "观察")

    # --- fail-closed shape / coverage ---
    def test_malformed_basket_result_raises(self):
        for bad in ({"rows": []}, {"regime": {}}, {"regime": {}, "rows": {}}):
            with self.assertRaises(cf.WeekendCostFloorError):
                cf.apply_probe_cost_floor(bad, cost_inputs={})

    def test_bad_final_action_raises(self):
        row = _probe("BBB")
        row["final_action"] = "BANANA"
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})

    def test_cost_inputs_missing_probe_raises(self):
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([_probe("BBB")]), cost_inputs={})   # probe BBB not covered

    def test_cost_inputs_stale_key_raises(self):
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([_probe("BBB")]),
                                      cost_inputs={"BBB": _ci(), "ZZZ": _ci()})   # ZZZ not a probe

    def test_cost_inputs_for_base_build_raises(self):
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([_base("AAA")]), cost_inputs={"AAA": _ci()})   # base is not a probe

    def test_bad_cost_inputs_shape_raises(self):
        for bad in (None, {"commission_round_trip": 1.0}, {**_ci(), "x": 1}):
            with self.assertRaises(cf.WeekendCostFloorError):
                cf.apply_probe_cost_floor(_result([_probe("BBB")]), cost_inputs={"BBB": bad})

    def test_non_dict_cost_inputs_raises(self):
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([_probe("BBB")]), cost_inputs="nope")

    def test_duplicate_probe_ticker_raises(self):
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([_probe("BBB"), _probe("BBB")]), cost_inputs={"BBB": _ci()})

    # --- canonical-unique ticker identity + promoted-probe trace VALUES (Codex 4d-ii-h identity finding) ---
    def test_lowercase_probe_ticker_canonicalized(self):
        out = cf.apply_probe_cost_floor(_result([_probe("bbb")]), cost_inputs={"BBB": _ci()})   # canonical cost key
        self.assertEqual(_by(out)["BBB"]["ticker"], "BBB")          # emitted canonical UPPERCASE
        self.assertEqual(_by(out)["BBB"]["final_action"], "建仓")

    def test_lowercase_cost_key_raises(self):
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([_probe("BBB")]), cost_inputs={"bbb": _ci()})   # non-canonical cost key

    def test_non_canonical_ticker_raises(self):
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([_base("000001.SZ")]), cost_inputs={})   # A-share code

    def test_duplicate_base_build_ticker_raises(self):
        # the duplicate-identity / double-count case: two base builds with the same canonical identity.
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([_base("AAA"), _base("aaa")]), cost_inputs={})

    def test_promoted_probe_must_be_forced_min_sizing(self):
        # cost-floor math is only valid for the 4d-ii-g forced-min probe; a risk-sized probe would multiply
        # profit by a larger share count and can bypass the min-size cost floor.
        row = _probe("BBB", shares=MIN_EXECUTABLE_SHARES + 499, entry=100.0, tp1=100.02)
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})

    def test_cost_bypass_geometry_uses_true_min_size(self):
        # At the true min size this geometry is uneconomic; a 500-share forged probe would clear if accepted.
        out = cf.apply_probe_cost_floor(
            _result([_probe("BBB", shares=MIN_EXECUTABLE_SHARES, entry=100.0, tp1=100.01)]),
            cost_inputs={"BBB": _ci()})
        self.assertEqual(_by(out)["BBB"]["observe_reason_type"], "cost_inefficient_min_size")
        row = _probe("BBB", shares=MIN_EXECUTABLE_SHARES + 499, entry=100.0, tp1=100.02)
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})

    def test_promoted_probe_sizing_status_must_be_sized(self):
        row = _probe("BBB", shares=MIN_EXECUTABLE_SHARES)
        row["sizing"]["status"] = "not_sized"
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})

    def test_promoted_probe_forced_min_trace_must_be_present(self):
        mutations = (
            ("bad_reason", lambda s: s.__setitem__("reason", "risk_sized")),
            ("missing_reason", lambda s: s.pop("reason")),
            ("zero_pre_probe", lambda s: s.__setitem__("pre_probe_risk_shares", 0)),
            ("bool_pre_probe", lambda s: s.__setitem__("pre_probe_risk_shares", True)),
            ("missing_pre_probe", lambda s: s.pop("pre_probe_risk_shares")),
        )
        for name, mutate in mutations:
            row = _probe("BBB", shares=MIN_EXECUTABLE_SHARES)
            mutate(row["sizing"])
            with self.assertRaises(cf.WeekendCostFloorError, msg=name):
                cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})

    def test_promoted_probe_bad_share_shapes_raise(self):
        for shares in (0, True, 1.0, None):
            row = _probe("BBB", shares=MIN_EXECUTABLE_SHARES)
            if shares is None:
                del row["sizing"]["desired_model_shares"]
            else:
                row["sizing"]["desired_model_shares"] = shares
            with self.assertRaises(cf.WeekendCostFloorError, msg=repr(shares)):
                cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})

    def test_wrong_value_probe_trace_raises(self):
        for trace in ({"risk_tag": "WRONG", "entry_mode_constraint": "pullback_only"},        # bad risk_tag
                      {"risk_tag": "theme_probe_min_size", "entry_mode_constraint": "WRONG"},  # bad entry-mode
                      {"risk_tag": "WRONG", "entry_mode_constraint": "WRONG"}):                # both wrong (exact keys)
            row = _probe("BBB")
            row["theme_probe"] = trace
            with self.assertRaises(cf.WeekendCostFloorError):
                cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})

    def test_valid_probe_trace_values_pass(self):
        for mode in ("none", "pullback_only", "breakout_exception_allowed"):
            row = _probe("BBB")
            row["theme_probe"] = {"risk_tag": tp_engine.RISK_TAG, "entry_mode_constraint": mode}
            out = cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})
            self.assertEqual(_by(out)["BBB"]["final_action"], "建仓")

    def test_entry_mode_constraints_match_engine(self):
        # triangulation: the local legal entry-mode set is pinned to theme_probe.defensive_entry_constraint.
        seen = {
            tp_engine.defensive_entry_constraint("进攻", "extreme"),                            # none
            tp_engine.defensive_entry_constraint("防御", "strong"),                             # pullback_only
            tp_engine.defensive_entry_constraint("防御", "extreme", no_gap_week=True, entry_in_band=True),  # breakout
        }
        self.assertEqual(seen, set(cf._ENTRY_MODE_CONSTRAINTS))

    # --- §9 final_action ⟺ observe_reason_type consistency (Codex 4d-ii-h finding) ---
    def test_bad_observe_reason_raises(self):
        row = _obs("OBS")
        row["observe_reason_type"] = "BANANA"
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([row]), cost_inputs={})

    def test_missing_observe_reason_raises(self):
        row = _obs("OBS")
        row["observe_reason_type"] = None
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([row]), cost_inputs={})

    def test_base_build_stale_reason_raises(self):
        row = _base("AAA")
        row["observe_reason_type"] = "data_restricted"   # a 建仓 must carry no observe reason
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([row]), cost_inputs={})

    def test_cost_cleared_probe_stale_reason_raises(self):
        row = _probe("BBB")
        row["observe_reason_type"] = "data_restricted"   # a 建仓 probe must carry no observe reason
        with self.assertRaises(cf.WeekendCostFloorError):
            cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})

    def test_malformed_probe_trace_raises(self):
        for tp in (None, {"risk_tag": "theme_probe_min_size"},
                   {"risk_tag": "x", "entry_mode_constraint": "y", "z": 1}):
            row = _probe("BBB")
            row["theme_probe"] = tp
            with self.assertRaises(cf.WeekendCostFloorError):
                cf.apply_probe_cost_floor(_result([row]), cost_inputs={"BBB": _ci()})


if __name__ == "__main__":
    unittest.main()
