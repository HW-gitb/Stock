from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/a_short_steady_alpha_reaudit_preregistration.schema.json")
ARTIFACT_PATH = Path("research/preregistrations/a_short_steady_alpha_reaudit_20260603.json")
LEDGER_SCHEMA_PATH = Path("schemas/program_test_budget_ledger.schema.json")
LEDGER_ARTIFACT_PATH = Path("research/ledgers/a_short_steady_alpha_reaudit_program_test_budget_ledger_20260603.json")


class AShortSteadyAlphaReauditPreregistrationTest(unittest.TestCase):
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

    def test_scope_locks_outcome_fetch_runner_datahub_and_ship_gate(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]

        self.assertEqual(scope["lane_id"], "a_short_steady")
        self.assertEqual(scope["market"], "A-share")
        self.assertTrue(scope["research_only"])
        self.assertTrue(scope["manual_order_only"])
        for field_name in [
            "outcome_run_allowed_by_this_artifact",
            "data_fetch_allowed",
            "egs_rerun_allowed",
            "cohort_regeneration_allowed",
            "provider_call_allowed",
            "datahub_allowed",
            "runner_change_allowed",
            "strategy_rule_change_allowed",
            "production_use_allowed",
            "ship_gate_claim_allowed",
            "full_size_manual_use_allowed",
            "broker_or_order_automation_allowed",
        ]:
            with self.subTest(field_name=field_name):
                self.assertFalse(scope[field_name])

    def test_metric_plan_freezes_same_anchor_5d_and_20d(self) -> None:
        artifact = self._load_artifact()
        metric_plan = artifact["metric_plan"]
        frozen_design = artifact["frozen_design"]

        self.assertEqual(metric_plan["primary_metric"], "same_anchor_benchmark_excess")
        self.assertTrue(metric_plan["same_anchor_required"])
        self.assertEqual(metric_plan["stock_leg"], "stock_T_plus_1_open_to_exit_close")
        self.assertEqual(metric_plan["benchmark_leg"], "benchmark_T_plus_1_open_to_same_exit_close")
        self.assertEqual(metric_plan["primary_benchmark"], "CSI1000")
        self.assertEqual(metric_plan["secondary_benchmark"], "CSI300")
        self.assertEqual(set(metric_plan["horizons_trading_days"]), {5, 20})
        self.assertEqual(set(frozen_design["exit_horizons_trading_days"]), {5, 20})
        self.assertEqual(metric_plan["net_return_field"], "t1_net")
        self.assertEqual(frozen_design["production_version"], "v7.10")
        self.assertEqual(frozen_design["cohort_window"]["cohort_count"], 24)

    def test_integrity_checks_cover_user_requested_five_reviews(self) -> None:
        checks = {item["check_id"]: item for item in self._load_artifact()["integrity_checks"]}

        self.assertEqual(
            set(checks),
            {
                "multiple_testing_adjustment",
                "time_cross_section_distribution_regime_slices",
                "factor_exposure_check",
                "veto_filter_effect_check",
                "survivorship_pit_check",
            },
        )
        for check in checks.values():
            self.assertTrue(check["required_before_conclusion"])
            self.assertGreater(len(check["plan"]), 20)

    def test_decision_policy_keeps_positive_result_candidate_only(self) -> None:
        artifact = self._load_artifact()
        decision = artifact["decision_policy"]
        decisive_question = artifact["decisive_question"]
        prohibited = artifact["prohibited_claims"]

        self.assertEqual(decisive_question["if_corrected_5d_signal_disappears"], "falsified_or_risk_filter_only")
        self.assertEqual(
            decisive_question["if_corrected_5d_signal_survives"],
            "candidate_alpha_only_requires_deep_validation_and_forward_live",
        )
        self.assertFalse(decisive_question["full_size_claim_if_survives_allowed"])
        self.assertEqual(decision["ship_gate_forward_live_months_required"], 12)
        self.assertFalse(decision["backtest_can_authorize_full_size"])
        self.assertTrue(any("candidate alpha clue" in item for item in decision["candidate_alpha_not_full_size"]))
        self.assertTrue(any("risk-control" in item for item in decision["risk_filter_only"]))
        self.assertTrue(any("No production promotion" in item for item in decision["falsified"]))
        self.assertTrue(all(value is False for value in prohibited.values()))

    def test_planned_budget_requires_review_and_later_execute(self) -> None:
        artifact = self._load_artifact()
        budget = artifact["planned_test_budget"]
        ledger = self._load_ledger()
        planned = ledger["planned_tests"][0]

        self.assertEqual(budget["ledger_ref"], str(LEDGER_ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(budget["planned_test_id"], "a_short_steady_alpha_reaudit_20260603")
        self.assertFalse(budget["outcome_run_authorized_now"])
        self.assertTrue(budget["requires_claude_review_before_run"])
        self.assertTrue(budget["requires_user_execute_before_run"])

        self.assertEqual(ledger["lane_id"], "a_short_steady")
        self.assertEqual(ledger["ledger_status"], "active_planned_test_pending_review")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(ledger["test_spend_log"], [])
        self.assertEqual(len(ledger["planned_tests"]), 1)
        self.assertEqual(planned["planned_status"], "planned_not_reviewed")
        self.assertEqual(planned["approval_status"], "pending_user_approval")
        self.assertEqual(planned["planned_preregistration_ref"], str(ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(planned["expected_tests_spent"], 1)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["outcome_run_allowed_by_this_artifact"] = True
        invalid["scope"]["data_fetch_allowed"] = True
        invalid["scope"]["runner_change_allowed"] = True
        invalid["scope"]["ship_gate_claim_allowed"] = True
        invalid["frozen_design"]["freeze_controls"]["parameter_search_allowed"] = True
        invalid["metric_plan"]["benchmark_leg"] = "benchmark_close_to_close"
        invalid["prohibited_claims"]["validated_alpha"] = True

        errors = list(Draft7Validator(self._load_schema()).iter_errors(invalid))

        self.assertNotEqual(errors, [])

    def test_ledger_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = copy.deepcopy(self._load_ledger())
        invalid["budget_policy"]["ledger_cardinality"] = "per_hypothesis"
        invalid["budget_policy"]["next_test_requires_reviewed_preregistration"] = False
        invalid["budget_policy"]["next_test_requires_user_approval"] = False
        invalid["planned_tests"][0]["promotion_relevant"] = False

        errors = list(Draft7Validator(self._load_ledger_schema()).iter_errors(invalid))

        self.assertNotEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
