from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engine.us_short_model_paper_store import load_head
import runners.us_short_weekly_capstone as capstone
from runners.us_short_weekly_capstone import Stage, _run_model_paper_adapter, _run_model_paper_weekly, default_pipeline, run_weekly_capstone


def _packet(decision: str, basis: str, points: list[dict]) -> dict:
    iso = f"{basis[:4]}-{basis[4:6]}-{basis[6:]}"
    return {
        "decision_clock": {"expected_decision_date": decision},
        "series_contract": {"as_of": iso, "session": "RTH", "adjustment_mode": "split_adjusted"},
        "provenance": {"observed_at": "2026-07-25T01:00:00Z"},
        "series_by_ticker": {"ABC": {"as_of": iso, "session": "RTH", "adjustment_mode": "split_adjusted", "points": points}},
    }


def _point(date: str, close: float) -> dict:
    return {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "open": close, "high": close + 0.1, "low": close - 0.1, "close": close}


def _record(decision: str, action: str) -> dict:
    fields = {
        "order_type": "pullback_limit", "order_expiry": "first_regular_session_only",
        "valid_entry_low": 9.8, "valid_entry_high": 10.2, "limit_order_price": 10.0,
        "breakout_entry_price": None, "stop_clear_price": 9.0,
        "take_profit_reduce_price": 11.0, "take_profit_exit_price": 12.0,
        "event_clear_reference_price": None,
    }
    return {"as_of": decision, "rows": [{"ticker": "ABC", "final_action": action, "price": {"action_fields": fields}, "sizing": {"desired_model_shares": 100}}]}


