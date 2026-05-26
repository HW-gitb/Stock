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
            self.assertEqual(report["schema_version"], "1.1.0")
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
                "candidate skipped: no deterministic stop input wired in skeleton",
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
                "Execution price data is schema-validated but not used for fills yet.",
                report["data_lineage"]["pit_limitations"],
            )

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
