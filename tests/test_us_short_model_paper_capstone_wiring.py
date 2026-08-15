from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engine.us_short_model_paper_store import load_head
from engine.us_short_result_effects import apply_result_effects, build_portfolio_guard_result
import runners.us_short_weekly_capstone as capstone
from runners import us_short_weekly_capstone_stages as capstone_stages
from runners.us_short_weekly_capstone import (
    Stage,
    WeeklyCapstoneError,
    _run_model_paper_adapter,
    _run_model_paper_weekly,
    default_pipeline,
    run_weekly_capstone,
)
from tests.provider.test_us_short_batch5_data_context import _candidate_artifact
from tests.provider.us_short_private_test_root import temporary_us_short_state_directory


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
    def test_model_paper_nav_reaches_portfolio_guard_and_result_effects(self) -> None:
        """The source-bound adapter packet must replace the synthetic bridge template at the real consumers."""
        as_of = "20260720"
        track = {
            "paper_evaluable": True,
            "consecutive_stops": 0,
            "paper_drawdown_frac": 0.0,
            "evidence_ref": {
                "kind": "source_id", "value": "model_paper_nav:source-bound-test", "as_of": as_of,
            },
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            template = root / "batch4_template.json"
            template.write_text(
                json.dumps({
                    "paper_track": {
                        "paper_evaluable": False,
                        "consecutive_stops": None,
                        "paper_drawdown_frac": None,
                        "evidence_ref": {
                            "kind": "source_id", "value": "synthetic_fixture:paper_track_not_evaluable",
                        },
                    },
                }),
                encoding="utf-8",
            )
            vix = root / "vix.json"
            vix.write_text(json.dumps({"vix_regime": "进攻", "vix_regime_is_unknown": False}), encoding="utf-8")
            seen: dict[str, object] = {}

            def fake_run_e2e(**kwargs):
                supplied = kwargs.get("model_paper_track")
                if supplied is None:
                    supplied = json.loads(template.read_text(encoding="utf-8"))["paper_track"]
                guard = build_portfolio_guard_result(
                    supplied,
                    prior_state={"schema_name": "us_short_portfolio_guard_state", "schema_version": "1.0.0",
                                 "as_of": as_of, "state": "normal"},
                    as_of=as_of,
                )
                effected = apply_result_effects(
                    {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": [{
                        "ticker": "ABC", "final_action": "观察", "observe_reason_type": "capacity_or_budget_deferred",
                    }]},
                    portfolio_guard_result=guard,
                    cooldown_by_ticker={"ABC": {
                        "status": "none", "cooldown_until": None, "reentry_allowed_reason": None,
                        "evidence_ref": {"kind": "source_id", "value": "cooldown:test", "as_of": as_of},
                    }},
                    as_of=as_of,
                )
                seen["evidence_ref"] = effected["rows"][0]["result_effects"]["evidence_refs"]["portfolio_guard"]["value"]
                return {"batch4_run": {"emitted": False, "no_emit_reason": "out_of_window"}}

            ctx = SimpleNamespace(
                vix_regime_summary_path=vix,
                research_live_capability=None,
                forward_policy_comparison_ledger_path=root / "comparison.json",
                source_packet_path=root / "source.json",
                batch4_template_path=template,
                account_state_path=root / "account.json",
                provider_health_path=root / "health.json",
                private_root=root,
                official_output_root=None,
                now_et=datetime(2026, 7, 20, 8, 0, 0),
                context_components_path=root / "components.json",
                generated_at="2026-07-20T08:00:00-04:00",
                serenity_shadow_result=None,
                serenity_quality_run_result=None,
                model_paper_store_root=root / "model_paper_private",
                model_paper_track=track,
            )
            with (
                mock.patch.object(capstone_stages, "_write_provider_health"),
                mock.patch.object(capstone_stages, "comparison_banner_from_private_ledger_path", return_value=None),
                mock.patch.object(capstone_stages, "classify_soft_boost_artifact_state", return_value={"state": "not_applicable", "reason_code": None}),
                mock.patch.object(capstone_stages._bridge, "run_e2e", side_effect=fake_run_e2e),
            ):
                capstone_stages.run_weekly_bridge(ctx)
        self.assertEqual(seen["evidence_ref"], "model_paper_nav:source-bound-test")

    def test_formal_model_paper_bridge_without_track_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx = SimpleNamespace(
                model_paper_store_root=root / "model_paper_private",
                model_paper_track=None,
                vix_regime_summary_path=root / "vix.json",
                forward_policy_comparison_ledger_path=root / "comparison.json",
                source_packet_path=root / "source.json",
                batch4_template_path=root / "template.json",
                account_state_path=root / "account.json",
                provider_health_path=root / "health.json",
                private_root=root,
                official_output_root=None,
                now_et=datetime(2026, 7, 20, 8, 0, 0),
                context_components_path=root / "components.json",
                generated_at="2026-07-20T08:00:00-04:00",
            )
            ctx.vix_regime_summary_path.write_text(
                json.dumps({"vix_regime": "进攻", "vix_regime_is_unknown": False}), encoding="utf-8"
            )
            with mock.patch.object(capstone_stages, "_write_provider_health"), \
                 mock.patch.object(capstone_stages, "comparison_banner_from_private_ledger_path", return_value=None), \
                 mock.patch.object(capstone_stages, "classify_soft_boost_artifact_state", return_value={"state": "not_applicable", "reason_code": None}), \
                 mock.patch.object(capstone_stages._bridge, "run_e2e") as run_e2e:
                with self.assertRaisesRegex(ValueError, "model-paper.*paper_track"):
                    capstone_stages.run_weekly_bridge(ctx)
                run_e2e.assert_not_called()

    def test_direct_model_paper_capstone_without_receipt_stops_before_stage(self) -> None:
        entered: list[str] = []

        def must_not_run(_ctx):
            entered.append("stage")
            raise AssertionError("model-paper stage was entered before activation")

        stage = Stage("must_not_run", False, lambda _ctx: [], lambda _ctx: [], must_not_run)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch(
                "engine.us_short_model_paper_activation.resolve_model_paper_activation",
                return_value={"status": "dormant", "receipt": None},
            ) as activation:
                summary = run_weekly_capstone(
                    now_et=datetime(2026, 7, 20, 8, 0, 0),
                    private_root=root / "private",
                    batch4_template_path=root / "template.json",
                    account_state_path=root / "account.json",
                    dry_run=False,
                    confirm_user_authorization=True,
                    state_dir=root / "state",
                    sample_root=root,
                    stages=[stage],
                    model_paper_store_root=root / "private" / "model_paper_private",
                    model_paper_run_account_mode="paper_only",
                )
            activation.assert_called_once_with()
        self.assertEqual(summary["activation_status"], "dormant")
        self.assertFalse(summary["model_paper_started"])
        self.assertEqual([], entered)

    def test_activation_failure_redacts_private_exception_details(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private_path = root / "private" / "diagnostic_start_receipt.json"
            with mock.patch(
                "engine.us_short_model_paper_activation.resolve_model_paper_activation",
                side_effect=ValueError(str(private_path)),
            ):
                with self.assertRaisesRegex(WeeklyCapstoneError, "activation_gate_broken: ValueError") as raised:
                    run_weekly_capstone(
                        now_et=datetime(2026, 7, 20, 8, 0, 0),
                        private_root=root / "private",
                        batch4_template_path=root / "template.json",
                        account_state_path=root / "account.json",
                        dry_run=False,
                        confirm_user_authorization=True,
                        state_dir=root / "state",
                        sample_root=root,
                        stages=[],
                        model_paper_store_root=root / "private" / "model_paper_private",
                        model_paper_run_account_mode="paper_only",
                    )
            self.assertNotIn("diagnostic_start_receipt.json", str(raised.exception))

    def test_absent_in_repo_model_paper_root_reaches_first_week_seed_preview(self) -> None:
        with temporary_us_short_state_directory(capstone.ROOT) as state_root_text:
            state_root = Path(state_root_text)
            store = state_root / "model_paper_private"
            self.assertFalse(store.exists(), f"fresh test model-paper root unexpectedly exists: {store}")
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                account = root / "paper_account_state.adapter.json"
                packet = root / "ohlcv.json"
                packet.write_text(json.dumps(_packet("20260720", "20260717", [])), encoding="utf-8")
                ctx = SimpleNamespace(
                    model_paper_store_root=store,
                    model_paper_run_account_mode="paper_only",
                    decision_date="20260720",
                    price_basis_date="20260717",
                    generated_at="2026-07-20T08:00:00Z",
                    ohlcv_series_packet_path=packet,
                    account_state_path=account,
                    official_output_root=state_root,
                    private_root=state_root,
                )
                preview = _run_model_paper_adapter(ctx)
                self.assertTrue(preview["seed_required"])
                self.assertTrue(account.is_file())
            self.assertFalse(store.exists(), "adapter preview must not create the model-paper store root")

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
                packet = _packet("20260615", "20260612", [])
                write_json(ctx.series_packet_path, packet)
                write_json(ctx.ohlcv_series_packet_path, packet)
                return {"stage": "momentum"}

            def seed_preflight(ctx):
                candidate = _candidate_artifact(("AAPL",))
                write_json(ctx.candidate_path, candidate)
                summary = {
                    "decision_clock": {
                        "expected_decision_date": ctx.decision_date,
                        "candidate_price_basis_date": ctx.price_basis_date,
                        "price_basis_date": "2026-06-12",
                        "used_date": "2026-06-12",
                    },
                    "candidate_universe": {
                        "candidate_artifact_path": f"state/us_short/{ctx.candidate_path.name}",
                        "candidate_artifact_path_gitignored": True,
                        "candidate_artifact_sha256": capstone._sha256_file(ctx.candidate_path),
                        "row_count": candidate["row_count"],
                        "eligible_count": candidate["eligible_count"],
                        "eligible_symbol_sample": candidate["eligible_tickers"],
                        "symbol_scope": "full_pass1_eligible_candidate_set",
                        "full_market_sample": False,
                    },
                    "pass2_target_universe": {
                        "selection_mode": "momentum_theme_top_k_plus_catalyst_recall_plus_forced_holdings",
                        "eligible_count": candidate["eligible_count"],
                        "momentum_scored_candidate_count": 1,
                        "momentum_top_k": ctx.authorized_momentum_top_k,
                        "forced_holding_count": 0,
                        "target_count": 1,
                        "target_symbols": ["AAPL"],
                        "target_symbol_sample": ["AAPL"],
                        "fmp_grade_call_cap": 250,
                        "fmp_grade_calls_within_free_daily_cap": True,
                        "neutral_fill_tickers_excluded_from_expensive_pass2": True,
                        "expensive_pass2_targets_full_eligible_set": True,
                    },
                    "endpoint_call_forecast": {
                        "families": {
                            "pass2_source_packet": {
                                "sec_company_tickers_mapping_calls": 1,
                                "fmp_grades_calls": 1,
                                "sec_submissions_calls": 1,
                                "massive_reference_news_calls": 1,
                                "total_calls": 4,
                            },
                            "corporate_action_live_half": {
                                "massive_split_calls": 1,
                                "massive_dividend_calls": 1,
                                "total_calls": 2,
                                "corporate_action_reconciliation_performed_by_preflight": False,
                            },
                            "momentum_price_refresh_if_local_projection_missing": {
                                "massive_daily_aggregates_calls": 2,
                                "benchmark_symbols": ["SPY", "QQQ"],
                                "not_in_total_until_separate_price_packet_review": True,
                            },
                        },
                        "forecast_basis": "pass2_target_universe_not_full_eligible_count",
                        "total_calls_for_pass2_target_cut": 6,
                        "total_calls_for_full_candidate_cut": 6,
                        "total_calls_for_full_candidate_cut_is_hypothetical": True,
                        "call_budget_must_be_explicit_before_network": True,
                        "full_market_call_performed": False,
                    },
                    "execution_gate": {"ready_to_run_full_candidate_live_packet": False},
                }
                write_json(ctx.preflight_summary_path, summary)
                return summary

            def seed_weekly_bridge(ctx):
                seen_track["value"] = ctx.model_paper_track
                report_path, action_path, machine_path = capstone._official_output_paths(ctx)
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text("# weekly base\n", encoding="utf-8")
                action_path.write_text("ticker\nABC\n", encoding="utf-8")
                write_json(machine_path, _record(ctx.decision_date, "建仓"))
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

            seen_track: dict[str, object] = {}
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
                mock.patch(
                    "engine.us_short_live_provider_preflight._now_et_wall_clock",
                    return_value=datetime(2026, 6, 15, 8, 0, 0),
                ),
                mock.patch(
                    "engine.us_short_model_paper_activation.resolve_model_paper_activation",
                    return_value={"status": "authorized", "receipt": {}},
                ),
                mock.patch(
                    "runners.us_short_batch5_full_candidate_pass2_preflight.finalize_preflight_from_existing_derivation",
                    side_effect=lambda **kwargs: json.loads(
                        kwargs["preflight_summary_path"].read_text(encoding="utf-8")
                    ),
                ),
            ):
                summary = run_weekly_capstone(
                    dry_run=False,
                    confirm_user_authorization=True,
                    auto_authorize_pass2_budget=True,
                    authorized_momentum_top_k=200,
                    private_root=private_root,
                    state_dir=root / "state",
                    sample_root=root,
                    batch4_template_path=capstone.ROOT / "schemas" / "examples" / "us_short_weekend_batch4_context_packet.empty.example.json",
                    account_state_path=root / "inputs" / "paper_account_state.adapter.json",
                    now_et=datetime(2026, 6, 15, 8, 0, 0),
                    model_paper_store_root=store_root,
                    model_paper_run_account_mode="paper_only",
                )

            self.assertTrue(summary["emitted"])
            self.assertEqual(
                seen_track["value"]["evidence_ref"]["value"],
                next(item for item in summary["stages"] if item["name"] == "model_paper_adapter")["result"]["adapter"]["paper_track"]["evidence_ref"]["value"],
            )
            self.assertEqual(1, receipt.call_count)
            terminal = next(item for item in summary["stages"] if item["name"] == "model_paper_weekly")
            weekly = terminal["result"]
            self.assertEqual("frozen", weekly["publish_status"])
            self.assertEqual(
                {"initial_capital", "current_cash", "holdings_market_value", "current_nav", "cumulative_pnl", "cumulative_return_pct", "consecutive_weeks"},
                {key for key in weekly["weekly_portfolio_metrics"] if key not in {"paper_evaluable", "performance_status"}},
            )
            self.assertEqual("20260615", load_head(store_root)["pending_decision"]["decision_date"])
            report = private_root / "weekly_private" / "20260615" / "weekly_report.md"
            self.assertTrue(report.exists())
            self.assertIn("cumulative_pnl", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
