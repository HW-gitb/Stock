from __future__ import annotations

import copy
import unittest

from engine.us_short_model_paper_portfolio import (
    ModelPaperPortfolioError,
    artifact_sha256,
    build_nav_snapshot,
    seed_portfolio_state,
    settle_decision_bundle,
    validate_nav_snapshot,
)


BOUNDARY = {
    "paper_only": True,
    "provider_fetch": False,
    "automatic_broker_execution": False,
    "manual_account_read": False,
    "ship_gate_eligible": False,
}


def _order(ticker: str = "ABC", action: str = "建仓", shares: int | None = 100) -> dict:
    return {
        "ticker": ticker,
        "final_action": action,
        "recommended_action_shares": shares,
        "order_type": "pullback_limit" if action == "建仓" else None,
        "order_expiry": "first_regular_session_only" if action == "建仓" else None,
        "valid_entry_low": 9.8 if action == "建仓" else None,
        "valid_entry_high": 10.2 if action == "建仓" else None,
        "limit_order_price": 10.0 if action == "建仓" else None,
        "breakout_entry_price": None,
        "stop_clear_price": 9.0,
        "take_profit_reduce_price": 11.0,
        "take_profit_exit_price": 12.0,
        "event_clear_reference_price": 8.5 if action == "清仓-事件" else None,
        "event_source_ref_sha256": "e" * 64 if action == "清仓-事件" else None,
    }


def _decision(state: dict, orders: list[dict], date: str = "20260720") -> dict:
    return {
        "schema_name": "us_short_model_paper_decision_bundle",
        "schema_version": "1.0.0",
        "decision_date": date,
        "price_basis_date": state["as_of"],
        "created_at": "2026-07-20T08:00:00Z",
        "prior_state_sha256": artifact_sha256(state),
        "supersedes_sha256": None,
        "source_binding": {
            "source_kind": "us_short_weekly_decision_artifact",
            "source_as_of": date,
            "decision_source_sha256": "d" * 64,
        },
        "cost_prior": {"commission_fee": 0.001, "slippage_bps": 0.0, "spread_cost": 0.0},
        "orders": orders,
        "boundary": copy.deepcopy(BOUNDARY),
    }


def _bar(date: str, open_: float, high: float, low: float, close: float) -> dict:
    return {"date": date, "open": open_, "high": high, "low": low, "close": close}


def _packet(bars: dict[str, list[dict]], as_of: str, evaluable: bool = True) -> dict:
    return {
        "as_of": as_of,
        "session_scope": "RTH",
        "adjustment_mode": "split_dividend_adjusted",
        "observed_at": "2026-07-29T01:00:00Z",
        "source_sha256": "b" * 64,
        "paper_evaluation": {
            "paper_evaluable": evaluable,
            "status": "evaluable" if evaluable else "not_evaluable",
            "degradation_reasons": [] if evaluable else ["corporate_action_unconfirmed"],
            "source_sha256": "c" * 64 if evaluable else None,
        },
        "bars_by_ticker": bars,
    }


