from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


CONTRACTS = {
    "quality": (
        Path("schemas/datahub_data_quality_monitor_contract.schema.json"),
        Path("docs/datahub_data_quality_monitor_contract_20260603.json"),
    ),
    "read_path": (
        Path("schemas/datahub_minimal_a_share_read_path_plan.schema.json"),
        Path("docs/datahub_minimal_a_share_read_path_plan_20260603.json"),
    ),
}


class DataHubQualityAndReadPathContractsTest(unittest.TestCase):
    def _load_schema(self, key: str) -> dict:
        return json.loads(CONTRACTS[key][0].read_text(encoding="utf-8"))

    def _load_artifact(self, key: str) -> dict:
        return json.loads(CONTRACTS[key][1].read_text(encoding="utf-8"))

    def _validate(self, key: str, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema(key)).iter_errors(payload))

    def test_schemas_are_strict_and_meta_valid(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        for key in CONTRACTS:
            with self.subTest(key=key):
                schema = self._load_schema(key)
                Draft7Validator.check_schema(schema)
                self.assertFalse(schema["additionalProperties"])
                self.assertIn("schema-first", schema["description"])

    def test_artifacts_validate(self) -> None:
        for key in CONTRACTS:
            with self.subTest(key=key):
                self.assertEqual(self._validate(key, self._load_artifact(key)), [])

    def test_quality_monitor_blocks_silent_green_and_covers_required_dimensions(self) -> None:
        artifact = self._load_artifact("quality")
        dimensions = {item["dimension_id"]: item for item in artifact["monitor_dimensions"]}
        policy = artifact["action_policy"]
        gates = artifact["implementation_gates"]

        self.assertEqual(
            set(dimensions),
            {
                "coverage",
                "freshness",
                "schema_drift",
                "pit_asof_integrity",
                "survivorship_security_master",
                "corporate_actions_revisions",
                "calendar_timezone",
                "provider_incident_quota",
                "outlier_revision_rate",
            },
        )
        self.assertFalse(policy["silent_green_allowed"])
        self.assertTrue(policy["missing_monitor_result_blocks_production"])
        self.assertTrue(policy["monitor_failure_blocks_ship_gate_claim"])
        self.assertTrue(gates["job_spec_helper_must_pass_before_monitor_run"])
        self.assertTrue(gates["provider_readiness_required_before_provider_backed_monitoring"])
        for dimension in dimensions.values():
            self.assertFalse(dimension["silent_pass_allowed"])
            self.assertEqual(dimension["implementation_status"], "not_implemented_contract_only")
        for value in artifact["prohibited_claims"].values():
            self.assertFalse(value)

    def test_minimal_a_share_read_path_is_local_cache_only_and_non_executable(self) -> None:
        artifact = self._load_artifact("read_path")
        scope = artifact["scope"]
        boundary = artifact["future_job_boundary"]
        gates = artifact["pre_execution_gates"]
        forbidden = artifact["forbidden_scope"]

        self.assertEqual(boundary["market"], "A")
        self.assertEqual(boundary["lane"], "a_short")
        self.assertEqual(boundary["provider_family"], "local_cache")
        self.assertEqual(boundary["read_mode"], "read_existing_local_cache_or_fixture_only")
        self.assertEqual(boundary["max_calendar_days"], 1)
        self.assertTrue(boundary["job_spec_helper_required"])
        self.assertTrue(boundary["manifest_required"])
        self.assertTrue(boundary["data_quality_summary_required"])
        self.assertFalse(scope["implementation_allowed_by_this_artifact"])
        self.assertFalse(scope["job_execution_allowed"])
        self.assertFalse(scope["provider_call_allowed"])
        self.assertFalse(scope["tushare_call_allowed"])
        self.assertFalse(scope["datahub_table_creation_allowed"])
        self.assertFalse(scope["a_egs_change_allowed"])
        self.assertTrue(gates["separate_user_execute_required"])
        self.assertTrue(gates["independent_review_pass_required"])
        self.assertTrue(gates["job_spec_helper_pass_required"])
        for value in forbidden.values():
            self.assertFalse(value)
        for item in artifact["allowed_inputs"] + artifact["allowed_outputs"]:
            self.assertFalse(item["contains_secret_or_raw_payload"])

    def test_scope_creep_is_rejected(self) -> None:
        cases: list[tuple[str, dict]] = []

        quality = copy.deepcopy(self._load_artifact("quality"))
        quality["scope"]["monitor_implementation_allowed"] = True
        quality["action_policy"]["silent_green_allowed"] = True
        quality["prohibited_claims"]["monitor_run_executed"] = True
        cases.append(("quality", quality))

        read_path = copy.deepcopy(self._load_artifact("read_path"))
        read_path["scope"]["tushare_call_allowed"] = True
        read_path["future_job_boundary"]["provider_family"] = "tushare"
        read_path["forbidden_scope"]["datahub_table_creation"] = True
        cases.append(("read_path", read_path))

        for key, payload in cases:
            with self.subTest(key=key):
                self.assertNotEqual(self._validate(key, payload), [])


if __name__ == "__main__":
    unittest.main()
