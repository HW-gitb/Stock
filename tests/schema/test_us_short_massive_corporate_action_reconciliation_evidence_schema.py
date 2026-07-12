from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_massive_corporate_action_reconciliation_evidence.schema.json"


def valid_evidence():
    return {
        "schema_name": "us_short_massive_corporate_action_reconciliation_evidence",
        "schema_version": "1.0.0",
        "decision_date": "20260712",
        "symbol": "AAPL",
        "source_binding": {
            "provider_id": "massive",
            "capture_packet_schema_name": "us_short_massive_corporate_action_validation_packet",
            "endpoint_families": ["splits", "dividends", "daily_adjusted", "daily_unadjusted"],
            "source_ref_sha256": {
                "splits": "a" * 64,
                "dividends": "b" * 64,
                "daily_adjusted": "c" * 64,
                "daily_unadjusted": "d" * 64,
            },
        },
        "event_price_windows": [
            {
                "event_id": "AAPL-split-20200831",
                "event_type": "split",
                "event_date": "2020-08-31",
                "source_family": "splits",
                "adjusted": {
                    "prior_session": "2020-08-28",
                    "event_session": "2020-08-31",
                    "window_status": "complete",
                },
                "unadjusted": {
                    "prior_session": "2020-08-28",
                    "event_session": "2020-08-31",
                    "window_status": "complete",
                },
                "assessment_status": "pending_price_reconciliation",
            }
        ],
        "coverage": {
            "split_event_count": 1,
            "dividend_event_count": 0,
            "complete_two_mode_window_count": 1,
            "insufficient_price_window_count": 0,
        },
        "boundary": {
            "provider_call_performed_during_derivation": False,
            "corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "paper_gate_evaluable_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


class MassiveCorporateActionReconciliationEvidenceSchemaTest(unittest.TestCase):
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

    def test_valid_evidence(self):
        self.assert_valid(valid_evidence())

    def test_reconciliation_and_downstream_permissions_are_const_false(self):
        for field in (
            "provider_call_performed_during_derivation",
            "corporate_action_reconciliation_performed",
            "return_calculation_performed",
            "paper_gate_evaluable_claimed",
            "ship_gate_or_production_authorized",
        ):
            evidence = valid_evidence()
            evidence["boundary"][field] = True
            self.assert_invalid(evidence)

    def test_source_binding_and_event_price_window_are_closed_world(self):
        evidence = valid_evidence()
        evidence["source_binding"]["request_url"] = "not-allowed"
        self.assert_invalid(evidence)

        evidence = valid_evidence()
        evidence["event_price_windows"][0]["adjusted"]["prior_session"] = None
        evidence["event_price_windows"][0]["adjusted"]["window_status"] = "complete"
        self.assert_invalid(evidence)

    def test_event_type_must_match_source_family(self):
        evidence = valid_evidence()
        evidence["event_price_windows"][0]["source_family"] = "dividends"
        self.assert_invalid(evidence)

    def test_incomplete_window_cannot_claim_pending_reconciliation(self):
        evidence = valid_evidence()
        evidence["event_price_windows"][0]["adjusted"] = {
            "prior_session": "2020-08-28",
            "event_session": None,
            "window_status": "missing_event_session",
        }
        evidence["event_price_windows"][0]["assessment_status"] = "pending_price_reconciliation"
        self.assert_invalid(evidence)

    def test_coverage_counts_are_nonnegative_integers(self):
        evidence = valid_evidence()
        evidence["coverage"]["split_event_count"] = -1
        self.assert_invalid(evidence)


if __name__ == "__main__":
    unittest.main()
