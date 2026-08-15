# -*- coding: utf-8 -*-
"""Schema tests for us_short_account_state + its lineage sidecar (US-short batch 1, slice 1a)."""
import copy
import json
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
STATE_SCHEMA = ROOT / "schemas" / "us_short_account_state.schema.json"
LINEAGE_SCHEMA = ROOT / "schemas" / "us_short_account_state_lineage.schema.json"
STATE_EXAMPLE = ROOT / "schemas" / "examples" / "us_short_account_state.example.json"
LINEAGE_EXAMPLE = ROOT / "schemas" / "examples" / "us_short_account_state_lineage.example.json"


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


class UsShortAccountStateSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(STATE_SCHEMA)
        cls.lineage_schema = _load(LINEAGE_SCHEMA)
        cls.example = _load(STATE_EXAMPLE)
        cls.lineage_example = _load(LINEAGE_EXAMPLE)

    def test_schemas_are_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)
        jsonschema.Draft7Validator.check_schema(self.lineage_schema)

    def test_examples_validate(self):
        jsonschema.validate(self.example, self.schema)
        jsonschema.validate(self.lineage_example, self.lineage_schema)

    def test_lineage_expected_facts_as_of_is_required_and_yyyymmdd(self):
        missing = copy.deepcopy(self.lineage_example)
        missing.pop("expected_facts_as_of")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(missing, self.lineage_schema)
        bad = copy.deepcopy(self.lineage_example)
        bad["expected_facts_as_of"] = "2026-06-22"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.lineage_schema)

    def test_us_short_owns_its_schema_not_a_share(self):
        # US-short must NOT reuse the A-share contract; its title/const are us_short-specific.
        self.assertEqual(self.schema["properties"]["schema_name"]["const"], "us_short_account_state")
        self.assertEqual(self.example["schema_name"], "us_short_account_state")

    def _reject(self, mutate):
        bad = copy.deepcopy(self.example)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_a_share_code_ticker_rejected(self):
        # an A-share digit code starts with a digit -> fails the letter-first US ticker pattern
        self._reject(lambda d: d["positions"][0].__setitem__("ticker", "000001.SZ"))

    def test_short_direction_rejected(self):
        self._reject(lambda d: d["positions"][0].__setitem__("direction", "short"))

    def test_broker_connection_true_rejected(self):
        self._reject(lambda d: d.__setitem__("broker_connection_allowed", True))

    def test_manual_order_only_false_rejected(self):
        self._reject(lambda d: d.__setitem__("manual_order_only", False))

    def test_additional_property_rejected(self):
        self._reject(lambda d: d.__setitem__("rule12", {"status": "inactive"}))

    def test_symbol_cooldown_reconciliation_is_required(self):
        self._reject(lambda d: d.pop("symbol_cooldown_reconciliation"))

    def test_negative_shares_rejected(self):
        self._reject(lambda d: d["positions"][0].__setitem__("shares", -1))

    def test_bad_as_of_pattern_rejected(self):
        self._reject(lambda d: d.__setitem__("as_of", "2026-06-22"))

    def test_zero_available_cash_allowed(self):
        ok = copy.deepcopy(self.example)
        ok["us_short_available_cash"] = 0
        jsonschema.validate(ok, self.schema)   # fully-deployed bucket: cash 0 is valid

    def test_negative_available_cash_rejected(self):
        self._reject(lambda d: d.__setitem__("us_short_available_cash", -1.0))

    def test_valid_class_share_ticker_accepted(self):
        ok = copy.deepcopy(self.example)
        ok["positions"][0]["ticker"] = "BRK.B"
        jsonschema.validate(ok, self.schema)


if __name__ == "__main__":
    unittest.main()
