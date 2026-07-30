from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "schemas" / "a_short_weekly_publish_receipt.schema.json").read_text(encoding="utf-8")
)


def _complete_receipt() -> dict:
    return {
        "schema_name": "a_short_weekly_publish_receipt",
        "schema_version": "1.1.0",
        "as_of": "20260727",
        "decision_as_of": "20260727",
        "run_date": "20260727",
        "price_data_through": "20260724",
        "run_id": "a-short-20260727-test",
        "candidate_digest": "a" * 64,
        "published_at": "2026-07-27T12:00:00+08:00",
        "account_snapshot": None,
        "stage_status": "complete",
        "outputs": ["weekly_m67.json", "weekly_m67.md"],
        "outputs_digest": {
            "weekly_m67.json": {"sha256": "b" * 64, "byte_length": 123},
            "weekly_m67.md": {"sha256": "c" * 64, "byte_length": 45},
        },
    }


class AShortWeeklyPublishReceiptSchemaTests(unittest.TestCase):
    def test_complete_receipt_requires_two_content_bindings(self):
        jsonschema.validate(_complete_receipt(), SCHEMA)
        for missing in ("outputs", "outputs_digest"):
            bad = copy.deepcopy(_complete_receipt())
            bad.pop(missing)
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, SCHEMA)

    def test_each_output_digest_requires_sha256_and_byte_length(self):
        for missing in ("sha256", "byte_length"):
            bad = copy.deepcopy(_complete_receipt())
            bad["outputs_digest"]["weekly_m67.json"].pop(missing)
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, SCHEMA)

    def test_failed_receipt_remains_schema_valid_without_outputs(self):
        failed = {
            "schema_name": "a_short_weekly_publish_receipt",
            "schema_version": "1.1.0",
            "as_of": "20260727",
            "stage_status": "failed",
            "failure_reason": "weekly_pipeline_failed",
            "exit_code": 22,
        }
        jsonschema.validate(failed, SCHEMA)

    def test_failed_receipt_cannot_claim_complete_outputs(self):
        failed = {
            "schema_name": "a_short_weekly_publish_receipt",
            "schema_version": "1.1.0",
            "as_of": "20260727",
            "stage_status": "failed",
            "failure_reason": "weekly_pipeline_failed",
            "exit_code": 22,
            "outputs": ["weekly_m67.json", "weekly_m67.md"],
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(failed, SCHEMA)


if __name__ == "__main__":
    unittest.main()
