from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_ticker_scoped_source_freeze.schema.json"


def valid_freeze():
    return {
        "schema_name": "us_short_ticker_scoped_source_freeze",
        "schema_version": "1.0.0",
        "frozen_security_id": "US-CIK-0000320193-COMMON",
        "frozen_tickers": ["AAPL"],
        "source_id": "yfinance",
        "failure_class": "unavailable_or_malformed_response",
        "manual_review_required": True,
        "global_run_blocked": False,
        "boundary": {
            "provider_retry_performed": False,
            "unrelated_symbols_frozen": False,
            "selection_or_ranking_changed": False,
            "account_state_read": False,
            "broker_or_order_automation_allowed": False,
        },
    }


class TickerScopedSourceFreezeSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.schema)
        cls.validator = Draft7Validator(cls.schema)

    def assert_valid(self, value):
        self.assertEqual(list(self.validator.iter_errors(value)), [])

    def assert_invalid(self, value):
        self.assertNotEqual(list(self.validator.iter_errors(value)), [])

    def test_valid_freeze(self):
        self.assert_valid(valid_freeze())

    def test_global_or_unrelated_freeze_is_rejected(self):
        for path, value in (
            (("global_run_blocked",), True),
            (("boundary", "unrelated_symbols_frozen"), True),
            (("boundary", "provider_retry_performed"), True),
            (("frozen_tickers",), ["AAPL", "MSFT"]),
        ):
            item = valid_freeze()
            if len(path) == 1:
                item[path[0]] = value
            else:
                item[path[0]][path[1]] = value
            self.assert_invalid(item)


if __name__ == "__main__":
    unittest.main()
