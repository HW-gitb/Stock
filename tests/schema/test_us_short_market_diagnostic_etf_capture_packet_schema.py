from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[2]
PACKET_PATH = ROOT / "docs" / "us_short_market_diagnostic_etf_capture_packet_20260805.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_etf_capture_packet.schema.json"


class EtfCapturePacketSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
        cls.validator = Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_packet_is_valid_and_has_exact_authorized_scope(self):
        self.assertEqual(list(self.validator.iter_errors(self.packet)), [])
        self.assertEqual(self.packet["scope"]["symbols"], ["SPY", "QQQ", "IWB", "VTI"])
        self.assertEqual(self.packet["scope"]["endpoint_families"], ["dividends", "splits", "daily_adjusted", "daily_unadjusted"])
        self.assertEqual(self.packet["execution"]["nominal_logical_calls"], 32)
        self.assertEqual(self.packet["execution"]["max_total_http_attempts"], 40)

    def test_symbol_budget_and_clock_boundary_are_const_pinned(self):
        changed = copy.deepcopy(self.packet)
        changed["scope"]["symbols"][0] = "AAPL"
        self.assertTrue(list(self.validator.iter_errors(changed)))
        changed = copy.deepcopy(self.packet)
        changed["execution"]["max_total_http_attempts"] = 41
        self.assertTrue(list(self.validator.iter_errors(changed)))
        changed = copy.deepcopy(self.packet)
        changed["boundary"]["week_aligned_sidecar_allowed"] = True
        self.assertTrue(list(self.validator.iter_errors(changed)))

    def test_packet_does_not_contain_week_identity_placeholders(self):
        serialized = json.dumps(self.packet, sort_keys=True)
        for forbidden in ("window_id", "diagnostic_epoch", "calendar_week_index", "valuation_date", "week 0", "pre_clock"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
