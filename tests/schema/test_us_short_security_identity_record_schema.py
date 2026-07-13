from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_security_identity_record.schema.json"


def valid_record():
    return {
        "schema_name": "us_short_security_identity_record",
        "schema_version": "1.0.0",
        "security_id": "US-CIK-0000320193-COMMON",
        "issuer_cik": "0000320193",
        "security_class": "COMMON",
        "current_ticker": "AAPL",
        "issuer_name": "Example Issuer",
        "primary_exchange": "NASDAQ",
        "observed_as_of": "20260713",
        "source_binding": {"source_id": "manual_seed", "source_ref_sha256": "a" * 64},
        "boundary": {
            "provider_call_performed": False,
            "raw_payload_read": False,
            "security_master_completeness_claimed": False,
            "selection_or_ranking_changed": False,
            "account_state_read": False,
            "broker_or_order_automation_allowed": False,
        },
    }


class SecurityIdentityRecordSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.schema)
        cls.validator = Draft7Validator(cls.schema)

    def assert_valid(self, value):
        self.assertEqual(list(self.validator.iter_errors(value)), [])

    def assert_invalid(self, value):
        self.assertNotEqual(list(self.validator.iter_errors(value)), [])

    def test_valid_record(self):
        self.assert_valid(valid_record())

    def test_security_identity_and_boundary_are_pinned(self):
        value = valid_record()
        value["security_id"] = "US-CIK-0000320193-AAPL"
        self.assert_invalid(value)
        for field in ("provider_call_performed", "raw_payload_read", "selection_or_ranking_changed", "account_state_read"):
            value = valid_record()
            value["boundary"][field] = True
            self.assert_invalid(value)

    def test_controlled_share_class_identifier_is_supported(self):
        value = valid_record()
        value["security_class"] = "CLASS_A"
        value["security_id"] = "US-CIK-0000320193-CLASS_A"
        self.assert_valid(value)
