from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/datahub_job_spec.schema.json")
EXAMPLE_PATH = Path("schemas/examples/datahub_job_spec.example.json")


class DataHubJobSpecSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_example(self) -> dict:
        return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "datahub_job_spec")
        self.assertIn("does not fetch data", schema["description"])
        self.assertIn("minimum job-spec shape", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_example_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_example()), [])

    def test_example_is_schema_only_and_does_not_authorize_runtime_work(self) -> None:
        example = self._load_example()
        scope = example["scope"]
        job_identity = example["job_identity"]
        prohibited = example["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "schema_first_job_spec_contract_no_runtime_enforcement")
        self.assertEqual(job_identity["job_kind"], "schema_validation_only")
        self.assertEqual(job_identity["job_spec_status"], "schema_example_not_executable")
        self.assertEqual(job_identity["review_status"], "schema_example")
        for field in [
            "data_fetch_allowed",
            "provider_call_allowed",
            "provider_selection_allowed",
            "new_token_or_paid_access_allowed",
            "datahub_table_implementation_allowed",
            "runner_change_allowed",
            "phase7c_implementation_authorized_by_this_artifact",
            "broker_or_order_automation_allowed",
            "ship_gate_claim_allowed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for value in prohibited.values():
            self.assertFalse(value)

    def test_budget_profile_uses_local_default_without_heavy_approval(self) -> None:
        profile = self._load_example()["budget_profile"]

        self.assertEqual(profile["profile_id"], "local_interactive_default")
        self.assertEqual(
            profile["profile_source_ref"],
            "docs/datahub_local_resource_budget_contract_20260602.json",
        )
        self.assertFalse(profile["requires_explicit_user_approval"])
        self.assertFalse(profile["explicit_user_approval_recorded"])
        self.assertIsNone(profile["approval_ref"])
        self.assertTrue(profile["reviewed_job_spec_required"])
        self.assertTrue(profile["profile_must_match_resource_budget_contract"])
        self.assertFalse(profile["authorizes_provider_calls"])
        self.assertFalse(profile["authorizes_datahub_implementation"])
        self.assertFalse(profile["authorizes_runner_change"])

    def test_partition_scope_is_one_market_one_lane_bounded_date_window(self) -> None:
        partition = self._load_example()["partition_scope"]

        self.assertEqual(partition["market"], "A")
        self.assertEqual(partition["lane"], "a_short")
        self.assertEqual(partition["as_of_date"], "20260602")
        self.assertEqual(partition["date_window"]["window_role"], "single_as_of")
        self.assertEqual(partition["date_window"]["start_date"], "20260602")
        self.assertEqual(partition["date_window"]["end_date"], "20260602")
        self.assertEqual(partition["date_window"]["max_calendar_days"], 1)
        self.assertEqual(partition["provider_family"], "none")
        self.assertFalse(partition["full_market_refresh_requested"])
        self.assertFalse(partition["all_markets_requested"])
        self.assertFalse(partition["all_lanes_requested"])
        self.assertFalse(partition["full_history_rebuild_requested"])

    def test_resource_and_execution_policies_are_declared_and_bounded(self) -> None:
        example = self._load_example()
        estimate = example["resource_estimate"]
        execution = example["execution_policy"]
        checkpoint = example["checkpoint_policy"]

        self.assertLessEqual(estimate["estimated_input_rows"], 1)
        self.assertLessEqual(estimate["estimated_output_rows"], 1)
        self.assertLessEqual(estimate["max_runtime_minutes"], 1)
        self.assertLessEqual(estimate["max_memory_mb"], 64)
        self.assertTrue(execution["lazy_load_required"])
        self.assertTrue(execution["incremental_cache_reuse_required"])
        self.assertTrue(execution["checkpoint_required"])
        self.assertTrue(execution["abort_policy_required"])
        self.assertFalse(execution["full_market_refresh_allowed"])
        self.assertFalse(execution["all_markets_all_lanes_allowed"])
        self.assertFalse(execution["provider_calls_allowed"])
        self.assertFalse(execution["raw_payload_write_allowed"])
        self.assertFalse(execution["production_runner_consumption_allowed"])
        self.assertTrue(checkpoint["resume_supported"])
        self.assertTrue(checkpoint["idempotent"])
        self.assertTrue(checkpoint["abort_on_budget_exceed"])

    def test_gates_block_heavy_or_broader_work_without_authorizing_anything(self) -> None:
        gates = {item["gate_id"]: item for item in self._load_example()["approval_gates"]}

        self.assertIn("budget_profile_declared", gates)
        self.assertIn("single_slice_partition_declared", gates)
        self.assertIn("resource_estimate_declared", gates)
        self.assertIn("heavy_run_approval", gates)
        self.assertTrue(gates["heavy_run_approval"]["blocks_execution"])
        for gate_id, gate in gates.items():
            with self.subTest(gate_id=gate_id):
                self.assertFalse(gate["authorizes_data_fetch"])
                self.assertFalse(gate["authorizes_provider_call"])
                self.assertFalse(gate["authorizes_datahub_implementation"])
                self.assertFalse(gate["authorizes_runner_change"])
                self.assertFalse(gate["authorizes_phase7c"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        cases: dict[str, dict] = {}

        provider_call = copy.deepcopy(self._load_example())
        provider_call["scope"]["provider_call_allowed"] = True
        cases["scope_provider_call"] = provider_call

        heavy_without_approval = copy.deepcopy(self._load_example())
        heavy_without_approval["budget_profile"]["profile_id"] = "reviewed_heavy_run_optional"
        heavy_without_approval["budget_profile"]["requires_explicit_user_approval"] = True
        heavy_without_approval["budget_profile"]["explicit_user_approval_recorded"] = False
        heavy_without_approval["budget_profile"]["approval_ref"] = None
        cases["heavy_profile_without_recorded_approval"] = heavy_without_approval

        all_markets = copy.deepcopy(self._load_example())
        all_markets["partition_scope"]["all_markets_requested"] = True
        cases["all_markets_requested"] = all_markets

        all_lanes_execution = copy.deepcopy(self._load_example())
        all_lanes_execution["execution_policy"]["all_markets_all_lanes_allowed"] = True
        cases["all_lanes_execution"] = all_lanes_execution

        prohibited_action = copy.deepcopy(self._load_example())
        prohibited_action["prohibited_actions"]["datahub_table_creation"] = True
        cases["prohibited_datahub_table_creation"] = prohibited_action

        negative_estimate = copy.deepcopy(self._load_example())
        negative_estimate["resource_estimate"]["estimated_output_rows"] = -1
        cases["negative_resource_estimate"] = negative_estimate

        for case_name, payload in cases.items():
            with self.subTest(case_name=case_name):
                self.assertNotEqual(self._validate(payload), [])


if __name__ == "__main__":
    unittest.main()
