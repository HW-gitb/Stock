from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_access_decision_plan.schema.json")
PLAN_PATH = Path("docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json")
MATRIX_PATH = Path("docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json")


class ProviderP1AccessDecisionPlanSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_plan(self) -> dict:
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    def _load_matrix(self) -> dict:
        return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "provider_p1_access_decision_plan")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("does not select providers", schema["description"])
        self.assertIn("request tokens or trials", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_plan_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        errors = list(Draft7Validator(self._load_schema()).iter_errors(self._load_plan()))

        self.assertEqual(errors, [])

    def test_scope_locks_plan_to_non_authorizing_access_boundary(self) -> None:
        plan = self._load_plan()
        scope = plan["scope"]
        boundary = plan["decision_boundary"]

        self.assertEqual(scope["purpose"], "p1_access_decision_and_sample_validation_plan")
        self.assertEqual(scope["plan_status"], "plan_only_no_access_requested")
        self.assertEqual(
            scope["based_on_readiness_matrix_ref"],
            "docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json",
        )
        self.assertFalse(scope["provider_selection_allowed"])
        self.assertFalse(scope["provider_ranking_allowed"])
        self.assertFalse(scope["provider_contact_or_account_creation_allowed"])
        self.assertFalse(scope["trial_or_token_request_allowed"])
        self.assertFalse(scope["paid_access_approved"])
        self.assertFalse(scope["sample_row_collection_allowed"])
        self.assertFalse(scope["data_fetch_allowed"])
        self.assertFalse(scope["provider_adapter_allowed"])
        self.assertFalse(scope["datahub_table_implementation_allowed"])
        self.assertFalse(scope["runner_change_allowed"])
        self.assertFalse(scope["phase7c_authorized_by_this_artifact"])
        self.assertTrue(scope["manual_order_only"])
        self.assertFalse(scope["ship_gate_relaxed"])
        self.assertFalse(scope["production_ready_claim_allowed"])
        self.assertEqual(boundary["cost_ceiling_status"], "pending_user_approval")
        self.assertEqual(boundary["approved_spend_usd"], 0)
        self.assertFalse(boundary["token_trial_paid_request_allowed"])
        self.assertFalse(boundary["sample_collection_allowed"])

    def test_candidate_queue_matches_readiness_matrix_without_ranking_or_selection(self) -> None:
        plan = self._load_plan()
        matrix = self._load_matrix()
        plan_candidates = {
            item["provider_candidate_id"]: item for item in plan["candidate_access_queue"]
        }
        matrix_candidates = {
            item["provider_candidate_id"]: item for item in matrix["provider_candidate_rollup"]
        }

        self.assertEqual(set(plan_candidates), set(matrix_candidates))
        for candidate_id, item in plan_candidates.items():
            with self.subTest(candidate_id=candidate_id):
                self.assertEqual(
                    item["candidate_evidence_grade"],
                    matrix_candidates[candidate_id]["candidate_evidence_grade"],
                )
                self.assertEqual(
                    set(item["useful_for_area_ids"]),
                    set(matrix_candidates[candidate_id]["useful_for_area_ids"]),
                )
                self.assertFalse(item["provider_selection_made"])
                self.assertFalse(item["provider_ranking_made"])
                self.assertFalse(item["access_request_allowed_by_this_plan"])
                self.assertFalse(item["paid_access_approved_by_this_plan"])
                self.assertTrue(item["sample_validation_required"])
                self.assertEqual(item["planned_review_status"], "plan_only_pending_user_boundary")

    def test_sample_workstreams_cover_matrix_area_ids_and_do_not_collect_rows(self) -> None:
        plan = self._load_plan()
        matrix = self._load_matrix()
        workstreams = {item["area_id"]: item for item in plan["sample_validation_workstreams"]}
        matrix_areas = {item["area_id"] for item in matrix["review_dimensions"]}

        self.assertEqual(set(workstreams), matrix_areas)
        self.assertTrue(
            all(
                item["validation_status"] == "planned_not_executed"
                and not item["collection_allowed_by_this_plan"]
                and not item["provider_selection_made"]
                and item["blocking_if_missing"]
                for item in workstreams.values()
            )
        )
        self.assertIn("fundamentals_observed_date_pit", workstreams)
        self.assertTrue(
            any(
                "accepted date" in text.lower()
                for text in workstreams["fundamentals_observed_date_pit"][
                    "required_sample_or_doc_items"
                ]
            )
        )
        self.assertTrue(
            any(
                "no-zero-fill" in text
                for text in workstreams["benchmark_returns"]["pass_criteria_for_later_review"]
            )
        )

    def test_decision_gates_block_access_data_fetch_and_phase7c(self) -> None:
        plan = self._load_plan()
        gates = {item["gate_id"]: item for item in plan["decision_gates"]}

        self.assertEqual(
            set(gates),
            {
                "user_cost_access_boundary",
                "license_storage_rights",
                "sample_validation_packet",
                "phase7c_authorization",
            },
        )
        self.assertEqual(gates["user_cost_access_boundary"]["status"], "pending_user_approval")
        self.assertEqual(gates["phase7c_authorization"]["status"], "blocked")
        self.assertTrue(all(item["blocks_until_resolved"] for item in gates.values()))
        self.assertFalse(any(item["authorizes_provider_selection"] for item in gates.values()))
        self.assertFalse(any(item["authorizes_data_fetch"] for item in gates.values()))
        self.assertFalse(any(item["authorizes_phase7c"] for item in gates.values()))

    def test_plan_routes_next_alpha_slice_without_turning_sec_parser_into_alpha_validation(self) -> None:
        plan = self._load_plan()
        joined_next_steps = "\n".join(plan["next_steps"])
        joined_limitations = "\n".join(plan["limitations"])

        self.assertIn("A-share minimal-data burst", joined_next_steps)
        self.assertIn("valid_signal_events = 0", joined_next_steps)
        self.assertIn("same-anchor benchmark excess", joined_next_steps)
        self.assertIn("corrected-basis supersession", joined_next_steps)
        self.assertIn("research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json", joined_next_steps)
        self.assertIn("provider-evidence track", joined_next_steps)
        self.assertIn("not long-alpha existence", joined_next_steps)
        self.assertIn("does not perform new web research", joined_limitations)
        self.assertIn("Candidate access queue ordering is a validation planning queue", joined_limitations)

    def test_authorization_change_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = copy.deepcopy(self._load_plan())
        invalid["scope"]["trial_or_token_request_allowed"] = True
        invalid["scope"]["data_fetch_allowed"] = True
        invalid["decision_boundary"]["approved_spend_usd"] = 100
        invalid["candidate_access_queue"][0]["access_request_allowed_by_this_plan"] = True

        errors = list(Draft7Validator(self._load_schema()).iter_errors(invalid))

        self.assertNotEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
