# -*- coding: utf-8 -*-
"""Schema-conformance + adversarial test for the US-short catalyst governance contract — round-2 core_score 25%.

Pins the frozen §4.2 catalyst-block rule-mapping governance artifact against its JSON schema, and proves the
schema is closed-world at every level + const-pins every governed v1 value (neutral / bounds / bucket bounds /
point values / §13.1 #14 anchor) so the mapping cannot silently drift/weaken without a reviewed version bump.
The runtime loader/validator the engine uses is engine/us_short_catalyst.py; this test is the CI contract gate
(jsonschema present). No provider/live; no A-share crossing.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402

_SCHEMA = ROOT / "schemas" / "us_short_catalyst_governance.schema.json"
_PRESET = ROOT / "presets" / "us_short_catalyst_governance_20260630.json"


def _schema():
    return json.loads(_SCHEMA.read_text(encoding="utf-8"))


def _preset():
    return json.loads(_PRESET.read_text(encoding="utf-8"))


class CatalystGovernanceSchemaTests(unittest.TestCase):
    def test_preset_conforms(self):
        jsonschema.validate(instance=_preset(), schema=_schema())

    def _rejects(self, mutate):
        bad = copy.deepcopy(_preset())
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=_schema())

    # --- closed-world / structural ---
    def test_rejects_extra_top_level_key(self):
        self._rejects(lambda c: c.__setitem__("unknown_field", "x"))

    def test_rejects_missing_required_key(self):
        self._rejects(lambda c: c.pop("earnings_surprise"))

    def test_rejects_wrong_schema_name(self):
        self._rejects(lambda c: c.__setitem__("schema_name", "something_else"))

    def test_rejects_bad_version(self):
        self._rejects(lambda c: c.__setitem__("schema_version", "v1"))

    def test_rejects_extra_earnings_point_key(self):
        self._rejects(lambda c: c["earnings_surprise"]["points"].__setitem__("mega_beat", 99.0))

    def test_rejects_extra_event8k_class(self):
        self._rejects(lambda c: c["event_8k"]["points"].__setitem__("catastrophic", -99.0))

    # --- const-pin drift negatives: a governed value cannot silently change ---
    def test_rejects_neutral_drift(self):
        self._rejects(lambda c: c.__setitem__("neutral_catalyst_score", 60.0))

    def test_rejects_score_bounds_drift(self):
        self._rejects(lambda c: c["score_bounds"].__setitem__("max", 120.0))

    def test_rejects_earnings_point_weakening(self):
        self._rejects(lambda c: c["earnings_surprise"]["points"].__setitem__("big_beat", 80.0))

    def test_rejects_earnings_bucket_bound_drift(self):
        self._rejects(lambda c: c["earnings_surprise"]["bucket_bounds_pct"].__setitem__("big_beat_min", 1.0))

    def test_rejects_miss_point_flip_to_positive(self):
        # a realized miss must never be a positive catalyst
        self._rejects(lambda c: c["earnings_surprise"]["points"].__setitem__("big_miss", 20.0))

    def test_rejects_revision_point_drift(self):
        self._rejects(lambda c: c["analyst_revision"]["points"].__setitem__("strong_positive", 50.0))

    def test_rejects_revision_bucket_bound_drift(self):
        self._rejects(lambda c: c["analyst_revision"]["bucket_bounds_net"].__setitem__("strong_positive_min", 1))

    def test_rejects_event8k_point_drift(self):
        self._rejects(lambda c: c["event_8k"]["points"].__setitem__("positive", 40.0))

    def test_rejects_semantic_cap_widening(self):
        # widening the advisory cap would let the LLM signal dominate the rule-mapping
        self._rejects(lambda c: c["semantic_advisory"].__setitem__("max_abs_points", 50.0))

    def test_rejects_semantic_input_bound_drift(self):
        self._rejects(lambda c: c["semantic_advisory"]["input_bounds"].__setitem__("max", 10.0))

    def test_rejects_calibration_anchor_swap(self):
        self._rejects(lambda c: c.__setitem__("scoring_caliber_calibration_item_id", 21))

    def test_rejects_noninteger_calibration_id(self):
        self._rejects(lambda c: c.__setitem__("scoring_caliber_calibration_item_id", "14"))

    # --- anchor must resolve to the INTENDED §13.1 registry item, not just be an int ---
    def test_calibration_anchor_resolves_to_lifecycle_registry_title(self):
        reg = json.loads((ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json").read_text(encoding="utf-8"))
        titles = {it["number"]: it["title"] for it in reg["calibration_items"]}
        self.assertIn("打分标准化", titles[_preset()["scoring_caliber_calibration_item_id"]])  # item 14


if __name__ == "__main__":
    unittest.main()
