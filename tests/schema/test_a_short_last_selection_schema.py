"""Schema and source-binding guards for the A-short candidate snapshot."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "a_short_last_selection.schema.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _record(**over):
    row = {
        "ts_code": "600000.SH",
        "name": "Example",
        "final_score": 72.5,
        "tier": "Tier1",
        "entry_flag": "observe",
        "cninfo_flag": "未检查",
        "close": 12.34,
        "price_basis": "qfq_anchored_as_of",
        "run_date": "20260609",
        "still_in_pool": True,
    }
    row.update(over)
    return row


class LastSelectionSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = _load(SCHEMA_PATH)
        self.example = {
            "schema_name": "a_short_last_selection",
            "schema_version": "1.0.0",
            "as_of": "20260609",
            "records": [_record()],
        }

    def test_example_and_empty_snapshot_validate(self):
        jsonschema.validate(self.example, self.schema)
        empty = copy.deepcopy(self.example)
        empty["records"] = []
        jsonschema.validate(empty, self.schema)

    def test_schema_rejects_extra_record_field(self):
        bad = copy.deepcopy(self.example)
        bad["records"][0]["source_as_of"] = "20260609"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_non_canonical_as_of(self):
        bad = copy.deepcopy(self.example)
        bad["as_of"] = "2026-06-09"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_egs_uses_strict_prior_and_versioned_write(self):
        source = (ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8")
        self.assertIn("previous_last_selection_version_path", source)
        self.assertIn("last_selection_version_path", source)
        self.assertIn("_prior_last_sel = _json.load(_f)", source)
        self.assertIn("_last_sel_doc", source)
        self.assertIn("write_json_atomic(_LAST_SEL_FILE, _last_sel_doc)", source)
        self.assertIn("_LEGACY_LAST_SEL_FILE", source)
        self.assertNotIn("open(_LEGACY_LAST_SEL_FILE", source)


if __name__ == "__main__":
    unittest.main()
