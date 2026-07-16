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
from tests.support.analysis_input_payload import (
    cloned_minimal_analysis_input_payload,
    current_hithink_analysis_input_payload,
)


@unittest.skipIf(Draft7Validator is None, "jsonschema not installed")
class BacktestExecutionSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._analysis_input_tmp = tempfile.TemporaryDirectory()
        cls.analysis_input_path = Path(cls._analysis_input_tmp.name) / "analysis_input.json"
        cls.analysis_input_path.write_text(
            json.dumps(cloned_minimal_analysis_input_payload(), ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._analysis_input_tmp.cleanup()

    def load_fixture_payload(self) -> dict:
        return json.loads(self.analysis_input_path.read_text(encoding="utf-8"))

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
                    str(self.analysis_input_path),
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
            self.assertEqual(report["schema_version"], "1.3.0")
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
            circuit = report["execution_assumptions"]["portfolio_circuit_breaker"]
            self.assertFalse(circuit["enabled"])
            self.assertFalse(circuit["new_entries_blocked"])
            self.assertEqual(circuit["existing_positions_action"], "not_implemented")
            self.assertFalse(report["execution_assumptions"]["cooldown"]["enabled"])
            declared_event_codes = report["execution_assumptions"]["event_log"]["event_codes"]
            self.assertNotIn("circuit_breaker", declared_event_codes)
            self.assertNotIn("cooldown_block", declared_event_codes)
            self.assertIn("not safety evidence", " ".join(report["limitations"]))
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
            self.assertIn("entry", declared_event_codes)
            self.assertIn("exit", declared_event_codes)

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

    def test_runner_normalizes_legacy_analysis_input_schema_version(self) -> None:
        payload = self.load_fixture_payload()
        payload["schema_version"] = "analysis_input.v1.0"
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            input_path = work_dir / "analysis_input.json"
            out_dir = work_dir / "execution"
            input_path.write_text(json.dumps(payload), encoding="utf-8")

            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(input_path),
                    *self.capital_cli_args(),
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))

        self.assertEqual(report["inputs"]["analysis_inputs"][0]["schema_version"], "1.0.0")
        self.assertEqual(report["data_lineage"]["analysis_input_schema_version"], "1.0.0")

    def test_runner_validates_and_references_execution_price_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(self.analysis_input_path),
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
                    "end_date": "20260526",
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
                    str(self.analysis_input_path),
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
            self.assertEqual(report["settings"]["end_date"], "20260526")
            self.assertEqual(report["metrics"]["trade_count"], 1)
            self.assertEqual(report["metrics"]["skipped_count"], 1)
            self.assertEqual(report["metrics"]["missing_stop_count"], 0)
            self.assertEqual(report["metrics"]["entry_unbuyable_count"], 0)
            self.assertEqual(report["metrics"]["win_rate"], 1.0)
            self.assertEqual(report["metrics"]["avg_holding_days"], 2.0)
            self.assertGreater(report["metrics"]["ending_equity"], 116666.55)
            self.assertIsNotNone(report["metrics"]["max_drawdown"])
            self.assertEqual(report["ship_gate_evaluation"]["status"], "not_evaluable")
            drawdown_result = report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]
            self.assertIsNotNone(drawdown_result["value"])
            self.assertIsNotNone(drawdown_result["passed"])
            self.assertIn("mark-to-market", drawdown_result["reason"])
            self.assertIn("not safety evidence", " ".join(report["limitations"]))
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
            self.assertEqual(trades[0]["exit_date"], "20260526")
            self.assertEqual(trades[0]["shares"], "800")
            self.assertEqual(trades[0]["exit_reason"], "time_stop")
            self.assertEqual(trades[0]["holding_days"], "2")

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

    def test_buy_day_stop_is_queued_until_t1_sellable_session(self) -> None:
        payload = self.load_fixture_payload()
        payload["candidates"] = [payload["candidates"][0]]
        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        price_data["symbols"] = ["600000.SH"]
        price_data["trade_calendar"] = ["20260522", "20260525", "20260526"]
        price_data["date_range"]["end_date"] = "20260526"
        price_data["rows"] = [
            row
            for row in price_data["rows"]
            if row["ts_code"] == "600000.SH" and row["trade_date"] != "20260526"
        ]
        entry_row = next(
            row for row in price_data["rows"] if row["trade_date"] == "20260525"
        )
        entry_row["low_qfq"] = 12.4
        next_row = deepcopy(entry_row)
        next_row.update(
            {
                "trade_date": "20260526",
                "open_qfq": 12.3,
                "high_qfq": 12.6,
                "low_qfq": 12.1,
                "close_qfq": 12.4,
                "pre_close_qfq": 13.6,
                "up_limit": 14.96,
                "down_limit": 12.24,
            }
        )
        price_data["rows"].append(next_row)

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
                    "10",
                    "--out-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(rc, 0)
            with (out_dir / "trades.csv").open("r", encoding="utf-8", newline="") as handle:
                trades = list(csv.DictReader(handle))

        self.assertEqual(trades[0]["entry_date"], "20260525")
        self.assertEqual(trades[0]["exit_date"], "20260526")
        self.assertEqual(trades[0]["exit_reason"], "stop_loss")

    def test_suspension_zero_volume_and_limit_down_delay_exit_and_mark_trapped_loss(self) -> None:
        payload = self.load_fixture_payload()
        payload["candidates"] = [payload["candidates"][0]]
        price_data = json.loads(
            (ROOT / "tests" / "fixtures" / "execution_price_data_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        price_data["symbols"] = ["600000.SH"]
        price_data["trade_calendar"] = [
            "20260522",
            "20260525",
            "20260526",
            "20260527",
            "20260528",
            "20260529",
            "20260601",
        ]
        price_data["date_range"]["end_date"] = "20260601"
        price_data["rows"] = [
            row
            for row in price_data["rows"]
            if row["ts_code"] == "600000.SH" and row["trade_date"] != "20260526"
        ]
        entry_row = next(
            row for row in price_data["rows"] if row["trade_date"] == "20260525"
        )
        entry_row["low_qfq"] = 12.4
        entry_row["volume"] = 1000.0

        # 20260526 deliberately has no symbol row: suspended on an open market date.
        zero_volume = deepcopy(entry_row)
        zero_volume.update(
            {
                "trade_date": "20260527",
                "open_qfq": 11.8,
                "high_qfq": 11.9,
                "low_qfq": 11.6,
                "close_qfq": 11.7,
                "pre_close_qfq": 13.6,
                "up_limit": 14.96,
                "down_limit": 12.24,
                "volume": 0.0,
            }
        )
        limit_down_1 = deepcopy(zero_volume)
        limit_down_1.update(
            {
                "trade_date": "20260528",
                "open_qfq": 10.8,
                "high_qfq": 10.8,
                "low_qfq": 10.8,
                "close_qfq": 10.8,
                "pre_close_qfq": 11.7,
                "down_limit": 10.8,
                "volume": 500.0,
            }
        )
        limit_down_2 = deepcopy(limit_down_1)
        limit_down_2.update(
            {
                "trade_date": "20260529",
                "open_qfq": 9.72,
                "high_qfq": 9.72,
                "low_qfq": 9.72,
                "close_qfq": 9.72,
                "pre_close_qfq": 10.8,
                "down_limit": 9.72,
            }
        )
        sellable = deepcopy(limit_down_2)
        sellable.update(
            {
                "trade_date": "20260601",
                "open_qfq": 10.2,
                "high_qfq": 10.5,
                "low_qfq": 9.9,
                "close_qfq": 10.3,
                "pre_close_qfq": 9.72,
                "down_limit": 8.75,
            }
        )
        price_data["rows"].extend([zero_volume, limit_down_1, limit_down_2, sellable])

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
                    "10",
                    "--out-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))
            with (out_dir / "trades.csv").open("r", encoding="utf-8", newline="") as handle:
                trades = list(csv.DictReader(handle))
            with (out_dir / "daily_equity.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                daily = list(csv.DictReader(handle))
            with (out_dir / "order_events.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                events = list(csv.DictReader(handle))

        self.assertEqual(trades[0]["exit_date"], "20260601")
        self.assertEqual(trades[0]["exit_price"], "10.2")
        self.assertEqual([row["trade_date"] for row in daily], price_data["trade_calendar"])
        trapped_day = next(row for row in daily if row["trade_date"] == "20260529")
        self.assertLess(float(trapped_day["drawdown"]), 0.0)
        self.assertEqual(report["metrics"]["max_drawdown"], min(float(row["drawdown"]) for row in daily))
        self.assertFalse(report["ship_gate_evaluation"]["full_size_allowed"])
        delay_messages = [row["message"] for row in events if row["event_code"] == "exit_delayed"]
        self.assertTrue(any("suspended" in message for message in delay_messages))
        self.assertTrue(any("zero_volume" in message for message in delay_messages))
        self.assertGreaterEqual(sum("one_price_limit_down" in message for message in delay_messages), 2)

    def test_ship_gate_drawdown_uses_daily_mark_to_market(self) -> None:
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
        self.assertIsNotNone(report["metrics"]["max_drawdown"])
        drawdown_result = report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]
        self.assertIsNotNone(drawdown_result["value"])
        self.assertIsNotNone(drawdown_result["passed"])
        self.assertIn("mark-to-market", drawdown_result["reason"])

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
                    str(self.analysis_input_path),
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
            self.assertGreater(report["metrics"]["ending_equity"], 116666.55)
            with (out_dir / "trades.csv").open("r", encoding="utf-8", newline="") as handle:
                trades = list(csv.DictReader(handle))
            self.assertEqual(trades[0]["exit_reason"], "stop_loss")
            self.assertEqual(trades[0]["exit_price"], "13.7")
            self.assertGreater(float(trades[0]["pnl"]), 0.0)

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
        for row in price_data["rows"]:
            if row["ts_code"] == "600000.SH" and row["trade_date"] == "20260526":
                row.update(
                    {
                        "open_qfq": 12.2,
                        "high_qfq": 12.4,
                        "low_qfq": 12.0,
                        "close_qfq": 12.1,
                        "pre_close_qfq": 13.6,
                        "up_limit": 14.96,
                        "down_limit": 12.24,
                    }
                )
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
                    str(self.analysis_input_path),
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
                    str(self.analysis_input_path),
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
                    str(self.analysis_input_path),
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
                    str(self.analysis_input_path),
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
                        str(self.analysis_input_path),
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
                        str(self.analysis_input_path),
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
                        str(self.analysis_input_path),
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

    def test_current_hithink_lineage_is_preserved(self) -> None:
        payload = current_hithink_analysis_input_payload()

        report = self.build_report_for_payload(payload)

        lineage = report["data_lineage"]
        self.assertEqual(lineage["data_provider"], "mixed")
        self.assertEqual(lineage["l3_provider"], "hithink_finance")
        self.assertEqual(lineage["l3_snapshot_date"], "20260522")
        self.assertEqual(lineage["l3_catalog_digest"], "a" * 64)
        self.assertEqual(lineage["l3_catalog_board_count"], 389)
        self.assertEqual(lineage["l3_scoring_universe"], "a_share_main_board")
        self.assertTrue(lineage["l3_coverage_complete"])

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
                        str(self.analysis_input_path),
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
                        str(self.analysis_input_path),
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
                        str(self.analysis_input_path),
                        "--portfolio-allocation",
                        str(ROOT / "tests" / "fixtures" / "portfolio_allocation_minimal.json"),
                        "--cash-buffer-state",
                        str(cash_path),
                        "--out-dir",
                        tmpdir,
                    ]
                )

    def test_bucket_capital_above_policy_ceiling_is_rejected(self) -> None:
        cash_state = json.loads(
            (ROOT / "tests" / "fixtures" / "cash_buffer_state_minimal.json").read_text(
                encoding="utf-8"
            )
        )
        a_market = cash_state["markets"][0]
        a_market["capital"]["short_bucket_capital"] = 200000.0
        for bucket in a_market["buckets"]:
            if bucket["bucket"] == "short":
                bucket["capital"] = 200000.0
                bucket["available"] = 200000.0
                break

        with tempfile.TemporaryDirectory() as tmpdir:
            cash_path = Path(tmpdir) / "cash_state.json"
            cash_path.write_text(json.dumps(cash_state), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bucket_capital exceeds bucket ceiling"):
                main(
                    [
                        "--as-of",
                        "20260522",
                        "--input-path",
                        str(self.analysis_input_path),
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
                        str(self.analysis_input_path),
                        *self.capital_cli_args(),
                        "--preset-path",
                        str(preset_path),
                        "--out-dir",
                        tmpdir,
                    ]
                )

    def build_report_for_payload(self, payload: dict) -> dict:
        args = parse_args(["--as-of", str(payload["trade_date"]), *self.capital_cli_args()])
        input_path = self.analysis_input_path
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
