from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_lifecycle_observation.schema.json"


def valid_observation():
    return {
        "schema_name": "us_short_forward_lifecycle_observation",
        "schema_version": "1.0.0",
        "forward_start_date": "20260713",
        "decision_date": "20260720",
        "observed_at": "2026-07-20T13:00:00Z",
        "snapshot_ref": {
            "path": "state/us_short/forward_universe_snapshot_20260713.json",
            "sha256": "a" * 64,
        },
        "candidate_ref": {
            "path": "state/us_short/candidate_universe_20260720.json",
            "sha256": "b" * 64,
        },
        "events": [
            {
                "event_id": "AAPL-inactive_or_ticker_change_unresolved-20260720-a1b2c3d4e5f6",
                "symbol": "AAPL",
                "event_type": "inactive_or_ticker_change_unresolved",
                "decision_date": "20260720",
                "observed_at": "2026-07-20T13:00:00Z",
                "manual_review_required": True,
                "new_entry_blocked": True,
                "automatic_conversion_or_cash_valuation_performed": False,
            }
        ],
        "coverage": {
            "frozen_symbol_count": 1,
            "current_candidate_row_count": 1,
            "matched_frozen_symbol_count": 1,
            "missing_frozen_symbol_count": 0,
            "known_clear_symbol_count": 0,
            "blocked_symbol_count": 1,
            "critical_status_unknown_symbol_count": 0,
        },
        "retention_policy": {
            "forward_snapshot_symbols_deleted": False,
            "lifecycle_events_retained": True,
        },
        "boundary": {
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_capture_performed": False,
            "merger_or_ticker_change_semantics_confirmed": False,
            "automatic_corporate_action_processing_performed": False,
            "return_calculation_performed": False,
            "selection_or_ranking_changed": False,
            "datahub_consumption_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
        },
    }


class ForwardLifecycleObservationSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.schema)
        cls.validator = Draft7Validator(cls.schema)

    def assert_valid(self, value):
        self.assertEqual(list(self.validator.iter_errors(value)), [])

    def assert_invalid(self, value):
        self.assertNotEqual(list(self.validator.iter_errors(value)), [])

    def test_valid_observation(self):
        self.assert_valid(valid_observation())

    def test_event_requires_manual_block_and_never_confirms_merger_semantics(self):
        value = valid_observation()
        value["events"][0]["manual_review_required"] = False
        self.assert_invalid(value)

        value = valid_observation()
        value["events"][0]["event_type"] = "confirmed_merger"
        self.assert_invalid(value)

    def test_boundary_cannot_claim_automatic_processing_or_selection_effect(self):
        for field in (
            "network_access_performed",
            "provider_calls_performed",
            "merger_or_ticker_change_semantics_confirmed",
            "automatic_corporate_action_processing_performed",
            "selection_or_ranking_changed",
            "ship_gate_evidence_claimed",
        ):
            value = valid_observation()
            value["boundary"][field] = True
            self.assert_invalid(value)


if __name__ == "__main__":
    unittest.main()