class ModelPaperCapstoneWiringTest(unittest.TestCase):
    def test_default_pipeline_matures_then_adapts_before_bridge_and_freezes_after(self) -> None:
        names = [stage.name for stage in default_pipeline(include_model_paper=True)]
        self.assertLess(names.index("momentum_fetch"), names.index("model_paper_adapter"))
        self.assertLess(names.index("model_paper_adapter"), names.index("pass2_preflight"))
        self.assertLess(names.index("weekly_bridge"), names.index("model_paper_weekly"))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = root / "model_paper_private"
            account = root / "paper_account_state.adapter.json"
            report = root / "weekly_private" / "20260720" / "weekly_report.md"
            machine = root / "runs_private" / "20260720" / "machine_record.json"
            packet = root / "ohlcv.json"
            report.parent.mkdir(parents=True)
            machine.parent.mkdir(parents=True)
            report.write_text("weekly base\n", encoding="utf-8")
            machine.write_text(json.dumps(_record("20260720", "建仓")), encoding="utf-8")
            packet.write_text(json.dumps(_packet("20260720", "20260717", [])), encoding="utf-8")
            ctx = SimpleNamespace(
                model_paper_store_root=store, model_paper_run_account_mode="paper_only",
                decision_date="20260720", price_basis_date="20260717", generated_at="2026-07-20T08:00:00Z",
                ohlcv_series_packet_path=packet, account_state_path=account, official_output_root=root, private_root=root,
            )
            preview = _run_model_paper_adapter(ctx)
            self.assertTrue(account.is_file())
            self.assertTrue(preview["seed_required"])
            terminal = _run_model_paper_weekly(ctx)
            self.assertEqual("frozen", terminal["publish_status"])
            self.assertIn("cumulative_pnl", report.read_text(encoding="utf-8"))
            self.assertEqual("20260720", load_head(store)["pending_decision"]["decision_date"])

            report2 = root / "weekly_private" / "20260727" / "weekly_report.md"
            machine2 = root / "runs_private" / "20260727" / "machine_record.json"
            packet2 = root / "ohlcv2.json"
            report2.parent.mkdir(parents=True)
            machine2.parent.mkdir(parents=True)
            report2.write_text("weekly base\n", encoding="utf-8")
            machine2.write_text(json.dumps(_record("20260727", "持有")), encoding="utf-8")
            packet2.write_text(json.dumps(_packet("20260727", "20260724", [_point("20260720", 10.0), _point("20260724", 10.1)])), encoding="utf-8")
            ctx.decision_date, ctx.price_basis_date, ctx.generated_at = "20260727", "20260724", "2026-07-27T08:00:00Z"
            ctx.ohlcv_series_packet_path, ctx.official_output_root = packet2, root
            preview2 = _run_model_paper_adapter(ctx)
            self.assertEqual("matured", preview2["maturity_status"])
            terminal2 = _run_model_paper_weekly(ctx)
            self.assertEqual("settled_and_frozen", terminal2["publish_status"])
            self.assertEqual(2, terminal2["weekly_portfolio_metrics"]["consecutive_weeks"])

    def test_run_weekly_capstone_reaches_model_paper_terminal_once_with_bridge_receipt(self) -> None:
        """Exercise the production loop; direct stage calls cannot prove this seam."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private_root = root / "private"
            store_root = private_root / "model_paper_private"

            def write_json(path: Path, payload: dict) -> None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")

            def seed_momentum(ctx):
                packet = _packet("20260720", "20260717", [])
                write_json(ctx.series_packet_path, packet)
                write_json(ctx.ohlcv_series_packet_path, packet)
                return {"stage": "momentum"}

            def seed_preflight(ctx):
                summary = {
                    "endpoint_call_forecast": {"total_calls_for_pass2_target_cut": 1},
                    "pass2_target_universe": {"target_count": 1},
                    "execution_gate": {"ready_to_run_full_candidate_live_packet": False},
                }
                write_json(ctx.preflight_summary_path, summary)
                return summary

            def seed_weekly_bridge(ctx):
                report_path, action_path, machine_path = capstone._official_output_paths(ctx)
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text("# weekly base\n", encoding="utf-8")
                action_path.write_text("ticker\nABC\n", encoding="utf-8")
                write_json(machine_path, _record("20260720", "建仓"))
                return {
                    "batch4_run": {
                        "emitted": True,
                        "output_paths": {
                            "weekly_report_path": str(report_path),
                            "action_table_path": str(action_path),
                            "machine_record_path": str(machine_path),
                        },
                    }
                }

            pipeline = (
                Stage("momentum", False, lambda _ctx: (), lambda ctx: (ctx.series_packet_path, ctx.ohlcv_series_packet_path), seed_momentum),
                Stage("model_paper_adapter", False, lambda ctx: (ctx.ohlcv_series_packet_path,), lambda ctx: (ctx.account_state_path,), _run_model_paper_adapter),
                Stage("pass2_preflight", False, lambda _ctx: (), lambda ctx: (ctx.preflight_summary_path,), seed_preflight),
                Stage("weekly_bridge", False, lambda _ctx: (), capstone._official_output_paths, seed_weekly_bridge),
                Stage("model_paper_weekly", False, lambda ctx: (ctx.ohlcv_series_packet_path, capstone._official_output_paths(ctx)[0], capstone._official_output_paths(ctx)[2]), lambda ctx: (capstone._official_output_paths(ctx)[0],), _run_model_paper_weekly),
            )
            receipt = mock.Mock(side_effect=[{"bridge": "receipt"}])
            with (
                mock.patch.object(capstone, "default_pipeline", return_value=pipeline),
                mock.patch.object(capstone, "_provider_execution_receipt", receipt),
            ):
                summary = run_weekly_capstone(
                    dry_run=False,
                    confirm_user_authorization=True,
                    auto_authorize_pass2_budget=True,
                    authorized_momentum_top_k=200,
                    private_root=private_root,
                    state_dir=root / "state",
                    sample_root=root,
                    batch4_template_path=root / "inputs" / "batch4_template.md",
                    account_state_path=root / "inputs" / "paper_account_state.adapter.json",
                    now_et=datetime(2026, 7, 20, 8, 0, 0),
                    model_paper_store_root=store_root,
                    model_paper_run_account_mode="paper_only",
                )

            self.assertTrue(summary["emitted"])
            self.assertEqual(1, receipt.call_count)
            terminal = next(item for item in summary["stages"] if item["name"] == "model_paper_weekly")
            weekly = terminal["result"]
            self.assertEqual("frozen", weekly["publish_status"])
            self.assertEqual(
                {"initial_capital", "current_cash", "holdings_market_value", "current_nav", "cumulative_pnl", "cumulative_return_pct", "consecutive_weeks"},
                {key for key in weekly["weekly_portfolio_metrics"] if key not in {"paper_evaluable", "performance_status"}},
            )
            self.assertEqual("20260720", load_head(store_root)["pending_decision"]["decision_date"])
            report = private_root / "weekly_private" / "20260720" / "weekly_report.md"
            self.assertTrue(report.exists())
            self.assertIn("cumulative_pnl", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
