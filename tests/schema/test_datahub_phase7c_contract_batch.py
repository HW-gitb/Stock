from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


CONTRACTS = {
    "shared": (
        Path("schemas/datahub_shared_layer_contract.schema.json"),
        Path("docs/datahub_shared_layer_contract_20260603.json"),
    ),
    "report": (
        Path("schemas/datahub_report_contract.schema.json"),
        Path("docs/datahub_report_contract_20260603.json"),
    ),
    "manifest": (
        Path("schemas/datahub_reproducibility_manifest.schema.json"),
        Path("docs/datahub_reproducibility_manifest_contract_20260603.json"),
    ),
}


class DataHubPhase7cContractBatchTest(unittest.TestCase):
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
                self.assertIn("schema-first contract", schema["description"])

    def test_artifacts_validate(self) -> None:
        for key in CONTRACTS:
            with self.subTest(key=key):
                self.assertEqual(self._validate(key, self._load_artifact(key)), [])

    def test_shared_layer_contract_covers_all_layers_without_authorizing_implementation(self) -> None:
        artifact = self._load_artifact("shared")
        scope = artifact["scope"]
        layers = {item["layer_id"]: item for item in artifact["layer_contracts"]}
        gates = artifact["implementation_gates"]

        self.assertEqual(set(layers), {"ods", "dwd", "dws", "factor"})
        self.assertEqual(scope["contract_status"], "schema_first_no_table_implementation")
        self.assertTrue(scope["schema_first_only"])
        self.assertTrue(gates["job_spec_helper_must_run_before_execution"])
        self.assertTrue(gates["sr_provider_001_must_be_closed_or_explicitly_accepted"])
        for field in [
            "data_fetch_allowed",
            "provider_call_allowed",
            "provider_selection_allowed",
            "datahub_table_implementation_allowed",
            "runner_change_allowed",
            "production_runner_consumption_allowed",
            "phase7c_implementation_authorized",
            "ship_gate_evidence_allowed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for layer in layers.values():
            self.assertEqual(layer["implementation_status"], "not_implemented_contract_only")

    def test_report_contract_keeps_plain_results_but_blocks_overclaims(self) -> None:
        artifact = self._load_artifact("report")
        families = {item["family_id"]: item for item in artifact["report_families"]}
        policy = artifact["report_output_policy"]
        evidence = artifact["decision_evidence_policy"]

        self.assertEqual(
            set(families),
            {"screening_report", "evidence_report", "provider_evidence_summary", "data_quality_report"},
        )
        self.assertTrue(policy["human_readable_plain_result_required"])
        self.assertTrue(policy["tracked_outputs_must_be_no_secret"])
        self.assertTrue(policy["tracked_outputs_must_exclude_raw_rows"])
        self.assertTrue(evidence["paper_evidence_is_not_ship_gate"])
        self.assertTrue(evidence["live_normalized_forward_evidence_required_for_ship_gate"])
        for value in artifact["prohibited_claims"].values():
            self.assertFalse(value)
        for family in families.values():
            self.assertEqual(family["implementation_status"], "not_implemented_contract_only")

    def test_reproducibility_manifest_requires_lineage_and_no_secret_outputs(self) -> None:
        artifact = self._load_artifact("manifest")
        manifest = artifact["manifest_requirements"]
        lineage = artifact["lineage_requirements"]
        secret_policy = artifact["secret_and_raw_policy"]
        gates = artifact["execution_gates"]

        self.assertFalse(artifact["scope"]["manifest_writer_implemented"])
        self.assertFalse(artifact["scope"]["job_execution_allowed"])
        self.assertTrue(manifest["job_spec_ref_required"])
        self.assertTrue(manifest["job_spec_validation_result_required"])
        self.assertTrue(manifest["input_artifact_hashes_required"])
        self.assertTrue(lineage["provider_lineage_required"])
        self.assertTrue(lineage["known_limitations_required"])
        self.assertTrue(secret_policy["tracked_manifest_must_be_no_secret"])
        self.assertTrue(secret_policy["tracked_manifest_must_exclude_request_urls"])
        self.assertTrue(secret_policy["tracked_manifest_must_exclude_raw_rows"])
        self.assertTrue(gates["job_spec_helper_must_pass_before_execution"])
        for value in artifact["prohibited_claims"].values():
            self.assertFalse(value)

    def test_scope_creep_is_rejected(self) -> None:
        cases: list[tuple[str, dict]] = []

        shared = copy.deepcopy(self._load_artifact("shared"))
        shared["scope"]["datahub_table_implementation_allowed"] = True
        shared["prohibited_actions"]["datahub_table_creation"] = True
        cases.append(("shared", shared))

        report = copy.deepcopy(self._load_artifact("report"))
        report["scope"]["report_generation_allowed"] = True
        report["prohibited_claims"]["ship_gate_evidence"] = True
        cases.append(("report", report))

        manifest = copy.deepcopy(self._load_artifact("manifest"))
        manifest["scope"]["manifest_writer_implemented"] = True
        manifest["secret_and_raw_policy"]["tracked_manifest_must_exclude_request_urls"] = False
        manifest["prohibited_claims"]["job_executed"] = True
        cases.append(("manifest", manifest))

        for key, payload in cases:
            with self.subTest(key=key):
                self.assertNotEqual(self._validate(key, payload), [])


if __name__ == "__main__":
    unittest.main()
