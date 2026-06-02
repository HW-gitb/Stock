from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/datahub_local_resource_budget.schema.json")
ARTIFACT_PATH = Path("docs/datahub_local_resource_budget_contract_20260602.json")


class DataHubLocalResourceBudgetSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_artifact(self) -> dict:
        return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

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
        self.assertEqual(schema["properties"]["schema_name"]["const"], "datahub_local_resource_budget")
        self.assertIn("local-machine-safe", schema["description"])
        self.assertIn("does not fetch data", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_default_mode_is_single_slice_incremental_and_not_whole_system(self) -> None:
        artifact = self._load_artifact()
        principles = artifact["local_execution_principles"]
        partition_axes = set(artifact["partition_axes"])

        self.assertEqual(principles["default_run_mode"], "single_slice_incremental")
        self.assertTrue(principles["one_market_default"])
        self.assertTrue(principles["one_lane_default"])
        self.assertTrue(principles["lazy_load_required"])
        self.assertTrue(principles["incremental_cache_reuse_required"])
        self.assertFalse(principles["whole_system_run_default_allowed"])
        self.assertFalse(principles["full_market_refresh_default_allowed"])
        self.assertFalse(principles["all_markets_all_lanes_parallel_default_allowed"])
        self.assertEqual(
            partition_axes,
            {"market", "lane", "as_of_date", "date_window", "provider_family", "artifact_type"},
        )

    def test_budget_profiles_do_not_authorize_heavy_or_provider_work(self) -> None:
        artifact = self._load_artifact()
        profiles = {item["profile_id"]: item for item in artifact["budget_profiles"]}

        self.assertEqual(set(profiles), {"local_interactive_default", "reviewed_heavy_run_optional"})
        self.assertTrue(profiles["local_interactive_default"]["default_allowed"])
        self.assertFalse(profiles["reviewed_heavy_run_optional"]["default_allowed"])
        self.assertTrue(profiles["reviewed_heavy_run_optional"]["requires_explicit_user_approval"])

        for profile_id, profile in profiles.items():
            with self.subTest(profile_id=profile_id):
                self.assertFalse(profile["allows_whole_system_run"])
                self.assertFalse(profile["allows_full_market_refresh"])
                self.assertFalse(profile["allows_parallel_all_lanes"])
                self.assertFalse(profile["authorizes_provider_calls"])
                self.assertFalse(profile["authorizes_datahub_implementation"])
                self.assertTrue(profile["requires_estimated_rows_and_disk"])
                self.assertTrue(profile["requires_abort_policy"])

    def test_implementation_gates_block_default_full_system_runs(self) -> None:
        artifact = self._load_artifact()
        gates = {item["gate_id"]: item for item in artifact["implementation_gates"]}

        self.assertIn("job_spec_budget_profile", gates)
        self.assertIn("partitioned_reads", gates)
        self.assertIn("lazy_materialization", gates)
        self.assertIn("incremental_resume", gates)
        self.assertIn("heavy_run_explicit_approval", gates)
        for gate_id, gate in gates.items():
            with self.subTest(gate_id=gate_id):
                self.assertTrue(gate["blocks_default_full_system_run"])
                self.assertFalse(gate["authorizes_runner_change"])
                self.assertFalse(gate["authorizes_provider_calls"])
                self.assertFalse(gate["authorizes_phase7c_implementation"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["data_fetch_allowed"] = True
        invalid["scope"]["phase7c_implementation_authorized_by_this_artifact"] = True
        invalid["local_execution_principles"]["whole_system_run_default_allowed"] = True
        invalid["budget_profiles"][0]["authorizes_provider_calls"] = True
        invalid["implementation_gates"][0]["authorizes_phase7c_implementation"] = True
        invalid["prohibited_actions"]["all_systems_default_run"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
