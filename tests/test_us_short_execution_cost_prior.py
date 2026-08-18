from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from engine.us_short_cost_floor import apply_cost_floor
from engine.us_short_execution_cost_prior import (
    build_execution_cost_prior,
    dollar_costs,
)
from engine.us_short_holding_action import attach_holding_action_context, plan_holding_action
from engine.us_short_model_paper_portfolio import settle_decision_bundle
from engine.us_short_model_paper_store import load_current_state, load_head, load_pending_decision
from engine.us_short_result_source_linkage import _ohlcv_price
from engine.us_short_weekend_orchestrator import _probe_cost_inputs
from runners.us_short_model_paper_weekly_capstone import (
    ModelPaperWeeklyCapstoneError,
    paper_plan_factory_from_machine_record,
    price_packet_from_arrived_ohlcv,
    run_offline_model_paper_capstone,
)


def _bars(offsets: list[float], *, volume: float | None = 1.0, price: float = 100.0) -> list[dict]:
    return [
        {
            "high": 200.0,
            "low": 50.0,
            "close": price * math.exp(offset),
            "volume": volume,
        }
        for offset in offsets
    ]


def _holding_row(prior: dict | None) -> dict:
    row = {"ticker": "ABC", "row_source": "holding", "execution_cost_prior": prior}
    return row


def _holding_context(**over) -> dict:
    context = {
        "status": "ready",
        "shares": 100,
        "entry_date": "20260601",
        "avg_cost_usd": 100.0,
        "tp1_completed": False,
        "tp1_completed_at": None,
        "active_tp1_price": 110.0,
        "active_tp2_price": 120.0,
        "levels_as_of": "20260612",
        "source_reconciliation_ref": "manual_account:test",
        "price_basis_value": 110.0,
    }
    context.update(over)
    return context


def _paper_point(date: str, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }


def _raw_packet(decision_date: str, price_basis_date: str, points: list[dict]) -> dict:
    iso = f"{price_basis_date[:4]}-{price_basis_date[4:6]}-{price_basis_date[6:]}"
    return {
        "decision_clock": {"expected_decision_date": decision_date},
        "series_contract": {"as_of": iso, "session": "RTH", "adjustment_mode": "split_adjusted"},
        "provenance": {"observed_at": "2026-08-18T01:00:00Z"},
        "series_by_ticker": {
            "ABC": {"as_of": iso, "session": "RTH", "adjustment_mode": "split_adjusted", "points": points}
        },
    }


def _machine_record(as_of: str, action: str) -> dict:
    fields = {
        "order_type": "pullback_limit" if action == "建仓" else None,
        "order_expiry": "first_regular_session_only" if action == "建仓" else None,
        "valid_entry_low": 9.8 if action == "建仓" else None,
        "valid_entry_high": 10.2 if action == "建仓" else None,
        "limit_order_price": 10.0 if action == "建仓" else None,
        "breakout_entry_price": None,
        "stop_clear_price": 9.0,
        "take_profit_reduce_price": 11.0,
        "take_profit_exit_price": 12.0,
        "event_clear_reference_price": None,
    }
    row = {
        "ticker": "ABC",
        "final_action": action,
        "price": {"action_fields": fields},
    }
    if action == "建仓":
        row["sizing"] = {"desired_model_shares": 100}
        row["execution_cost_prior"] = {
            "round_trip_spread_fraction": 0.001,
            "spread_source": "adv_bucket_v1",
        }
    return {"as_of": as_of, "rows": [row]}


