from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - environment guard
    Draft7Validator = None  # type: ignore[assignment]

from runners.aggregate_execution_reports import main as aggregate_main
from runners.backtest_execution import ROOT, main as execution_main


@unittest.skipIf(Draft7Validator is None, "jsonschema not installed")
class AggregateExecutionReportsTest(unittest.TestCase):
    def capital_cli_args(self) -> list[str]:
        return [
            "--portfolio-allocation",
            str(ROOT / "tests" / "fixtures" / "portfolio_allocation_minimal.json"),
            "--cash-buffer-state",
            str(ROOT / "tests" / "fixtures" / "cash_buffer_state_minimal.json"),
        ]

    def write_execution_report(
        self,
        work_dir: Path,
        end_date: str,
        total_return: float | None,
        max_drawdown: float,
        trade_count: int | None = None,
        mode: str = "smoke",
    ) -> Path:
        out_dir = work_dir / end_date
        rc = execution_main(
            [
                "--mode",
                mode,
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
        path = out_dir / "execution_report.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["settings"]["start_date"] = end_date
        report["settings"]["end_date"] = end_date
        report["inputs"]["analysis_inputs"][0]["as_of"] = end_date
        report["metrics"]["total_return"] = total_return
        report["metrics"]["max_drawdown"] = max_drawdown
        if trade_count is not None:
            report["metrics"]["trade_count"] = trade_count
        if trade_count == 0:
            report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]["value"] = None
            report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]["passed"] = None
        else:
            report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]["value"] = max_drawdown
            report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]["passed"] = (
                abs(max_drawdown) <= 0.15
            )
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def test_aggregate_without_benchmark_keeps_alpha_not_evaluable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_a = self.write_execution_report(work_dir, "20260522", 0.03, -0.05)
            report_b = self.write_execution_report(work_dir, "20260626", 0.09, -0.10)
            out_path = work_dir / "aggregate.json"

            rc = aggregate_main(
                [
                    "--report",
                    str(report_a),
                    "--report",
                    str(report_b),
                    "--out-path",
                    str(out_path),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads(out_path.read_text(encoding="utf-8"))
            schema = json.loads(
                (ROOT / "schemas" / "execution_aggregate_report.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            errors = sorted(
                Draft7Validator(schema).iter_errors(report),
                key=lambda item: list(item.path),
            )

        self.assertEqual(errors, [])
        self.assertEqual(report["schema_name"], "execution_aggregate_report")
        self.assertEqual(report["schema_version"], "1.1.1")
        self.assertEqual(report["metrics"]["report_count"], 2)
        self.assertEqual(report["metrics"]["month_count"], 2)
        self.assertEqual(report["metrics"]["trade_count_total"], 2)
        self.assertEqual(report["metrics"]["monthly_return_count"], 2)
        self.assertEqual(report["metrics"]["max_drawdown"], -0.1)
        self.assertIsNotNone(report["ship_gate_evaluation"]["metric_results"]["sharpe"]["value"])
        self.assertIsNone(
            report["ship_gate_evaluation"]["metric_results"]["monthly_alpha_t_stat"]["passed"]
        )
        self.assertFalse(
            report["ship_gate_evaluation"]["metric_results"]["forward_live_months"]["passed"]
        )
        self.assertEqual(report["ship_gate_evaluation"]["status"], "not_evaluable")
        self.assertFalse(report["ship_gate_evaluation"]["full_size_allowed"])

    def test_zero_trade_report_without_return_is_excluded_from_monthly_series(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_a = self.write_execution_report(work_dir, "20260522", 0.03, -0.05)
            report_b = self.write_execution_report(
                work_dir,
                "20260626",
                None,
                0.0,
                trade_count=0,
            )
            out_path = work_dir / "aggregate.json"

            rc = aggregate_main(
                [
                    "--report",
                    str(report_a),
                    "--report",
                    str(report_b),
                    "--out-path",
                    str(out_path),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(report["metrics"]["month_count"], 2)
        self.assertEqual(report["metrics"]["monthly_return_count"], 1)
        self.assertEqual(
            report["metrics"]["monthly_return_series"],
            [
                {"month": "202605", "report_count": 1, "total_return_mean": 0.03},
            ],
        )
        self.assertEqual(report["metrics"]["total_return_mean"], 0.03)

    def test_single_report_aggregate_returns_null_sharpe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_path = self.write_execution_report(work_dir, "20260522", 0.03, -0.05)
            out_path = work_dir / "aggregate.json"

            rc = aggregate_main(
                [
                    "--report",
                    str(report_path),
                    "--out-path",
                    str(out_path),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(report["metrics"]["report_count"], 1)
        self.assertEqual(report["metrics"]["month_count"], 1)
        self.assertIsNone(report["metrics"]["sharpe"])
        self.assertIsNone(report["ship_gate_evaluation"]["metric_results"]["sharpe"]["passed"])
        self.assertEqual(report["ship_gate_evaluation"]["status"], "not_evaluable")

    def test_production_aggregate_requires_reviewed_forward_evidence_ref_for_full_size(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_a = self.write_execution_report(
                work_dir, "20260522", 0.06, -0.05, mode="production"
            )
            report_b = self.write_execution_report(
                work_dir, "20260626", 0.07, -0.10, mode="production"
            )
            benchmark_path = work_dir / "benchmark.json"
            benchmark_path.write_text(
                json.dumps({"202605": 0.01, "202606": 0.01}),
                encoding="utf-8",
            )
            out_path = work_dir / "aggregate.json"

            rc = aggregate_main(
                [
                    "--report",
                    str(report_a),
                    "--report",
                    str(report_b),
                    "--benchmark-monthly-returns",
                    str(benchmark_path),
                    "--forward-live-months",
                    "12",
                    "--out-path",
                    str(out_path),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertGreaterEqual(report["metrics"]["monthly_alpha_t_stat"], 2.0)
        self.assertGreaterEqual(report["metrics"]["sharpe"], 1.0)
        self.assertTrue(
            report["ship_gate_evaluation"]["metric_results"]["monthly_alpha_t_stat"]["passed"]
        )
        self.assertTrue(report["ship_gate_evaluation"]["metric_results"]["sharpe"]["passed"])
        self.assertTrue(report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]["passed"])
        self.assertIsNone(
            report["ship_gate_evaluation"]["metric_results"]["forward_live_months"]["passed"]
        )
        self.assertIn(
            "reviewed --forward-live-evidence-ref",
            report["ship_gate_evaluation"]["metric_results"]["forward_live_months"]["reason"],
        )
        self.assertEqual(report["settings"]["forward_live_evidence_source"], None)
        self.assertEqual(report["ship_gate_evaluation"]["status"], "not_evaluable")
        self.assertFalse(report["ship_gate_evaluation"]["full_size_allowed"])

    def test_smoke_aggregate_with_reviewed_forward_evidence_stays_not_evaluable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_a = self.write_execution_report(work_dir, "20260522", 0.06, -0.05)
            report_b = self.write_execution_report(work_dir, "20260626", 0.07, -0.10)
            benchmark_path = work_dir / "benchmark.json"
            benchmark_path.write_text(
                json.dumps({"202605": 0.01, "202606": 0.01}),
                encoding="utf-8",
            )
            evidence_path = work_dir / "forward_evidence.json"
            evidence_path.write_text(
                json.dumps({"review_status": "reviewed", "forward_live_months": 12}),
                encoding="utf-8",
            )
            out_path = work_dir / "aggregate.json"

            rc = aggregate_main(
                [
                    "--report",
                    str(report_a),
                    "--report",
                    str(report_b),
                    "--benchmark-monthly-returns",
                    str(benchmark_path),
                    "--forward-live-evidence-ref",
                    str(evidence_path),
                    "--out-path",
                    str(out_path),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertTrue(
            report["ship_gate_evaluation"]["metric_results"]["forward_live_months"]["passed"]
        )
        self.assertEqual(report["ship_gate_evaluation"]["status"], "not_evaluable")
        self.assertFalse(report["ship_gate_evaluation"]["full_size_allowed"])
        self.assertIn("smoke-mode", " ".join(report["ship_gate_evaluation"]["limitations"]))

    def test_production_aggregate_with_reviewed_forward_evidence_can_pass_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_a = self.write_execution_report(
                work_dir, "20260522", 0.06, -0.05, mode="production"
            )
            report_b = self.write_execution_report(
                work_dir, "20260626", 0.07, -0.10, mode="production"
            )
            benchmark_path = work_dir / "benchmark.json"
            benchmark_path.write_text(
                json.dumps({"202605": 0.01, "202606": 0.01}),
                encoding="utf-8",
            )
            evidence_path = work_dir / "forward_evidence.json"
            evidence_path.write_text(
                json.dumps({"review_status": "reviewed", "forward_live_months": 12}),
                encoding="utf-8",
            )
            out_path = work_dir / "aggregate.json"

            rc = aggregate_main(
                [
                    "--report",
                    str(report_a),
                    "--report",
                    str(report_b),
                    "--benchmark-monthly-returns",
                    str(benchmark_path),
                    "--forward-live-months",
                    "12",
                    "--forward-live-evidence-ref",
                    str(evidence_path),
                    "--out-path",
                    str(out_path),
                ]
            )

            self.assertEqual(rc, 0)
            report = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertTrue(
            report["ship_gate_evaluation"]["metric_results"]["forward_live_months"]["passed"]
        )
        self.assertEqual(report["settings"]["forward_live_months"], 12)
        self.assertTrue(
            str(report["settings"]["forward_live_evidence_source"]).endswith(
                "forward_evidence.json"
            )
        )
        self.assertEqual(report["ship_gate_evaluation"]["status"], "pass")
        self.assertTrue(report["ship_gate_evaluation"]["full_size_allowed"])

    def test_forward_live_evidence_months_must_match_cli_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_a = self.write_execution_report(
                work_dir, "20260522", 0.06, -0.05, mode="production"
            )
            report_b = self.write_execution_report(
                work_dir, "20260626", 0.07, -0.10, mode="production"
            )
            evidence_path = work_dir / "forward_evidence.json"
            evidence_path.write_text(
                json.dumps({"review_status": "reviewed", "forward_live_months": 11}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "must match"):
                aggregate_main(
                    [
                        "--report",
                        str(report_a),
                        "--report",
                        str(report_b),
                        "--forward-live-months",
                        "12",
                        "--forward-live-evidence-ref",
                        str(evidence_path),
                    ]
                )

    def test_v11_input_report_is_rejected_before_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_a = self.write_execution_report(work_dir, "20260522", 0.03, -0.05)
            report_b = self.write_execution_report(work_dir, "20260626", 0.09, -0.10)
            payload_b = json.loads(report_b.read_text(encoding="utf-8"))
            payload_b["schema_version"] = "1.1.0"
            payload_b.pop("ship_gate_evaluation")
            report_b.write_text(
                json.dumps(payload_b, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "schema validation failed"):
                aggregate_main(["--report", str(report_a), "--report", str(report_b)])

    def test_incompatible_capital_context_is_rejected(self) -> None:
        mismatches = [
            ("preset", "us_short"),
            ("market", "US"),
            ("bucket", "long"),
            ("currency", "USD"),
        ]
        for field, value in mismatches:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmpdir:
                    work_dir = Path(tmpdir)
                    report_a = self.write_execution_report(work_dir, "20260522", 0.03, -0.05)
                    report_b = self.write_execution_report(work_dir, "20260626", 0.09, -0.10)
                    payload_b = json.loads(report_b.read_text(encoding="utf-8"))
                    payload_b["capital_context"][field] = value
                    report_b.write_text(
                        json.dumps(payload_b, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ValueError, "same capital_context summary"):
                        aggregate_main(["--report", str(report_a), "--report", str(report_b)])


if __name__ == "__main__":
    unittest.main()
