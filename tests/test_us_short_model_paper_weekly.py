from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from engine.us_short_model_paper_portfolio import artifact_sha256
from engine.us_short_model_paper_store import load_head
from engine.us_short_model_paper_weekly import ModelPaperWeeklyError, run_paper_weekly_transition
from runners.us_short_model_paper_weekly_capstone import (
    ModelPaperWeeklyCapstoneError,
    fixed_weekly_portfolio_metrics,
    forecast_holding_target_union,
    prepare_offline_model_paper_adapter,
    run_offline_model_paper_capstone,
)


def _raw_ohlcv(as_of: str, points: list[dict]) -> dict:
    iso = f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}"
    return {
        "decision_clock": {"expected_decision_date": "20260720" if as_of == "20260717" else "20260727"},
        "series_contract": {"as_of": iso, "session": "RTH", "adjustment_mode": "split_adjusted"},
        "provenance": {"observed_at": "2026-07-25T01:00:00Z"},
        "series_by_ticker": {
            "ABC": {"as_of": iso, "session": "RTH", "adjustment_mode": "split_adjusted", "points": points}
        },
    }


def _point(date: str, open_: float, high: float, low: float, close: float) -> dict:
    return {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "open": open_, "high": high, "low": low, "close": close}


def _raw_for(decision_date: str, price_basis_date: str, points: list[dict]) -> dict:
    iso = f"{price_basis_date[:4]}-{price_basis_date[4:6]}-{price_basis_date[6:]}"
    return {
        "decision_clock": {"expected_decision_date": decision_date},
        "series_contract": {"as_of": iso, "session": "RTH", "adjustment_mode": "split_adjusted"},
        "provenance": {"observed_at": "2026-08-15T01:00:00Z"},
        "series_by_ticker": {
            "ABC": {"as_of": iso, "session": "RTH", "adjustment_mode": "split_adjusted", "points": points}
        },
    }


def _order(action: str, *, shares: int | None) -> dict:
    return {
        "ticker": "ABC",
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
        "event_clear_reference_price": None,
        "event_source_ref_sha256": None,
    }


def _plan(order: dict):
    def factory(adapter: dict) -> dict:
        return {
            "source_receipt_sha256": "a" * 64,
            "source_as_of": adapter["decision_date"],
            "paper_account_adapter_sha256": artifact_sha256(adapter),
            "cost_prior": {"commission_fee": 0.001, "slippage_bps": 0.0, "spread_cost": 0.0},
            "orders": [copy.deepcopy(order)],
        }
    return factory