class ExecutionCostPriorAcceptanceTest(unittest.TestCase):
    def test_chl_is_arithmetic_winsorized_and_needs_fifteen_pairs(self) -> None:
        offsets = [0.004, 0.004, -0.002, 0.001, 0.0008, 0.0006, 0.0005, 0.0004,
                   0.0003, 0.0002, 0.0001, -0.0001, -0.0002, -0.0003, -0.0004, -0.0005]
        prior = build_execution_cost_prior(_bars(offsets), adv_usd=100_000_000.0)
        samples = [offsets[index] ** 2 for index in range(15)]
        ordered = sorted(samples)
        ordered[0] = ordered[1] = ordered[2]
        ordered[-1] = ordered[-2] = ordered[-3]
        expected = math.sqrt(max(4.0 * sum(ordered) / 15.0, 0.0))
        self.assertEqual(prior["spread_source"], "modeled_chl_winsor_v1")
        self.assertAlmostEqual(prior["round_trip_spread_fraction"], expected)

        short_history = build_execution_cost_prior(_bars(offsets[:15]), adv_usd=100_000_000.0)
        self.assertEqual(short_history["spread_source"], "adv_bucket_v1")
        self.assertAlmostEqual(short_history["round_trip_spread_fraction"], 0.0004)

    def test_single_bar_spike_is_capped_across_both_adjacent_pair_tails(self) -> None:
        bars = _bars([0.002] * 20)
        bars[8]["high"] = 600.0
        prior = build_execution_cost_prior(bars, adv_usd=100_000_000.0)
        self.assertEqual(prior["spread_source"], "modeled_chl_winsor_v1")
        self.assertLess(prior["round_trip_spread_fraction"], 0.01)

    def test_chl_does_not_get_tick_floor_but_adv_does(self) -> None:
        tiny = build_execution_cost_prior(_bars([0.000001] * 16), adv_usd=100_000_000.0)
        self.assertEqual(tiny["spread_source"], "modeled_chl_winsor_v1")
        self.assertLess(tiny["round_trip_spread_fraction"], 0.00005)

        five_dollar = build_execution_cost_prior(
            _bars([0.0] * 15, price=5.0), adv_usd=100_000_000.0)
        self.assertEqual(five_dollar["spread_source"], "adv_bucket_v1")
        self.assertAlmostEqual(five_dollar["round_trip_spread_fraction"], 0.002)

        too_wide = build_execution_cost_prior(
            _bars([0.0] * 15, price=0.25), adv_usd=100_000_000.0)
        self.assertEqual(too_wide, {
            "round_trip_spread_fraction": None,
            "spread_source": "unavailable_too_wide",
        })

    def test_three_prior_degradation_paths_are_explicit(self) -> None:
        modeled = build_execution_cost_prior(_bars([0.002] * 16), adv_usd=100_000_000.0)
        self.assertEqual(modeled["spread_source"], "modeled_chl_winsor_v1")
        adv = build_execution_cost_prior(_bars([0.02] * 10), adv_usd=100_000_000.0)
        self.assertEqual(adv["spread_source"], "adv_bucket_v1")
        unavailable = build_execution_cost_prior(None, adv_usd=None)
        self.assertEqual(unavailable, {"round_trip_spread_fraction": None, "spread_source": "unavailable"})

    def test_dollar_conversion_and_existing_cost_floor_use_round_trip_dollars(self) -> None:
        costs = dollar_costs(
            {"round_trip_spread_fraction": 0.001, "spread_source": "modeled_chl_winsor_v1"},
            shares=10,
            reference_price=100.0,
        )
        self.assertEqual(costs, {
            "commission_round_trip": 1.0,
            "slippage_dollars": 0.0,
            "spread_dollars": 1.0,
        })
        self.assertEqual(apply_cost_floor(1, 100.0, 108.1, 1.0, 0.0, 1.0)["status"], "ok")
        self.assertEqual(apply_cost_floor(1, 100.0, 108.0, 1.0, 0.0, 1.0)["observe_reason_type"],
                         "cost_inefficient_min_size")

    def test_result_source_keeps_existing_volume_and_manual_spread_tag(self) -> None:
        points = [
            {
                "date": f"2026-06-{day:02d}",
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 123.0,
            }
            for day in range(1, 16)
        ]
        packet = {
            "series_contract": {"as_of": "2026-06-15", "session": "RTH", "adjustment_mode": "adjusted"},
            "provenance": {
                "observed_at": "2026-06-15T00:00:00Z",
                "coverage_status": "full",
                "parser_status": "ok",
            },
            "series_by_ticker": {
                "AAPL": {
                    "as_of": "2026-06-15", "session": "RTH", "adjustment_mode": "adjusted", "points": points,
                }
            },
        }
        price, _check, _tags, constraints = _ohlcv_price(
            packet, ticker="AAPL", price_basis_date="20260615", universe_close=100.0,
            as_of="20260615", source_digest="a" * 64,
        )
        self.assertEqual(price["input"]["bars"][-1]["volume"], 123.0)
        self.assertEqual(constraints, ["spread:unavailable_manual_check"])

    def test_entry_cost_floor_is_after_final_basket_and_has_exact_coverage(self) -> None:
        prior = {"round_trip_spread_fraction": 0.001, "spread_source": "modeled_chl_winsor_v1"}
        row = {
            "ticker": "ABC",
            "final_action": "建仓",
            "theme_probe": {"risk_tag": "theme_probe_min_size", "entry_mode_constraint": "none"},
            "sizing": {"desired_model_shares": 1},
            "price": {"action_fields": {"valid_entry_high": 100.0}},
            "execution_cost_prior": prior,
        }
        costs = _probe_cost_inputs({"rows": [row]})
        self.assertEqual(costs, {
            "ABC": {"commission_round_trip": 0.1, "slippage_dollars": 0.0, "spread_dollars": 0.1}
        })
        self.assertEqual(_probe_cost_inputs({"rows": [{"ticker": "ABC", "final_action": "建仓"}]}), {})

    def test_holding_tp1_uses_avg_cost_and_distinguishes_untrusted_price(self) -> None:
        prior = {"round_trip_spread_fraction": 0.001, "spread_source": "modeled_chl_winsor_v1"}
        attached = attach_holding_action_context(
            [_holding_row(prior)], {"ABC": _holding_context()}, price_basis_date="20260815")
        context = attached[0]["holding_action_context"]
        self.assertEqual(context["cost_input"], {
            "commission_round_trip": 1.0, "slippage_dollars": 0.0, "spread_dollars": 1.0,
        })
        evidence = {
            "holding_action_context": context,
            "price": {"action_fields": {
                "stop_clear_price": 95.0,
                "take_profit_reduce_price": 112.0,
                "take_profit_exit_price": 124.0,
                "event_clear_reference_price": 94.0,
            }},
        }
        action, reason, _proposal, _price = plan_holding_action(evidence, "持有", None)
        self.assertEqual((action, reason), ("减仓", None))

        unavailable = attach_holding_action_context(
            [_holding_row({"round_trip_spread_fraction": None, "spread_source": "unavailable"})],
            {"ABC": _holding_context()}, price_basis_date="20260815")[0]["holding_action_context"]
        action, reason, proposal, _price = plan_holding_action(
            {"holding_action_context": unavailable, "price": evidence["price"]}, "持有", None)
        self.assertEqual((action, reason), ("持有", None))
        self.assertEqual(proposal["reason"], "tp1_deferred_unverifiable_cost")

        untrusted_price = copy.deepcopy(context)
        untrusted_price["price_basis_value"] = None
        action, reason, _proposal, _price = plan_holding_action(
            {"holding_action_context": untrusted_price, "price": evidence["price"]}, "持有", None)
        self.assertEqual((action, reason), ("观察", "cash_or_account_missing"))

    def test_model_paper_real_machine_chain_charges_actual_fill_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = str(Path(td) / "model_paper_private")
            first_path = Path(td) / "machine_build.json"
            first_path.write_text(
                json.dumps(_machine_record("20260720", "建仓"), ensure_ascii=False), encoding="utf-8")
            first_factory = paper_plan_factory_from_machine_record(first_path)
            run_offline_model_paper_capstone(
                run_account_mode="paper_only", store_root=root, decision_date="20260720",
                price_basis_date="20260717", created_at="2026-07-20T08:00:00Z",
                arrived_ohlcv_packet=_raw_packet("20260720", "20260717", []),
                paper_plan_factory=first_factory,
            )
            pending = load_pending_decision(root)
            self.assertEqual(pending["orders"][0]["spread_source"], "adv_bucket_v1")
            self.assertEqual(pending["orders"][0]["round_trip_spread_fraction"], 0.001)

            price_packet = price_packet_from_arrived_ohlcv(
                ohlcv_packet=_raw_packet("20260727", "20260724", [
                    _paper_point("20260720", 10.0, 10.2, 9.9, 10.0),
                    _paper_point("20260724", 10.0, 10.2, 9.9, 10.1),
                ]),
                pending_decision=pending, decision_date="20260727", price_basis_date="20260724",
            )
            legacy_plus_order = copy.deepcopy(pending)
            legacy_plus_order["cost_prior"]["spread_cost"] = 0.0005
            settlement, state, nav = settle_decision_bundle(
                load_current_state(root), legacy_plus_order, price_packet, "20260724")
            self.assertEqual(settlement["order_outcomes"][0]["transactions"][0]["cost_paid_delta"], "2.000000")
            self.assertEqual(state["cumulative_cost_paid"], "2.000000")
            self.assertEqual(nav["nav"], "100008.000000")

            second_path = Path(td) / "machine_hold.json"
            second_path.write_text(
                json.dumps(_machine_record("20260727", "持有"), ensure_ascii=False), encoding="utf-8")
            run_offline_model_paper_capstone(
                run_account_mode="paper_only", store_root=root, decision_date="20260727",
                price_basis_date="20260724", created_at="2026-07-27T08:00:00Z",
                arrived_ohlcv_packet=_raw_packet("20260727", "20260724", [
                    _paper_point("20260720", 10.0, 10.2, 9.9, 10.0),
                    _paper_point("20260724", 10.0, 10.2, 9.9, 10.1),
                ]),
                paper_plan_factory=paper_plan_factory_from_machine_record(second_path),
            )
            head = load_head(root)
            settlement = json.loads(
                (Path(root) / "weeks" / "20260720" / "settlement.json").read_text(encoding="utf-8"))
            self.assertEqual(settlement["order_outcomes"][0]["transactions"][0]["cost_paid_delta"], "2.000000")
            self.assertEqual(load_current_state(root)["cumulative_cost_paid"], "2.000000")

    def test_new_machine_build_without_usable_prior_fails_before_store_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "machine_missing_prior.json"
            record = _machine_record("20260720", "建仓")
            record["rows"][0]["execution_cost_prior"] = {
                "round_trip_spread_fraction": None,
                "spread_source": "unavailable",
            }
            path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ModelPaperWeeklyCapstoneError, "usable execution-cost prior"):
                paper_plan_factory_from_machine_record(path)
            self.assertFalse((Path(td) / "model_paper_private").exists())


if __name__ == "__main__":
    unittest.main()
