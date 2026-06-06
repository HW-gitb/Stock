from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/a_long_data_integrity_audit_preregistration.schema.json")
ARTIFACT_PATH = Path("research/preregistrations/a_long_data_integrity_audit_20260603.json")
LEDGER_SCHEMA_PATH = Path("schemas/program_test_budget_ledger.schema.json")
LEDGER_ARTIFACT_PATH = Path("research/ledgers/a_long_data_integrity_audit_program_test_budget_ledger_20260603.json")


class ALongDataIntegrityAuditPreregistrationTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_schema(self) -> dict:
        return self._load_json(SCHEMA_PATH)

    def _load_artifact(self) -> dict:
        return self._load_json(ARTIFACT_PATH)

    def _load_ledger_schema(self) -> dict:
        return self._load_json(LEDGER_SCHEMA_PATH)

    def _load_ledger(self) -> dict:
        return self._load_json(LEDGER_ARTIFACT_PATH)

    def test_schema_artifact_and_ledger_validate_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()
        artifact = self._load_artifact()
        ledger_schema = self._load_ledger_schema()
        ledger = self._load_ledger()

        Draft7Validator.check_schema(schema)
        Draft7Validator.check_schema(ledger_schema)
        self.assertEqual(list(Draft7Validator(schema).iter_errors(artifact)), [])
        self.assertEqual(list(Draft7Validator(ledger_schema).iter_errors(ledger)), [])

    def test_scope_locks_out_audit_run_signal_search_provider_datahub_and_ship_gate(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertEqual(scope["lane_id"], "a_long")
        self.assertEqual(scope["market"], "A-share")
        self.assertTrue(scope["research_only"])
        self.assertTrue(scope["manual_order_only"])
        for field_name in [
            "audit_run_allowed_by_this_artifact",
            "signal_search_allowed",
            "alpha_backtest_allowed",
            "new_data_purchase_allowed",
            "provider_expansion_allowed",
            "provider_call_allowed_by_this_artifact",
            "datahub_allowed",
            "production_use_allowed",
            "ship_gate_claim_allowed",
            "full_size_manual_use_allowed",
            "broker_or_order_automation_allowed",
        ]:
            with self.subTest(field_name=field_name):
                self.assertFalse(scope[field_name])

    def test_active_alpha_route_is_a_long_only_and_a_short_5d_is_not_rescued(self) -> None:
        route = self._load_artifact()["active_alpha_search_route"]

        self.assertEqual(route["active_workstream"], "a_long_data_integrity_first_then_signal_search")
        self.assertEqual(route["a_short_5d_disposition"], "forward_observation_only_no_rescue")
        self.assertEqual(route["us_work_disposition"], "background_active_only_forward_validation")
        self.assertFalse(route["parallel_active_alpha_search_allowed"])

    def test_audit_as_of_schedule_is_frozen_before_runner_execution(self) -> None:
        schedule = self._load_artifact()["audit_as_of_schedule"]

        self.assertEqual(schedule["schedule_id"], "a_long_monthly_last_trading_day_20180131_20251231")
        self.assertEqual(schedule["frequency"], "monthly")
        self.assertEqual(schedule["start_as_of"], "2018-01-31")
        self.assertEqual(schedule["end_as_of"], "2025-12-31")
        self.assertEqual(schedule["calendar_source"], "Tushare trade_cal")
        self.assertEqual(schedule["as_of_selection_rule"], "last_open_A_share_trading_day_of_each_calendar_month")
        self.assertEqual(schedule["timezone"], "Asia/Shanghai")

    def test_required_runner_self_tests_cover_planted_violations(self) -> None:
        fixtures = {item["fixture_id"]: item for item in self._load_artifact()["required_runner_self_tests"]}

        self.assertEqual(
            set(fixtures),
            {
                "future_ann_date_hard_fail",
                "restated_value_asof_fail",
                "dropped_delisted_member_fail",
                "missing_delisting_terminal_return_fail",
                "benchmark_anchor_mismatch_fail",
                "sparse_early_coverage_declares_usable_window",
            },
        )
        for fixture in fixtures.values():
            self.assertTrue(fixture["required_before_audit_execution"])
            self.assertTrue(fixture["artifact_or_test_output_required"])
            self.assertGreater(len(fixture["planted_violation"]), 20)
            self.assertGreater(len(fixture["expected_audit_response"]), 20)

        self.assertIn("fundamental_pit", fixtures["future_ann_date_hard_fail"]["target_check_ids"])
        self.assertIn("restatement_revision_asof", fixtures["restated_value_asof_fail"]["target_check_ids"])
        self.assertIn("survivorship_pit_universe", fixtures["dropped_delisted_member_fail"]["target_check_ids"])
        self.assertEqual(
            set(fixtures["missing_delisting_terminal_return_fail"]["target_check_ids"]),
            {"survivorship_pit_universe", "return_benchmark_measurement_basis"},
        )
        self.assertIn("return_benchmark_measurement_basis", fixtures["benchmark_anchor_mismatch_fail"]["target_check_ids"])
        self.assertIn("temporal_coverage_bias", fixtures["sparse_early_coverage_declares_usable_window"]["target_check_ids"])

    def test_five_audit_checks_freeze_sources_formulas_and_thresholds(self) -> None:
        checks = {item["check_id"]: item for item in self._load_artifact()["audit_checks"]}

        self.assertEqual(
            set(checks),
            {
                "fundamental_pit",
                "restatement_revision_asof",
                "survivorship_pit_universe",
                "return_benchmark_measurement_basis",
                "temporal_coverage_bias",
            },
        )
        self.assertEqual(checks["fundamental_pit"]["pass_threshold"], {
            "metric": "ann_date_future_lookahead_violation_rate",
            "operator": "<=",
            "value": 0,
            "unit": "fraction",
        })
        self.assertEqual(checks["fundamental_pit"]["blocking_effect"], "hard_block_signal_search_if_failed")
        self.assertEqual(checks["fundamental_pit"]["non_blocking_tolerance"], {
            "metric": "ann_date_missing_or_invalid_exclusion_rate",
            "operator": "<=",
            "value": 5,
            "unit": "percent",
            "action_if_exceeded": "exclude_and_report_affects_usable_window_not_global_fail",
        })
        self.assertEqual(checks["restatement_revision_asof"]["pass_threshold"]["value"], 0)
        self.assertEqual(checks["restatement_revision_asof"]["non_blocking_tolerance"], {
            "metric": "same_ann_date_ambiguous_exclusion_rate_pct",
            "operator": "<=",
            "value": 0.5,
            "unit": "percent",
            "action_if_exceeded": "fail_data_not_ready_and_require_re_review_not_auto_tolerate",
        })
        self.assertEqual(checks["survivorship_pit_universe"]["pass_threshold"]["value"], 0)
        self.assertEqual(checks["return_benchmark_measurement_basis"]["pass_threshold"]["value"], 0)
        self.assertEqual(checks["temporal_coverage_bias"]["blocking_effect"], "characterize_and_limit_usable_window_not_global_block")
        self.assertEqual(checks["temporal_coverage_bias"]["pass_threshold"], {
            "metric": "minimum_yearly_required_fundamental_table_coverage_pct",
            "operator": ">=",
            "value": 80,
            "unit": "percent",
        })

        joined_sources = "\n".join(
            source
            for check in checks.values()
            for source in check["data_sources"]
        )
        joined_fields = "\n".join(
            field
            for check in checks.values()
            for field in check["field_requirements"]
        )
        for required_text in [
            "Tushare income",
            "Tushare balancesheet",
            "Tushare fina_indicator",
            "Tushare stock_basic",
            "Tushare daily",
            "Tushare adj_factor",
            "Tushare dividend",
            "Tushare index_daily",
            "ann_date",
            "ts_code",
            "end_date",
            "list_date",
            "delist_date",
            "same entry and exit",
                "terminal / delisting return",
                "restatement_ambiguous_exclusions.csv",
            ]:
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, joined_sources + "\n" + joined_fields)

        for check_id, check in checks.items():
            if check_id == "temporal_coverage_bias":
                self.assertIn("usable_start_year", check["violation_rate_formula"])
                self.assertEqual(check["failure_action"], "characterize_coverage_and_declare_usable_start_year")
            else:
                self.assertIn("violation_numerator", check["violation_rate_formula"])
                self.assertEqual(
                    check["failure_action"],
                    "block_signal_search_until_data_repaired_or_new_reviewed_audit_plan",
                )

    def test_reviewed_repair_amendment_precommits_restatement_exclusion_policy(self) -> None:
        amendment = self._load_artifact()["reviewed_repair_amendments"][0]

        self.assertEqual(amendment["amendment_id"], "a_long_full_main_board_restatement_exclusion_policy_20260605")
        self.assertEqual(amendment["applies_to_check_id"], "restatement_revision_asof")
        self.assertEqual(amendment["ambiguous_group_signal_treatment"], "mandatory_exclusion_from_signal_inputs")
        self.assertEqual(amendment["max_ambiguous_exclusion_rate_pct"], 0.5)
        self.assertLessEqual(amendment["observed_ambiguous_exclusion_rate_pct"], amendment["max_ambiguous_exclusion_rate_pct"])
        self.assertEqual(
            amendment["exclusion_list_artifact"],
            "research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv",
        )
        self.assertTrue(amendment["signal_search_preregistration_must_consume_exclusion_list"])
        self.assertFalse(amendment["silent_use_of_ambiguous_groups_allowed"])
        self.assertFalse(amendment["signal_search_authorized_by_this_amendment"])
        self.assertFalse(amendment["alpha_or_production_claim_allowed"])
        self.assertIn("same 0.5 percent ceiling", amendment["cap_rationale"])

    def test_decision_policy_blocks_signal_search_until_all_checks_pass(self) -> None:
        decision = self._load_artifact()["decision_policy"]
        prohibited = self._load_artifact()["prohibited_claims"]

        self.assertEqual(decision["all_checks_pass"], "may_create_next_reviewed_a_long_signal_search_preregistration")
        self.assertEqual(decision["any_check_fails"], "repair_data_or_revise_provider_route_before_any_signal_backtest")
        self.assertEqual(
            decision["hard_checks_pass_and_usable_window_declared"],
            "may_create_next_reviewed_a_long_signal_search_preregistration_limited_to_declared_usable_window",
        )
        self.assertEqual(decision["coverage_characterization_result"], "declare_usable_start_year_not_global_fail")
        self.assertEqual(
            decision["missing_or_invalid_ann_date_result"],
            "exclude_and_report_not_global_fail_unless_required_table_has_no_pit_usable_ann_date_field",
        )
        self.assertTrue(decision["signal_search_after_pass_requires_new_preregistration"])
        self.assertFalse(decision["backtest_can_authorize_full_size"])
        self.assertTrue(all(value is False for value in prohibited.values()))

    def test_ledger_records_spent_blocked_data_gate_without_alpha_budget(self) -> None:
        artifact = self._load_artifact()
        budget = artifact["planned_test_budget"]
        ledger = self._load_ledger()

        self.assertEqual(budget["ledger_ref"], str(LEDGER_ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(budget["planned_test_id"], "a_long_data_integrity_audit_20260603")
        self.assertEqual(budget["data_integrity_gate_units"], 1)
        self.assertEqual(budget["alpha_test_budget_units_consumed"], 0)
        self.assertFalse(budget["audit_run_authorized_now"])
        self.assertTrue(budget["requires_claude_review_before_run"])
        self.assertTrue(budget["requires_user_execute_before_run"])

        self.assertEqual(ledger["lane_id"], "a_long_data_integrity")
        self.assertEqual(ledger["ledger_status"], "active_no_new_test_authorized")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 1)
        self.assertEqual(ledger["budget_policy"]["tests_available_without_new_review"], 0)
        self.assertEqual(ledger["planned_tests"], [])
        self.assertEqual(len(ledger["test_spend_log"]), 1)
        spent = ledger["test_spend_log"][0]
        self.assertEqual(spent["test_id"], "a_long_data_integrity_audit_20260603")
        self.assertEqual(spent["status"], "spent_voided_by_data_integrity_failure")
        self.assertIn("blocked_missing_required_source", spent["result_summary"])
        self.assertIn("signal_search_allowed=false", spent["result_summary"])
        self.assertIn("zero alpha-test budget", ledger["budget_policy"]["spend_rule"])
        self.assertIn("Do not start A-long signal search", ledger["next_required_actions"][0])

    def test_scope_creep_and_threshold_changes_are_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["signal_search_allowed"] = True
        invalid["scope"]["alpha_backtest_allowed"] = True
        invalid["scope"]["audit_run_allowed_by_this_artifact"] = True
        invalid["scope"]["provider_expansion_allowed"] = True
        invalid["scope"]["ship_gate_claim_allowed"] = True
        invalid["active_alpha_search_route"]["parallel_active_alpha_search_allowed"] = True
        invalid["prohibited_claims"]["a_long_alpha_found"] = True
        invalid["audit_checks"][0]["pass_threshold"]["value"] = 0.01
        invalid["audit_checks"][0]["non_blocking_tolerance"]["value"] = 50
        invalid["audit_checks"][1]["non_blocking_tolerance"]["value"] = 5
        invalid["reviewed_repair_amendments"][0]["silent_use_of_ambiguous_groups_allowed"] = True
        invalid["reviewed_repair_amendments"][0]["max_ambiguous_exclusion_rate_pct"] = 5
        invalid["audit_checks"][4]["pass_threshold"]["value"] = 60
        invalid["audit_checks"][4]["failure_action"] = "block_signal_search_until_data_repaired_or_new_reviewed_audit_plan"
        invalid["audit_as_of_schedule"]["start_as_of"] = "2015-01-31"
        invalid["required_runner_self_tests"] = invalid["required_runner_self_tests"][:-1]

        errors = list(Draft7Validator(self._load_schema()).iter_errors(invalid))

        self.assertNotEqual(errors, [])

    def test_ledger_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = copy.deepcopy(self._load_ledger())
        invalid["lane_id"] = "a_long_research"
        invalid["budget_policy"]["ledger_cardinality"] = "per_hypothesis"
        invalid["budget_policy"]["next_test_requires_reviewed_preregistration"] = False
        invalid["budget_policy"]["next_test_requires_user_approval"] = False
        invalid["test_spend_log"][0]["status"] = "spent_passed_research_continue_only"

        errors = list(Draft7Validator(self._load_ledger_schema()).iter_errors(invalid))

        self.assertNotEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
