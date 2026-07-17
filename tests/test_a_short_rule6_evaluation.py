"""Per-check clear/fail/unknown coverage for the computable Rule6 evaluators."""

from __future__ import annotations

import unittest

from engine.a_short_rule6_evaluation import (
    evaluate_ar_growth_gt_revenue_growth,
    evaluate_block_trade_discount,
    evaluate_cash_debt_double_high,
    evaluate_holder_below_5pct,
    evaluate_margin_extreme_accumulation,
    evaluate_short_selling_surge,
    evaluate_volume_stall,
    materialize_50etf_iv_rule6_check,
)
from engine.a_short_rule6_contract import RULE6_CONDITIONAL_NA_REASONS


AS_OF = "20260714"


class Rule6EvaluationTests(unittest.TestCase):
    def test_holder_below_5pct_clear_fail_unknown(self):
        self.assertEqual(evaluate_holder_below_5pct([], AS_OF)["status"], "pass")
        self.assertEqual(evaluate_holder_below_5pct([
            {"ann_date": "20260710", "in_de": "DE", "after_ratio": 4.99}
        ], AS_OF)["status"], "fail")
        self.assertEqual(evaluate_holder_below_5pct([
            {"ann_date": "20260710", "in_de": "DE", "after_ratio": None}
        ], AS_OF)["status"], "unknown")

    def test_volume_stall_clear_fail_unknown(self):
        history = [{"vol": 100.0}] * 5
        clear = [{"vol": 200.0, "pct_chg": 2.0, "high": 11.0, "low": 9.0, "close": 9.5}] + history
        failed = [{"vol": 201.0, "pct_chg": 1.99, "high": 11.0, "low": 9.0, "close": 9.5}] + history
        self.assertEqual(evaluate_volume_stall(clear)["status"], "pass")
        self.assertEqual(evaluate_volume_stall(failed)["status"], "fail")
        self.assertEqual(evaluate_volume_stall(failed[:-1])["status"], "unknown")

    def test_margin_extreme_clear_fail_unknown(self):
        self.assertEqual(evaluate_margin_extreme_accumulation(120, 100, 105, 100)["status"], "pass")
        self.assertEqual(evaluate_margin_extreme_accumulation(121, 100, 104, 100)["status"], "fail")
        self.assertEqual(evaluate_margin_extreme_accumulation(121, 0, 104, 100)["status"], "unknown")

    def test_short_selling_clear_fail_unknown(self):
        self.assertEqual(evaluate_short_selling_surge(200, 100, "hedge_announcement")["status"], "pass")
        self.assertEqual(evaluate_short_selling_surge(201, 100, "no_hedge_announcement")["status"], "fail")
        self.assertEqual(evaluate_short_selling_surge(201, 100, None)["status"], "unknown")

    def test_cash_debt_clear_fail_unknown(self):
        base = {"ann_date": "20260430", "end_date": "20260331", "total_assets": 1000.0}
        self.assertEqual(evaluate_cash_debt_double_high({**base, "money_cap": 250.0, "st_borr": 251.0}, AS_OF)["status"], "pass")
        self.assertEqual(evaluate_cash_debt_double_high({**base, "money_cap": 251.0, "st_borr": 251.0}, AS_OF)["status"], "fail")
        self.assertEqual(evaluate_cash_debt_double_high({**base, "money_cap": None, "st_borr": 251.0}, AS_OF)["status"], "unknown")

    def test_block_trade_clear_fail_unknown(self):
        dates = [f"202607{i:02d}" for i in range(1, 11)]
        clear = {date: [] for date in dates}
        failed = {date: [] for date in dates}
        failed[dates[0]] = [{"price": 90.0, "close": 100.0, "vol": 600.0}]
        failed[dates[1]] = [{"price": 90.0, "close": 100.0, "vol": 600.0}]
        self.assertEqual(evaluate_block_trade_discount(dates, clear)["status"], "pass")
        self.assertEqual(evaluate_block_trade_discount(dates, failed)["status"], "fail")
        incomplete = dict(clear)
        incomplete.pop(dates[-1])
        self.assertEqual(evaluate_block_trade_discount(dates, incomplete)["status"], "unknown")

    def test_ar_growth_clear_fail_unknown(self):
        periods = [
            {"period": "20250331", "ann_date": "20250430", "revenue_yoy_pct": 10.0},
            {"period": "20241231", "ann_date": "20250331", "revenue_yoy_pct": 10.0},
        ]
        balances = {
            "20250331": {"ann_date": "20250430", "accounts_receiv": 130.0, "contract_liab": 105.0},
            "20240331": {"ann_date": "20240430", "accounts_receiv": 100.0, "contract_liab": 100.0},
            "20241231": {"ann_date": "20250331", "accounts_receiv": 140.0, "contract_liab": 105.0},
            "20231231": {"ann_date": "20240331", "accounts_receiv": 100.0, "contract_liab": 100.0},
        }
        self.assertEqual(evaluate_ar_growth_gt_revenue_growth(periods, balances, AS_OF)["status"], "fail")
        clear_periods = [dict(item, revenue_yoy_pct=50.0) for item in periods]
        self.assertEqual(evaluate_ar_growth_gt_revenue_growth(clear_periods, balances, AS_OF)["status"], "pass")
        self.assertEqual(evaluate_ar_growth_gt_revenue_growth(periods, {"20250331": balances["20250331"]}, AS_OF)["status"], "unknown")
        stale_revenue = [dict(item, ann_date="20990101") for item in periods]
        self.assertEqual(evaluate_ar_growth_gt_revenue_growth(stale_revenue, balances, AS_OF)["status"], "unknown")

    def test_iv_feed_materialization_is_strictly_above_90_and_missing_is_unknown(self):
        checks = [{"id": "rule6_50etf_iv", "status": "unknown", "severity": "watch", "metrics": {}}]
        self.assertEqual(materialize_50etf_iv_rule6_check(checks, 90.0)[0]["status"], "pass")
        self.assertEqual(materialize_50etf_iv_rule6_check(checks, 90.01)[0]["status"], "fail")
        self.assertEqual(materialize_50etf_iv_rule6_check(checks, None)[0]["status"], "unknown")


