from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/a_long_full_main_board_data_integrity_audit_report.schema.json")
REPORT_PATH = Path("research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json")


class ALongFullMainBoardDataIntegrityAuditSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def _valid_report(self) -> dict:
        return {
            "schema_name": "a_long_full_main_board_data_integrity_audit_report",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-05T00:00:00+00:00",
            "artifact_id": "a_long_full_main_board_data_integrity_audit_report_20260605",
            "source_refs": ["docs/a_long_full_main_board_materialization_execution_summary_20260605.json"],
            "scope": {
                "phase": "7a_alpha_validation",
                "purpose": "a_long_full_main_board_data_integrity_audit",
                "lane_id": "a_long",
                "market": "A-share",
                "research_only": True,
                "materialized_raw_read_only": True,
                "reviewed_sw_repair_raw_read_only": True,
                "provider_call_executed": False,
                "tushare_call_executed": False,
                "data_fetch_executed": False,
                "raw_rows_in_tracked_report": False,
                "endpoint_results_in_tracked_report": False,
                "signal_search_executed": False,
                "alpha_backtest_executed": False,
                "production_use_allowed": False,
                "ship_gate_claim_allowed": False,
                "full_size_manual_use_allowed": False,
                "broker_or_order_automation_allowed": False,
                "manual_order_only": True,
            },
            "execution": {
                "materialization_summary_ref": "docs/a_long_full_main_board_materialization_execution_summary_20260605.json",
                "raw_root": "data/a_long/raw/tushare/full_main_board_signal_search_20260605/",
                "endpoint_results_count": 23717,
                "network_calls_executed": 0,
                "provider_calls_executed": 0,
                "self_tests_required": 11,
                "self_tests_passed": 11,
                "tracked_report_contains_raw_records": False,
                "tracked_report_contains_endpoint_results": False,
                "tracked_report_contains_secret": False,
                "tracked_report_contains_request_url": False,
            },
            "full_main_board_boundary": {
                "board_scope": "main_board_only",
                "start_date": "20180101",
                "end_date": "20251231",
                "active_symbol_count": 3200,
                "delisted_symbol_count": 187,
                "candidate_universe_count": 3387,
                "reviewed_no_industry_exception_count": 191,
                "active_delisting_shell_symbols": ["600421.SH", "600599.SH", "600636.SH", "600696.SH"],
                "benchmark_indices": ["000300.SH", "000852.SH"],
                "monthly_as_of_count": 96,
                "not_full_market_or_cross_board": True,
            },
            "required_runner_self_tests": [
                {"fixture_id": "future_ann_date_hard_fail", "checker_origin": "legacy_preregistration_base_audit", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "restated_value_asof_fail", "checker_origin": "legacy_preregistration_base_audit", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "dropped_delisted_member_fail", "checker_origin": "legacy_preregistration_base_audit", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "missing_delisting_terminal_return_fail", "checker_origin": "legacy_preregistration_base_audit", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "benchmark_anchor_mismatch_fail", "checker_origin": "legacy_preregistration_base_audit", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "sparse_early_coverage_declares_usable_window", "checker_origin": "legacy_preregistration_base_audit", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "full_main_board_fundamental_missing_ann_date_column_blocks", "checker_origin": "full_main_board_data_integrity_runner", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "full_main_board_restatement_same_ann_date_conflict_fails", "checker_origin": "full_main_board_data_integrity_runner", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "full_main_board_survivorship_missing_terminal_return_fails", "checker_origin": "full_main_board_data_integrity_runner", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "full_main_board_return_benchmark_missing_open_fails", "checker_origin": "full_main_board_data_integrity_runner", "status": "pass", "detected_expected_violation": True},
                {"fixture_id": "full_main_board_temporal_coverage_below_threshold_detected", "checker_origin": "full_main_board_data_integrity_runner", "status": "pass", "detected_expected_violation": True}
            ],
            "check_results": [
                {"check_id": "fundamental_pit", "status": "pass_full_main_board", "hard_check": True, "blocks_signal_search": True, "metrics": {}, "findings": ["ok"], "allowed_followup": "reviewed next gate only"},
                {"check_id": "restatement_revision_asof", "status": "pass_full_main_board", "hard_check": True, "blocks_signal_search": True, "metrics": {}, "findings": ["ok"], "allowed_followup": "reviewed next gate only"},
                {"check_id": "survivorship_pit_universe", "status": "pass_full_main_board", "hard_check": True, "blocks_signal_search": True, "metrics": {}, "findings": ["ok"], "allowed_followup": "reviewed next gate only"},
                {"check_id": "return_benchmark_measurement_basis", "status": "pass_full_main_board", "hard_check": True, "blocks_signal_search": True, "metrics": {}, "findings": ["ok"], "allowed_followup": "reviewed next gate only"},
                {"check_id": "temporal_coverage_bias", "status": "coverage_characterized_full_main_board", "hard_check": False, "blocks_signal_search": True, "metrics": {}, "findings": ["ok"], "allowed_followup": "reviewed next gate only"}
            ],
            "coverage_by_year": [
                {"year": year, "table_id": table, "eligible_symbol_count": 1, "covered_symbol_count": 1, "coverage_pct": 100.0, "status": "pass_full_main_board"}
                for year in range(2018, 2026)
                for table in ["income", "balancesheet", "cashflow", "fina_indicator"]
            ],
            "decision": {
                "audit_status": "passed_full_main_board_data_integrity_for_signal_search",
                "hard_checks_pass": True,
                "usable_start_year": 2018,
                "data_can_be_used_for_alpha_now": False,
                "signal_search_may_be_executed_after_review": True,
                "signal_search_authorized_by_this_report": False,
                "alpha_found": False,
                "plain_result": "Full main-board data audit passed.",
                "next_action": "reviewed next gate only",
            },
            "prohibited_claims": {
                "a_long_alpha_found": False,
                "signal_search_executed": False,
                "signal_search_authorized": False,
                "alpha_backtest_executed": False,
                "production_ready": False,
                "ship_gate_evidence": False,
                "full_size_allowed": False,
                "provider_selected": False,
                "datahub_authorized": False,
                "broker_or_order_automation_authorized": False,
            },
            "result_artifacts": ["research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json"],
            "limitations": ["no alpha"],
        }

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "a_long_full_main_board_data_integrity_audit_report")
        self.assertFalse(schema["additionalProperties"])

    def test_minimal_report_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._valid_report()), [])

    def test_generated_report_validates_when_present(self) -> None:
        if not REPORT_PATH.exists():
            raise unittest.SkipTest("full main-board audit report has not been generated yet")

        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self._validate(report), [])
        text = REPORT_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"records"', text)
        self.assertNotIn('"endpoint_results"', text)
        self.assertNotIn('"same_ann_date_ambiguous_exclusion_rows":', text)
        self.assertNotIn("TUSHARE_TOKEN", text)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._valid_report())
        invalid["scope"]["provider_call_executed"] = True
        invalid["scope"]["raw_rows_in_tracked_report"] = True
        invalid["scope"]["signal_search_executed"] = True
        invalid["decision"]["data_can_be_used_for_alpha_now"] = True
        invalid["decision"]["signal_search_authorized_by_this_report"] = True
        invalid["prohibited_claims"]["a_long_alpha_found"] = True
        invalid["prohibited_claims"]["production_ready"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
