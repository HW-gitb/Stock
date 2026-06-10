"""Schema tests for the A-short 赛道热度 overlay comparison artifact (Slice A).

The bespoke schema const-pins frozen design values (weights / thresholds / track / boundary)
so post-review drift cannot validate. Fixtures are built from the runner so schema↔runner align.
"""
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

from runners.a_short_theme_overlay_comparison import (  # noqa: E402
    assemble_overlay, build_summary,
)
import pandas as pd  # noqa: E402

SCHEMA_PATH = ROOT / "schemas" / "a_short_theme_overlay_comparison.schema.json"


def _summary():
    pool = pd.DataFrame([
        {"ts_code": "B.SH", "baseline_rank": 1, "esp_score": 50.0, "l4_score": 70.0,
         "overheat_flag": False, "chasing_high": False, "chase_flag": False, "high_pos_shrink": False},
        {"ts_code": "A.SZ", "baseline_rank": 2, "esp_score": 80.0, "l4_score": 60.0,
         "overheat_flag": False, "chasing_high": False, "chase_flag": False, "high_pos_shrink": False},
    ])
    th = {"score": {"B.SH": 90.0, "A.SZ": None}, "best_concept": {"B.SH": "c1", "A.SZ": None}}
    ih = {"半导体": 95.0, "银行": 20.0}
    sw = {"B.SH": "半导体", "A.SZ": "银行"}
    br = {"B.SH": {"up_frac": 0.8, "vol_frac": 0.6, "pass": True},
          "A.SZ": {"up_frac": 0.1, "vol_frac": 0.1, "pass": False}}
    pe = {"B.SH": 1.0, "A.SZ": 0.0}
    ft = {"B.SH": 0.8, "A.SZ": None}
    df = assemble_overlay(pool, th, ih, br, pe, ft, sw)
    return build_summary(df, as_of="20260612",
                         pit_source={"concept_membership": "pit", "sw_mapping": "forward"},
                         dropped_at_l0_l5=[{"ts_code": "Z.SZ", "theme_heat_score": 99.0, "drop_stage": "L4_overheat"}],
                         generated_at="2026-06-10T00:00:00+08:00")


class OverlaySchemaValidTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.summary = _summary()

    def test_real_summary_validates(self):
        jsonschema.validate(self.summary, self.schema)

    def test_dropped_instrumentation_present(self):
        self.assertEqual(self.summary["dropped_at_l0_l5"][0]["drop_stage"], "L4_overheat")

    def test_boundary_non_production(self):
        b = self.summary["boundary"]
        self.assertFalse(b["production"])
        self.assertFalse(b["changes_final_score_or_tier"])
        self.assertFalse(b["is_buy_advice"])
        self.assertFalse(b["satisfies_ship_gate"])


class OverlaySchemaAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.summary = _summary()

    def _reject(self, s):
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)

    def test_weight_drift_rejected(self):
        s = copy.deepcopy(self.summary)
        s["weights"]["theme"] = 0.5
        self._reject(s)

    def test_threshold_drift_rejected(self):
        s = copy.deepcopy(self.summary)
        s["thresholds"]["pass_percentile"] = 50.0
        self._reject(s)

    def test_extra_threshold_key_rejected(self):
        s = copy.deepcopy(self.summary)
        s["thresholds"]["crowding_demote_factor"] = 0.5
        self._reject(s)

    def test_theme_window_blend_drift_rejected(self):
        s = copy.deepcopy(self.summary)
        s["thresholds"]["theme_window_blend"]["d5"] = 0.7
        self._reject(s)

    def test_track_flip_rejected(self):
        s = copy.deepcopy(self.summary)
        s["track"] = "production"
        self._reject(s)

    def test_boundary_production_true_rejected(self):
        s = copy.deepcopy(self.summary)
        s["boundary"]["production"] = True
        self._reject(s)

    def test_industry_norm_out_of_range_rejected(self):
        s = copy.deepcopy(self.summary)
        s["candidates"][0]["industry_heat_norm_ortho"] = 250.0
        self._reject(s)

    def test_bad_pit_source_enum_rejected(self):
        s = copy.deepcopy(self.summary)
        s["pit_source"]["sw_mapping"] = "today"
        self._reject(s)

    def test_extra_candidate_field_rejected(self):
        s = copy.deepcopy(self.summary)
        s["candidates"][0]["unexpected"] = 1
        self._reject(s)


if __name__ == "__main__":
    unittest.main()