class MarginEligibilityConditionalNATests(unittest.TestCase):
    """The two margin-based checks are not_applicable only for a POSITIVELY
    non-margin stock; a merely-absent margin universe must stay unknown."""

    def test_non_margin_target_is_not_applicable(self):
        margin = evaluate_margin_extreme_accumulation(None, None, None, None, is_margin_eligible=False)
        self.assertEqual(margin["status"], "not_applicable")
        self.assertEqual(margin["severity"], "none")
        self.assertEqual(margin["notes"], RULE6_CONDITIONAL_NA_REASONS["rule6_margin_extreme_accumulation"])
        short = evaluate_short_selling_surge(None, None, None, is_margin_eligible=False)
        self.assertEqual(short["status"], "not_applicable")
        self.assertEqual(short["notes"], RULE6_CONDITIONAL_NA_REASONS["rule6_short_selling_surge"])

    def test_unknown_eligibility_stays_unknown_when_data_missing(self):
        # None = margin universe not established (fetch failed): must NOT clear.
        self.assertEqual(
            evaluate_margin_extreme_accumulation(None, None, None, None, is_margin_eligible=None)["status"],
            "unknown")
        self.assertEqual(
            evaluate_short_selling_surge(None, None, None, is_margin_eligible=None)["status"],
            "unknown")

    def test_eligible_stock_still_evaluates_and_can_fail(self):
        # Eligibility True must not short-circuit real evaluation.
        self.assertEqual(
            evaluate_margin_extreme_accumulation(130, 100, 101, 100, is_margin_eligible=True)["status"],
            "fail")   # +30% financing, +1% price
        self.assertEqual(
            evaluate_margin_extreme_accumulation(101, 100, 101, 100, is_margin_eligible=True)["status"],
            "pass")

    def test_default_argument_is_backward_compatible(self):
        self.assertEqual(evaluate_margin_extreme_accumulation(None, None, None, None)["status"], "unknown")
        self.assertEqual(evaluate_short_selling_surge(None, None, None)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
