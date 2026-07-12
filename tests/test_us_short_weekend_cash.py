# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline global cash allocation (engine/us_short_weekend_cash.py) — batch4 slice 4d-ii-i.

Design authority: docs/us_short_system_design.md §8 (全局现金分配, line 240) / §9 / §18.2.

Covers: the finalized 建仓 set funded sequentially in 排名(selection_rank)-primary order at valid_entry_high;
a build the remaining cash cannot cover downgraded 建仓 → 观察(cash_or_account_missing) with build_count
recomputed and the 5 cash_allocation_fields attached; enough cash funds all; zero cash observes all;
non-建仓 rows carry through with None cash fields; and fail-closed result / §9 action-reason / canonical
ticker / duplicate identity / malformed build-input validation.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_cash as wc  # noqa: E402
from engine.us_short_cash_allocation import CASH_ALLOCATION_FIELDS  # noqa: E402


def _build(ticker, rank, shares=10, entry=100.0, rr=2.0):
    return {"ticker": ticker, "final_action": "建仓", "observe_reason_type": None, "selection_rank": rank,
            "portfolio_theme": "test_theme",
            "sizing": {"desired_model_shares": shares, "status": "sized"},
            "price": {"action_fields": {"valid_entry_high": entry, "risk_reward_ratio": rr}}}


def _obs(ticker):
    return {"ticker": ticker, "final_action": "观察", "observe_reason_type": "capacity_or_budget_deferred",
            "selection_rank": 9}


def _result(rows):
    return {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": rows,
            "weekly_build_limit": 3, "build_count": sum(1 for r in rows if r["final_action"] == "建仓")}


def _portfolio_capacity(existing_positions=()):
    return {"short_bucket_dollars": 10000.0, "existing_positions": list(existing_positions)}


def _by(out):
    return {r["ticker"]: r for r in out["rows"]}


