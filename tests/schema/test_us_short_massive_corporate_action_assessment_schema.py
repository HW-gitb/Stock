from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_massive_corporate_action_assessment.schema.json"


def valid_assessment():
    return {
        "schema_name": "us_short_massive_corporate_action_assessment",
        "schema_version": "1.0.0",
        "evidence_binding": {
            "evidence_schema_name": "us_short_massive_corporate_action_reconciliation_evidence",
            "decision_date": "20260712",
            "symbol": "AAPL",
            "source_binding_sha256": "a" * 64,
            "event_price_windows_sha256": "b" * 64,
        },
        "event_assessments": [
            {"event_id": "AAPL-split-20200831", "event_type": "split", "status": "split_factor_exact_match"},
            {
                "event_id": "AAPL-dividend-20210507",
                "event_type": "dividend",
                "status": "dividend_adjustment_semantics_unresolved",
            },
        ],
        "coverage": {
            "split_exact_match_count": 1,
            "split_mismatch_or_rounding_unresolved_count": 0,
            "dividend_semantics_unresolved_count": 1,
            "insufficient_price_window_count": 0,
        },
        "boundary": {
            "split_factor_assessment_performed": True,
            "provider_call_performed_during_derivation": False,
            "raw_payload_adapter_performed": False,
            "full_corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "paper_gate_evaluable_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


class MassiveCorporateActionAssessmentSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.schema)
        cls.validator = Draft7Validator(cls.schema)

    def assert_valid(self, value):
        errors = sorted(self.validator.iter_errors(value), key=lambda error: list(error.path))
        self.assertEqual(errors, [], [error.message for error in errors])

    def assert_invalid(self, value):
        errors = sorted(self.validator.iter_errors(value), key=lambda error: list(error.path))
        self.assertNotEqual(errors, [])

    def test_valid_assessment(self):
        self.assert_valid(valid_assessment())

    def test_dividend_cannot_claim_split_match(self):
        assessment = valid_assessment()
        assessment["event_assessments"][1]["status"] = "split_factor_exact_match"
        self.assert_invalid(assessment)

    def test_split_cannot_claim_dividend_semantics_status(self):
        assessment = valid_assessment()
        assessment["event_assessments"][0]["status"] = "dividend_adjustment_semantics_unresolved"
        self.assert_invalid(assessment)

    def test_full_reconciliation_and_paper_permissions_are_const_false(self):
        for field in (
            "provider_call_performed_during_derivation",
            "raw_payload_adapter_performed",
            "full_corporate_action_reconciliation_performed",
            "return_calculation_performed",
            "paper_gate_evaluable_claimed",
            "ship_gate_or_production_authorized",
        ):
            assessment = valid_assessment()
            assessment["boundary"][field] = True
            self.assert_invalid(assessment)


if __name__ == "__main__":
    unittest.main()
