from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from runners import a_long_materialized_thin_slice_data_integrity_audit as runner


class ALongMaterializedThinSliceDataIntegrityAuditTest(unittest.TestCase):
    def write_payload(
        self,
        raw_root: Path,
        call_id: str,
        *,
        table_id: str,
        api_family: str,
        columns: list[str],
        records: list[dict[str, object]],
    ) -> str:
        path = raw_root / f"{call_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "call_id": call_id,
            "table_id": table_id,
            "api_family": api_family,
            "request_shape_without_token": {},
            "call_status": "success",
            "row_count": len(records),
            "columns": columns,
            "records": records,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(path)

    def build_fixture(
        self,
        tmp_path: Path,
        *,
        future_ann_date: bool = False,
        omit_raw: bool = False,
        drop_ann_date_column: bool = False,
    ) -> tuple[Path, Path]:
        raw_root = tmp_path / "raw"
        endpoint_results: list[dict[str, object]] = []

        def add(call_id: str, table_id: str, api_family: str, columns: list[str], rows: list[dict[str, object]]) -> None:
            raw_ref = self.write_payload(
                raw_root,
                call_id,
                table_id=table_id,
                api_family=api_family,
                columns=columns,
                records=rows,
            )
            endpoint_results.append(
                {
                    "call_id": call_id,
                    "table_id": table_id,
                    "api_family": api_family,
                    "call_status": "success",
                    "raw_payload_ref": raw_ref,
                }
            )

        add(
            "trade_calendar_2022_2023",
            "trade_calendar",
            "trade_cal",
            ["cal_date", "is_open", "exchange"],
            [
                {"cal_date": "20220131", "is_open": "1", "exchange": "SSE"},
                {"cal_date": "20221230", "is_open": "1", "exchange": "SSE"},
                {"cal_date": "20230131", "is_open": "1", "exchange": "SSE"},
                {"cal_date": "20231229", "is_open": "1", "exchange": "SSE"},
            ],
        )
        add(
            "stock_basic_active_L",
            "stock_basic_active",
            "stock_basic",
            ["ts_code", "name", "list_status", "list_date", "delist_date"],
            [
                {"ts_code": "000001.SZ", "name": "one", "list_status": "L", "list_date": "19910403", "delist_date": None},
                {"ts_code": "600519.SH", "name": "two", "list_status": "L", "list_date": "20010827", "delist_date": None},
            ],
        )
        add(
            "stock_basic_delisted_D",
            "stock_basic_delisted",
            "stock_basic",
            ["ts_code", "name", "list_status", "list_date", "delist_date"],
            [{"ts_code": "000666.SZ", "name": "del", "list_status": "D", "list_date": "19961231", "delist_date": "20230920"}],
        )

        fundamental_rows_by_year = [
            {"ann_date": "20220430", "end_date": "20211231"},
            {"ann_date": "20230430", "end_date": "20221231"},
        ]
        if future_ann_date:
            fundamental_rows_by_year[1] = {"ann_date": "20240101", "end_date": "20221231"}
        fundamental_columns = {
            "income": ["ts_code", "ann_date", "end_date", "revenue", "n_income_attr_p"],
            "balancesheet": ["ts_code", "ann_date", "end_date", "total_assets", "total_liab", "total_hldr_eqy_exc_min_int"],
            "cashflow": ["ts_code", "ann_date", "end_date", "n_cashflow_act"],
            "fina_indicator": ["ts_code", "ann_date", "end_date", "roe", "profit_dedt"],
        }
        for table in runner.FUNDAMENTAL_TABLES:
            for symbol in runner.SYMBOLS:
                rows = []
                for base in fundamental_rows_by_year:
                    row = {"ts_code": symbol, **base}
                    if table == "income":
                        row.update({"revenue": 1.0, "n_income_attr_p": 1.0})
                    elif table == "balancesheet":
                        row.update({"total_assets": 1.0, "total_liab": 0.5, "total_hldr_eqy_exc_min_int": 0.5})
                    elif table == "cashflow":
                        row.update({"n_cashflow_act": 1.0})
                    else:
                        row.update({"roe": 1.0, "profit_dedt": 1.0})
                    rows.append(row)
                add(
                    f"{table}_{symbol.replace('.', '_')}_2022_2023",
                    table,
                    table,
                    [column for column in fundamental_columns[table] if not (drop_ann_date_column and table == "income" and symbol == "000001.SZ" and column == "ann_date")],
                    rows,
                )

        add(
            "index_classify_sw_L1",
            "industry_classification",
            "index_classify",
            ["index_code", "industry_name", "level", "parent_code"],
            [{"index_code": "L1", "industry_name": "L1", "level": "L1", "parent_code": ""}],
        )
        add(
            "index_classify_sw_L2",
            "industry_classification",
            "index_classify",
            ["index_code", "industry_name", "level", "parent_code"],
            [{"index_code": "L2", "industry_name": "L2", "level": "L2", "parent_code": "L1"}],
        )
        add(
            "index_member_all_sw_membership",
            "industry_membership",
            "index_member_all",
            ["ts_code", "l2_code", "l2_name", "in_date", "out_date"],
            [{"ts_code": symbol, "l2_code": "L2", "l2_name": "Industry", "in_date": "20200101", "out_date": None} for symbol in runner.SYMBOLS],
        )

        price_rows = [
            {"trade_date": "20220131", "open": 10.0, "close": 10.5},
            {"trade_date": "20221230", "open": 11.0, "close": 11.5},
            {"trade_date": "20230131", "open": 12.0, "close": 12.5},
            {"trade_date": "20230831", "open": 8.0, "close": 8.5},
        ]
        for symbol in runner.SYMBOLS:
            add(
                f"daily_{symbol.replace('.', '_')}_2022_2023",
                "daily_price_adj_factor_dividend",
                "daily",
                ["ts_code", "trade_date", "open", "close"],
                [{"ts_code": symbol, **row} for row in price_rows],
            )
            add(
                f"adj_factor_{symbol.replace('.', '_')}_2022_2023",
                "daily_price_adj_factor_dividend",
                "adj_factor",
                ["ts_code", "trade_date", "adj_factor"],
                [{"ts_code": symbol, "trade_date": row["trade_date"], "adj_factor": 1.0} for row in price_rows],
            )
            add(
                f"dividend_{symbol.replace('.', '_')}",
                "daily_price_adj_factor_dividend",
                "dividend",
                ["ts_code", "ann_date", "ex_date"],
                [
                    {"ts_code": symbol, "ann_date": "20220430", "ex_date": "20220701"},
                    {"ts_code": symbol, "ann_date": "20230430", "ex_date": "20230701"},
                ],
            )

        for benchmark in runner.BENCHMARKS:
            add(
                f"index_daily_{benchmark.replace('.', '_')}_2022_2023",
                "benchmark_index_daily",
                "index_daily",
                ["ts_code", "trade_date", "open", "close"],
                [{"ts_code": benchmark, **row} for row in price_rows],
            )

        if omit_raw:
            missing = raw_root / "income_000001_SZ_2022_2023.json"
            missing.unlink()

        summary = {
            "schema_name": "a_long_tushare_incremental_materialization_execution_summary",
            "decision": {"materialization_status": "passed_thin_slice_materialization_shape"},
            "execution": {
                "new_network_call_count": 29,
                "reused_raw_payload_count": 0,
                "token_logged": False,
                "request_url_logged": False,
            },
            "thin_slice_boundary": {
                "start_date": "20220101",
                "end_date": "20231231",
                "active_symbols": ["000001.SZ", "600519.SH"],
                "delisted_symbols": ["000666.SZ"],
                "benchmark_indices": ["000300.SH", "000852.SH"],
            },
            "endpoint_results": endpoint_results,
        }
        summary_path = tmp_path / "summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary_path, raw_root

    def test_materialized_thin_slice_passes_without_raw_records_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path, raw_root = self.build_fixture(tmp_path)
            output_dir = tmp_path / "out"

            report = runner.run(
                argparse.Namespace(
                    materialization_summary=summary_path,
                    raw_root=raw_root,
                    output_dir=output_dir,
                    generated_at="2026-06-04T00:00:00Z",
                )
            )

            self.assertEqual(report["decision"]["audit_status"], "passed_thin_slice_data_integrity_not_alpha_ready")
            self.assertTrue(report["decision"]["thin_slice_checks_pass"])
            self.assertFalse(report["decision"]["data_can_be_used_for_alpha_now"])
            self.assertEqual(report["execution"]["network_calls_executed"], 0)
            self.assertEqual(report["execution"]["provider_calls_executed"], 0)
            self.assertEqual(report["execution"]["self_tests_required"], 11)
            self.assertEqual(report["execution"]["self_tests_passed"], 11)
            materialized_self_tests = [
                item
                for item in report["required_runner_self_tests"]
                if item["checker_origin"] == "materialized_thin_slice_runner"
            ]
            self.assertEqual(len(materialized_self_tests), 5)
            self.assertTrue(all(item["detected_expected_violation"] for item in materialized_self_tests))
            self.assertEqual({item["status"] for item in report["check_results"]}, {"pass_thin_slice", "coverage_characterized_thin_slice"})
            self.assertTrue((output_dir / "audit_report.json").exists())
            self.assertTrue((output_dir / "check_summary.csv").exists())
            self.assertTrue((output_dir / "coverage_by_year.csv").exists())
            persisted = (output_dir / "audit_report.json").read_text(encoding="utf-8")
            self.assertNotIn('"records"', persisted)

    def test_future_ann_date_is_excluded_from_asof_not_raw_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path, raw_root = self.build_fixture(tmp_path, future_ann_date=True)

            report = runner.run(
                argparse.Namespace(
                    materialization_summary=summary_path,
                    raw_root=raw_root,
                    output_dir=tmp_path / "out",
                    generated_at="2026-06-04T00:00:00Z",
                )
            )

            checks = {item["check_id"]: item for item in report["check_results"]}
            self.assertEqual(report["decision"]["audit_status"], "passed_thin_slice_data_integrity_not_alpha_ready")
            self.assertEqual(checks["fundamental_pit"]["status"], "pass_thin_slice")
            self.assertGreater(checks["fundamental_pit"]["metrics"]["future_ann_date_rows_excluded_by_asof_gate"], 0)
            self.assertTrue(checks["fundamental_pit"]["metrics"]["ann_date_asof_gating_feasible"])
            self.assertNotIn("ann_date_future_lookahead_violation_rows", checks["fundamental_pit"]["metrics"])

    def test_missing_required_ann_date_column_blocks_pit_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path, raw_root = self.build_fixture(tmp_path, drop_ann_date_column=True)

            report = runner.run(
                argparse.Namespace(
                    materialization_summary=summary_path,
                    raw_root=raw_root,
                    output_dir=tmp_path / "out",
                    generated_at="2026-06-04T00:00:00Z",
                )
            )

            checks = {item["check_id"]: item for item in report["check_results"]}
            self.assertEqual(report["decision"]["audit_status"], "blocked_missing_required_source")
            self.assertEqual(checks["fundamental_pit"]["status"], "blocked_missing_required_source")
            self.assertIn("income_000001_SZ_2022_2023:ann_date", checks["fundamental_pit"]["metrics"]["missing_required_columns"])

    def test_missing_raw_payload_blocks_before_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path, raw_root = self.build_fixture(tmp_path, omit_raw=True)

            with self.assertRaises(FileNotFoundError):
                runner.run(
                    argparse.Namespace(
                        materialization_summary=summary_path,
                        raw_root=raw_root,
                        output_dir=tmp_path / "out",
                        generated_at="2026-06-04T00:00:00Z",
                    )
                )

    def test_cli_keeps_materialization_summary_and_raw_root_fixed(self) -> None:
        args = runner.parse_args([])

        self.assertEqual(args.materialization_summary, runner.SUMMARY_PATH)
        self.assertEqual(args.raw_root, runner.RAW_ROOT)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                runner.parse_args(["--raw-root", "other"])


if __name__ == "__main__":
    unittest.main()
