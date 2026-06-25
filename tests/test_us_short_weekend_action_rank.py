# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline action ranking (engine/us_short_weekend_action_rank.py) — batch4 slice 4d-ii-j.

Design authority: docs/us_short_system_design.md §9 (操作排名, line 248 survival-first) / §18.2.

Covers: group-major + survival-first action_rank (a holding reduce/clear group-1 row outranks a new 建仓
group-2 row even with a better selection_rank), the within-group-1 survival sub-order (止损/事件 → 减仓 →
止盈), groups 2-5 ordered by selection_rank, every row carrying action_group + action_rank, and fail-closed
result / §9 action-reason / canonical ticker / duplicate identity validation.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_action_rank as ar  # noqa: E402


def _row(ticker, final_action, selection_rank=None, reason=None):
    return {"ticker": ticker, "final_action": final_action, "observe_reason_type": reason,
            "selection_rank": selection_rank}


def _result(rows):
    return {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": rows,
            "weekly_build_limit": 3, "build_count": sum(1 for r in rows if r["final_action"] == "建仓")}


def _by(out):
    return {r["ticker"]: r for r in out["rows"]}


class ApplyActionRankTests(unittest.TestCase):
    def test_holding_clear_outranks_new_build(self):
        # survival-first group-major: 清仓-止损 (group 1) outranks 建仓 (group 2) even with a worse selection_rank.
        out = ar.apply_action_rank(_result([_row("AAA", "建仓", 1), _row("BBB", "清仓-止损")]))
        by = _by(out)
        self.assertEqual((by["BBB"]["action_group"], by["BBB"]["action_rank"]), (1, 1))
        self.assertEqual((by["AAA"]["action_group"], by["AAA"]["action_rank"]), (2, 2))

    def test_group1_survival_suborder(self):
        # within group 1: 止损/事件 (0) before 减仓 (1) before 止盈 (2).
        out = ar.apply_action_rank(_result([_row("TP", "清仓-止盈"), _row("RED", "减仓"), _row("SL", "清仓-止损")]))
        by = _by(out)
        self.assertEqual((by["SL"]["action_rank"], by["RED"]["action_rank"], by["TP"]["action_rank"]), (1, 2, 3))

    def test_builds_ordered_by_selection_rank(self):
        out = ar.apply_action_rank(_result([_row("AAA", "建仓", 2), _row("BBB", "建仓", 1)]))
        by = _by(out)
        self.assertEqual(by["BBB"]["action_rank"], 1)
        self.assertEqual(by["AAA"]["action_rank"], 2)
        self.assertTrue(all(by[t]["action_group"] == 2 for t in ("AAA", "BBB")))

    def test_groups_2_to_5(self):
        out = ar.apply_action_rank(_result([
            _row("REJ", "否决/避开"), _row("OBS", "观察", reason="capacity_or_budget_deferred"),
            _row("ADD", "加仓", 1), _row("BUILD", "建仓", 1)]))
        by = _by(out)
        self.assertEqual(by["BUILD"]["action_group"], 2)
        self.assertEqual(by["ADD"]["action_group"], 3)
        self.assertEqual(by["OBS"]["action_group"], 4)
        self.assertEqual(by["REJ"]["action_group"], 5)
        # global action_rank reflects the group order: build(2) < add(3) < observe(4) < reject(5)
        self.assertLess(by["BUILD"]["action_rank"], by["ADD"]["action_rank"])
        self.assertLess(by["ADD"]["action_rank"], by["OBS"]["action_rank"])
        self.assertLess(by["OBS"]["action_rank"], by["REJ"]["action_rank"])

    def test_every_row_carries_group_and_rank(self):
        out = ar.apply_action_rank(_result([_row("AAA", "建仓", 1), _row("HLD", "持有")]))
        for row in out["rows"]:
            self.assertIn("action_group", row)
            self.assertIn("action_rank", row)

    def test_lowercase_ticker_canonicalized(self):
        out = ar.apply_action_rank(_result([_row("aapl", "建仓", 1)]))
        self.assertEqual(_by(out)["AAPL"]["ticker"], "AAPL")

    # --- fail-closed (single-source consumer-validation) ---
    def test_malformed_result_raises(self):
        for bad in ({"rows": []}, {"regime": {}}, {"regime": {}, "rows": {}}):
            with self.assertRaises(ar.WeekendActionRankError):
                ar.apply_action_rank(bad)

    def test_bad_action_reason_raises(self):
        with self.assertRaises(ar.WeekendActionRankError):
            ar.apply_action_rank(_result([_row("AAA", "观察", reason="BANANA")]))

    def test_non_observe_stale_reason_raises(self):
        with self.assertRaises(ar.WeekendActionRankError):
            ar.apply_action_rank(_result([_row("AAA", "建仓", 1, reason="data_restricted")]))

    def test_unknown_final_action_raises(self):
        with self.assertRaises(ar.WeekendActionRankError):
            ar.apply_action_rank(_result([_row("AAA", "BANANA")]))

    def test_non_canonical_ticker_raises(self):
        with self.assertRaises(ar.WeekendActionRankError):
            ar.apply_action_rank(_result([_row("000001.SZ", "建仓", 1)]))

    def test_duplicate_identity_raises(self):
        with self.assertRaises(ar.WeekendActionRankError):
            ar.apply_action_rank(_result([_row("AAA", "建仓", 1), _row("aaa", "观察",
                                                                       reason="capacity_or_budget_deferred")]))


if __name__ == "__main__":
    unittest.main()
