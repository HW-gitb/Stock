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
from tests.support.analysis_input_payload import (
    cloned_minimal_analysis_input_payload,
    current_hithink_analysis_input_payload,
)


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
        analysis_payload: dict | None = None,
    ) -> Path:
        out_dir = work_dir / end_date
        analysis_input = work_dir / "analysis_input_current.json"
        if not analysis_input.exists():
            analysis_input.write_text(
                json.dumps(
                    analysis_payload or cloned_minimal_analysis_input_payload(),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        rc = execution_main(
            [
                "--mode",
                mode,
                "--as-of",
                "20260522",
                "--input-path",
                str(analysis_input),
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

    def write_forward_live_evidence(self, work_dir: Path, months: int = 12) -> Path:
        evidence_path = work_dir / "forward_evidence.json"
        payload = {
            "schema_name": "forward_live_evidence",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-01T00:00:00Z",
            "evidence_id": "test_forward_live_evidence",
            "evidence_date": "20260601",
            "preset": "a_short",
            "market": "A",
            "horizon": "short",
            "bucket": "short",
            "lane_id": "a_short_steady",
            "evidence_level": "live_normalized",
            "review_status": "reviewed",
            "forward_live_months": months,
            "source_window": {
                "start_date": "20250501",
                "end_date": "20260430",
                "captured_month_basis": "calendar_months_with_reviewed_tracker_packets",
                "market_calendar": "SSE/SZSE",
                "process_stable_before_window": True,
            },
            "provenance": {
                "source_system": "unit_test_forward_tracker",
                "captured_by": "unit_test",
                "captured_at": "2026-06-01T00:00:00Z",
                "tracker_artifact_refs": [
                    {
                        "artifact_type": "forward_tracker_summary",
                        "path": "result/a_short/forward/unit_test_summary.json",
                        "role": "unit-test reviewed forward tracker summary",
                    }
                ],
            },
            "review": {
                "reviewer_role": "claude",
                "reviewer_id": "unit_test_reviewer",
                "reviewed_at": "2026-06-01T00:00:00Z",
                "review_verdict": "pass",
                "review_entry_ref": "docs/SESSION_LOG.md#unit-test",
            },
            "position_reconciliation": {
                "actual_position_reconciliation_available": True,
                "reconciliation_status": "live_reconciled",
                "actual_positions_ref": "state/a_short/unit_test_positions.json",
                "manual_override_log_ref": None,
            },
            "scope_locks": {
                "manual_execution_only": True,
                "broker_or_order_automation_allowed": False,
                "production_strategy_rule_change_allowed": False,
                "paper_evidence_allowed_for_ship_gate": False,
                "full_size_manual_use_authorized_by_this_artifact": False,
            },
            "limitations": [
                "Unit-test fixture only.",
                "This artifact does not authorize full-size manual use.",
            ],
        }
        evidence_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return evidence_path

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
        self.assertEqual(report["schema_version"], "1.1.6")
        self.assertEqual(report["metrics"]["report_count"], 2)
        self.assertEqual(report["metrics"]["month_count"], 2)
        self.assertEqual(report["metrics"]["trade_count_total"], 2)
        self.assertEqual(report["metrics"]["monthly_return_count"], 2)
        self.assertEqual(report["metrics"]["monthly_alpha_observation_count"], 0)
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

    def test_current_hithink_lineage_is_carried_into_aggregate_input_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_path = self.write_execution_report(
                work_dir,
                "20260522",
                0.03,
                -0.05,
                analysis_payload=current_hithink_analysis_input_payload(),
            )
            out_path = work_dir / "aggregate.json"

            rc = aggregate_main([
                "--report", str(report_path),
                "--out-path", str(out_path),
            ])

            self.assertEqual(rc, 0)
            ref = json.loads(out_path.read_text(encoding="utf-8"))["inputs"]["execution_reports"][0]
            self.assertEqual(ref["data_provider"], "mixed")
            self.assertEqual(ref["l3_provider"], "hithink_finance")
            self.assertEqual(ref["l3_snapshot_date"], "20260522")
            self.assertEqual(ref["l3_catalog_digest"], "a" * 64)
            self.assertEqual(ref["l3_catalog_board_count"], 389)
            self.assertEqual(ref["l3_scoring_universe"], "a_share_main_board")
            self.assertTrue(ref["l3_coverage_complete"])

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
        self.assertEqual(report["metrics"]["monthly_alpha_observation_count"], 2)
        self.assertIsNone(
            report["ship_gate_evaluation"]["metric_results"]["monthly_alpha_t_stat"]["passed"]
        )
        self.assertIn(
            "at least 12 matched monthly alpha observations",
            report["ship_gate_evaluation"]["metric_results"]["monthly_alpha_t_stat"]["reason"],
        )
        self.assertIsNone(report["ship_gate_evaluation"]["metric_results"]["sharpe"]["passed"])
        self.assertIn(
            "at least 12 monthly return observations",
            report["ship_gate_evaluation"]["metric_results"]["sharpe"]["reason"],
        )
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
            evidence_path = self.write_forward_live_evidence(work_dir, 12)
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

    def test_production_aggregate_with_reviewed_forward_evidence_stays_not_evaluable_without_concurrency_model(
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
            evidence_path = self.write_forward_live_evidence(work_dir, 12)
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
        self.assertEqual(report["metrics"]["monthly_alpha_observation_count"], 2)
        self.assertIsNone(
            report["ship_gate_evaluation"]["metric_results"]["monthly_alpha_t_stat"]["passed"]
        )
        self.assertIn(
            "at least 12 matched monthly alpha observations",
            report["ship_gate_evaluation"]["metric_results"]["monthly_alpha_t_stat"]["reason"],
        )
        self.assertIsNone(report["ship_gate_evaluation"]["metric_results"]["sharpe"]["passed"])
        self.assertIn(
            "at least 12 monthly return observations",
            report["ship_gate_evaluation"]["metric_results"]["sharpe"]["reason"],
        )
        self.assertTrue(report["ship_gate_evaluation"]["metric_results"]["max_drawdown"]["passed"])
        self.assertEqual(report["ship_gate_evaluation"]["status"], "not_evaluable")
        self.assertFalse(report["ship_gate_evaluation"]["full_size_allowed"])
        self.assertIn(
            "capacity/concurrency-adjusted returns are not evaluable",
            " ".join(report["ship_gate_evaluation"]["limitations"]),
        )
        self.assertIn(
            "not capacity/concurrency-adjusted ship-gate evidence",
            " ".join(report["limitations"]),
        )

    def test_forward_live_evidence_months_must_match_cli_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_a = self.write_execution_report(
                work_dir, "20260522", 0.06, -0.05, mode="production"
            )
            report_b = self.write_execution_report(
                work_dir, "20260626", 0.07, -0.10, mode="production"
            )
            evidence_path = self.write_forward_live_evidence(work_dir, 11)

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

    def test_forward_live_evidence_ref_must_match_schema(self) -> None:
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
                json.dumps({"review_status": "reviewed", "forward_live_months": 12}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "forward-live evidence .*schema validation failed"):
                aggregate_main(
                    [
                        "--report",
                        str(report_a),
                        "--report",
                        str(report_b),
                        "--forward-live-evidence-ref",
                        str(evidence_path),
                    ]
                )

    def test_forward_live_evidence_context_must_match_aggregate_reports(self) -> None:
        mismatches = [
            ("market", "US", "aggregate capital_context.market"),
            ("lane_id", "us_long_core", "lane_id must match aggregate preset"),
        ]
        for field, value, message in mismatches:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmpdir:
                    work_dir = Path(tmpdir)
                    report_a = self.write_execution_report(
                        work_dir, "20260522", 0.06, -0.05, mode="production"
                    )
                    report_b = self.write_execution_report(
                        work_dir, "20260626", 0.07, -0.10, mode="production"
                    )
                    evidence_path = self.write_forward_live_evidence(work_dir, 12)
                    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
                    payload[field] = value
                    evidence_path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ValueError, message):
                        aggregate_main(
                            [
                                "--report",
                                str(report_a),
                                "--report",
                                str(report_b),
                                "--forward-live-evidence-ref",
                                str(evidence_path),
                            ]
                        )

    def test_forward_live_evidence_window_must_cover_claimed_months(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            report_a = self.write_execution_report(
                work_dir, "20260522", 0.06, -0.05, mode="production"
            )
            report_b = self.write_execution_report(
                work_dir, "20260626", 0.07, -0.10, mode="production"
            )
            evidence_path = self.write_forward_live_evidence(work_dir, 12)
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            payload["source_window"]["end_date"] = "20250501"
            evidence_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "source_window .*forward_live_months"):
                aggregate_main(
                    [
                        "--report",
                        str(report_a),
                        "--report",
                        str(report_b),
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
