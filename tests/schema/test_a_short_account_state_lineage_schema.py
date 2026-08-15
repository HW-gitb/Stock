"""Schema tests for the A-short 4.3 manual-tables -> account_state converter lineage sidecar."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_PATH = ROOT / "schemas" / "a_short_account_state_lineage.schema.json"
EXAMPLE_PATH = ROOT / "schemas" / "examples" / "a_short_account_state_lineage.example.json"


class AShortAccountStateLineageSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    def test_example_validates(self):
        jsonschema.validate(self.example, self.schema)

    def test_unknown_top_level_field_rejected(self):
        bad = copy.deepcopy(self.example)
        bad["extra"] = 1
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_facts_staleness_enum_enforced(self):
        bad = copy.deepcopy(self.example)
        bad["facts_staleness"] = "whatever"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_expected_facts_as_of_is_required_and_yyyymmdd(self):
        missing = copy.deepcopy(self.example)
        missing.pop("expected_facts_as_of")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(missing, self.schema)
        bad = copy.deepcopy(self.example)
        bad["expected_facts_as_of"] = "2026-06-15"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_rule13_source_enum_enforced(self):
        bad = copy.deepcopy(self.example)
        bad["rule13_cooldowns"][0]["source"] = "made_up"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_sha256_pattern_enforced(self):
        bad = copy.deepcopy(self.example)
        bad["source_tables"][0]["sha256"] = "not-a-hash"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_progressed_object_shape_enforced(self):
        bad = copy.deepcopy(self.example)
        bad["rule13_cooldowns"][1]["progressed"] = {"from_status": "active_cooldown"}  # missing to_status
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


if __name__ == "__main__":
    unittest.main()
