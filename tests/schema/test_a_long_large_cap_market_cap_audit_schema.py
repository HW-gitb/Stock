from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

from runners import a_long_large_cap_market_cap_audit as runner


PACKET_SCHEMA_PATH = Path("schemas/a_long_large_cap_market_cap_audit_packet.schema.json")
REPORT_SCHEMA_PATH = Path("schemas/a_long_large_cap_market_cap_audit_report.schema.json")
PACKET_PATH = Path("docs/a_long_large_cap_market_cap_audit_packet_20260607.json")


class ALongLargeCapMarketCapAuditSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _fake_monthly_rows(self) -> list[dict]:
        rows = []
        for trade_date in runner.MONTHLY_AS_OF_DATES:
            rows.append(
                {
                    "as_of": trade_date,
                    "raw_row_count": 5000,
                    "summary_row_count": 5000,
                    "date_mismatch_count": 0,
                    "main_board_row_count": 3000,
                    "positive_main_board_circ_mv_count": 3000,
                    "selected_top500_count": 500,
                    "selected_top500_complete": True,
                    "selected_top500_min_circ_mv": 1000.0,
                    "selected_top500_max_circ_mv": 100000.0,
                    "summary_rederivation_mismatch": False,
                    "outside_prior_audited_universe_count": 0,
                    "outside_prior_audited_universe_sample": [],
                    "size_q1_count": 100,
                    "size_q2_count": 100,
                    "size_q3_count": 100,
                    "size_q4_count": 100,
                    "size_q5_count": 100,
                    "minimum_size_quintile_count": 100,
                    "top500_symbols_written_to_tracked_report": False,
                }
            )
        return rows

    def _fake_report(self) -> dict:
        self_tests = [
            {
                "fixture_id": fixture_id,
                "checker_origin": "large_cap_market_cap_audit_runner",
                "status": "pass",
                "detected_expected_violation": True,
            }
            for fixture_id in runner.SELF_TEST_IDS
        ]
        checks = [
            {
                "check_id": check_id,
                "status": "pass_large_cap_market_cap_audit",
                "hard_check": True,
                "blocks_signal_search": False,
                "metrics": {},
                "findings": ["ok"],
                "allowed_followup": "ok",
            }
            for check_id in runner.CHECK_IDS
        ]
        return {
            "schema_name": "a_long_large_cap_market_cap_audit_report",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-07T00:00:00+00:00",
            "artifact_id": "a_long_large_cap_market_cap_audit_report_20260607",
            "source_refs": [
                "docs/a_long_large_cap_market_cap_audit_packet_20260607.json",
                "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
            ],
            "scope": {
                "phase": "7a_alpha_validation",
                "purpose": "a_long_large_cap_market_cap_materialization_audit",
                "lane_id": "a_long",
                "market": "A-share",
                "research_only": True,
                "local_market_cap_raw_read_only": True,
                "prior_full_main_board_raw_read_only": True,
                "provider_call_executed": False,
                "tushare_call_executed": False,
                "data_fetch_executed": False,
                "raw_rows_in_tracked_report": False,
                "top500_symbols_in_tracked_report": False,
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
                "audit_packet_ref": "docs/a_long_large_cap_market_cap_audit_packet_20260607.json",
                "materialization_summary_ref": "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
                "market_cap_raw_root": "data/a_long/raw/tushare/large_cap_market_cap_materialization_20260607/",
                "prior_full_main_board_raw_root": "data/a_long/raw/tushare/full_main_board_signal_search_20260605/",
                "monthly_as_of_count": 96,
                "months_audited": 96,
                "network_calls_executed": 0,
                "provider_calls_executed": 0,
                "self_tests_required": 5,
                "self_tests_passed": 5,
                "independent_review_confirmed": True,
                "post_review_execute_confirmed": True,
                "tracked_report_contains_raw_records": False,
                "tracked_report_contains_top500_symbols": False,
                "tracked_report_contains_endpoint_results": False,
                "tracked_report_contains_secret": False,
                "tracked_report_contains_request_url": False,
            },
            "audit_boundary": {
                "materialization_id": "a_long_large_cap_market_cap_top500_monthly_2018_2025",
                "selected_market_cap_field": "circ_mv",
                "universe_size_n": 500,
                "board_scope": "main_board_only",
                "main_board_filter_source": "engine.data.a_share_board_scope.is_main_board_ts_code",
                "monthly_as_of_count": 96,
                "monthly_as_of_dates": runner.MONTHLY_AS_OF_DATES,
                "same_as_materialization_dates": True,
                "prior_audited_universe_count": 3387,
                "size_bucket_count": 5,
                "minimum_size_bucket_count_for_primary_percentile": 50,
                "top500_symbols_written_to_tracked_report": False,
                "not_signal_search": True,
            },
            "required_runner_self_tests": self_tests,
            "check_results": checks,
            "monthly_coverage": self._fake_monthly_rows(),
            "decision": {
                "audit_status": "passed_large_cap_market_cap_audit_for_signal_package",
                "hard_checks_pass": True,
                "market_cap_universe_ready_for_signal_package_after_review": True,
                "signal_search_package_may_be_built_after_review": True,
                "signal_search_authorized_by_this_report": False,
                "alpha_found": False,
                "plain_result": "ok",
                "next_action": "ok",
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
            "result_artifacts": [
                "research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json",
                "research/results/a_long_large_cap_market_cap_audit_20260607/monthly_coverage.csv",
            ],
            "limitations": ["research only"],
        }

    def test_packet_and_report_schemas_are_valid(self) -> None:
        packet_schema = self._load_json(PACKET_SCHEMA_PATH)
        report_schema = self._load_json(REPORT_SCHEMA_PATH)
        packet = self._load_json(PACKET_PATH)
        report = self._fake_report()

        Draft7Validator.check_schema(packet_schema)
        Draft7Validator.check_schema(report_schema)
        self.assertEqual(list(Draft7Validator(packet_schema).iter_errors(packet)), [])
        self.assertEqual(list(Draft7Validator(report_schema).iter_errors(report)), [])

    def test_packet_locks_local_only_audit_boundary(self) -> None:
        packet = self._load_json(PACKET_PATH)

        self.assertTrue(packet["scope"]["ready_for_later_execution_after_independent_review"])
        self.assertTrue(packet["scope"]["actual_audit_requires_post_review_execute_command"])
        self.assertFalse(packet["scope"]["provider_calls_executed_by_this_artifact"])
        self.assertFalse(packet["scope"]["signal_search_allowed"])
        self.assertEqual(packet["audit_boundary"]["selected_market_cap_field"], "circ_mv")
        self.assertEqual(packet["audit_boundary"]["universe_size_n"], 500)
        self.assertEqual(packet["audit_boundary"]["monthly_as_of_count"], 96)
        self.assertFalse(packet["audit_boundary"]["top500_symbols_written_to_tracked_report"])
        self.assertEqual([item["check_id"] for item in packet["audit_checks"]], runner.CHECK_IDS)

    def test_schema_rejects_scope_creep_and_raw_payloads(self) -> None:
        report_schema = self._load_json(REPORT_SCHEMA_PATH)
        report = self._fake_report()
        report["decision"]["signal_search_authorized_by_this_report"] = True
        report["monthly_coverage"][0]["top500_symbols"] = ["600000.SH"]
        report["scope"]["raw_rows_in_tracked_report"] = True

        errors = list(Draft7Validator(report_schema).iter_errors(report))

        self.assertGreaterEqual(len(errors), 3)

    def test_packet_schema_rejects_signal_authorization(self) -> None:
        packet_schema = self._load_json(PACKET_SCHEMA_PATH)
        packet = copy.deepcopy(self._load_json(PACKET_PATH))
        packet["scope"]["signal_search_allowed"] = True
        packet["output_contract"]["audit_report_authorizes_signal_search_by_itself"] = True
        packet["prohibited_claims"]["signal_search_authorized"] = True

        errors = list(Draft7Validator(packet_schema).iter_errors(packet))

        self.assertGreaterEqual(len(errors), 3)


if __name__ == "__main__":
    unittest.main()
