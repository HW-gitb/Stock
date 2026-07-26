"""The field-policy family is frozen in one declarative authority."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "a_short_theme_forward_comparison_governance.schema.json"
GOVERNANCE_PATH = ROOT / "presets" / "a_short_theme_forward_comparison_governance_20260725.json"
EPOCH_SCHEMA_PATH = ROOT / "schemas" / "a_short_theme_forward_comparison_epoch.schema.json"
EPOCH_PATH = ROOT / "docs" / "a_short_theme_forward_comparison_epoch_20260725.json"


class ThemeForwardComparisonGovernanceSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.governance = json.loads(GOVERNANCE_PATH.read_text(encoding="utf-8"))

    def test_active_governance_is_valid_and_freezes_the_seven_policy_family(self):
        jsonschema.validate(self.governance, self.schema)
        self.assertEqual([row["criterion_id"] for row in self.governance["criteria"]], [
            "industry_trend", "business_role", "industry_heat", "persistence",
            "theme_breadth_pass", "theme_fit_pass", "theme_heat",
        ])

    def test_threshold_or_strategy_drift_is_rejected(self):
        threshold = copy.deepcopy(self.governance)
        threshold["policy"]["practical_margin_pp"] = 0.02
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(threshold, self.schema)
        strategy = copy.deepcopy(self.governance)
        strategy["criteria"][3]["value"] = 50.0
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(strategy, self.schema)

    def test_pre_freeze_epoch_is_valid_and_cannot_smuggle_a_clock(self):
        epoch_schema = json.loads(EPOCH_SCHEMA_PATH.read_text(encoding="utf-8"))
        epoch = json.loads(EPOCH_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(epoch, epoch_schema)
        epoch["epoch_start_as_of"] = "20260725"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(epoch, epoch_schema)

    def test_frozen_epoch_requires_a_non_empty_theme_family(self):
        epoch_schema = json.loads(EPOCH_SCHEMA_PATH.read_text(encoding="utf-8"))
        epoch = json.loads(EPOCH_PATH.read_text(encoding="utf-8"))
        epoch.update({
            "mode": "frozen_enforced", "epoch_id": "theme-v1", "epoch_start_as_of": "20260725",
            "governance_fingerprint": "a" * 64, "contract_fingerprint": "b" * 64,
            "source_configuration_fingerprints": {"industry_trend_configuration_fingerprint": "c" * 64,
                                                   "theme_taxonomy_configuration_fingerprint": "d" * 64,
                                                   "runtime_configuration_fingerprint": "e" * 64},
        })
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(epoch, epoch_schema)


if __name__ == "__main__":
    unittest.main()
