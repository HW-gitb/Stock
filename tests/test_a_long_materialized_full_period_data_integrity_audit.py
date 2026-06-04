from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from runners import a_long_materialized_full_period_data_integrity_audit as runner


class ALongMaterializedFullPeriodDataIntegrityAuditTest(unittest.TestCase):
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
        drop_ann_date_column: bool = False,
        missing_benchmark_open: bool = False,
        missing_terminal_return: bool = False,
        omit_raw: bool = False,
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
            "trade_calendar_2018_2025",
            "trade_calendar",
            "trade_cal",
            ["cal_date", "is_open", "exchange"],
            [
                {"cal_date": f"{year}{month:02d}28", "is_open": "1", "exchange": "SSE"}
                for year in range(2018, 2026)
                for month in range(1, 13)
            ],
        )
        add(
            "stock_basic_active_L",
            "stock_basic_active",
            "stock_basic",
            ["ts_code", "name", "list_status", "list_date", "delist_date"],
            [
                {
                    "ts_code": symbol,
                    "name": symbol,
                    "list_status": "L",
                    "list_date": "20000101",
                    "delist_date": None,
                }
                for symbol in runner.ACTIVE_SYMBOLS
            ],
        )
        add(
            "stock_basic_delisted_D",
            "stock_basic_delisted",
            "stock_basic",
            ["ts_code", "name", "list_status", "list_date", "delist_date"],
            [{"ts_code": "000666.SZ", "name": "del", "list_status": "D", "list_date": "19961231", "delist_date": "20231026"}],
        )

        fundamental_columns = {
            "income": ["ts_code", "ann_date", "f_ann_date", "end_date", "revenue", "n_income_attr_p"],
            "balancesheet": ["ts_code", "ann_date", "f_ann_date", "end_date", "total_assets", "total_liab", "total_hldr_eqy_exc_min_int"],
            "cashflow": ["ts_code", "ann_date", "f_ann_date", "end_date", "n_cashflow_act"],
            "fina_indicator": ["ts_code", "ann_date", "f_ann_date", "end_date", "roe", "profit_dedt"],
        }
        for table in runner.FUNDAMENTAL_TABLES:
            for symbol in runner.SYMBOLS:
                rows = []
                for year in range(2018, 2026):
                    row: dict[str, object] = {
                        "ts_code": symbol,
                        "ann_date": f"{year}0430",
                        "f_ann_date": f"{year}0430",
                        "end_date": f"{year - 1}1231",
                    }
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
                    runner.call_id_for(table, symbol),
                    table,
                    table,
                    [
                        column
                        for column in fundamental_columns[table]
                        if not (drop_ann_date_column and table == "income" and symbol == "000001.SZ" and column == "ann_date")
                    ],
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
            [{"ts_code": symbol, "l2_code": "L2", "l2_name": "Industry", "in_date": "20100101", "out_date": None} for symbol in runner.SYMBOLS],
        )

        price_rows = [{"trade_date": f"{year}1231", "open": 10.0, "close": 10.5} for year in range(2018, 2026)]
        terminal_rows = [
            {"trade_date": "20230831", "open": 8.0, "close": 8.5},
            {"trade_date": "20231025", "open": 7.0, "close": 7.5},
        ]
        for symbol in runner.SYMBOLS:
            rows = [{"ts_code": symbol, **row} for row in price_rows]
            adj_rows = [{"ts_code": symbol, "trade_date": row["trade_date"], "adj_factor": 1.0} for row in price_rows]
            if symbol == "000666.SZ":
                if missing_terminal_return:
                    rows = [{"ts_code": symbol, "trade_date": "20181231", "open": 8.0, "close": 8.5}]
                else:
                    pre_delist_rows = [row for row in price_rows if str(row["trade_date"]) < "20231026"]
                    rows = [{"ts_code": symbol, **row} for row in pre_delist_rows + terminal_rows]
                    adj_rows = [
                        {"ts_code": symbol, "trade_date": row["trade_date"], "adj_factor": 1.0}
                        for row in pre_delist_rows + terminal_rows
                    ]
            add(runner.call_id_for("daily", symbol), "daily_price_adj_factor_dividend", "daily", ["ts_code", "trade_date", "open", "close"], rows)
            add(
                runner.call_id_for("adj_factor", symbol),
                "daily_price_adj_factor_dividend",
                "adj_factor",
                ["ts_code", "trade_date", "adj_factor"],
                adj_rows,
            )
            add(
                runner.dividend_call_id(symbol),
                "daily_price_adj_factor_dividend",
                "dividend",
                ["ts_code", "ann_date", "ex_date"],
                [{"ts_code": symbol, "ann_date": "20200430", "ex_date": "20200701"}],
            )

        for benchmark in runner.BENCHMARKS:
            columns = ["ts_code", "trade_date", "open", "close"]
            if missing_benchmark_open and benchmark == "000300.SH":
                columns = ["ts_code", "trade_date", "close"]
            add(
                runner.index_call_id(benchmark),
                "benchmark_index_daily",
                "index_daily",
                columns,
                [{"ts_code": benchmark, **row} for row in price_rows],
            )

        if omit_raw:
            (raw_root / "income_000001_SZ_2018_2025.json").unlink()

        summary = {
            "schema_name": "a_long_tushare_broader_materialization_execution_summary",
            "decision": {
                "materialization_status": "passed_full_period_panel_materialization_shape",
                "data_can_be_used_for_alpha_now": False,
            },
            "execution": {
                "endpoint_results_count": 71,
                "token_logged": False,
                "request_url_logged": False,
            },
            "broader_materialization_boundary": {
                "materialization_id": "a_long_tushare_full_period_panel_2018_2025",
                "start_date": "20180101",
                "end_date": "20251231",
                "active_symbols": runner.ACTIVE_SYMBOLS,
                "delisted_symbols": runner.DELISTED_SYMBOLS,
                "benchmark_indices": runner.BENCHMARKS,
                "not_full_market": True,
                "not_full_universe": True,
            },
            "table_rollup": [
                {"table_id": table, "status": "passed_full_period_panel_shape"}
                for table in [
                    "trade_calendar",
                    "stock_basic_active",
                    "stock_basic_delisted",
                    "income",
                    "balancesheet",
                    "cashflow",
                    "fina_indicator",
                    "industry_classification",
                    "industry_membership",
                    "daily_price_adj_factor_dividend",
                    "benchmark_index_daily",
                ]
            ],
            "endpoint_results": endpoint_results,
        }
        summary_path = tmp_path / "summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary_path, raw_root

    def test_full_period_fixed_panel_passes_without_raw_records_in_report(self) -> None:
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

            self.assertEqual(report["decision"]["audit_status"], "passed_fixed_panel_data_integrity_for_signal_preregistration")
            self.assertTrue(report["decision"]["hard_checks_pass"])
            self.assertTrue(report["decision"]["signal_search_preregistration_may_be_created"])
            self.assertFalse(report["decision"]["signal_search_authorized_by_this_report"])
            self.assertFalse(report["decision"]["data_can_be_used_for_alpha_now"])
            self.assertEqual(report["execution"]["network_calls_executed"], 0)
            self.assertEqual(report["execution"]["provider_calls_executed"], 0)
            self.assertEqual(report["execution"]["self_tests_required"], 11)
            self.assertEqual(report["execution"]["self_tests_passed"], 11)
            self.assertEqual({item["status"] for item in report["check_results"]}, {"pass_fixed_panel", "coverage_characterized_fixed_panel"})
            self.assertEqual(len(report["coverage_by_year"]), 32)
            persisted = (output_dir / "audit_report.json").read_text(encoding="utf-8")
            self.assertNotIn('"records"', persisted)

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
            self.assertIn("income_000001_SZ_2018_2025:ann_date", checks["fundamental_pit"]["metrics"]["missing_required_columns"])

    def test_same_ann_date_profit_dedt_blank_duplicate_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path, raw_root = self.build_fixture(tmp_path)
            cid = runner.call_id_for("fina_indicator", "000001.SZ")
            payload_path = raw_root / f"{cid}.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            payload["records"].append(
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20200430",
                    "f_ann_date": "20200430",
                    "end_date": "20191231",
                    "roe": 1.0,
                    "profit_dedt": None,
                }
            )
            payload["row_count"] = len(payload["records"])
            payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            report = runner.run(
                argparse.Namespace(
                    materialization_summary=summary_path,
                    raw_root=raw_root,
                    output_dir=tmp_path / "out",
                    generated_at="2026-06-04T00:00:00Z",
                )
            )

            checks = {item["check_id"]: item for item in report["check_results"]}
            restatement = checks["restatement_revision_asof"]
            self.assertEqual(restatement["status"], "pass_fixed_panel")
            self.assertEqual(restatement["metrics"]["same_ann_date_conflicting_duplicate_groups"], 0)
            self.assertEqual(restatement["metrics"]["same_ann_date_duplicate_groups_resolved_by_non_null_preference"], 1)
            self.assertEqual(report["decision"]["audit_status"], "passed_fixed_panel_data_integrity_for_signal_preregistration")

    def test_missing_benchmark_open_fails_measurement_basis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path, raw_root = self.build_fixture(tmp_path, missing_benchmark_open=True)

            report = runner.run(
                argparse.Namespace(
                    materialization_summary=summary_path,
                    raw_root=raw_root,
                    output_dir=tmp_path / "out",
                    generated_at="2026-06-04T00:00:00Z",
                )
            )

            checks = {item["check_id"]: item for item in report["check_results"]}
            self.assertEqual(report["decision"]["audit_status"], "fail_data_not_ready")
            self.assertIn("000300.SH", checks["return_benchmark_measurement_basis"]["metrics"]["benchmarks_with_failed_anchor_input_shape"])

    def test_non_main_board_summary_is_rejected_before_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path, raw_root = self.build_fixture(tmp_path)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["broader_materialization_boundary"]["active_symbols"] = [
                "000001.SZ",
                "600519.SH",
                "300750.SZ",
                "601318.SH",
                "600036.SH",
                "000651.SZ",
                "002415.SZ",
                "600276.SH",
            ]
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "main-board only"):
                runner.run(
                    argparse.Namespace(
                        materialization_summary=summary_path,
                        raw_root=raw_root,
                        output_dir=tmp_path / "out",
                        generated_at="2026-06-04T00:00:00Z",
                    )
                )

    def test_missing_terminal_delisting_return_fails_survivorship(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path, raw_root = self.build_fixture(tmp_path, missing_terminal_return=True)

            report = runner.run(
                argparse.Namespace(
                    materialization_summary=summary_path,
                    raw_root=raw_root,
                    output_dir=tmp_path / "out",
                    generated_at="2026-06-04T00:00:00Z",
                )
            )

            checks = {item["check_id"]: item for item in report["check_results"]}
            self.assertEqual(report["decision"]["audit_status"], "fail_data_not_ready")
            self.assertIn("000666.SZ", checks["survivorship_pit_universe"]["metrics"]["terminal_return_input_failed_symbols"])

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
