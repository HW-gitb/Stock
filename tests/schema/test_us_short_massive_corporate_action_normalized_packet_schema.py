from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_massive_corporate_action_normalized_packet.schema.json"


def valid_packet():
    return {
        "schema_name": "us_short_massive_corporate_action_normalized_packet",
        "schema_version": "1.0.0",
        "capture_binding": {
            "capture_packet_schema_name": "us_short_massive_corporate_action_validation_packet",
            "capture_packet_sha256": "a" * 64,
            "provider_id": "massive",
            "session_timezone": "America/New_York",
            "day_timestamp_semantics": "new_york_midnight_timestamp",
            "raw_wrapper_sha256": {
                "splits": "b" * 64,
                "dividends": "c" * 64,
                "daily_adjusted": "d" * 64,
                "daily_unadjusted": "e" * 64,
            },
        },
        "symbol": "AAPL",
        "normalized_events": [
            {
                "event_id": "AAPL-split-20200831-a1b2c3d4e5f6",
                "event_type": "split",
                "event_date": "2020-08-31",
                "source_family": "splits",
                "source_ref_sha256": "b" * 64,
                "split_from": 1,
                "split_to": 4,
            },
            {
                "event_id": "AAPL-dividend-20210507-a1b2c3d4e5f6",
                "event_type": "dividend",
                "event_date": "2021-05-07",
                "source_family": "dividends",
                "source_ref_sha256": "c" * 64,
            },
        ],
        "normalized_price_rows": [
            {
                "symbol": "AAPL",
                "session_date": "2020-08-28",
                "adjustment_mode": "adjusted",
                "source_family": "daily_adjusted",
                "source_ref_sha256": "d" * 64,
                "close": 25.0,
            }
        ],
        "boundary": {
            "provider_call_performed_during_normalization": False,
            "raw_payload_read_and_normalized": True,
            "corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "paper_gate_evaluable_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


class MassiveCorporateActionNormalizedPacketSchemaTest(unittest.TestCase):
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

    def test_valid_packet(self):
        self.assert_valid(valid_packet())

    def test_split_requires_ratio_and_dividend_cannot_carry_split_ratio(self):
        packet = valid_packet()
        del packet["normalized_events"][0]["split_from"]
        self.assert_invalid(packet)

        packet = valid_packet()
        packet["normalized_events"][1]["split_from"] = 1
        self.assert_invalid(packet)

    def test_price_mode_must_match_source_family(self):
        packet = valid_packet()
        packet["normalized_price_rows"][0]["source_family"] = "daily_unadjusted"
        self.assert_invalid(packet)

    def test_boundary_cannot_claim_reconciliation_or_downstream_permission(self):
        for field in (
            "provider_call_performed_during_normalization",
            "corporate_action_reconciliation_performed",
            "return_calculation_performed",
            "paper_gate_evaluable_claimed",
            "ship_gate_or_production_authorized",
        ):
            packet = valid_packet()
            packet["boundary"][field] = True
            self.assert_invalid(packet)


if __name__ == "__main__":
    unittest.main()
