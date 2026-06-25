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

SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_incident_log_record.schema.json"


def valid_record() -> dict:
    return {
        "schema_name": "us_short_batch5_incident_log_record",
        "schema_version": "1.0.0",
        "incident_id": "batch5-incident-20260625-0001",
        "detected_at": "2026-06-25T00:00:00+08:00",
        "detected_by": "unit_test_offline_writer",
        "source_family": "price_volume_liquidity",
        "provider_candidate": "financial_modeling_prep",
        "endpoint_family": "historical_eod_price_volume",
        "affected_symbols_or_universe": ["AAPL"],
        "affected_date_window": {
            "start": "2026-06-24",
            "end": "2026-06-24",
        },
        "incident_type": "quota_or_rate_limit",
        "severity": "production_blocker",
        "trigger_summary": "Bounded probe returned a quota/rate-limit category signal.",
        "evidence_artifact_refs": [
            "docs/us_short_batch5_provider_live_probe_summary_20260625.json"
        ],
        "raw_payload_storage_ref": "",
        "secret_scan_status": "clean",
        "immediate_action": "block_production_use",
        "production_use_blocked": True,
        "fallback_execution_performed": False,
        "provider_calls_performed_by_log_contract": False,
        "status_page_polled_by_log_contract": False,
        "manual_review_owner": "Codex",
        "review_status": "pending_review",
        "disposition": "pending",
        "replay_or_revalidation_requirement": "separate_approval_required",
        "scope_locks": {
            "provider_selection_allowed": False,
            "provider_status_polling_allowed": False,
            "fallback_execution_allowed": False,
            "datahub_consumption_allowed": False,
            "runner_consumption_allowed": False,
            "production_storage_allowed": False,
            "live_normalized_evidence_allowed": False,
            "ship_gate_evidence_allowed": False,
        },
    }


class UsShortBatch5IncidentLogRecordSchemaTest(unittest.TestCase):
    def _schema(self) -> dict:
        self.assertTrue(SCHEMA_PATH.exists(), f"missing required file: {SCHEMA_PATH}")
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _errors(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._schema()).iter_errors(payload))

    def test_schema_meta_is_batch5_private_record_contract(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._schema()
        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "us_short_batch5_incident_log_record")
        self.assertIn("US-short batch5", schema["description"])
        self.assertIn("private incident log", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_valid_record_passes(self) -> None:
        self.assertEqual(self._errors(valid_record()), [])

    def test_required_gate_fields_are_fail_closed(self) -> None:
        for field in [
            "production_use_blocked",
            "fallback_execution_performed",
            "provider_calls_performed_by_log_contract",
            "status_page_polled_by_log_contract",
        ]:
            with self.subTest(field=field):
                invalid = valid_record()
                invalid[field] = not invalid[field]
                self.assertNotEqual(self._errors(invalid), [])

    def test_scope_locks_are_required_false(self) -> None:
        for field in valid_record()["scope_locks"]:
            with self.subTest(field=field):
                invalid = valid_record()
                invalid["scope_locks"][field] = True
                self.assertNotEqual(self._errors(invalid), [])

    def test_extra_raw_or_request_url_fields_are_rejected(self) -> None:
        for field in ["request_url", "url", "raw_payload", "provider_response_body", "api_key"]:
            with self.subTest(field=field):
                invalid = valid_record()
                invalid[field] = "forbidden"
                self.assertNotEqual(self._errors(invalid), [])

    def test_raw_payload_ref_must_be_blank_or_private_pointer(self) -> None:
        valid = valid_record()
        valid["raw_payload_storage_ref"] = (
            "provider_samples/us_short_batch5_provider_incidents/raw/AAPL/profile.json"
        )
        self.assertEqual(self._errors(valid), [])

        for ref in [
            "https://financialmodelingprep.com/api/v3/profile/AAPL?apikey=SECRET",
            "docs/raw_payload.json",
            "../provider_samples/us_short_batch5_provider_incidents/raw.json",
        ]:
            with self.subTest(ref=ref):
                invalid = valid_record()
                invalid["raw_payload_storage_ref"] = ref
                self.assertNotEqual(self._errors(invalid), [])

    def test_missing_required_record_field_is_rejected(self) -> None:
        invalid = valid_record()
        invalid.pop("incident_type")
        self.assertNotEqual(self._errors(invalid), [])

    def test_incident_type_and_action_vocab_are_locked_to_storage_contract(self) -> None:
        invalid = copy.deepcopy(valid_record())
        invalid["incident_type"] = "new_unreviewed_incident_type"
        self.assertNotEqual(self._errors(invalid), [])

        invalid = copy.deepcopy(valid_record())
        invalid["immediate_action"] = "unreviewed_action"
        self.assertNotEqual(self._errors(invalid), [])


if __name__ == "__main__":
    unittest.main()
