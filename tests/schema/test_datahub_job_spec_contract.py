from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from engine.datahub.job_spec_contract import (
    DataHubJobSpecContractError,
    validate_datahub_job_spec_contract,
    validate_datahub_job_spec_file,
)


EXAMPLE_PATH = Path("schemas/examples/datahub_job_spec.example.json")


class DataHubJobSpecContractTest(unittest.TestCase):
    def _load_example(self) -> dict:
        return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    def test_example_file_passes_runtime_contract(self) -> None:
        payload = validate_datahub_job_spec_file(EXAMPLE_PATH)

        self.assertEqual(payload["schema_name"], "datahub_job_spec")

    def test_reviewed_executable_single_slice_can_pass_when_no_gate_blocks(self) -> None:
        payload = self._load_example()
        payload["job_identity"]["job_spec_status"] = "reviewed_executable_plan"
        payload["job_identity"]["review_status"] = "reviewed"
        for gate in payload["approval_gates"]:
            gate["status"] = "satisfied_for_schema_example"
            gate["blocks_execution"] = False

        validate_datahub_job_spec_contract(payload)

    def test_heavy_profile_requires_recorded_approval_and_gate(self) -> None:
        payload = self._load_example()
        payload["budget_profile"]["profile_id"] = "reviewed_heavy_run_optional"
        payload["budget_profile"]["requires_explicit_user_approval"] = True
        payload["budget_profile"]["explicit_user_approval_recorded"] = False
        payload["budget_profile"]["approval_ref"] = None

        with self.assertRaisesRegex(DataHubJobSpecContractError, "schema validation failed"):
            validate_datahub_job_spec_contract(payload)

        payload["budget_profile"]["explicit_user_approval_recorded"] = True
        payload["budget_profile"]["approval_ref"] = "docs/reviewed_heavy_run_approval.json"
        for gate in payload["approval_gates"]:
            if gate["gate_id"] == "heavy_run_approval":
                gate["gate_id"] = "renamed_heavy_gate"

        with self.assertRaisesRegex(DataHubJobSpecContractError, "heavy profile requires a heavy_run_approval"):
            validate_datahub_job_spec_contract(payload)

    def test_profile_must_match_resource_budget_contract(self) -> None:
        payload = self._load_example()
        resource_budget = json.loads(
            Path("docs/datahub_local_resource_budget_contract_20260602.json").read_text(encoding="utf-8")
        )
        resource_budget["budget_profiles"][0]["requires_explicit_user_approval"] = True
        temp_path = Path("tests") / "_tmp_profile_mismatch_resource_budget.json"
        try:
            temp_path.write_text(json.dumps(resource_budget), encoding="utf-8")

            with self.assertRaisesRegex(DataHubJobSpecContractError, "does not match resource budget"):
                validate_datahub_job_spec_contract(payload, resource_budget_path=temp_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_rejects_market_lane_mismatch_at_runtime_boundary(self) -> None:
        payload = self._load_example()
        payload["partition_scope"]["market"] = "A"
        payload["partition_scope"]["lane"] = "us_short"

        with self.assertRaisesRegex(DataHubJobSpecContractError, "schema validation failed"):
            validate_datahub_job_spec_contract(payload)

    def test_rejects_as_of_outside_date_window(self) -> None:
        payload = self._load_example()
        payload["partition_scope"]["date_window"]["start_date"] = "20260601"
        payload["partition_scope"]["date_window"]["end_date"] = "20260601"
        payload["partition_scope"]["date_window"]["max_calendar_days"] = 1

        with self.assertRaisesRegex(DataHubJobSpecContractError, "as_of_date must be inside date_window"):
            validate_datahub_job_spec_contract(payload)

    def test_rejects_window_that_exceeds_declared_calendar_days(self) -> None:
        payload = self._load_example()
        payload["partition_scope"]["as_of_date"] = "20260603"
        payload["partition_scope"]["date_window"]["start_date"] = "20260601"
        payload["partition_scope"]["date_window"]["end_date"] = "20260603"
        payload["partition_scope"]["date_window"]["window_role"] = "bounded_history_slice"
        payload["partition_scope"]["date_window"]["max_calendar_days"] = 2

        with self.assertRaisesRegex(DataHubJobSpecContractError, "spans 3 days"):
            validate_datahub_job_spec_contract(payload)

    def test_single_as_of_must_be_exact_single_day(self) -> None:
        payload = self._load_example()
        payload["partition_scope"]["date_window"]["max_calendar_days"] = 2

        with self.assertRaisesRegex(DataHubJobSpecContractError, "single_as_of"):
            validate_datahub_job_spec_contract(payload)

    def test_reviewed_executable_jobs_cannot_have_blocking_gates(self) -> None:
        payload = self._load_example()
        payload["job_identity"]["job_spec_status"] = "reviewed_executable_plan"
        payload["job_identity"]["review_status"] = "reviewed"

        with self.assertRaisesRegex(DataHubJobSpecContractError, "blocking gates"):
            validate_datahub_job_spec_contract(payload)

    def test_rejects_any_scope_creep_even_if_schema_is_not_relaxed(self) -> None:
        cases = {}

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
            payload = self._load_example()
            payload["scope"][field] = True
            cases[f"scope_{field}"] = payload

        for field in [
            "provider_call",
            "provider_selection",
            "new_token_or_paid_access",
            "full_market_download",
            "raw_payload_parse",
            "datahub_table_creation",
            "runner_or_adapter_change",
            "production_runner_consumption",
            "all_systems_default_run",
            "parallel_all_lanes_default",
            "ship_gate_claim",
            "broker_or_order_automation",
        ]:
            payload = self._load_example()
            payload["prohibited_actions"][field] = True
            cases[f"prohibited_{field}"] = payload

        for field in [
            "full_market_refresh_allowed",
            "all_markets_all_lanes_allowed",
            "provider_calls_allowed",
            "raw_payload_write_allowed",
            "production_runner_consumption_allowed",
        ]:
            payload = self._load_example()
            payload["execution_policy"][field] = True
            cases[f"execution_{field}"] = payload

        for case_name, payload in cases.items():
            with self.subTest(case_name=case_name):
                with self.assertRaises(DataHubJobSpecContractError):
                    validate_datahub_job_spec_contract(payload)

    def test_resource_budget_contract_must_keep_lane_concurrency_bound(self) -> None:
        resource_budget = json.loads(
            Path("docs/datahub_local_resource_budget_contract_20260602.json").read_text(encoding="utf-8")
        )
        resource_budget["budget_profiles"][1]["max_concurrent_lanes"] = 3
        temp_path = Path("tests") / "_tmp_invalid_resource_budget.json"
        try:
            temp_path.write_text(json.dumps(resource_budget), encoding="utf-8")
            with self.assertRaisesRegex(DataHubJobSpecContractError, "resource budget"):
                validate_datahub_job_spec_contract(self._load_example(), resource_budget_path=temp_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_payload_is_not_mutated_by_validation(self) -> None:
        payload = self._load_example()
        before = copy.deepcopy(payload)

        validate_datahub_job_spec_contract(payload)

        self.assertEqual(payload, before)


if __name__ == "__main__":
    unittest.main()
