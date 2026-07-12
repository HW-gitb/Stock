from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[2]
PACKET_PATH = ROOT / "docs" / "us_short_massive_corporate_action_validation_packet_20260712.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_massive_corporate_action_validation_packet.schema.json"


class MassiveCorporateActionValidationPacketSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
        cls.validator = Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def _assert_invalid(self, packet):
        self.assertTrue(list(self.validator.iter_errors(packet)))

    def test_frozen_packet_is_valid(self):
        self.assertEqual(list(self.validator.iter_errors(self.packet)), [])

    def test_symbol_and_budget_are_const_pinned(self):
        changed_symbol = copy.deepcopy(self.packet)
        changed_symbol["sample"][0]["symbol"] = "NVDA"
        self._assert_invalid(changed_symbol)
        changed_budget = copy.deepcopy(self.packet)
        changed_budget["execution"]["max_total_endpoint_calls"] = 13
        self._assert_invalid(changed_budget)

    def test_boundary_cannot_claim_reconciliation_or_ship_gate(self):
        for field in ("corporate_action_reconciliation_performed", "ship_gate_or_production_authorized"):
            changed = copy.deepcopy(self.packet)
            changed["boundary"][field] = True
            self._assert_invalid(changed)


if __name__ == "__main__":
    unittest.main()