class ModelPaperPortfolioTest(unittest.TestCase):
    def _opened_state(self) -> tuple[dict, dict, dict]:
        seed = seed_portfolio_state("20260717")
        decision = _decision(seed, [_order()])
        packet = _packet(
            {"ABC": [_bar("20260720", 10.1, 10.2, 9.8, 10.1), _bar("20260721", 10.3, 10.6, 10.2, 10.5)]},
            "20260721",
        )
        return settle_decision_bundle(seed, decision, packet, "20260721")

    def test_build_hold_marks_nav_without_double_counting_realized_pnl(self) -> None:
        settlement, state, nav = self._opened_state()
        self.assertEqual("opened", settlement["order_outcomes"][0]["status"])
        self.assertEqual("98999.000000", state["cash"])
        self.assertEqual("-1.000000", state["cumulative_realized_pnl"])
        self.assertEqual(100, state["positions"][0]["shares"])
        self.assertEqual("10.500000", state["positions"][0]["mark_price"])
        self.assertEqual("1050.000000", nav["market_value"])
        self.assertEqual("100049.000000", nav["nav"])
        self.assertEqual("49.000000", nav["total_pnl"])
        self.assertEqual("50.000000", nav["unrealized_pnl"])

    def test_same_day_stop_is_realized_once(self) -> None:
        seed = seed_portfolio_state("20260717")
        decision = _decision(seed, [_order()])
        packet = _packet({"ABC": [_bar("20260720", 10.1, 10.2, 8.5, 9.1)]}, "20260720")
        settlement, state, nav = settle_decision_bundle(seed, decision, packet, "20260720")
        self.assertEqual("closed", settlement["order_outcomes"][0]["status"])
        self.assertEqual([], state["positions"])
        self.assertEqual("99899.000000", nav["nav"])
        self.assertEqual("-101.000000", nav["total_pnl"])

    def test_reduce_uses_governed_share_count_and_preserves_remaining_position(self) -> None:
        _, prior, _ = self._opened_state()
        reduce = _order(action="减仓", shares=10)
        decision = _decision(prior, [reduce], date="20260727")
        packet = _packet({"ABC": [_bar("20260727", 10.8, 11.4, 10.7, 11.2)]}, "20260727")
        settlement, state, nav = settle_decision_bundle(prior, decision, packet, "20260727")
        self.assertEqual("partially_reduced", settlement["order_outcomes"][0]["status"])
        self.assertEqual(90, state["positions"][0]["shares"])
        self.assertTrue(state["positions"][0]["tp1_completed"])
        self.assertEqual("100117.000000", nav["nav"])

    def test_gap_stop_exits_at_open_not_stale_stop_price(self) -> None:
        _, prior, _ = self._opened_state()
        hold = _order(action="持有", shares=None)
        decision = _decision(prior, [hold], date="20260727")
        packet = _packet({"ABC": [_bar("20260727", 8.0, 8.4, 7.5, 8.1)]}, "20260727")
        settlement, state, nav = settle_decision_bundle(prior, decision, packet, "20260727")
        tx = settlement["order_outcomes"][0]["transactions"][0]
        self.assertEqual("gap_stop", tx["reason"])
        self.assertEqual("8.000000", tx["price"])
        self.assertEqual([], state["positions"])
        self.assertEqual("99799.000000", nav["nav"])

    def test_event_exit_without_source_freezes_ticker_but_keeps_diagnostic_mark(self) -> None:
        _, prior, _ = self._opened_state()
        event = _order(action="清仓-事件", shares=100)
        event["event_source_ref_sha256"] = None
        decision = _decision(prior, [event], date="20260727")
        packet = _packet({"ABC": [_bar("20260727", 10.7, 10.9, 10.5, 10.8)]}, "20260727", evaluable=False)
        settlement, state, nav = settle_decision_bundle(prior, decision, packet, "20260727")
        self.assertEqual("manual_review_frozen", settlement["order_outcomes"][0]["status"])
        self.assertEqual("manual_review_frozen", state["positions"][0]["trade_state"])
        self.assertEqual("event_source_unbound", state["positions"][0]["freeze_reason"])
        self.assertFalse(nav["paper_evaluable"])
        self.assertEqual("diagnostic_data_degraded", nav["performance_status"])

    def test_add_remains_fail_closed(self) -> None:
        _, prior, _ = self._opened_state()
        decision = _decision(prior, [_order(action="加仓", shares=10)], date="20260727")
        packet = _packet({"ABC": [_bar("20260727", 10.5, 10.8, 10.2, 10.6)]}, "20260727")
        with self.assertRaisesRegex(ModelPaperPortfolioError, "add action is not implemented"):
            settle_decision_bundle(prior, decision, packet, "20260727")

    def test_future_bar_is_rejected_instead_of_settled_early(self) -> None:
        seed = seed_portfolio_state("20260717")
        decision = _decision(seed, [_order()])
        packet = _packet(
            {"ABC": [_bar("20260720", 10.1, 10.2, 9.8, 10.1), _bar("20260722", 10.3, 10.6, 10.2, 10.5)]},
            "20260721",
        )
        with self.assertRaisesRegex(ModelPaperPortfolioError, "bar date exceeds maturity_as_of"):
            settle_decision_bundle(seed, decision, packet, "20260721")

    def test_remaining_position_requires_exact_maturity_mark(self) -> None:
        seed = seed_portfolio_state("20260717")
        decision = _decision(seed, [_order()])
        packet = _packet({"ABC": [_bar("20260720", 10.1, 10.2, 9.8, 10.1)]}, "20260721")
        with self.assertRaisesRegex(ModelPaperPortfolioError, "lacks an exact maturity mark"):
            settle_decision_bundle(seed, decision, packet, "20260721")

    def test_decision_source_clock_must_bind_decision_date(self) -> None:
        seed = seed_portfolio_state("20260717")
        decision = _decision(seed, [_order()])
        decision["source_binding"]["source_as_of"] = "20260719"
        packet = _packet({"ABC": [_bar("20260720", 10.1, 10.2, 9.8, 10.1)]}, "20260720")
        with self.assertRaisesRegex(ModelPaperPortfolioError, "source_binding.source_as_of"):
            settle_decision_bundle(seed, decision, packet, "20260720")

    def test_nonfinite_price_fails_closed(self) -> None:
        seed = seed_portfolio_state("20260717")
        decision = _decision(seed, [_order()])
        packet = _packet({"ABC": [_bar("20260720", 10.1, float("inf"), 9.8, 10.1)]}, "20260720")
        with self.assertRaisesRegex(ModelPaperPortfolioError, "finite positive"):
            settle_decision_bundle(seed, decision, packet, "20260720")

    def test_huge_integer_price_maps_to_domain_failure(self) -> None:
        seed = seed_portfolio_state("20260717")
        decision = _decision(seed, [_order()])
        packet = _packet({"ABC": [_bar("20260720", 10.1, 10**400, 9.8, 10.1)]}, "20260720")
        with self.assertRaisesRegex(ModelPaperPortfolioError, "finite positive"):
            settle_decision_bundle(seed, decision, packet, "20260720")

    def test_source_bound_event_exit_uses_next_regular_session_open(self) -> None:
        _, prior, _ = self._opened_state()
        event = _order(action="清仓-事件", shares=100)
        decision = _decision(prior, [event], date="20260727")
        packet = _packet({"ABC": [_bar("20260727", 10.7, 10.9, 10.5, 10.8)]}, "20260727")
        settlement, state, nav = settle_decision_bundle(prior, decision, packet, "20260727")
        tx = settlement["order_outcomes"][0]["transactions"][0]
        self.assertEqual("event_clear_next_open", tx["reason"])
        self.assertEqual("10.700000", tx["price"])
        self.assertEqual([], state["positions"])
        self.assertEqual("100069.000000", nav["nav"])

    def test_every_existing_holding_requires_one_decision_row(self) -> None:
        _, prior, _ = self._opened_state()
        decision = _decision(prior, [], date="20260727")
        packet = _packet({"ABC": [_bar("20260727", 10.5, 10.8, 10.2, 10.6)]}, "20260727")
        with self.assertRaisesRegex(ModelPaperPortfolioError, "missing decision row for holding"):
            settle_decision_bundle(prior, decision, packet, "20260727")

    def test_observe_holding_adds_no_action_but_keeps_existing_protective_stop(self) -> None:
        _, prior, _ = self._opened_state()
        observe = _order(action="观察", shares=None)
        observe["stop_clear_price"] = None
        observe["take_profit_reduce_price"] = None
        observe["take_profit_exit_price"] = None
        decision = _decision(prior, [observe], date="20260727")
        packet = _packet({"ABC": [_bar("20260727", 8.5, 8.8, 8.0, 8.4)]}, "20260727")
        settlement, state, _nav = settle_decision_bundle(prior, decision, packet, "20260727")
        self.assertEqual("观察", settlement["order_outcomes"][0]["final_action"])
        self.assertEqual("gap_stop", settlement["order_outcomes"][0]["transactions"][0]["reason"])
        self.assertEqual([], state["positions"])

    def test_forged_nav_identity_is_rejected(self) -> None:
        _, _, nav = self._opened_state()
        forged = copy.deepcopy(nav)
        forged["nav"] = "100050.000000"
        with self.assertRaisesRegex(ModelPaperPortfolioError, "NAV accounting identity"):
            validate_nav_snapshot(forged)

    def test_same_inputs_produce_byte_stable_artifacts(self) -> None:
        seed = seed_portfolio_state("20260717")
        decision = _decision(seed, [_order()])
        packet = _packet({"ABC": [_bar("20260720", 10.1, 10.2, 9.8, 10.1)]}, "20260720")
        first = settle_decision_bundle(seed, decision, packet, "20260720")
        second = settle_decision_bundle(copy.deepcopy(seed), copy.deepcopy(decision), copy.deepcopy(packet), "20260720")
        self.assertEqual(first, second)
        self.assertEqual([artifact_sha256(x) for x in first], [artifact_sha256(x) for x in second])

    def test_seed_nav_is_diagnostic_and_zero_balanced(self) -> None:
        state = seed_portfolio_state("20260717")
        nav = build_nav_snapshot(
            state,
            {"paper_evaluable": False, "status": "not_evaluable", "degradation_reasons": ["seed_state"], "source_sha256": None},
        )
        self.assertEqual("100000.000000", nav["nav"])
        self.assertEqual("0.000000", nav["total_pnl"])


if __name__ == "__main__":
    unittest.main()
