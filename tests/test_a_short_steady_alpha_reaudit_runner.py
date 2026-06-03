from __future__ import annotations

import argparse
import csv
import json
import pickle
import tempfile
import unittest
from pathlib import Path

from runners import a_short_steady_alpha_reaudit as runner


REQUIRED_COLUMNS = [
    "trade_date",
    "ts_code",
    "tier",
    "tier1_veto_passed",
    "has_l4_overheat",
    "overheat_flag",
    "chasing_high",
    "entry_date",
    "ret_5d_status",
    "ret_5d_exit_date",
    "ret_5d_t1",
    "ret_5d_t1_net",
    "ret_5d_csi1000",
    "ret_5d_excess_csi1000",
    "ret_5d_csi300",
    "ret_5d_excess_csi300",
    "ret_20d_status",
    "ret_20d_exit_date",
    "ret_20d_t1",
    "ret_20d_t1_net",
    "ret_20d_csi1000",
    "ret_20d_excess_csi1000",
    "ret_20d_csi300",
    "ret_20d_excess_csi300",
]


class AShortSteadyAlphaReauditRunnerTest(unittest.TestCase):
    def write_rank_samples(self, path: Path) -> list[dict[str, str]]:
        months = [
            "20240131",
            "20240229",
            "20240329",
            "20240430",
            "20240531",
            "20240628",
            "20240731",
            "20240830",
            "20240930",
            "20241031",
            "20241129",
            "20241231",
        ]
        excess_values = [1.0, 1.2, 0.8, 1.1, 0.9, 1.3, 0.7, 1.4, 0.95, 1.05, 1.25, 0.85]
        rows = []
        for index, (month, excess) in enumerate(zip(months, excess_values), start=1):
            csi1000 = (index % 5) - 2
            csi300 = csi1000 - 0.25
            entry_date = f"2025{index:02d}01"
            exit_5d = f"2025{index:02d}05"
            exit_20d = f"2025{index:02d}20"
            for leg in range(2):
                net_5d = csi1000 + excess + leg * 0.05
                net_20d = csi1000 + 0.1 + leg * 0.01
                rows.append(
                    {
                        "trade_date": month,
                        "ts_code": f"000{index:03d}.SZ",
                        "tier": "Tier1",
                        "tier1_veto_passed": "true",
                        "has_l4_overheat": "false",
                        "overheat_flag": "false",
                        "chasing_high": "false",
                        "entry_date": entry_date,
                        "ret_5d_status": "ok",
                        "ret_5d_exit_date": exit_5d,
                        "ret_5d_t1": f"{net_5d + 0.16:.6f}",
                        "ret_5d_t1_net": f"{net_5d:.6f}",
                        "ret_5d_csi1000": f"{csi1000:.6f}",
                        "ret_5d_excess_csi1000": f"{net_5d - csi1000:.6f}",
                        "ret_5d_csi300": f"{csi300:.6f}",
                        "ret_5d_excess_csi300": f"{net_5d - csi300:.6f}",
                        "ret_20d_status": "ok",
                        "ret_20d_exit_date": exit_20d,
                        "ret_20d_t1": f"{net_20d + 0.16:.6f}",
                        "ret_20d_t1_net": f"{net_20d:.6f}",
                        "ret_20d_csi1000": f"{csi1000:.6f}",
                        "ret_20d_excess_csi1000": f"{net_20d - csi1000:.6f}",
                        "ret_20d_csi300": f"{csi300:.6f}",
                        "ret_20d_excess_csi300": f"{net_20d - csi300:.6f}",
                    }
                )
        rows.append(
            {
                "trade_date": "20241231",
                "ts_code": "999999.SZ",
                "tier": "Tier2",
                "tier1_veto_passed": "false",
                "has_l4_overheat": "true",
                "overheat_flag": "true",
                "chasing_high": "true",
                "entry_date": "20251201",
                "ret_5d_status": "ok",
                "ret_5d_exit_date": "20251205",
                "ret_5d_t1": "-1.000000",
                "ret_5d_t1_net": "-1.160000",
                "ret_5d_csi1000": "0.000000",
                "ret_5d_excess_csi1000": "-1.160000",
                "ret_5d_csi300": "0.000000",
                "ret_5d_excess_csi300": "-1.160000",
                "ret_20d_status": "ok",
                "ret_20d_exit_date": "20251220",
                "ret_20d_t1": "-1.000000",
                "ret_20d_t1_net": "-1.160000",
                "ret_20d_csi1000": "0.000000",
                "ret_20d_excess_csi1000": "-1.160000",
                "ret_20d_csi300": "0.000000",
                "ret_20d_excess_csi300": "-1.160000",
            }
        )
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return rows

    def write_benchmark_cache(self, path: Path, rows: list[dict[str, str]]) -> None:
        grouped: dict[tuple[str, str, str], list[float]] = {}
        for row in rows:
            if row["tier"] != "Tier1":
                continue
            for horizon in (5, 20):
                for benchmark in ("csi1000", "csi300"):
                    key = (benchmark, row["entry_date"], row[f"ret_{horizon}d_exit_date"])
                    net_value = float(row[f"ret_{horizon}d_t1_net"])
                    grouped.setdefault(key, []).append(net_value)
        benchmarks = {"csi1000": [], "csi300": []}
        seen_entries: set[tuple[str, str]] = set()
        for (benchmark, entry_date, exit_date), returns in sorted(grouped.items()):
            target_excess = 0.10 if int(entry_date[4:6]) % 2 else -0.10
            mean_return = (sum(returns) / len(returns)) - target_excess
            if (benchmark, entry_date) not in seen_entries:
                benchmarks[benchmark].append({"trade_date": entry_date, "open": 100.0, "close": 100.0})
                seen_entries.add((benchmark, entry_date))
            benchmarks[benchmark].append(
                {"trade_date": exit_date, "open": 100.0, "close": 100.0 * (1.0 + mean_return / 100.0)}
            )
        payload = {
            "meta": {
                "benchmark_return_basis": "benchmark_entry_open_to_exit_close",
                "fixture": True,
            },
            "benchmarks": benchmarks,
        }
        path.write_bytes(pickle.dumps(payload))

    def copy_ledger(self, path: Path) -> None:
        source = json.loads(runner.DEFAULT_LEDGER.read_text(encoding="utf-8"))
        source["ledger_status"] = "active_planned_test_pending_review"
        source["budget_policy"]["tests_spent_count"] = 0
        source["budget_policy"]["tests_available_without_new_review"] = 0
        source["test_spend_log"] = []
        source["planned_tests"] = [
            {
                "test_id": runner.TEST_ID,
                "planned_status": "reviewed_not_run",
                "created_at": "2026-06-03T00:00:00Z",
                "planned_preregistration_ref": str(runner.DEFAULT_PREREGISTRATION).replace("\\", "/"),
                "planned_result_ref": "research/results/a_short_steady_alpha_reaudit_20260603/evidence_report.json",
                "promotion_relevant": True,
                "expected_tests_spent": 1,
                "approval_status": "reviewed_authorized",
                "design_summary": "Fixture planned test.",
                "review_boundary": ["Fixture review boundary."],
            }
        ]
        path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_metric_summary_mean_fields_use_row_weighting(self) -> None:
        rows = [
            {
                "trade_date": "20240131",
                "ret_5d_same_anchor_csi1000_status": "ok",
                "ret_5d_net_excess_csi1000_same_anchor": "1.0",
                "ret_5d_gross_excess_csi1000_same_anchor": "10.0",
                "ret_5d_excess_csi1000": "1.0",
            },
            {
                "trade_date": "20240131",
                "ret_5d_same_anchor_csi1000_status": "ok",
                "ret_5d_net_excess_csi1000_same_anchor": "1.0",
                "ret_5d_gross_excess_csi1000_same_anchor": "10.0",
                "ret_5d_excess_csi1000": "1.0",
            },
            {
                "trade_date": "20240229",
                "ret_5d_same_anchor_csi1000_status": "ok",
                "ret_5d_net_excess_csi1000_same_anchor": "-1.0",
                "ret_5d_gross_excess_csi1000_same_anchor": "0.0",
                "ret_5d_excess_csi1000": "5.0",
            },
        ]

        summary = runner.metric_summary(rows, 5, "csi1000")

        self.assertAlmostEqual(summary["mean_gross_excess_pct"], 20.0 / 3.0, places=6)
        self.assertAlmostEqual(summary["mean_uncorrected_gross_excess_pct"], 7.0 / 3.0, places=6)
        self.assertAlmostEqual(summary["mean_anchor_only_delta_pct"], 13.0 / 3.0, places=6)
        self.assertAlmostEqual(summary["monthly_clustered_t_stat"], 0.0, places=6)

    def test_run_writes_research_only_outputs_and_updates_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rank_samples = tmp_path / "rank_samples.csv"
            ledger = tmp_path / "ledger.json"
            output_dir = tmp_path / "results"
            benchmark_cache = tmp_path / "forward_daily.pkl"
            rows = self.write_rank_samples(rank_samples)
            self.write_benchmark_cache(benchmark_cache, rows)
            self.copy_ledger(ledger)

            result = runner.run(
                argparse.Namespace(
                    rank_samples=rank_samples,
                    benchmark_cache=benchmark_cache,
                    preregistration=runner.DEFAULT_PREREGISTRATION,
                    ledger=ledger,
                    output_dir=output_dir,
                    generated_at="2026-06-03T00:00:00Z",
                    code_version_ref="test",
                    update_ledger=True,
                )
            )

            evidence_report = json.loads((output_dir / "evidence_report.json").read_text(encoding="utf-8"))
            diagnostics = json.loads((output_dir / "diagnostics.json").read_text(encoding="utf-8"))
            updated_ledger = json.loads(ledger.read_text(encoding="utf-8"))

            self.assertEqual(result["diagnostics"]["decision"]["data_usability"], "usable_for_research_only_not_ship_gate_or_full_size")
            self.assertFalse(evidence_report["scope"]["data_fetch_allowed"])
            self.assertEqual(evidence_report["ship_gate_claim"]["claim_status"], "not_eligible")
            self.assertFalse(evidence_report["ship_gate_claim"]["full_size_manual_use_authorized_by_this_report"])
            self.assertEqual(diagnostics["decision"]["label"], "risk_filter_only")
            self.assertEqual(
                diagnostics["same_anchor_correction"]["old_csv_excess_basis"],
                "uncorrected control only: old rank_samples ret_*d_excess_* was gross stock T+1 minus close-to-close benchmark",
            )
            primary = diagnostics["metric_summaries"]["5d_CSI1000"]
            self.assertAlmostEqual(primary["mean_net_excess_pct"], 0.0, places=6)
            self.assertGreater(primary["mean_uncorrected_gross_excess_pct"], primary["mean_net_excess_pct"])
            self.assertEqual(updated_ledger["ledger_status"], "active_no_new_test_authorized")
            self.assertEqual(updated_ledger["budget_policy"]["tests_spent_count"], 1)
            self.assertEqual(updated_ledger["planned_tests"], [])
            self.assertEqual(updated_ledger["test_spend_log"][0]["status"], "spent_failed_outcome_threshold")
            for output_name in [
                "monthly_stats.csv",
                "metric_summary.csv",
                "stock_concentration.csv",
                "veto_filter_stats.csv",
            ]:
                self.assertTrue((output_dir / output_name).exists())

    def test_missing_required_column_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_samples.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["trade_date", "ts_code"])
                writer.writeheader()
                writer.writerow({"trade_date": "20240131", "ts_code": "000001.SZ"})

            with self.assertRaisesRegex(ValueError, "missing required columns"):
                runner.read_rank_samples(path)


if __name__ == "__main__":
    unittest.main()
