# -*- coding: utf-8 -*-
"""Schema-conformance + adversarial test for the US-short eligibility governance contract — batch4 slice 4c-i.

Pins the frozen Pass1 cheap-eligibility governance artifact against its JSON schema, and proves the
schema is closed-world at every level (rejects extra keys, bad types, non-positive thresholds,
unknown status flags). The runtime loader/validator that the Pass1 predicate uses is slice 4c-ii;
this test is the CI contract gate (jsonschema present). No provider/live; no A-share crossing.
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

_SCHEMA = ROOT / "schemas" / "us_short_eligibility_governance.schema.json"
_PRESET = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"


def _schema():
    return json.loads(_SCHEMA.read_text(encoding="utf-8"))


def _preset():
    return json.loads(_PRESET.read_text(encoding="utf-8"))


class EligibilityGovernanceSchemaTests(unittest.TestCase):
    def test_preset_conforms(self):
        jsonschema.validate(instance=_preset(), schema=_schema())

    def test_preset_thresholds_are_positive_numbers(self):
        th = _preset()["cheap_eligibility_thresholds"]
        for k in ("min_price_usd", "min_adv_usd", "min_market_cap_usd"):
            self.assertIsInstance(th[k], (int, float))
            self.assertGreater(th[k], 0)

    def _rejects(self, mutate):
        bad = copy.deepcopy(_preset())
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=_schema())

    def test_rejects_extra_top_level_key(self):
        self._rejects(lambda c: c.__setitem__("unknown_field", "x"))

    def test_rejects_missing_required_key(self):
        self._rejects(lambda c: c.pop("cheap_eligibility_thresholds"))

    def test_rejects_wrong_schema_name(self):
        self._rejects(lambda c: c.__setitem__("schema_name", "something_else"))

    def test_rejects_bad_version(self):
        self._rejects(lambda c: c.__setitem__("schema_version", "v1"))

    def test_rejects_extra_threshold_key(self):
        self._rejects(lambda c: c["cheap_eligibility_thresholds"].__setitem__("max_price_usd", 100.0))

    def test_rejects_nonpositive_threshold(self):
        self._rejects(lambda c: c["cheap_eligibility_thresholds"].__setitem__("min_price_usd", 0))

    def test_rejects_empty_exchange_whitelist(self):
        self._rejects(lambda c: c.__setitem__("exchange_whitelist", []))

    def test_rejects_unknown_status_flag(self):
        self._rejects(lambda c: c.__setitem__("disqualifying_status_flags", ["delisted", "frozen"]))

    def test_rejects_noninteger_calibration_id(self):
        self._rejects(lambda c: c.__setitem__("thresholds_calibration_item_id", "2"))

    # --- semantic-pin drift negatives: const-pinned governed v1 semantics cannot silently drift ---
    def test_rejects_exchange_replace(self):
        self._rejects(lambda c: c.__setitem__("exchange_whitelist", ["OTC"]))

    def test_rejects_exchange_drop(self):
        self._rejects(lambda c: c.__setitem__("exchange_whitelist", ["NYSE"]))

    def test_rejects_exchange_add(self):
        self._rejects(lambda c: c.__setitem__("exchange_whitelist", ["NYSE", "NASDAQ", "NYSE American"]))

    def test_rejects_disqualifier_drop(self):
        # dropping a required disqualifier (halted) must NOT validate
        self._rejects(lambda c: c.__setitem__("disqualifying_status_flags", ["delisted", "bankruptcy", "otc"]))

    def test_rejects_disqualifier_reorder(self):
        # const pins the exact set+order
        self._rejects(lambda c: c.__setitem__("disqualifying_status_flags", ["halted", "delisted", "bankruptcy", "otc"]))

    def test_rejects_calibration_anchor_swap(self):
        self._rejects(lambda c: c.__setitem__("thresholds_calibration_item_id", 19))  # wrong §13.1 anchor

    def test_rejects_price_floor_weakening(self):
        self._rejects(lambda c: c["cheap_eligibility_thresholds"].__setitem__("min_price_usd", 0.01))

    def test_rejects_market_cap_floor_weakening(self):
        self._rejects(lambda c: c["cheap_eligibility_thresholds"].__setitem__("min_market_cap_usd", 1.0))

    def test_rejects_adv_floor_weakening(self):
        self._rejects(lambda c: c["cheap_eligibility_thresholds"].__setitem__("min_adv_usd", 100.0))

    def test_calibration_anchors_resolve_to_lifecycle_registry_titles(self):
        # The const §13.1 anchors must point to the INTENDED lifecycle-registry items, not just be ints.
        reg = json.loads((ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json").read_text(encoding="utf-8"))
        titles = {it["number"]: it["title"] for it in reg["calibration_items"]}
        p = _preset()
        self.assertIn("价格", titles[p["thresholds_calibration_item_id"]])        # item 2 = 安全闸阈值(流动性/价格/市值)
        self.assertIn("候选集", titles[p["candidate_set_calibration_item_id"]])    # item 19 = universe/候选集大小/FMP 预算
        self.assertIn("catalyst_recall", titles[p["catalyst_recall_calibration_item_id"]])  # item 21


if __name__ == "__main__":
    unittest.main()
