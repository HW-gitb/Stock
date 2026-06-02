from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_sample_validation_access_approval.schema.json")
APPROVAL_PATH = Path("docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json")
PLAN_PATH = Path("docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json")


class ProviderP1SampleValidationAccessApprovalSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_approval(self) -> dict:
        return json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))

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
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "provider_p1_sample_validation_access_approval",
        )
        self.assertIn("zero-dollar budget", schema["description"])
        self.assertIn("does not select a provider", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_approval_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_approval()), [])

    def test_boundary_allows_only_existing_fmp_key_and_sec_small_sample(self) -> None:
        approval = self._load_approval()
        boundary = approval["approval_boundary"]
        universe = approval["sample_universe"]
        storage = approval["storage_and_secret_boundary"]
        roles = {
            item["provider_id"]: item["allowed_in_sample_validation"]
            for item in approval["provider_roles"]
        }

        self.assertEqual(boundary["approved_spend_usd"], 0)
        self.assertTrue(boundary["fmp_existing_api_key_use_allowed"])
        self.assertTrue(boundary["sec_edgar_public_api_allowed"])
        self.assertFalse(boundary["paid_access_allowed"])
        self.assertFalse(boundary["fmp_new_token_request_allowed"])
        self.assertFalse(boundary["fmp_trial_request_allowed"])
        self.assertFalse(boundary["yfinance_allowed"])
        self.assertFalse(boundary["full_market_download_allowed"])
        self.assertFalse(boundary["provider_selection_allowed"])
        self.assertFalse(boundary["datahub_table_implementation_allowed"])
        self.assertEqual(universe["allowed_symbols"], ["AAPL", "MSFT"])
        self.assertEqual(universe["max_symbols"], 2)
        self.assertLessEqual(universe["max_total_endpoint_calls"], 40)
        self.assertEqual(roles, {
            "financial_modeling_prep": True,
            "sec_edgar": True,
            "yfinance": False,
        })
        self.assertEqual(
            storage["raw_sample_storage_path"],
            "provider_samples/us_egs_sample_validation_20260602/",
        )
        self.assertTrue(storage["raw_sample_storage_must_be_gitignored"])
        self.assertFalse(storage["secrets_in_repo_allowed"])
        self.assertFalse(storage["api_key_logging_allowed"])

    def test_schema_locks_boundary_without_jsonschema(self) -> None:
        schema = self._load_schema()
        boundary_schema = schema["properties"]["approval_boundary"]["properties"]
        scope_schema = schema["properties"]["scope"]["properties"]
        storage_schema = schema["properties"]["storage_and_secret_boundary"]["properties"]

        self.assertEqual(boundary_schema["approved_spend_usd"]["const"], 0)
        self.assertTrue(boundary_schema["fmp_existing_api_key_use_allowed"]["const"])
        self.assertTrue(boundary_schema["sec_edgar_public_api_allowed"]["const"])
        for field in [
            "fmp_new_token_request_allowed",
            "fmp_trial_request_allowed",
            "paid_access_allowed",
            "yfinance_allowed",
            "full_market_download_allowed",
            "provider_selection_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "runner_change_allowed",
        ]:
            self.assertFalse(boundary_schema[field]["const"], field)

        self.assertFalse(scope_schema["phase7c_authorized_by_this_artifact"]["const"])
        self.assertFalse(scope_schema["ship_gate_relaxed"]["const"])
        self.assertFalse(scope_schema["production_ready_claim_allowed"]["const"])
        self.assertFalse(storage_schema["secrets_in_repo_allowed"]["const"])
        self.assertFalse(storage_schema["api_key_logging_allowed"]["const"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_approval())
        invalid["approval_boundary"]["paid_access_allowed"] = True
        invalid["approval_boundary"]["full_market_download_allowed"] = True
        invalid["approval_boundary"]["yfinance_allowed"] = True
        invalid["sample_universe"]["allowed_symbols"].append("TSLA")
        invalid["sample_universe"]["max_symbols"] = 3
        invalid["storage_and_secret_boundary"]["secrets_in_repo_allowed"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_original_access_plan_remains_non_authorizing(self) -> None:
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

        self.assertFalse(plan["scope"]["sample_row_collection_allowed"])
        self.assertFalse(plan["scope"]["data_fetch_allowed"])
        self.assertFalse(plan["decision_boundary"]["sample_collection_allowed"])
        self.assertEqual(plan["decision_boundary"]["approved_spend_usd"], 0)

    def test_next_steps_do_not_authorize_phase7c_or_provider_selection(self) -> None:
        approval = self._load_approval()
        joined_next = "\n".join(approval["next_steps"])
        joined_limits = "\n".join(approval["limitations"])
        joined_prohibited = "\n".join(approval["prohibited_actions"])

        self.assertIn("AAPL / MSFT", joined_next)
        self.assertIn("environment variable presence without printing secrets", joined_next)
        self.assertIn("raw provider samples only under the gitignored provider_samples path", joined_next)
        self.assertIn("before any provider selection", joined_next)
        self.assertIn("does not authorize yfinance", joined_limits)
        self.assertIn("Do not use yfinance", joined_prohibited)
        self.assertIn("Do not download the full US market", joined_prohibited)


if __name__ == "__main__":
    unittest.main()
