from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

SCHEMA_PATH = Path("schemas/us_short_batch5_bankruptcy_8k_access_packet.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_bankruptcy_8k_access_packet_20260703.json")


class UsShortBatch5Bankruptcy8kAccessPacketSchemaTest(unittest.TestCase):
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
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "us_short_batch5_bankruptcy_8k_access_packet",
        )
        self.assertIn("bankruptcy 8-K", schema["description"])
        self.assertIn("executes NO SEC call", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_is_offline_boundary_not_live_scan(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertEqual(scope["market"], "US")
        self.assertEqual(scope["lane"], "us_short")
        self.assertEqual(scope["batch"], "batch5_provider_live")
        self.assertEqual(scope["packet_status"], "bankruptcy_8k_access_packet_recorded_for_review_not_executed")
        self.assertFalse(scope["status_source_calls_executed_by_this_artifact"])
        self.assertFalse(scope["raw_payloads_read_by_this_artifact"])
        self.assertFalse(scope["network_access_required_for_this_artifact"])
        self.assertTrue(scope["future_bankruptcy_scan_requires_explicit_user_authorization"])
        self.assertTrue(scope["future_bankruptcy_scan_requires_preflight"])
        self.assertTrue(scope["future_bankruptcy_scan_requires_user_execute"])
        for field in [
            "bankruptcy_8k_calls_allowed_without_future_authorization",
            "full_market_or_per_symbol_fetch_allowed",
            "parser_into_runner_integration_allowed",
            "candidate_artifact_schema_change_allowed",
            "datahub_consumption_allowed",
            "production_storage_allowed",
            "provider_selection_allowed",
            "broker_or_order_automation_allowed",
            "live_normalized_evidence_allowed",
            "ship_gate_evidence_allowed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_boundary_is_exact_small_sample_sec_submissions_budget(self) -> None:
        artifact = self._load_artifact()
        sample = artifact["bankruptcy_8k_scan_boundary"]["sample_universe"]
        budget = artifact["bankruptcy_8k_scan_boundary"]["endpoint_call_budget"]
        families = artifact["bankruptcy_8k_scan_boundary"]["endpoint_families"]

        self.assertEqual(sample["symbols"], ["AAPL", "MSFT", "JPM"])
        self.assertEqual(sample["cik_by_symbol"], {"AAPL": 320193, "MSFT": 789019, "JPM": 19617})
        self.assertEqual(sample["max_symbols"], 3)
        self.assertTrue(sample["shape_validation_only"])
        self.assertTrue(sample["not_full_market_or_security_master"])

        self.assertEqual(budget["max_total_endpoint_calls"], 3)
        self.assertEqual(budget["sec_company_submissions_calls"], 3)
        self.assertEqual(budget["bankruptcy_8k_calls"], 3)
        self.assertEqual(budget["retry_count_allowed"], 0)
        self.assertTrue(budget["abort_if_budget_exceeded"])
        self.assertFalse(budget["budget_authorized_by_this_artifact"])

        self.assertEqual(len(families), 1)
        self.assertEqual(families[0]["source_id"], "sec_8k_item_103")
        self.assertEqual(families[0]["provider_id"], "sec_edgar")
        self.assertEqual(families[0]["endpoint_family"], "company_submissions_recent_filings")
        self.assertEqual(families[0]["call_count"], 3)
        self.assertFalse(families[0]["authorizes_status_call_now"])
        self.assertFalse(families[0]["authorizes_datahub_or_runner_consumption"])

    def test_storage_preflight_and_prohibited_claims_are_locked(self) -> None:
        artifact = self._load_artifact()
        storage = artifact["storage_and_secret_boundary"]

        self.assertEqual(
            storage["future_raw_sample_storage_path"],
            "provider_samples/us_short_batch5_bankruptcy_8k_20260703/",
        )
        self.assertEqual(
            storage["future_tracked_summary_path"],
            "docs/us_short_batch5_bankruptcy_8k_probe_summary_20260703.json",
        )
        self.assertTrue(storage["provider_samples_gitignore_check_required"])
        self.assertTrue(storage["tracked_summary_must_exclude_raw_payloads"])
        self.assertTrue(storage["tracked_summary_must_exclude_request_urls"])
        self.assertTrue(storage["tracked_summary_must_exclude_secrets"])
        self.assertFalse(storage["tracked_summary_write_authorized_by_this_artifact"])
        self.assertFalse(storage["raw_payload_write_authorized_by_this_artifact"])
        self.assertFalse(storage["production_storage_authorized"])

        for field, value in artifact["preflight_gates"].items():
            self.assertTrue(value, field)
        for field, value in artifact["prohibited_claims"].items():
            self.assertFalse(value, field)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["bankruptcy_8k_calls_allowed_without_future_authorization"] = True
        invalid["scope"]["full_market_or_per_symbol_fetch_allowed"] = True
        invalid["scope"]["datahub_consumption_allowed"] = True
        invalid["bankruptcy_8k_scan_boundary"]["sample_universe"]["symbols"].append("NVDA")
        invalid["bankruptcy_8k_scan_boundary"]["endpoint_call_budget"]["max_total_endpoint_calls"] = 4
        invalid["bankruptcy_8k_scan_boundary"]["endpoint_call_budget"]["budget_authorized_by_this_artifact"] = True
        invalid["bankruptcy_8k_scan_boundary"]["endpoint_families"][0]["authorizes_status_call_now"] = True
        invalid["storage_and_secret_boundary"]["tracked_summary_must_exclude_request_urls"] = False
        invalid["prohibited_claims"]["ship_gate_evidence_claimed"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
