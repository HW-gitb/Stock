from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runners import a_long_full_main_board_data_integrity_audit as runner


class ALongFullMainBoardDataIntegrityAuditTest(unittest.TestCase):
    def test_runner_self_tests_detect_expected_violations(self) -> None:
        results = runner.run_full_board_runner_self_tests()

        self.assertEqual(len(results), 5)
        self.assertTrue(all(item["status"] == "pass" for item in results))
        self.assertTrue(all(item["detected_expected_violation"] for item in results))

    def test_materialization_summary_must_not_claim_alpha_ready(self) -> None:
        summary = {
            "schema_name": "a_long_full_main_board_materialization_execution_summary",
            "decision": {
                "materialization_status": "passed_full_main_board_materialization_shape",
                "data_can_be_used_for_alpha_now": True,
                "next_reviewed_step_can_be_full_data_integrity_audit": True,
            },
            "execution": {
                "endpoint_results_count": 23717,
                "token_logged": False,
                "request_url_logged": False,
            },
            "execution_boundary": {
                "board_scope": "main_board_only",
                "start_date": "20180101",
                "end_date": "20251231",
                "expected_active_count": 3200,
                "expected_delisted_count": 187,
                "expected_candidate_universe_count": 3387,
                "reviewed_no_industry_exception_count": 191,
                "active_investable_missing_industry_allowed": False,
                "active_delisting_shell_symbols": runner.ACTIVE_DELISTING_SHELL_SYMBOLS,
                "manual_industry_fill_allowed": False,
                "silent_unknown_or_default_industry_allowed": False,
                "drop_boundary_names_from_returns_or_risk_allowed": False,
                "industry_denominator_exclusion_only": True,
                "terminal_delisting_return_required": True,
            },
            "table_rollup": [{"calls_error": 0}],
        }

        with self.assertRaises(ValueError):
            runner.validate_materialization_summary(summary)

    def test_survivorship_check_fails_missing_terminal_return(self) -> None:
        store, context, repair = runner.build_self_test_store()
        payloads = copy.deepcopy(store.payloads)
        payloads[runner.call_id_for("daily", "000666.SZ")]["records"] = []

        with patch.object(runner, "REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT", 0):
            check = runner.check_survivorship(runner.PayloadStore(raw_root=Path("."), payloads=payloads), context, repair)

        self.assertEqual(check["status"], "fail_data_not_ready")
        self.assertEqual(check["metrics"]["terminal_return_input_failed_count"], 1)
        self.assertIn("000666.SZ", check["metrics"]["terminal_return_input_failed_symbols"])

    def test_context_uses_reviewed_delisted_boundary_even_when_stock_basic_is_short(self) -> None:
        payloads = {
            "trade_calendar_2018_2025": runner.self_test_payload(
                "trade_calendar_2018_2025",
                ["cal_date", "is_open"],
                [{"cal_date": "20180131", "is_open": "1"}],
            ),
            "stock_basic_active_L": runner.self_test_payload(
                "stock_basic_active_L",
                ["ts_code", "list_status", "list_date", "delist_date"],
                [
                    {"ts_code": "000001.SZ", "list_status": "L", "list_date": "20000101", "delist_date": None},
                    {"ts_code": "600001.SH", "list_status": "L", "list_date": "20000101", "delist_date": None},
                ],
            ),
            "stock_basic_delisted_D": runner.self_test_payload(
                "stock_basic_delisted_D",
                ["ts_code", "list_status", "list_date", "delist_date"],
                [{"ts_code": "000666.SZ", "list_status": "D", "list_date": "19961231", "delist_date": "20231026"}],
            ),
        }
        repair = {
            "delisted_no_industry_boundary": {
                "no_usable_sw_source_symbols": ["000666.SZ", "000777.SZ"],
            }
        }

        with (
            patch.object(runner, "EXPECTED_ACTIVE_COUNT", 2),
            patch.object(runner, "EXPECTED_DELISTED_COUNT", 2),
            patch.object(runner, "REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT", 2),
            patch.object(runner, "ACTIVE_DELISTING_SHELL_SYMBOLS", []),
        ):
            context = runner.build_context(runner.PayloadStore(raw_root=Path("."), payloads=payloads), repair)

        self.assertEqual(context.active_symbols, ["000001.SZ", "600001.SH"])
        self.assertEqual(context.delisted_symbols, ["000666.SZ", "000777.SZ"])

    def test_survivorship_reads_active_supplement_success_flag(self) -> None:
        store, context, repair = runner.build_self_test_store()
        payloads = copy.deepcopy(store.payloads)
        payloads["index_member_all_sw_membership"]["records"] = [
            row for row in payloads["index_member_all_sw_membership"]["records"] if row["ts_code"] != "600001.SH"
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_root = Path(temp_dir).resolve()
            raw_path = raw_root / "active_index_member_all_600001_SH.json"
            raw_path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "ts_code": "600001.SH",
                                "l2_code": "L2",
                                "l2_name": "Industry",
                                "in_date": "20100101",
                                "out_date": None,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            repair = {
                "active_sw_supplement": {
                    "symbol_results": [
                        {
                            "symbol": "600001.SH",
                            "supplement_success": True,
                            "raw_payload_ref": str(raw_path),
                        }
                    ]
                }
            }

            with patch.object(runner, "SW_REPAIR_RAW_ROOT", raw_root):
                check = runner.check_survivorship(runner.PayloadStore(raw_root=Path("."), payloads=payloads), context, repair)

        self.assertEqual(check["metrics"]["active_investable_missing_industry_count"], 0)
        self.assertEqual(check["metrics"]["active_supplemented_sw_invalid_raw_count"], 0)

    def test_return_check_excludes_post_panel_listings(self) -> None:
        store, context, _repair = runner.build_self_test_store()
        payloads = copy.deepcopy(store.payloads)
        payloads["stock_basic_active_L"]["records"].append(
            {"ts_code": "001220.SZ", "list_status": "L", "list_date": "20260203", "delist_date": None}
        )
        future_symbol = "001220.SZ"
        for table in runner.FUNDAMENTAL_TABLES:
            payloads[runner.call_id_for(table, future_symbol)] = runner.self_test_payload(
                runner.call_id_for(table, future_symbol),
                ["ts_code", "ann_date", "end_date"],
                [],
            )
        payloads[runner.call_id_for("daily", future_symbol)] = runner.self_test_payload(
            runner.call_id_for("daily", future_symbol),
            ["ts_code", "trade_date", "open", "close"],
            [],
        )
        payloads[runner.call_id_for("adj_factor", future_symbol)] = runner.self_test_payload(
            runner.call_id_for("adj_factor", future_symbol),
            ["ts_code", "trade_date", "adj_factor"],
            [],
        )
        payloads[runner.dividend_call_id(future_symbol)] = runner.self_test_payload(
            runner.dividend_call_id(future_symbol),
            ["ts_code", "ann_date", "ex_date"],
            [],
        )
        context = runner.AuditContext(
            active_symbols=context.active_symbols + [future_symbol],
            delisted_symbols=context.delisted_symbols,
            exception_symbols=context.exception_symbols,
            active_delisting_shell_symbols=context.active_delisting_shell_symbols,
            as_ofs=context.as_ofs,
        )

        check = runner.check_return_benchmark(runner.PayloadStore(raw_root=Path("."), payloads=payloads), context)

        self.assertEqual(check["status"], "pass_full_main_board")
        self.assertEqual(check["metrics"]["post_panel_listing_symbols_excluded_from_return_shape_count"], 1)

    def test_decision_blocks_signal_when_hard_check_fails(self) -> None:
        checks = [
            runner.make_check("fundamental_pit", "pass_full_main_board", {}, ["ok"]),
            runner.make_check("restatement_revision_asof", "pass_full_main_board", {}, ["ok"]),
            runner.make_check("survivorship_pit_universe", "fail_data_not_ready", {}, ["bad"]),
            runner.make_check("return_benchmark_measurement_basis", "pass_full_main_board", {}, ["ok"]),
            runner.make_check("temporal_coverage_bias", "coverage_characterized_full_main_board", {"usable_start_year": 2018, "below_threshold_cell_count": 0}, ["ok"]),
        ]

        decision = runner.decision_from_checks(checks)

        self.assertEqual(decision["audit_status"], "fail_data_not_ready")
        self.assertFalse(decision["signal_search_may_be_executed_after_review"])
        self.assertFalse(decision["data_can_be_used_for_alpha_now"])

    def test_restatement_resolves_distinct_f_ann_date_versions(self) -> None:
        rows = [
            {
                "ts_code": "000001.SZ",
                "ann_date": "20220430",
                "f_ann_date": "20220430",
                "end_date": "20211231",
                "report_type": "1",
                "revenue": 100.0,
            },
            {
                "ts_code": "000001.SZ",
                "ann_date": "20220430",
                "f_ann_date": "20230430",
                "end_date": "20211231",
                "report_type": "1",
                "revenue": 110.0,
            },
        ]

        resolved, fields, rule = runner.same_ann_duplicate_resolution(rows)

        self.assertTrue(resolved)
        self.assertIn("revenue", fields)
        self.assertEqual(rule, "resolved_by_f_ann_date_asof_disambiguation")

    def test_restatement_exclusion_cap_is_loaded_from_preregistration(self) -> None:
        policy = runner.load_restatement_exclusion_policy()

        self.assertEqual(policy["max_pct"], 0.5)
        self.assertEqual(policy["amendment_id"], "a_long_full_main_board_restatement_exclusion_policy_20260605")
        self.assertIn("same 0.5 percent ceiling", policy["cap_rationale"])

    def test_restatement_check_keeps_full_exclusion_rows_out_of_report_metrics(self) -> None:
        store, context, _repair = runner.build_self_test_store()
        payloads = copy.deepcopy(store.payloads)
        payloads[runner.call_id_for("income", "000001.SZ")]["records"].append(
            {
                "ts_code": "000001.SZ",
                "ann_date": "20200430",
                "f_ann_date": "20200430",
                "end_date": "20191231",
                "revenue": 999.0,
            }
        )
        sidecars: dict[str, object] = {}

        check = runner.check_restatement_revision(runner.PayloadStore(raw_root=Path("."), payloads=payloads), context, sidecars)

        self.assertEqual(check["status"], "fail_data_not_ready")
        self.assertNotIn("same_ann_date_ambiguous_exclusion_rows", check["metrics"])
        self.assertEqual(check["metrics"]["same_ann_date_ambiguous_exclusion_rows_count"], 1)
        self.assertEqual(len(check["metrics"]["same_ann_date_ambiguous_exclusion_rows_sample"]), 1)
        self.assertEqual(len(sidecars["restatement_ambiguous_exclusions"]), 1)

    def test_survivorship_accepts_verified_extended_no_trade_terminal_policy(self) -> None:
        store, context, repair = runner.build_self_test_store()
        payloads = copy.deepcopy(store.payloads)
        payloads[runner.call_id_for("daily", "000666.SZ")]["records"] = [
            row for row in payloads[runner.call_id_for("daily", "000666.SZ")]["records"]
            if row["trade_date"] <= "20221231"
        ]
        payloads[runner.call_id_for("adj_factor", "000666.SZ")]["records"] = [
            row for row in payloads[runner.call_id_for("adj_factor", "000666.SZ")]["records"]
            if row["trade_date"] <= "20221231"
        ]

        with patch.object(runner, "REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT", 0):
            check = runner.check_survivorship(runner.PayloadStore(raw_root=Path("."), payloads=payloads), context, repair)

        self.assertEqual(check["status"], "pass_full_main_board")
        self.assertEqual(check["metrics"]["extended_no_trade_terminal_return_symbols_count"], 1)
        self.assertEqual(check["metrics"]["extended_no_trade_terminal_unverified_count"], 0)


if __name__ == "__main__":
    unittest.main()
