from __future__ import annotations

import csv
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - environment guard
    Draft7Validator = None  # type: ignore[assignment]

from runners.backtest_execution import ROOT, build_report, classify_skips, main, parse_args


@unittest.skipIf(Draft7Validator is None, "jsonschema not installed")
class BacktestExecutionSmokeTest(unittest.TestCase):
    def load_fixture_payload(self) -> dict:
        return json.loads(
            (ROOT / "tests" / "fixtures" / "analysis_input_minimal.json").read_text(
                encoding="utf-8"
            )
        )

    def capital_cli_args(self) -> list[str]:
        return [
            "--portfolio-allocation",
            str(ROOT / "tests" / "fixtures" / "portfolio_allocation_minimal.json"),
            "--cash-buffer-state",
            str(ROOT / "tests" / "fixtures" / "cash_buffer_state_minimal.json"),
        ]

    def test_runner_writes_schema_valid_skeleton_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                    *self.capital_cli_args(),
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            report_path = out_dir / "execution_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            schema = json.loads(
                (ROOT / "schemas" / "execution_backtest_report.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            errors = sorted(
                Draft7Validator(schema).iter_errors(report),
                key=lambda item: list(item.path),
            )

            self.assertEqual(errors, [])
            self.assertEqual(report["schema_name"], "execution_backtest_report")
            self.assertEqual(report["schema_version"], "1.2.0")
            self.assertEqual(report["settings"]["primary_input"], "analysis_input")
            self.assertFalse(report["settings"]["deterministic_report_required"])
            self.assertEqual(report["settings"]["initial_capital"], 116666.55)
            self.assertEqual(report["capital_context"]["capital_basis"], "bucket_capital")
            self.assertEqual(report["capital_context"]["market"], "A")
            self.assertEqual(report["capital_context"]["bucket"], "short")
            self.assertEqual(report["capital_context"]["bucket_capital"], 116666.55)
            self.assertEqual(
                report["capital_context"]["portfolio_allocation_ref"]["path"],
                "tests/fixtures/portfolio_allocation_minimal.json",
            )
            self.assertEqual(
                report["capital_context"]["cash_buffer_state_ref"]["path"],
                "tests/fixtures/cash_buffer_state_minimal.json",
            )
            self.assertEqual(
                report["execution_assumptions"]["position_sizing"]["bucket_ceiling_pct"],
                0.333333,
            )
            self.assertEqual(report["metrics"]["candidate_count"], 2)
            self.assertEqual(report["metrics"]["trade_count"], 0)
            self.assertEqual(report["metrics"]["skipped_count"], 2)
            self.assertEqual(report["ship_gate_evaluation"]["status"], "not_evaluable")
            self.assertFalse(report["ship_gate_evaluation"]["full_size_allowed"])
            self.assertEqual(
                report["ship_gate_evaluation"]["metric_results"]["forward_live_months"]["value"],
                0.0,
            )
            self.assertFalse(
                report["ship_gate_evaluation"]["metric_results"]["forward_live_months"]["passed"]
            )
            self.assertEqual(report["inputs"]["deterministic_reports"], [])
            self.assertIn("entry", report["execution_assumptions"]["event_log"]["event_codes"])
            self.assertIn("exit", report["execution_assumptions"]["event_log"]["event_codes"])

            for name in [
                "trades.csv",
                "daily_equity.csv",
                "order_events.csv",
                "skipped_candidates.csv",
            ]:
                self.assertTrue((out_dir / name).exists(), name)

            with (out_dir / "skipped_candidates.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                skipped_rows = list(csv.DictReader(handle))

            self.assertEqual(len(skipped_rows), 2)
            self.assertEqual(
                {row["reason"] for row in skipped_rows},
                {"missing_stop", "analyzer_hard_veto"},
            )
            self.assertNotIn("|", skipped_rows[1]["analyzer_reason_codes"])

            with (out_dir / "order_events.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                event_rows = list(csv.DictReader(handle))

            self.assertIn(
                "candidate skipped: no deterministic stop input below entry price",
                {row["message"] for row in event_rows},
            )

    def test_runner_validates_and_references_execution_price_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                    "--price-data",
                    str(ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json"),
                    *self.capital_cli_args(),
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))
            self.assertEqual(
                report["inputs"]["price_data"],
                {
                    "path": "tests/fixtures/execution_price_data_minimal.json",
                    "start_date": "20260522",
                    "end_date": "20260525",
                    "adj": "qfq_via_adj_factor",
                },
            )
            self.assertEqual(
                report["data_lineage"]["api_families"]["execution_price"],
                ["daily", "adj_factor", "stk_limit", "trade_cal"],
            )
            self.assertIn(
                "Execution price data is used by the Phase 5 minimal daily-OHLC fill simulator.",
                report["data_lineage"]["pit_limitations"],
            )

    def test_runner_simulates_time_stop_trade_with_bucket_sizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                    "--price-data",
                    str(ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json"),
                    *self.capital_cli_args(),
                    "--time-stop-days",
                    "1",
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["metrics"]["trade_count"], 1)
            self.assertEqual(report["metrics"]["skipped_count"], 1)
            self.assertEqual(report["metrics"]["missing_stop_count"], 0)
            self.assertEqual(report["metrics"]["entry_unbuyable_count"], 0)
            self.assertEqual(report["metrics"]["win_rate"], 1.0)
            self.assertEqual(report["metrics"]["avg_holding_days"], 1.0)
            self.assertGreater(report["metrics"]["ending_equity"], 116666.55)
            self.assertEqual(report["ship_gate_evaluation"]["status"], "not_evaluable")
            self.assertTrue(
                report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]["passed"]
            )
            self.assertIsNone(
                report["ship_gate_evaluation"]["metric_results"]["monthly_alpha_t_stat"]["passed"]
            )
            self.assertNotIn(
                "no_executable_candidates",
                {warning["warning_type"] for warning in report["date_warnings"]},
            )

            with (out_dir / "trades.csv").open("r", encoding="utf-8", newline="") as handle:
                trades = list(csv.DictReader(handle))
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["ts_code"], "600000.SH")
            self.assertEqual(trades[0]["entry_date"], "20260525")
            self.assertEqual(trades[0]["exit_date"], "20260525")
            self.assertEqual(trades[0]["shares"], "800")
            self.assertEqual(trades[0]["exit_reason"], "time_stop")
            self.assertEqual(trades[0]["holding_days"], "1")

            with (out_dir / "order_events.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                event_codes = {row["event_code"] for row in csv.DictReader(handle)}
            self.assertIn("entry", event_codes)
            self.assertIn("time_stop", event_codes)
            self.assertIn("exit", event_codes)

            with (out_dir / "skipped_candidates.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                skipped = list(csv.DictReader(handle))
            self.assertEqual([row["reason"] for row in skipped], ["analyzer_hard_veto"])

    def test_ship_gate_drawdown_uses_realized_multi_trade_path(self) -> None:
        payload = self.load_fixture_payload()
        payload["candidates"][1] = deepcopy(payload["candidates"][1])
        payload["candidates"][1]["industry"] = deepcopy(payload["candidates"][1]["industry"])
        payload["candidates"][1]["industry"]["sw_l2_name"] = "一般零售"

        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        for row in price_data["rows"]:
            if row["ts_code"] == "600001.SH" and row["trade_date"] == "20260525":
                row["low_qfq"] = 18.8
                break

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            input_path = work_dir / "analysis_input.json"
            price_path = work_dir / "price_data.json"
            out_dir = work_dir / "execution"
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            price_path.write_text(json.dumps(price_data), encoding="utf-8")
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(input_path),
                    "--price-data",
                    str(price_path),
                    *self.capital_cli_args(),
                    "--time-stop-days",
                    "1",
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))

        self.assertEqual(report["metrics"]["trade_count"], 2)
        self.assertLess(report["metrics"]["max_drawdown"], 0.0)
        drawdown_result = report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]
        self.assertEqual(drawdown_result["value"], report["metrics"]["max_drawdown"])
        self.assertTrue(drawdown_result["passed"])

    def test_stop_loss_takes_priority_over_time_stop(self) -> None:
        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        for row in price_data["rows"]:
            if row["ts_code"] == "600000.SH" and row["trade_date"] == "20260525":
                row["low_qfq"] = 12.4
                break

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            price_path = out_dir / "price_data.json"
            price_path.write_text(json.dumps(price_data), encoding="utf-8")
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                    "--price-data",
                    str(price_path),
                    *self.capital_cli_args(),
                    "--time-stop-days",
                    "1",
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["metrics"]["trade_count"], 1)
            self.assertLess(report["metrics"]["ending_equity"], 116666.55)
            with (out_dir / "trades.csv").open("r", encoding="utf-8", newline="") as handle:
                trades = list(csv.DictReader(handle))
            self.assertEqual(trades[0]["exit_reason"], "stop_loss")
            self.assertEqual(trades[0]["exit_price"], "12.5")
            self.assertLess(float(trades[0]["pnl"]), 0.0)

            with (out_dir / "order_events.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                event_codes = {row["event_code"] for row in csv.DictReader(handle)}
            self.assertIn("stop_loss", event_codes)

    def test_gap_down_stop_loss_fills_at_open(self) -> None:
        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        price_data["date_range"]["end_date"] = "20260526"
        for row in list(price_data["rows"]):
            if row["ts_code"] == "600000.SH" and row["trade_date"] == "20260525":
                next_row = deepcopy(row)
                next_row.update(
                    {
                        "trade_date": "20260526",
                        "open_qfq": 12.2,
                        "high_qfq": 12.4,
                        "low_qfq": 12.0,
                        "close_qfq": 12.1,
                        "pre_close_qfq": 13.6,
                        "up_limit": 14.96,
                        "down_limit": 12.24,
                    }
                )
                price_data["rows"].append(next_row)
                break

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            price_path = out_dir / "price_data.json"
            price_path.write_text(json.dumps(price_data), encoding="utf-8")
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                    "--price-data",
                    str(price_path),
                    *self.capital_cli_args(),
                    "--time-stop-days",
                    "2",
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            with (out_dir / "trades.csv").open("r", encoding="utf-8", newline="") as handle:
                trades = list(csv.DictReader(handle))
            self.assertEqual(trades[0]["exit_reason"], "stop_loss")
            self.assertEqual(trades[0]["exit_date"], "20260526")
            self.assertEqual(trades[0]["exit_price"], "12.2")
            self.assertLess(float(trades[0]["pnl"]), 0.0)

    def test_entry_open_at_or_below_stop_is_skipped(self) -> None:
        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        for row in price_data["rows"]:
            if row["ts_code"] == "600000.SH" and row["trade_date"] == "20260525":
                row["open_qfq"] = 12.4
                row["high_qfq"] = 12.6
                row["low_qfq"] = 12.3
                row["close_qfq"] = 12.4
                break

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            price_path = out_dir / "price_data.json"
            price_path.write_text(json.dumps(price_data), encoding="utf-8")
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                    "--price-data",
                    str(price_path),
                    *self.capital_cli_args(),
                    "--time-stop-days",
                    "1",
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["metrics"]["trade_count"], 0)
            self.assertEqual(report["metrics"]["missing_stop_count"], 1)
            with (out_dir / "skipped_candidates.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                reasons = {row["reason"] for row in csv.DictReader(handle)}
            self.assertEqual(reasons, {"missing_stop", "analyzer_hard_veto"})
            with (out_dir / "order_events.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                event_codes = {row["event_code"] for row in csv.DictReader(handle)}
            self.assertNotIn("entry", event_codes)

    def test_cash_constrained_candidate_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                    "--price-data",
                    str(ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json"),
                    *self.capital_cli_args(),
                    "--time-stop-days",
                    "1",
                    "--max-position-pct",
                    "0.0001",
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["metrics"]["trade_count"], 0)
            drawdown_result = report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]
            self.assertIsNone(drawdown_result["value"])
            self.assertIsNone(drawdown_result["passed"])
            self.assertIn("no executed trades", drawdown_result["reason"])
            with (out_dir / "skipped_candidates.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                reasons = {row["reason"] for row in csv.DictReader(handle)}
            self.assertEqual(reasons, {"cash_constrained", "analyzer_hard_veto"})
            with (out_dir / "order_events.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                event_codes = {row["event_code"] for row in csv.DictReader(handle)}
            self.assertIn("cash_constrained", event_codes)

    def test_limit_up_entry_is_unbuyable(self) -> None:
        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        for row in price_data["rows"]:
            if row["ts_code"] == "600000.SH" and row["trade_date"] == "20260525":
                row["open_qfq"] = row["up_limit"]
                row["high_qfq"] = row["up_limit"]
                row["low_qfq"] = row["up_limit"]
                row["close_qfq"] = row["up_limit"]
                break

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            price_path = out_dir / "price_data.json"
            price_path.write_text(json.dumps(price_data), encoding="utf-8")
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                    "--price-data",
                    str(price_path),
                    *self.capital_cli_args(),
                    "--time-stop-days",
                    "1",
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["metrics"]["trade_count"], 0)
            self.assertEqual(report["metrics"]["entry_unbuyable_count"], 1)
            with (out_dir / "skipped_candidates.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                reasons = {row["reason"] for row in csv.DictReader(handle)}
            self.assertEqual(reasons, {"entry_unbuyable", "analyzer_hard_veto"})

            with (out_dir / "order_events.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                event_codes = {row["event_code"] for row in csv.DictReader(handle)}
            self.assertIn("entry_unbuyable", event_codes)

    def test_price_data_date_range_must_cover_as_of(self) -> None:
        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        price_data["date_range"] = {"start_date": "20260523", "end_date": "20260525"}
        with tempfile.TemporaryDirectory() as tmpdir:
            price_path = Path(tmpdir) / "price_data.json"
            price_path.write_text(json.dumps(price_data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "date_range must cover --as-of"):
                main(
                    [
                        "--as-of",
                        "20260522",
                        "--input-path",
                        str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                        "--price-data",
                        str(price_path),
                        *self.capital_cli_args(),
                        "--out-dir",
                        tmpdir,
                    ]
                )

    def test_price_data_symbols_must_cover_candidates(self) -> None:
        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        price_data["symbols"] = ["600000.SH"]
        with tempfile.TemporaryDirectory() as tmpdir:
            price_path = Path(tmpdir) / "price_data.json"
            price_path.write_text(json.dumps(price_data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "symbols must include all"):
                main(
                    [
                        "--as-of",
                        "20260522",
                        "--input-path",
                        str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                        "--price-data",
                        str(price_path),
                        *self.capital_cli_args(),
                        "--out-dir",
                        tmpdir,
                    ]
                )

    def test_price_data_rows_must_cover_candidates_on_as_of(self) -> None:
        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        price_data["rows"] = [
            row for row in price_data["rows"] if row["ts_code"] == "600000.SH"
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            price_path = Path(tmpdir) / "price_data.json"
            price_path.write_text(json.dumps(price_data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "rows must include each"):
                main(
                    [
                        "--as-of",
                        "20260522",
                        "--input-path",
                        str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                        "--price-data",
                        str(price_path),
                        *self.capital_cli_args(),
                        "--out-dir",
                        tmpdir,
                    ]
                )

    def test_l3_mode_pit_is_preserved_in_lineage(self) -> None:
        payload = self.load_fixture_payload()
        payload["source"]["l3_mode"] = "pit"

        report = self.build_report_for_payload(payload)

        self.assertEqual(report["data_lineage"]["l3_mode"], "pit")

    def test_missing_l3_mode_falls_back_to_today(self) -> None:
        payload = self.load_fixture_payload()
        payload["source"] = deepcopy(payload["source"])
        payload["source"].pop("l3_mode")

        report = self.build_report_for_payload(payload)

        self.assertEqual(report["data_lineage"]["l3_mode"], "today")

    def test_invalid_l3_mode_raises(self) -> None:
        payload = self.load_fixture_payload()
        payload["source"]["l3_mode"] = "invalid_value"

        with self.assertRaisesRegex(ValueError, "unsupported analysis_input.source.l3_mode"):
            self.build_report_for_payload(payload)

    def test_trade_date_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "does not match --as-of"):
                main(
                    [
                        "--as-of",
                        "20260523",
                        "--input-path",
                        str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                        *self.capital_cli_args(),
                        "--out-dir",
                        tmpdir,
                    ]
                )

    def test_initial_capital_guard_must_match_bucket_capital(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "must equal capital_context.bucket_capital"):
                main(
                    [
                        "--as-of",
                        "20260522",
                        "--input-path",
                        str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                        *self.capital_cli_args(),
                        "--initial-capital",
                        "1000000",
                        "--out-dir",
                        tmpdir,
                    ]
                )

    def test_cash_state_policy_id_must_match_allocation(self) -> None:
        cash_state = json.loads(
            (ROOT / "tests" / "fixtures" / "cash_buffer_state_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        cash_state["portfolio_policy_ref"]["policy_id"] = "wrong_policy"
        with tempfile.TemporaryDirectory() as tmpdir:
            cash_path = Path(tmpdir) / "cash_state.json"
            cash_path.write_text(json.dumps(cash_state), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "policy_id must match"):
                main(
                    [
                        "--as-of",
                        "20260522",
                        "--input-path",
                        str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                        "--portfolio-allocation",
                        str(ROOT / "tests" / "fixtures" / "portfolio_allocation_minimal.json"),
                        "--cash-buffer-state",
                        str(cash_path),
                        "--out-dir",
                        tmpdir,
                    ]
                )

    def test_preset_yaml_drives_capital_profile(self) -> None:
        preset_text = (ROOT / "presets" / "a_short.yaml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / "a_short.yaml"
            preset_path.write_text(
                preset_text.replace("  bucket: short", "  bucket: long"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "must reference preset a_short"):
                main(
                    [
                        "--as-of",
                        "20260522",
                        "--input-path",
                        str(ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"),
                        *self.capital_cli_args(),
                        "--preset-path",
                        str(preset_path),
                        "--out-dir",
                        tmpdir,
                    ]
                )

    def build_report_for_payload(self, payload: dict) -> dict:
        args = parse_args(["--as-of", str(payload["trade_date"]), *self.capital_cli_args()])
        input_path = ROOT / "tests" / "fixtures" / "analysis_input_minimal.json"
        skipped_rows = classify_skips(payload["candidates"])
        capital_context = {
            "portfolio_allocation_ref": {
                "path": "tests/fixtures/portfolio_allocation_minimal.json",
                "schema_version": "1.0.0",
                "policy_id": "p0c_user_confirmed_20260526",
            },
            "cash_buffer_state_ref": {
                "path": "tests/fixtures/cash_buffer_state_minimal.json",
                "schema_version": "1.0.0",
                "state_id": "cash_state_fixture_20260522",
                "as_of": "20260522",
            },
            "preset": "a_short",
            "market": "A",
            "horizon": "short",
            "bucket": "short",
            "currency": "CNY",
            "capital_basis": "bucket_capital",
            "total_portfolio_capital": 1000000.0,
            "market_allocation_pct": 0.35,
            "market_capital": 350000.0,
            "bucket_target_pct": 0.333333,
            "bucket_ceiling_pct": 0.333333,
            "bucket_capital": 116666.55,
            "liquidity_reserve_pct": 0.333333,
            "liquidity_floor_policy": "hard_floor_with_explicit_exceptions",
            "cross_market_cash_fungible": False,
            "manual_execution_only": True,
            "ship_gate": {
                "policy_logic": "and",
                "monthly_alpha_t_stat_min": 2.0,
                "sharpe_min": 1.0,
                "max_drawdown_max": 0.15,
                "forward_live_months_min": 12,
                "failure_mode": "paper_or_minimal_size_or_risk_filter_only",
                "status": "not_evaluated",
                "full_size_allowed": False,
                "reason": "fixture",
            },
        }
        return build_report(
            payload,
            input_path,
            Path("unused"),
            args,
            capital_context,
            skipped_rows=skipped_rows,
            generated_at="2026-05-26T00:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
