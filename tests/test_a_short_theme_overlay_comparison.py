"""Unit tests for the A-short 赛道热度 overlay comparison-track runner (Slice A).

Covers the frozen computation contract + the design invariants:
fit_pass single-gate, industry_heat_norm_ortho re-normalized to 0-100 (R-ASLICEA fixes),
crowding strips bonus (heat cannot rescue), eligibility, governance parity, consistency validation.
All synthetic fixtures; no live data / no fetch.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_theme_overlay_comparison import (  # noqa: E402
    OVERLAY_WEIGHTS, EMITTED_THRESHOLDS, FIT_FLOOR,
    concept_intensity, orthogonalize_industry_on_theme, assemble_overlay,
    build_summary, validate_overlay_summary_consistency,
    build_overlay_summary_from_panels, write_overlay_summary, overlay_emit_allowed,
)

GOV_PATH = ROOT / "presets" / "a_short_theme_overlay_governance_20260610.json"


def _pool():
    return pd.DataFrame([
        {"ts_code": "A.SZ", "baseline_rank": 1, "esp_score": 80.0, "l4_score": 60.0,
         "overheat_flag": False, "chasing_high": False, "chase_flag": False, "high_pos_shrink": False},
        {"ts_code": "B.SH", "baseline_rank": 2, "esp_score": 50.0, "l4_score": 70.0,
         "overheat_flag": False, "chasing_high": False, "chase_flag": False, "high_pos_shrink": False},
        {"ts_code": "C.SH", "baseline_rank": 3, "esp_score": 50.0, "l4_score": 70.0,
         "overheat_flag": True, "chasing_high": False, "chase_flag": False, "high_pos_shrink": False},
    ])


def _components():
    theme_heat = {"score": {"A.SZ": None, "B.SH": 90.0, "C.SH": 85.0},
                  "best_concept": {"A.SZ": None, "B.SH": "c1", "C.SH": "c1"}}
    industry_heat_by_l2 = {"半导体": 95.0, "银行": 20.0}
    sw_l2_by_code = {"A.SZ": "银行", "B.SH": "半导体", "C.SH": "半导体"}
    breadth = {"A.SZ": {"up_frac": 0.1, "vol_frac": 0.1, "pass": False},
               "B.SH": {"up_frac": 0.8, "vol_frac": 0.6, "pass": True},
               "C.SH": {"up_frac": 0.8, "vol_frac": 0.6, "pass": True}}
    persistence = {"A.SZ": 0.0, "B.SH": 1.0, "C.SH": 1.0}
    fit = {"A.SZ": None, "B.SH": 0.8, "C.SH": 0.8}   # A unknown
    return theme_heat, industry_heat_by_l2, breadth, persistence, fit, sw_l2_by_code


def _assemble():
    th, ih, br, pe, ft, sw = _components()
    return assemble_overlay(_pool(), th, ih, br, pe, ft, sw)


class ConceptIntensityTests(unittest.TestCase):
    def test_amount_weighted(self):
        dw = pd.DataFrame([
            {"ts_code": "x", "pct_chg": 10.0, "amount": 100.0},
            {"ts_code": "y", "pct_chg": -2.0, "amount": 100.0},
        ])
        self.assertAlmostEqual(concept_intensity(dw, ["x", "y"]), 4.0)

    def test_empty_or_zero_amount_none(self):
        self.assertIsNone(concept_intensity(pd.DataFrame(columns=["ts_code", "pct_chg", "amount"]), ["x"]))


class OrthogonalizeScaleTests(unittest.TestCase):
    def test_output_in_0_100_or_nan(self):
        # R-ASLICEA-INDUSTRY-ORTHO-SCALE: result must be 0-100 (re-normalized), never raw residual.
        df = pd.DataFrame({
            "theme_heat_score": [10.0, 40.0, 70.0, 90.0, None],
            "industry_heat_score": [20.0, 30.0, 80.0, 60.0, 50.0],
        })
        norm = orthogonalize_industry_on_theme(df)
        vals = norm.dropna()
        self.assertTrue((vals >= 0.0).all() and (vals <= 100.0).all())


class AssembleOverlayTests(unittest.TestCase):
    def setUp(self):
        self.df = _assemble()
        self.by = {r["ts_code"]: r for _, r in self.df.iterrows()}

    def test_fit_unknown_blocks_theme_industry_bonus(self):
        a = self.by["A.SZ"]
        self.assertFalse(bool(a["fit_pass"]))
        self.assertFalse(bool(a["eligible"]))
        # fit_pass=false → overlay = esp*0.15 + l4*0.45 only (no bonus, no crowding here)
        self.assertAlmostEqual(a["overlay_score"], 0.15 * 80.0 + 0.45 * 60.0)

    def test_eligible_requires_fit_pass_and_2_pass(self):
        b = self.by["B.SH"]
        self.assertTrue(bool(b["fit_pass"]))
        self.assertTrue(bool(b["eligible"]))
        self.assertEqual(int(b["overlay_rank"]), 1)

    def test_crowding_strips_bonus_heat_cannot_rescue(self):
        c = self.by["C.SH"]
        self.assertTrue(bool(c["crowding_hit"]))
        # crowding → 剥夺红利,overlay 退回 esp+l4 base(高热度不得救回)
        base = 0.15 * 50.0 + 0.45 * 70.0
        self.assertAlmostEqual(c["overlay_score"], base)
        # clean eligible 名(B)即便 C 热度很高也压不过 B
        self.assertGreater(self.by["B.SH"]["overlay_score"], c["overlay_score"])

    def test_fit_pass_but_under_two_gates_no_bonus(self):
        # R-ASLICEA-RUNNER-ELIGIBILITY-BONUS-GATE: fit_pass=true 但只过 1/3 门 → 无红利
        pool = pd.DataFrame([{"ts_code": "D.SZ", "baseline_rank": 1, "esp_score": 50.0, "l4_score": 70.0,
                              "overheat_flag": False, "chasing_high": False, "chase_flag": False,
                              "high_pos_shrink": False}])
        th = {"score": {"D.SZ": 90.0}, "best_concept": {"D.SZ": "c1"}}
        ih = {"半导体": 95.0, "银行": 20.0}
        sw = {"D.SZ": "银行"}                                   # industry_heat 20<70 → industry_pass False
        br = {"D.SZ": {"up_frac": 0.1, "vol_frac": 0.1, "pass": False}}   # breadth fail
        r = assemble_overlay(pool, th, ih, br, {"D.SZ": 1.0}, {"D.SZ": 0.8}, sw).iloc[0]
        self.assertTrue(bool(r["theme_pass"]))
        self.assertFalse(bool(r["industry_pass"]))
        self.assertFalse(bool(r["breadth_pass"]))
        self.assertTrue(bool(r["fit_pass"]))
        self.assertFalse(bool(r["eligible"]))                   # 只过 1/3 → 不合格
        self.assertAlmostEqual(r["overlay_score"], 0.15 * 50.0 + 0.45 * 70.0)  # base only

    def test_industry_norm_in_0_100(self):
        for _, r in self.df.iterrows():
            v = r["industry_heat_norm_ortho"]
            if pd.notna(v):
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 100.0)


class SummaryConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.summary = build_summary(
            _assemble(), as_of="20260612",
            pit_source={"concept_membership": "pit", "sw_mapping": "forward"},
            dropped_at_l0_l5=[], generated_at="2026-06-10T00:00:00+08:00")

    def test_valid_summary_passes(self):
        validate_overlay_summary_consistency(self.summary)

    def test_fit_false_with_bonus_rejected(self):
        s = json.loads(json.dumps(self.summary))
        for c in s["candidates"]:
            if not c["fit_pass"]:
                c["overlay_score"] = (c["overlay_score"] or 0.0) + 25.0
                break
        with self.assertRaises(ValueError):
            validate_overlay_summary_consistency(s)

    def test_industry_norm_out_of_range_rejected(self):
        s = json.loads(json.dumps(self.summary))
        s["candidates"][0]["industry_heat_norm_ortho"] = 250.0
        with self.assertRaises(ValueError):
            validate_overlay_summary_consistency(s)

    def test_eligible_without_fit_pass_rejected(self):
        s = json.loads(json.dumps(self.summary))
        c = s["candidates"][0]
        c["eligible"], c["fit_pass"] = True, False
        with self.assertRaises(ValueError):
            validate_overlay_summary_consistency(s)

    def test_candidate_count_mismatch_rejected(self):
        s = json.loads(json.dumps(self.summary))
        s["candidate_count"] = s["candidate_count"] + 5
        with self.assertRaises(ValueError):
            validate_overlay_summary_consistency(s)

    def test_rank_not_contiguous_rejected(self):
        s = json.loads(json.dumps(self.summary))
        s["candidates"][0]["overlay_rank"] = 999
        with self.assertRaises(ValueError):
            validate_overlay_summary_consistency(s)


class EmitGateAndForwardLabelTests(unittest.TestCase):
    """(b) overlay 在 live(today)也产出、概念标 forward,使其在 live weekly 自然 forward 累积。
    (emit-gate 的 pit+today/not-neutralize 断言见 GovernanceParityTests.test_overlay_emit_pit_and_today_not_neutralize。)"""
    def test_forward_concept_membership_summary_valid(self):
        # today 模式概念标 'forward' 的 summary 须过 schema + consistency(forward 是合法、诚实标签)
        summary = build_summary(
            _assemble(), as_of="20260612",
            pit_source={"concept_membership": "forward", "sw_mapping": "forward"},
            dropped_at_l0_l5=[], generated_at="2026-06-10T00:00:00+08:00")
        self.assertEqual(summary["pit_source"]["concept_membership"], "forward")
        validate_overlay_summary_consistency(summary)
        with tempfile.TemporaryDirectory() as td:           # write = schema + consistency
            write_overlay_summary(summary, os.path.join(td, "overlay.json"))


class EmitOverlayEgsBlockTests(unittest.TestCase):
    """#2(b) R-ASHORT-OVERLAY-LIVE-FORWARD-EMIT-EGS-GUARD:守护从 egs_main 提取的 emit_overlay(真实落点)——
    门控 + 按模式标 concept + 写盘。此前 emit 块无测试、又在 swallow-all except 内,断线/错标会静默过。"""
    def _args(self):
        all_daily, sc, cm, sw = _panels()
        l3 = (None, sc, cm, "20260612")     # 仿 _load_l3_snapshot:(concepts_df, stock_concepts, concept_members, snap_date)
        return _pool(), all_daily, l3, sw

    def _emit(self, mode, l3, td):
        from runners.a_short_theme_overlay_comparison import emit_overlay
        pool, ad, _l3, sw = self._args()
        p = os.path.join(td, "overlay.json")
        out = emit_overlay(mode, pool, ad, (l3 if l3 != "use" else _l3), sw,
                           "20260612", "2026-06-12T00:00:00+08:00", p)
        return out, p

    def test_today_emits_forward_label(self):
        with tempfile.TemporaryDirectory() as td:
            out, p = self._emit("today", "use", td)
            self.assertEqual(out, p)
            self.assertEqual(json.loads(Path(p).read_text(encoding="utf-8"))["pit_source"]["concept_membership"], "forward")

    def test_pit_emits_pit_label(self):
        with tempfile.TemporaryDirectory() as td:
            out, p = self._emit("pit", "use", td)
            self.assertEqual(out, p)
            self.assertEqual(json.loads(Path(p).read_text(encoding="utf-8"))["pit_source"]["concept_membership"], "pit")

    def test_neutralize_skips_no_write(self):
        with tempfile.TemporaryDirectory() as td:
            out, p = self._emit("neutralize", "use", td)
            self.assertIsNone(out)
            self.assertFalse(os.path.exists(p))

    def test_no_snapshot_skips_no_write(self):
        with tempfile.TemporaryDirectory() as td:
            out, p = self._emit("today", None, td)
            self.assertIsNone(out)
            self.assertFalse(os.path.exists(p))


class GovernanceParityTests(unittest.TestCase):
    def test_weights_and_thresholds_match_governance(self):
        gov = json.loads(GOV_PATH.read_text(encoding="utf-8"))
        self.assertEqual(gov["overlay_weights"], OVERLAY_WEIGHTS)
        self.assertEqual(gov["thresholds"], EMITTED_THRESHOLDS)

    def test_governance_does_not_define_a_second_adjudication_route(self):
        gov = json.loads(GOV_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("promotion_rule", gov)
        self.assertFalse(gov["scope"]["production_ranking_changed_by_this_artifact"])

    def test_governance_egs_main_boundary_honest(self):
        # A 方案 wiring: egs_main runtime DID gain a non-production side-output, but production
        # scoring (final_score/tier/admission) is UNCHANGED. Both must be machine-asserted honestly.
        gov = json.loads(GOV_PATH.read_text(encoding="utf-8"))
        self.assertTrue(gov["scope"]["egs_main_runtime_changed"])              # side-output added
        self.assertFalse(gov["scope"]["egs_main_production_behavior_changed"])  # scoring untouched
        self.assertFalse(gov["scope"]["production_ranking_changed_by_this_artifact"])

    def test_overlay_emit_pit_and_today_not_neutralize(self):
        # R-ASHORT-OVERLAY-L3-MODE-BOUNDARY-DRIFT (updated by (b) 2026-06-16): pit + today emit
        # (pit→concept 'pit';today→concept 'forward',honest live 决策当日成员 → live forward 累积);
        # neutralize/None/"" 不产出。原为 pit-only;(b) 加 today 让 overlay 在 live weekly 自然累积。
        from runners.a_short_theme_overlay_comparison import overlay_emit_allowed
        self.assertTrue(overlay_emit_allowed("pit"))
        self.assertTrue(overlay_emit_allowed("today"))
        for m in ("neutralize", None, ""):
            self.assertFalse(overlay_emit_allowed(m), m)


def _panels():
    """Synthetic in-memory EGS data (A 方案 inputs): all_daily ≥60 dates + concepts + sw_map + pool."""
    import itertools
    stocks = ["A.SZ", "B.SH", "C.SH"]
    dates = [f"202601{d:02d}" for d in range(1, 29)] + [f"202602{d:02d}" for d in range(1, 33)]  # ~60
    rows = []
    for i, (code, d) in enumerate(itertools.product(stocks, dates)):
        rows.append({"ts_code": code, "trade_date": d,
                     "pct_chg": (2.0 if code == "B.SH" else (1.0 if code == "C.SH" else -0.5)),
                     "amount": 1e8 + (i % 7) * 1e7})
    all_daily = pd.DataFrame(rows)
    stock_concepts = {"A.SZ": ["c1"], "B.SH": ["c1"], "C.SH": ["c2"]}
    concept_members = {"c1": ["A.SZ", "B.SH"], "c2": ["C.SH"]}
    sw_map = {"A.SZ": {"l2_name": "银行"}, "B.SH": {"l2_name": "半导体"}, "C.SH": {"l2_name": "半导体"}}
    return all_daily, stock_concepts, concept_members, sw_map


class BuildFromPanelsTests(unittest.TestCase):
    def test_assembles_valid_summary(self):
        all_daily, sc, cm, sw = _panels()
        summary = build_overlay_summary_from_panels(
            _pool(), all_daily, sc, cm, sw, as_of="20260612",
            generated_at="2026-06-12T00:00:00+08:00")
        validate_overlay_summary_consistency(summary)            # no raise
        self.assertEqual(summary["candidate_count"], 3)
        self.assertEqual(summary["track"], "comparison_non_production")
        self.assertFalse(any(summary["boundary"].values()))

    def test_write_roundtrip(self):
        import json
        all_daily, sc, cm, sw = _panels()
        summary = build_overlay_summary_from_panels(
            _pool(), all_daily, sc, cm, sw, as_of="20260612",
            generated_at="2026-06-12T00:00:00+08:00")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "overlay.json"
            write_overlay_summary(summary, str(p))
            loaded = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(loaded["candidate_count"], 3)


if __name__ == "__main__":
    unittest.main()
