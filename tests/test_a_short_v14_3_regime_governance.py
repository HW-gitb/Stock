"""Tests for the V14.3 regime classifier design slice (slice 1, schema-first, comparison-only).

Pins: both schemas are valid draft-07; the governance + daily-feature artifacts validate against
their schemas; the comparison-only boundary is machine-enforced (V14.2 stays the frozen production
baseline, V14.3 does NOT drive Phase 5 / does NOT auto-switch); the attack low-risk gate is a
CEILING not a floor; the action matrix is documented-only. No runner / no production wiring here.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOV = ROOT / "presets" / "a_short_v14_3_regime_governance_20260611.json"
GOV_SCHEMA = ROOT / "schemas" / "a_short_v14_3_regime_governance.schema.json"
DAILY_SCHEMA = ROOT / "schemas" / "a_short_market_regime_daily.schema.json"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


class SchemaValidityTests(unittest.TestCase):
    def test_schemas_are_valid_draft7(self):
        for s in (GOV_SCHEMA, DAILY_SCHEMA):
            jsonschema.Draft7Validator.check_schema(_load(s))


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.gov = _load(GOV)

    def test_governance_validates(self):
        jsonschema.validate(self.gov, _load(GOV_SCHEMA))

    def test_comparison_only_boundary(self):
        b = self.gov["boundary"]
        self.assertTrue(b["comparison_only"])
        self.assertFalse(b["production_switch_authorized"])
        self.assertFalse(b["changes_phase5_downstream"])
        self.assertTrue(b["v14_2_remains_frozen_baseline"])
        self.assertFalse(b["mixes_with_overlay_star_or_m67_action"])
        self.assertFalse(self.gov["switch_candidate_gate"]["auto_switch_allowed"])

    def test_attack_limit_down_is_ceiling_not_floor(self):
        # the corrected bug: low-risk gate caps (min(50, ...)), never widens (max(P25,50)).
        v = self.gov["thresholds"]["attack_all_of_confirm_3d"]["limit_down_count_le"]
        self.assertIn("min(50", v)
        self.assertNotIn("max(P25_252, 50)", v)

    def test_action_matrix_documented_only_all_regimes(self):
        m = self.gov["downstream_action_matrix"]
        self.assertIn("DOCUMENTED ONLY", m["_status"])
        for r in ("attack", "shock", "normal_defense", "extreme_defense", "contraction"):
            self.assertIn(r, m)

    def test_schema_rejects_broken_attack_threshold(self):
        # R-V143-REGIME-GOVERNANCE-CONST-PIN-GAP: frozen formulas are const-pinned → drift rejected.
        g = _load(GOV)
        g["thresholds"]["attack_all_of_confirm_3d"]["promotion_rate_ge"] = "broken"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(g, _load(GOV_SCHEMA))

    def test_schema_rejects_removed_or_flipped_switch_gate(self):
        g = _load(GOV)
        del g["switch_candidate_gate"]["backtest_years_min"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(g, _load(GOV_SCHEMA))
        g2 = _load(GOV)
        g2["switch_candidate_gate"]["auto_switch_allowed"] = True   # const False
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(g2, _load(GOV_SCHEMA))

    def test_schema_rejects_flipped_comparison_only_boundary(self):
        g = _load(GOV)
        g["boundary"]["production_switch_authorized"] = True   # const False
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(g, _load(GOV_SCHEMA))


class DailySchemaShapeTests(unittest.TestCase):
    def test_valid_daily_row(self):
        row = {
            "schema_name": "a_short_market_regime_daily", "schema_version": "1.0.0",
            "as_of": "20260609", "limit_up_count": 40, "limit_down_count": 12, "net_limit": 28,
            "max_limit_streak": 4, "promotion_rate": 0.42, "failed_limit_rate": 0.18,
            "iv_percentile_252d": 67.0, "csi300_ret_1d": 0.3, "csi1000_ret_1d": 0.5,
            "pct_above_ma20": 55.0, "csi1000_below_ma20": False, "data_quality_flags": [],
            "boundary": {"production": False, "comparison_only": True, "drives_phase5_risk_posture": False},
        }
        jsonschema.validate(row, _load(DAILY_SCHEMA))

    def test_daily_requires_csi1000_below_ma20(self):
        # R-V143-REGIME-SLOW-BLEED-FIELD-GAP: the slow-bleed operand must be a represented field.
        row = _valid_daily()
        del row["csi1000_below_ma20"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(row, _load(DAILY_SCHEMA))

    def test_daily_boundary_must_be_comparison_only(self):
        row = _valid_daily()
        row["boundary"]["drives_phase5_risk_posture"] = True   # must be const False
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(row, _load(DAILY_SCHEMA))

    def test_null_csi1000_requires_unavailable_flag(self):
        # R-V143-REGIME-MISSING-INDEX-FLAG-NOT-ENFORCED: null slow-bleed operand must carry the
        # csi1000_unavailable data-quality flag — null + empty/absent flag must be rejected.
        row = _valid_daily()
        row["csi1000_below_ma20"] = None
        row["data_quality_flags"] = []   # missing the required csi1000_unavailable flag
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(row, _load(DAILY_SCHEMA))

    def test_null_csi1000_with_flag_validates(self):
        # positive: null + csi1000_unavailable present is the documented missing-index representation.
        row = _valid_daily()
        row["csi1000_below_ma20"] = None
        row["data_quality_flags"] = ["csi1000_unavailable"]
        jsonschema.validate(row, _load(DAILY_SCHEMA))

    def test_nonnull_csi1000_does_not_require_flag(self):
        # the conditional must NOT fire when the operand is present (boolean), so empty flags is fine.
        row = _valid_daily()
        row["csi1000_below_ma20"] = True
        row["data_quality_flags"] = []
        jsonschema.validate(row, _load(DAILY_SCHEMA))


def _valid_daily():
    return {
        "schema_name": "a_short_market_regime_daily", "schema_version": "1.0.0",
        "as_of": "20260609", "limit_up_count": 40, "limit_down_count": 12, "net_limit": 28,
        "max_limit_streak": 4, "promotion_rate": None, "failed_limit_rate": None,
        "iv_percentile_252d": None, "csi300_ret_1d": None, "csi1000_ret_1d": None,
        "pct_above_ma20": None, "csi1000_below_ma20": None,
        "data_quality_flags": ["insufficient_sample", "csi1000_unavailable"],
        "boundary": {"production": False, "comparison_only": True, "drives_phase5_risk_posture": False},
    }


if __name__ == "__main__":
    unittest.main()
