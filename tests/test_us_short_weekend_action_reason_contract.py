# -*- coding: utf-8 -*-
"""Single-source §9 (final_action, observe_reason_type) contract guard across the weekend pipeline.

Root-cause guard for the RECURRING consumer-validation class: a weekend stage shape-checks `final_action`
but does NOT value-validate the §9 action/reason consistency, so a bad / missing / stale `observe_reason_type`
passes the stage boundary (Codex caught this on 4d-ii-h, and the same gap existed in 4d-ii-c). The fix is a
single-source validator `engine.us_short_weekend_decision.action_reason_error` that every stage uses. This
guard makes the class non-recurring by enforcing, position-independently:
  1. the validator itself accepts every valid §9 pair and rejects every invalid one;
  2. NO weekend stage re-implements the inline check (the inline error strings live ONLY in the validator);
  3. every consuming stage imports the single source AND adversarially rejects a bad pair at its boundary;
  4. the producer (`decide_actions`) wires the validator as an emit self-check.
A future stage that handles the action/reason surface must use `action_reason_error` and be added to the
behavioral list below — re-implementing the check inline fails guard (2).
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_weekend_decision import OBSERVE_REASONS, action_reason_error  # noqa: E402
import engine.us_short_weekend_sizing as sizing  # noqa: E402
import engine.us_short_weekend_basket as basket  # noqa: E402
import engine.us_short_weekend_cost_floor as cost_floor  # noqa: E402
import engine.us_short_weekend_cash as cash  # noqa: E402

_ENGINE = ROOT / "engine"
# the §9 inline-check error strings the single-source validator emits — they must NOT appear in any OTHER
# weekend module (i.e. no stage re-implements the check inline instead of calling action_reason_error).
_INLINE_MARKERS = ("观察 行 observe_reason_type 须 ∈ 冻结词表", "不得带 observe_reason_type")
_SINGLE_SOURCE_MODULE = "us_short_weekend_decision.py"


def _inline_marker_offenders(sources):
    """SHARED scan logic for the live guard AND its planted-failure test (so they can't drift apart):
    `sources` = {module_name: source_text}; returns [(name, marker)] for every non-validator weekend module
    that re-implements an inline §9 check string."""
    offenders = []
    for name, src in sources.items():
        if name == _SINGLE_SOURCE_MODULE:
            continue
        for marker in _INLINE_MARKERS:
            if marker in src:
                offenders.append((name, marker))
    return offenders


class ActionReasonValidatorTests(unittest.TestCase):
    def test_valid_pairs_pass(self):
        for fa in ("建仓", "持有", "清仓-事件", "清仓-止损", "否决/避开"):
            self.assertIsNone(action_reason_error(fa, None))
        for reason in OBSERVE_REASONS:
            self.assertIsNone(action_reason_error("观察", reason))

    def test_unknown_action_rejected(self):
        self.assertIsNotNone(action_reason_error("BANANA", None))

    def test_observe_bad_or_missing_reason_rejected(self):
        self.assertIsNotNone(action_reason_error("观察", "BANANA"))
        self.assertIsNotNone(action_reason_error("观察", None))

    def test_non_observe_stale_reason_rejected(self):
        self.assertIsNotNone(action_reason_error("建仓", "data_restricted"))
        self.assertIsNotNone(action_reason_error("持有", "data_restricted"))


class SingleSourceStructureTests(unittest.TestCase):
    def test_inline_check_only_in_validator(self):
        # the §9 inline-check strings may appear ONLY in the single-source module; a stage re-implementing the
        # check inline (the exact recurrence mode) re-introduces them and fails here.
        sources = {p.name: p.read_text(encoding="utf-8") for p in _ENGINE.glob("us_short_weekend_*.py")}
        self.assertEqual(_inline_marker_offenders(sources), [],
                         "a weekend stage re-implements the §9 check inline instead of using action_reason_error")

    def test_inline_marker_guard_planted_failure(self):
        # proves the scan is not a no-op: a synthetic stage that re-implements the inline check IS caught.
        planted = {"us_short_weekend_fake.py": "raise X('观察 行 observe_reason_type 须 ∈ 冻结词表')",
                   _SINGLE_SOURCE_MODULE: "the validator legitimately owns the string 不得带 observe_reason_type"}
        self.assertEqual(_inline_marker_offenders(planted), [("us_short_weekend_fake.py", _INLINE_MARKERS[0])])

    def test_consuming_stages_import_single_source(self):
        for mod_path in (_ENGINE / "us_short_weekend_sizing.py", _ENGINE / "us_short_weekend_basket.py",
                         _ENGINE / "us_short_weekend_cost_floor.py", _ENGINE / "us_short_weekend_cash.py"):
            self.assertIn("action_reason_error", mod_path.read_text(encoding="utf-8"),
                          f"{mod_path.name} does not consume the single-source action/reason validator")

    def test_producer_wires_emit_self_check(self):
        src = (_ENGINE / _SINGLE_SOURCE_MODULE).read_text(encoding="utf-8")
        # decide_actions must call action_reason_error as a producer self-check (not just define it)
        self.assertGreaterEqual(len(re.findall(r"action_reason_error\(", src)), 2)


class StageRejectsBadPairTests(unittest.TestCase):
    # one bad (观察 + BANANA) row at each stage boundary must fail closed — the behavioral half of the guard.
    def test_sizing_rejects_bad_pair(self):
        bad = {"ticker": "AAA", "final_action": "观察", "observe_reason_type": "BANANA",
               "price": {"executable": True, "action_fields": {}}}
        with self.assertRaises(sizing.WeekendSizingError):
            sizing.size_rows({"regime": {"position_cap": 1.0}, "rows": [bad]},
                             sizing_context={"short_bucket_dollars": 10000.0, "per_ticker": {}})

    def test_basket_rejects_bad_pair(self):
        bad = {"ticker": "AAA", "final_action": "观察", "observe_reason_type": "BANANA"}
        with self.assertRaises(basket.WeekendBasketError):
            basket.resolve_build_capacity(
                {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": [bad]},
                basket_context={"per_ticker": {}, "portfolio_guard_status": "normal",
                                "theme_opportunity_state": "no_strong_theme"})

    def test_cost_floor_rejects_bad_pair(self):
        bad = {"ticker": "AAA", "final_action": "观察", "observe_reason_type": "BANANA", "selection_rank": 9}
        with self.assertRaises(cost_floor.WeekendCostFloorError):
            cost_floor.apply_probe_cost_floor(
                {"regime": {"market_risk_regime": "进攻"}, "rows": [bad], "weekly_build_limit": 1,
                 "build_count": 0}, cost_inputs={})

    def test_cash_rejects_bad_pair(self):
        bad = {"ticker": "AAA", "final_action": "观察", "observe_reason_type": "BANANA", "selection_rank": 9}
        with self.assertRaises(cash.WeekendCashError):
            cash.apply_cash_allocation(
                {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": [bad],
                 "weekly_build_limit": 1, "build_count": 0}, available_cash=5000.0)

    def test_non_observe_stale_reason_rejected_each_stage(self):
        # the reverse half: a non-观察 row carrying a stale reason is also rejected at each stage.
        sized_bad = {"ticker": "AAA", "final_action": "持有", "observe_reason_type": "data_restricted",
                     "price": {"executable": True, "action_fields": {}}}
        with self.assertRaises(sizing.WeekendSizingError):
            sizing.size_rows({"regime": {"position_cap": 1.0}, "rows": [sized_bad]},
                             sizing_context={"short_bucket_dollars": 10000.0, "per_ticker": {}})
        basket_bad = {"ticker": "AAA", "final_action": "持有", "observe_reason_type": "data_restricted"}
        with self.assertRaises(basket.WeekendBasketError):
            basket.resolve_build_capacity(
                {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": [basket_bad]},
                basket_context={"per_ticker": {}, "portfolio_guard_status": "normal",
                                "theme_opportunity_state": "no_strong_theme"})
        cf_bad = {"ticker": "AAA", "final_action": "持有", "observe_reason_type": "data_restricted",
                  "selection_rank": 9}
        with self.assertRaises(cost_floor.WeekendCostFloorError):
            cost_floor.apply_probe_cost_floor(
                {"regime": {"market_risk_regime": "进攻"}, "rows": [cf_bad], "weekly_build_limit": 1,
                 "build_count": 0}, cost_inputs={})
        cash_bad = {"ticker": "AAA", "final_action": "持有", "observe_reason_type": "data_restricted",
                    "selection_rank": 9}
        with self.assertRaises(cash.WeekendCashError):
            cash.apply_cash_allocation(
                {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": [cash_bad],
                 "weekly_build_limit": 1, "build_count": 0}, available_cash=5000.0)


if __name__ == "__main__":
    unittest.main()
