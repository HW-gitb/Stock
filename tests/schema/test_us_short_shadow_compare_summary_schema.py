# -*- coding: utf-8 -*-
"""Schema tests for US-short §12.2 shadow comparison summary (schemas/us_short_shadow_compare_summary.schema.json).

Pins the TRACKED de-identified contract: const schema_name / track / primary_profile / boundary, required fields,
additionalProperties:false everywhere (so a ticker / $ / performance field can NEVER be smuggled into a tracked
artifact), integer-only non-negative counts (no ticker strings), and the divergence covering EXACTLY the frozen
shadow profiles. No provider/live; no A-share crossing.
"""
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = json.loads((ROOT / "schemas" / "us_short_shadow_compare_summary.schema.json").read_text(encoding="utf-8"))


def _entry():
    return {"balanced_only_count": 1, "shadow_extra_count": 1, "overlap_count": 2}


def _valid():
    return {
        "schema_name": "us_short_shadow_compare_summary", "schema_version": "1.0.0", "as_of": "20260112",
        "track": "comparison_non_production", "primary_profile": "balanced",
        "top_n": 3, "pool_size": 5, "selected_count": 3, "min_comparison_weeks": 12,
        "divergence": {"theme_plus": _entry(), "theme_aggressive": _entry(), "theme_off": _entry()},
        "boundary": {"production": False, "is_buy_advice": False,
                     "shadow_counts_ship_gate": False, "changes_primary_selection": False},
    }


def _invalid(mutate):
    bad = _valid()
    mutate(bad)
    return not jsonschema.Draft7Validator(SCHEMA).is_valid(bad)


class SummarySchema(unittest.TestCase):
    def test_schema_is_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(SCHEMA)

    def test_valid_example_passes(self):
        jsonschema.Draft7Validator(SCHEMA).validate(_valid())

    def test_const_fields(self):
        self.assertTrue(_invalid(lambda b: b.__setitem__("schema_name", "other")))
        self.assertTrue(_invalid(lambda b: b.__setitem__("track", "production")))
        self.assertTrue(_invalid(lambda b: b.__setitem__("primary_profile", "theme_plus")))

    def test_additional_properties_false_rejects_ticker(self):
        self.assertFalse(SCHEMA.get("additionalProperties", True))
        self.assertTrue(_invalid(lambda b: b.__setitem__("ticker", "AAPL")))  # de-id gate: no extra top-level field

    def test_required_fields(self):
        for k in ("schema_name", "schema_version", "as_of", "track", "primary_profile",
                  "top_n", "pool_size", "selected_count", "min_comparison_weeks", "divergence", "boundary"):
            self.assertTrue(_invalid(lambda b, k=k: b.pop(k)), k)

    def test_counts_integer_only_non_negative(self):
        self.assertTrue(_invalid(lambda b: b["divergence"]["theme_off"].__setitem__("overlap_count", "AAPL")))  # ticker string rejected
        self.assertTrue(_invalid(lambda b: b["divergence"]["theme_off"].__setitem__("overlap_count", 1.5)))      # float rejected
        self.assertTrue(_invalid(lambda b: b["divergence"]["theme_off"].__setitem__("overlap_count", -1)))       # negative rejected
        self.assertTrue(_invalid(lambda b: b.__setitem__("top_n", 0)))  # top_n minimum 1

    def test_divergence_exactly_frozen_shadow_profiles(self):
        self.assertTrue(_invalid(lambda b: b["divergence"].pop("theme_off")))                 # missing one
        self.assertTrue(_invalid(lambda b: b["divergence"].__setitem__("theme_extra", _entry())))  # extra (additionalProperties:false)

    def test_divergence_entry_closed_world(self):
        self.assertTrue(_invalid(lambda b: b["divergence"]["theme_off"].__setitem__("leaked", "AAPL")))  # extra key in entry
        self.assertTrue(_invalid(lambda b: b["divergence"]["theme_off"].pop("overlap_count")))           # missing count

    def test_boundary_const_all_false(self):
        self.assertTrue(_invalid(lambda b: b["boundary"].__setitem__("shadow_counts_ship_gate", True)))
        self.assertTrue(_invalid(lambda b: b["boundary"].__setitem__("production", True)))


if __name__ == "__main__":
    unittest.main()