class ApplyCashAllocationTests(unittest.TestCase):
    def test_existing_holding_consumes_total_cap_before_cash(self):
        # $4,000 current holding + $3,000 rank-1 new build would breach the §8 $6,000 total cap even though
        # $10,000 cash is available; the new build must become observe rather than silently over-deploy.
        build = _build("AAA", 1, shares=30, entry=100.0)
        build["portfolio_theme"] = "new_theme"
        out = wc.apply_cash_allocation(
            _result([build]), available_cash=10000.0,
            portfolio_capacity=_portfolio_capacity([
                {"ticker": "HLD", "shares": 40, "mark_price": 100.0, "theme": "held_theme"},
            ]),
        )
        aaa = _by(out)["AAA"]
        self.assertEqual(aaa["final_action"], "观察")
        self.assertEqual(aaa["observe_reason_type"], "capacity_or_budget_deferred")
        self.assertEqual(aaa["portfolio_capacity_status"], "deferred_total_cap")
        self.assertIsNone(aaa["cash_allocation_status"])

    def test_existing_holding_consumes_same_theme_cap_case_insensitively(self):
        # Existing $2,500 `software` exposure plus a $1,000 `Software` build breaches the $3,000 same-theme
        # cap. Case/whitespace variants must not create a second capacity bucket.
        build = _build("AAA", 1, shares=10, entry=100.0)
        build["portfolio_theme"] = " Software "
        out = wc.apply_cash_allocation(
            _result([build]), available_cash=10000.0,
            portfolio_capacity=_portfolio_capacity([
                {"ticker": "HLD", "shares": 25, "mark_price": 100.0, "theme": "software"},
            ]),
        )
        aaa = _by(out)["AAA"]
        self.assertEqual(aaa["final_action"], "观察")
        self.assertEqual(aaa["portfolio_capacity_status"], "deferred_theme_cap")

    def test_capacity_keeps_ranked_build_that_fits_and_defers_later_one(self):
        # Existing $2,000 leaves $4,000 total capacity. Rank-1 $3,000 fits; rank-2 $2,000 does not. No partial
        # position is fabricated and the later name never bypasses the earlier reservation.
        first = _build("AAA", 1, shares=30, entry=100.0)
        second = _build("BBB", 2, shares=20, entry=100.0)
        first["portfolio_theme"] = "a"
        second["portfolio_theme"] = "b"
        out = wc.apply_cash_allocation(
            _result([first, second]), available_cash=10000.0,
            portfolio_capacity=_portfolio_capacity([
                {"ticker": "HLD", "shares": 20, "mark_price": 100.0, "theme": "held"},
            ]),
        )
        by = _by(out)
        self.assertEqual(by["AAA"]["final_action"], "建仓")
        self.assertEqual(by["BBB"]["final_action"], "观察")
        self.assertEqual(by["BBB"]["portfolio_capacity_status"], "deferred_total_cap")

    def test_unavailable_existing_mark_defers_every_new_build(self):
        build = _build("AAA", 1, shares=1, entry=100.0)
        out = wc.apply_cash_allocation(
            _result([build]), available_cash=10000.0,
            portfolio_capacity=_portfolio_capacity([
                {"ticker": "HLD", "shares": 1, "mark_price": None, "theme": "held"},
            ]),
        )
        aaa = _by(out)["AAA"]
        self.assertEqual(aaa["final_action"], "观察")
        self.assertEqual(aaa["portfolio_capacity_status"], "deferred_unavailable_existing_exposure")

    def test_funded_build_stays_build(self):
        out = wc.apply_cash_allocation(_result([_build("AAA", 1, 10, 100.0)]), available_cash=5000.0,
                                       portfolio_capacity=_portfolio_capacity())
        aaa = _by(out)["AAA"]
        self.assertEqual(aaa["final_action"], "建仓")
        self.assertEqual(aaa["cash_allocation_status"], "allocated")
        self.assertEqual(aaa["allocated_model_shares"], 10)
        self.assertEqual(aaa["cash_required_at_entry_high"], 1000.0)
        self.assertEqual(out["build_count"], 1)

    def test_insufficient_cash_downgrades_to_observe(self):
        # AAA(rank1) + BBB(rank2), each 10×100=1000; cash 1500 funds AAA only, BBB → 观察(cash_or_account_missing).
        out = wc.apply_cash_allocation(_result([_build("AAA", 1), _build("BBB", 2)]), available_cash=1500.0,
                                       portfolio_capacity=_portfolio_capacity())
        by = _by(out)
        self.assertEqual(by["AAA"]["final_action"], "建仓")
        self.assertEqual(by["BBB"]["final_action"], "观察")
        self.assertEqual(by["BBB"]["observe_reason_type"], "cash_or_account_missing")
        self.assertEqual(by["BBB"]["cash_allocation_status"], "observe")
        self.assertEqual(by["BBB"]["allocated_model_shares"], 0)
        self.assertEqual(out["build_count"], 1)

    def test_rank_primary_funding_order(self):
        # BBB has the better rank (1); even listed second it is funded first, AAA(rank2) misses out.
        out = wc.apply_cash_allocation(_result([_build("AAA", 2), _build("BBB", 1)]), available_cash=1500.0,
                                       portfolio_capacity=_portfolio_capacity())
        by = _by(out)
        self.assertEqual(by["BBB"]["final_action"], "建仓")
        self.assertEqual(by["AAA"]["final_action"], "观察")

    def test_enough_cash_funds_all(self):
        out = wc.apply_cash_allocation(_result([_build("AAA", 1), _build("BBB", 2), _build("CCC", 3)]),
                                       available_cash=99999.0, portfolio_capacity=_portfolio_capacity())
        self.assertEqual(out["build_count"], 3)
        self.assertTrue(all(_by(out)[t]["final_action"] == "建仓" for t in ("AAA", "BBB", "CCC")))

    def test_zero_cash_observes_all(self):
        out = wc.apply_cash_allocation(_result([_build("AAA", 1), _build("BBB", 2)]), available_cash=0.0,
                                       portfolio_capacity=_portfolio_capacity())
        self.assertEqual(out["build_count"], 0)
        self.assertTrue(all(_by(out)[t]["observe_reason_type"] == "cash_or_account_missing"
                            for t in ("AAA", "BBB")))

    def test_non_build_rows_carry_none_cash_fields(self):
        out = wc.apply_cash_allocation(_result([_build("AAA", 1), _obs("OBS")]), available_cash=5000.0,
                                       portfolio_capacity=_portfolio_capacity())
        obs = _by(out)["OBS"]
        self.assertEqual(obs["final_action"], "观察")
        self.assertEqual(obs["observe_reason_type"], "capacity_or_budget_deferred")   # unchanged
        for f in CASH_ALLOCATION_FIELDS:
            self.assertIsNone(obs[f])                          # cash allocation N/A on a non-建仓 row

    def test_cash_fields_present_on_every_row(self):
        out = wc.apply_cash_allocation(_result([_build("AAA", 1), _obs("OBS")]), available_cash=5000.0,
                                       portfolio_capacity=_portfolio_capacity())
        for row in out["rows"]:
            for f in CASH_ALLOCATION_FIELDS:
                self.assertIn(f, row)

    # --- fail-closed (single-source consumer-validation) ---
    def test_malformed_result_raises(self):
        for bad in ({"rows": []}, {"regime": {}}, {"regime": {}, "rows": {}}):
            with self.assertRaises(wc.WeekendCashError):
                wc.apply_cash_allocation(bad, available_cash=5000.0, portfolio_capacity=_portfolio_capacity())

    def test_bad_action_reason_raises(self):
        bad = {"ticker": "AAA", "final_action": "观察", "observe_reason_type": "BANANA", "selection_rank": 1}
        with self.assertRaises(wc.WeekendCashError):
            wc.apply_cash_allocation(_result([bad]), available_cash=5000.0, portfolio_capacity=_portfolio_capacity())

    def test_non_observe_stale_reason_raises(self):
        row = _build("AAA", 1)
        row["observe_reason_type"] = "data_restricted"        # a 建仓 must carry no reason
        with self.assertRaises(wc.WeekendCashError):
            wc.apply_cash_allocation(_result([row]), available_cash=5000.0, portfolio_capacity=_portfolio_capacity())

    def test_non_canonical_ticker_raises(self):
        with self.assertRaises(wc.WeekendCashError):
            wc.apply_cash_allocation(_result([_build("000001.SZ", 1)]), available_cash=5000.0,
                                     portfolio_capacity=_portfolio_capacity())

    def test_lowercase_ticker_canonicalized(self):
        out = wc.apply_cash_allocation(_result([_build("aapl", 1)]), available_cash=5000.0,
                                       portfolio_capacity=_portfolio_capacity())
        self.assertEqual(_by(out)["AAPL"]["ticker"], "AAPL")

    def test_duplicate_identity_raises(self):
        with self.assertRaises(wc.WeekendCashError):
            wc.apply_cash_allocation(_result([_build("AAA", 1), _build("aaa", 2)]), available_cash=5000.0,
                                     portfolio_capacity=_portfolio_capacity())

    def test_malformed_build_inputs_raise(self):
        for bad in (_build("AAA", 1, shares=0), _build("AAA", 1, shares=10, entry=0.0)):
            with self.assertRaises(wc.WeekendCashError):
                wc.apply_cash_allocation(_result([bad]), available_cash=5000.0, portfolio_capacity=_portfolio_capacity())
        bad_rank = _build("AAA", 1)
        bad_rank["selection_rank"] = None                     # a 建仓 must carry a valid funding rank
        with self.assertRaises(wc.WeekendCashError):
            wc.apply_cash_allocation(_result([bad_rank]), available_cash=5000.0, portfolio_capacity=_portfolio_capacity())


if __name__ == "__main__":
    unittest.main()
