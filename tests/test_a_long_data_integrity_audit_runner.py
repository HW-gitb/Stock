from __future__ import annotations

import argparse
import json
import pickle
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from runners import a_long_data_integrity_audit as runner


class ALongDataIntegrityAuditRunnerTest(unittest.TestCase):
    def write_cache_fixture(self, cache_dir: Path, forward_cache: Path) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "q0_dt_yoy": 1.0,
                    "q0_profit_dedt": 2.0,
                    "q0_dt_profit_ratio": 3.0,
                    "roe": 4.0,
                }
            ]
        ).to_pickle(cache_dir / "financial_20240131_1.pkl")
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "fixture",
                    "list_date": "20000101",
                    "delist_date": None,
                    "market": "主板",
                    "list_status": "L",
                }
            ]
        ).to_pickle(cache_dir / "stock_list_20240131_v2.pkl")
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20240131",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.5,
                    "close": 10.1,
                    "pre_close": 10.0,
                    "pct_chg": 1.0,
                    "vol": 100.0,
                    "amount": 1000.0,
                }
            ]
        ).to_pickle(cache_dir / "daily_all_20240131_60d.pkl")
        pd.DataFrame([{"ts_code": "000001.SZ", "close": 10.1, "pe": 12.0}]).to_pickle(
            cache_dir / "daily_basic_20240131.pkl"
        )
        (cache_dir / "trade_dates_20240131.pkl").write_bytes(pickle.dumps(["20240131", "20240130"]))
        (cache_dir / "csi300_20240131.pkl").write_bytes(pickle.dumps(1.25))

        forward_cache.parent.mkdir(parents=True, exist_ok=True)
        forward_cache.write_bytes(
            pickle.dumps(
                {
                    "meta": {"start_date": "20240131", "end_date": "20240229"},
                    "stocks": pd.DataFrame(
                        [{"ts_code": "000001.SZ", "trade_date": "20240131", "open": 10.0, "close": 10.1, "adj_factor": 1.0}]
                    ),
                    "limits": pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20240131"}]),
                    "benchmarks": {
                        "csi300": pd.DataFrame([{"trade_date": "20240131", "open": 100.0, "close": 101.0}]),
                        "csi1000": pd.DataFrame([{"trade_date": "20240131", "open": 100.0, "close": 102.0}]),
                    },
                }
            )
        )

    def copy_ledger(self, path: Path) -> None:
        shutil.copyfile(runner.DEFAULT_LEDGER, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["ledger_status"] = "active_planned_test_pending_review"
        payload["budget_policy"]["tests_spent_count"] = 0
        payload["budget_policy"]["tests_available_without_new_review"] = 0
        payload["test_spend_log"] = []
        payload["planned_tests"] = [
            {
                "test_id": runner.TEST_ID,
                "planned_status": "reviewed_not_run",
                "created_at": "2026-06-03T00:00:00Z",
                "planned_preregistration_ref": str(runner.DEFAULT_PREREGISTRATION).replace("\\", "/"),
                "planned_result_ref": "research/results/a_long_data_integrity_audit_20260603/audit_report.json",
                "promotion_relevant": True,
                "expected_tests_spent": 1,
                "approval_status": "reviewed_authorized",
                "design_summary": "Fixture planned A-long data-integrity audit.",
                "review_boundary": ["Fixture review boundary."],
            }
        ]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_self_tests_detect_planted_violations(self) -> None:
        preregistration = json.loads(runner.DEFAULT_PREREGISTRATION.read_text(encoding="utf-8"))

        results = runner.run_required_self_tests(preregistration)

        self.assertEqual(len(results), 6)
        self.assertEqual({item["status"] for item in results}, {"pass"})
        self.assertTrue(all(item["detected_expected_violation"] for item in results))
        coverage = {item["fixture_id"]: item for item in results}["sparse_early_coverage_declares_usable_window"]
        self.assertEqual(coverage["metrics"]["usable_start_year"], 2020)
        self.assertFalse(coverage["metrics"]["global_hard_fail"])

    def test_ann_date_missing_is_excluded_but_future_ann_date_hard_fails(self) -> None:
        result = runner.check_fundamental_pit_rows(
            [
                {"ts_code": "000001.SZ", "ann_date": "20240501"},
                {"ts_code": "000002.SZ", "ann_date": None},
                {"ts_code": "000003.SZ", "ann_date": "bad"},
            ],
            "20240430",
        )

        self.assertTrue(result["hard_fail"])
        self.assertEqual(result["future_ann_date_rows"], 1)
        self.assertEqual(result["missing_or_invalid_ann_date_rows"], 2)
        self.assertGreater(result["ann_date_missing_or_invalid_exclusion_rate_pct"], 0)

    def test_run_writes_blocked_report_and_spends_data_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_dir = tmp_path / "egs_cache"
            forward_cache = tmp_path / "forward_daily.pkl"
            output_dir = tmp_path / "results"
            ledger = tmp_path / "ledger.json"
            self.write_cache_fixture(cache_dir, forward_cache)
            self.copy_ledger(ledger)

            result = runner.run(
                argparse.Namespace(
                    cache_dir=cache_dir,
                    forward_daily_cache=forward_cache,
                    preregistration=runner.DEFAULT_PREREGISTRATION,
                    ledger=ledger,
                    output_dir=output_dir,
                    generated_at="2026-06-03T00:00:00Z",
                    code_version_ref="test",
                    no_update_ledger=False,
                )
            )

            report = result["report"]
            updated_ledger = json.loads(ledger.read_text(encoding="utf-8"))
            persisted = json.loads((output_dir / "audit_report.json").read_text(encoding="utf-8"))

            self.assertEqual(report["decision"]["audit_status"], "blocked_missing_required_source")
            self.assertFalse(report["decision"]["hard_checks_pass"])
            self.assertIsNone(report["decision"]["usable_start_year"])
            self.assertFalse(report["decision"]["signal_search_allowed_by_this_report"])
            self.assertEqual(report["execution"]["network_calls_executed"], 0)
            self.assertEqual(report["execution"]["provider_calls_executed"], 0)
            self.assertEqual(report["execution"]["self_tests_passed"], 6)
            self.assertEqual(persisted["decision"]["audit_status"], "blocked_missing_required_source")
            self.assertTrue((output_dir / "check_summary.csv").exists())
            self.assertTrue((output_dir / "coverage_by_year.csv").exists())

            checks = {item["check_id"]: item for item in report["audit_checks"]}
            self.assertEqual(checks["fundamental_pit"]["status"], "blocked_missing_required_source")
            self.assertFalse(checks["fundamental_pit"]["metrics"]["derived_financial_has_ann_date_column"])
            self.assertEqual(checks["return_benchmark_measurement_basis"]["metrics"]["dividend_or_total_return_source_available"], False)

            self.assertEqual(updated_ledger["ledger_status"], "active_no_new_test_authorized")
            self.assertEqual(updated_ledger["budget_policy"]["tests_spent_count"], 1)
            self.assertEqual(updated_ledger["planned_tests"], [])
            self.assertEqual(updated_ledger["test_spend_log"][0]["status"], "spent_voided_by_data_integrity_failure")


if __name__ == "__main__":
    unittest.main()
