# -*- coding: utf-8 -*-
"""Schema tests for US-short §13 lifecycle readiness artifact (schemas/us_short_lifecycle_readiness.schema.json).

Pins the TRACKED de-identified contract: const schema_name, required fields, additionalProperties:false (so a
ticker / performance field can NEVER be smuggled into a tracked artifact), integer-only item numbers (no ticker
strings), and positive bounds. No provider/live; no A-share crossing.
"""
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = json.loads((ROOT / "schemas" / "us_short_lifecycle_readiness.schema.json").read_text(encoding="utf-8"))


def _valid():
    return {"schema_name": "us_short_lifecycle_readiness", "schema_version": "1.0.0", "as_of": "20260112",
            "total_items": 39, "due_count": 1, "due_items": [1], "upgrade_eligible_items": []}


class ReadinessSchema(unittest.TestCase):
    def test_schema_is_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(SCHEMA)

    def test_valid_example_passes(self):
        jsonschema.Draft7Validator(SCHEMA).validate(_valid())

    def test_schema_name_const(self):
        self.assertEqual(SCHEMA["properties"]["schema_name"]["const"], "us_short_lifecycle_readiness")
        bad = _valid(); bad["schema_name"] = "other"
        self.assertFalse(jsonschema.Draft7Validator(SCHEMA).is_valid(bad))

    def test_additional_properties_false_rejects_ticker(self):
        self.assertFalse(SCHEMA.get("additionalProperties", True))
        bad = _valid(); bad["ticker"] = "AAPL"   # de-identification gate: no extra field may land on a tracked artifact
        self.assertFalse(jsonschema.Draft7Validator(SCHEMA).is_valid(bad))

    def test_required_fields(self):
        for k in ("schema_name", "schema_version", "as_of", "total_items", "due_count", "due_items", "upgrade_eligible_items"):
            bad = _valid(); del bad[k]
            self.assertFalse(jsonschema.Draft7Validator(SCHEMA).is_valid(bad), k)

    def test_item_fields_integer_only_positive(self):
        for field in ("due_items", "upgrade_eligible_items"):
            bad = _valid(); bad[field] = ["AAPL"]   # ticker string rejected — de-identified integers only
            self.assertFalse(jsonschema.Draft7Validator(SCHEMA).is_valid(bad), field)
            bad = _valid(); bad[field] = [0]        # minimum 1
            self.assertFalse(jsonschema.Draft7Validator(SCHEMA).is_valid(bad), field)

    def test_total_items_minimum_1(self):
        bad = _valid(); bad["total_items"] = 0
        self.assertFalse(jsonschema.Draft7Validator(SCHEMA).is_valid(bad))


if __name__ == "__main__":
    unittest.main()