class ModelPaperWeeklyCapstoneTest(unittest.TestCase):
    def test_five_consecutive_fixture_weeks_keep_one_100k_head_and_report_nav_pnl_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = str(Path(td) / "model_paper_private")
            weeks = [
                ("20260720", "20260717", [], _order("建仓", shares=100)),
                ("20260727", "20260724", [_point("20260720", 10.0, 10.2, 9.9, 10.0), _point("20260724", 10.0, 10.2, 9.9, 10.1)], _order("持有", shares=None)),
                ("20260803", "20260731", [_point("20260727", 10.1, 10.4, 10.0, 10.2), _point("20260731", 10.2, 10.5, 10.1, 10.3)], _order("持有", shares=None)),
                ("20260810", "20260807", [_point("20260803", 10.3, 10.6, 10.2, 10.4), _point("20260807", 10.4, 10.7, 10.3, 10.5)], _order("持有", shares=None)),
                ("20260817", "20260814", [_point("20260810", 10.5, 10.8, 10.4, 10.6), _point("20260814", 10.6, 10.9, 10.5, 10.7)], _order("持有", shares=None)),
            ]
            summaries = []
            for decision_date, price_basis_date, points, order in weeks:
                summaries.append(run_offline_model_paper_capstone(
                    run_account_mode="dual", store_root=root, decision_date=decision_date,
                    price_basis_date=price_basis_date, created_at=f"{decision_date[:4]}-{decision_date[4:6]}-{decision_date[6:]}T08:00:00Z",
                    arrived_ohlcv_packet=_raw_for(decision_date, price_basis_date, points),
                    paper_plan_factory=_plan(order),
                ))
            self.assertIsNotNone(summaries[0]["seed_status"])
            self.assertTrue(all(summary["seed_status"] is None for summary in summaries[1:]))
            metrics = fixed_weekly_portfolio_metrics(store_root=root)
            self.assertEqual(5, metrics["consecutive_weeks"])
            self.assertEqual(
                f"{float(metrics['current_nav']) - 100000.0:.6f}",
                metrics["cumulative_pnl"],
            )

    def test_two_local_weeks_mature_then_freeze_without_manual_account_or_provider(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = str(Path(td) / "model_paper_private")
            first = run_offline_model_paper_capstone(
                run_account_mode="paper_only", store_root=root,
                decision_date="20260720", price_basis_date="20260717", created_at="2026-07-20T08:00:00Z",
                arrived_ohlcv_packet=_raw_ohlcv("20260717", []), paper_plan_factory=_plan(_order("建仓", shares=100)),
            )
            self.assertEqual("frozen", first["publish_status"])
            self.assertEqual("not_due", first["maturity_status"])
            self.assertFalse(first["provider_calls_performed"])
            self.assertFalse(first["manual_account_read"])
            self.assertFalse(first["ship_gate_eligible"])

            second = run_offline_model_paper_capstone(
                run_account_mode="dual", store_root=root,
                decision_date="20260727", price_basis_date="20260724", created_at="2026-07-27T08:00:00Z",
                arrived_ohlcv_packet=_raw_ohlcv("20260724", [
                    _point("20260720", 10.1, 10.2, 9.8, 10.1),
                    _point("20260721", 10.3, 10.6, 10.2, 10.5),
                    _point("20260724", 10.4, 10.8, 10.3, 10.7),
                ]),
                paper_plan_factory=_plan(_order("持有", shares=None)),
            )
            self.assertEqual("matured", second["maturity_status"])
            self.assertEqual("settled_and_frozen", second["publish_status"])
            self.assertFalse(second["paper_evaluable"])
            head = load_head(root)
            self.assertEqual("20260720", head["last_settlement"]["decision_date"])
            self.assertEqual("20260727", head["pending_decision"]["decision_date"])
            self.assertEqual("20260724", head["current_state"]["as_of"])

            forecast = forecast_holding_target_union(store_root=root, manual_holding_tickers=["MSFT", "ABC"])
            self.assertEqual(["ABC", "MSFT"], forecast["manual_paper_holding_target_union"])
            self.assertFalse(forecast["provider_calls_performed"])

            preview = prepare_offline_model_paper_adapter(
                store_root=root, decision_date="20260803", price_basis_date="20260731",
                arrived_ohlcv_packet=_raw_for("20260803", "20260731", [
                    _point("20260727", 10.5, 10.6, 10.4, 10.5), _point("20260731", 10.6, 10.7, 10.5, 10.6),
                ]),
            )
            self.assertEqual("matured", preview["maturity_status"])
            self.assertEqual("long", preview["account_state"]["positions"][0]["direction"])
            self.assertFalse(preview["provider_calls_performed"])

    def test_same_current_input_is_idempotent_not_superseded_even_when_rerun_clock_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = str(Path(td) / "model_paper_private")
            kwargs = {
                "run_account_mode": "paper_only", "store_root": root,
                "decision_date": "20260720", "price_basis_date": "20260717", "created_at": "2026-07-20T08:00:00Z",
                "arrived_ohlcv_packet": _raw_ohlcv("20260717", []), "paper_plan_factory": _plan(_order("建仓", shares=100)),
            }
            run_offline_model_paper_capstone(**kwargs)
            retry_kwargs = {**kwargs, "created_at": "2026-07-20T08:05:00Z"}
            retry = run_offline_model_paper_capstone(**retry_kwargs)
            self.assertEqual("idempotent", retry["publish_status"])
            self.assertIsNone(load_head(root)["pending_decision"]["supersedes_sha256"])

    def test_current_ohlcv_packet_from_a_different_decision_clock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = str(Path(td) / "model_paper_private")
            wrong_clock = _raw_ohlcv("20260717", [])
            wrong_clock["decision_clock"]["expected_decision_date"] = "20260721"
            with self.assertRaisesRegex(ModelPaperWeeklyCapstoneError, "decision clock"):
                run_offline_model_paper_capstone(
                    run_account_mode="paper_only", store_root=root,
                    decision_date="20260720", price_basis_date="20260717", created_at="2026-07-20T08:00:00Z",
                    arrived_ohlcv_packet=wrong_clock, paper_plan_factory=_plan(_order("建仓", shares=100)),
                )

    def test_factory_failure_after_pure_maturity_does_not_advance_head(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = str(Path(td) / "model_paper_private")
            run_offline_model_paper_capstone(
                run_account_mode="paper_only", store_root=root,
                decision_date="20260720", price_basis_date="20260717", created_at="2026-07-20T08:00:00Z",
                arrived_ohlcv_packet=_raw_ohlcv("20260717", []), paper_plan_factory=_plan(_order("建仓", shares=100)),
            )
            with self.assertRaisesRegex(ModelPaperWeeklyCapstoneError, "plan_factory"):
                run_offline_model_paper_capstone(
                    run_account_mode="paper_only", store_root=root,
                    decision_date="20260727", price_basis_date="20260724", created_at="2026-07-27T08:00:00Z",
                    arrived_ohlcv_packet=_raw_ohlcv("20260724", [
                        _point("20260720", 10.1, 10.2, 9.8, 10.1), _point("20260724", 10.3, 10.6, 10.2, 10.5),
                    ]),
                    paper_plan_factory=lambda _adapter: (_ for _ in ()).throw(ModelPaperWeeklyError("plan_factory failed")),
                )
            head = load_head(root)
            self.assertIsNone(head["last_settlement"])
            self.assertEqual("20260720", head["pending_decision"]["decision_date"])

    def test_pending_holding_missing_from_arrived_source_rejects_without_borrowing_candidate_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = str(Path(td) / "model_paper_private")
            run_offline_model_paper_capstone(
                run_account_mode="paper_only", store_root=root,
                decision_date="20260720", price_basis_date="20260717", created_at="2026-07-20T08:00:00Z",
                arrived_ohlcv_packet=_raw_ohlcv("20260717", []), paper_plan_factory=_plan(_order("建仓", shares=100)),
            )
            missing = _raw_ohlcv("20260724", [])
            missing["series_by_ticker"] = {}
            with self.assertRaisesRegex(ModelPaperWeeklyCapstoneError, "lacks source-bound OHLCV coverage"):
                run_offline_model_paper_capstone(
                    run_account_mode="paper_only", store_root=root,
                    decision_date="20260727", price_basis_date="20260724", created_at="2026-07-27T08:00:00Z",
                    arrived_ohlcv_packet=missing, paper_plan_factory=_plan(_order("持有", shares=None)),
                )
            head = load_head(root)
            self.assertIsNone(head["last_settlement"])
            self.assertEqual("20260720", head["pending_decision"]["decision_date"])

    def test_manual_actual_is_rejected_from_the_paper_driver(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ModelPaperWeeklyError, "manual_actual"):
                run_paper_weekly_transition(
                    run_account_mode="manual_actual", store_root=str(Path(td) / "model_paper_private"),
                    decision_date="20260720", price_basis_date="20260717", created_at="2026-07-20T08:00:00Z",
                    price_packet={"as_of": "20260717"}, plan_factory=_plan(_order("建仓", shares=100)),
                )


if __name__ == "__main__":
    unittest.main()
