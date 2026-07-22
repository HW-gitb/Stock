"""Tests for engine/egs_industry_heat.py — production EGS SW L2 industry_heat + governed weights.

Covers: industry_heat definition (0-100 cross-industry percentile, unknown→NaN), weight profiles
sum to 1.0 + active=balanced (LIVE promotion; legacy retained as rollback/regression anchor),
governance schema (profiles + industry_heat_def const-pinned), the legacy profile being
byte-identical to the pre-change formula (esp*.20+cat*.30+l4*.50, the regression anchor / rollback),
industry heat ranking-only (cannot rescue overheat/chasing/unknown-industry demotion), and
selection_diff + per-variant top-N. Pure module; no egs_main import (egs_main has an import-time side effect).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tempfile  # noqa: E402

from engine.egs_industry_heat import (  # noqa: E402
    compute_industry_heat_score, load_governance, get_active_weights, egs_base,
    final_score_and_tier, select_profile_watch_pool, selection_diff,
    build_weight_comparison, write_weight_comparison, GOV_PATH,
)

GOV_SCHEMA = ROOT / "schemas" / "egs_industry_heat_governance.schema.json"
LEGACY = {"esp": 0.20, "cat": 0.30, "l4": 0.50, "industry_heat": 0.00}
BALANCED = {"esp": 0.20, "cat": 0.25, "l4": 0.40, "industry_heat": 0.15}


def _df(rows):
    base_cols = {"l2_flags": "", "cat_flag": "", "overheat_flag": False, "chasing_high": False,
                 "esp_raw": 1.0, "val_bonus": 0.0, "reduce_penalty": 0.0, "val_penalty": 0.0}
    out = []
    for r in rows:
        d = dict(base_cols)
        d.update(r)
        out.append(d)
    return pd.DataFrame(out)


def _universe():
    # 3 industries: HOT (high 20d/60d), MID, COLD. 4 stocks each so tier quantiles are meaningful.
    rows = []
    spec = [("HOT", 12.0, 30.0), ("MID", 4.0, 10.0), ("COLD", -3.0, -8.0)]
    for ind, p20, p60 in spec:
        for i in range(4):
            rows.append({"ts_code": f"{ind}{i}.SH", "l2_name": ind,
                         "l1_name": f"L1_{ind}",
                         "pct_20d_n": p20 + i * 0.1, "pct_60d_n": p60 + i * 0.1,
                         "esp_score": 60.0, "cat_score": 60.0, "l4_score": 60.0,
                         "q0_dt_yoy": 10.0})
    return _df(rows)


class IndustryHeatTests(unittest.TestCase):
    def test_range_and_ordering(self):
        df = _universe()
        df["industry_heat_score"] = compute_industry_heat_score(df)
        by_ind = df.groupby("l2_name")["industry_heat_score"].first()
        self.assertTrue(((by_ind >= 0) & (by_ind <= 100)).all())
        self.assertGreater(by_ind["HOT"], by_ind["MID"])
        self.assertGreater(by_ind["MID"], by_ind["COLD"])

    def test_unknown_and_missing_is_nan(self):
        df = _df([{"ts_code": "U.SH", "l2_name": "未知", "pct_20d_n": 9.0, "pct_60d_n": 9.0,
                   "esp_score": 50, "cat_score": 50, "l4_score": 50},
                  {"ts_code": "A.SH", "l2_name": "X", "pct_20d_n": 9.0, "pct_60d_n": 9.0,
                   "esp_score": 50, "cat_score": 50, "l4_score": 50}])
        s = compute_industry_heat_score(df)
        self.assertTrue(np.isnan(s.iloc[0]))           # 未知 industry → NaN

    def test_empty_df(self):
        s = compute_industry_heat_score(_df([]))
        self.assertEqual(len(s), 0)

    def test_definition_pinned_values(self):
        # production-pinned def: per-L2 median momentum → cross-industry percentile. 2 industries → 50/100.
        df = _df([{"ts_code": "A.SH", "l2_name": "A", "pct_20d_n": 10.0, "pct_60d_n": 10.0,
                   "esp_score": 50, "cat_score": 50, "l4_score": 50},
                  {"ts_code": "B.SH", "l2_name": "B", "pct_20d_n": 2.0, "pct_60d_n": 2.0,
                   "esp_score": 50, "cat_score": 50, "l4_score": 50}])
        s = compute_industry_heat_score(df)
        self.assertAlmostEqual(s.iloc[0], 100.0)   # A = hotter industry
        self.assertAlmostEqual(s.iloc[1], 50.0)    # B = cooler

    def test_does_not_mutate_l4(self):
        # l4-overlap treatment: industry_heat is a SEPARATE additive term; it must not touch l4_score.
        df = _universe()
        before = df["l4_score"].copy()
        _ = compute_industry_heat_score(df)
        pd.testing.assert_series_equal(df["l4_score"], before)


class WeightProfileTests(unittest.TestCase):
    def test_governance_schema_and_sums(self):
        gov = load_governance()
        with open(GOV_SCHEMA, encoding="utf-8") as f:
            jsonschema.validate(gov, json.load(f))
        for name, w in gov["profiles"].items():
            self.assertAlmostEqual(sum(w.values()), 1.0, places=9, msg=f"{name} weights must sum to 1")

    def test_active_profile_is_balanced(self):
        # v1 LIVE: balanced is the active production formula (raises industry/theme → changes selection).
        name, w = get_active_weights()
        self.assertEqual(name, "balanced")
        self.assertEqual(w, BALANCED)

    def test_legacy_profile_retained_as_rollback_anchor(self):
        # legacy profile kept as one-flag rollback + regression anchor = egs_main's pre-change formula.
        self.assertEqual(load_governance()["profiles"]["legacy"], LEGACY)

    def test_schema_rejects_profile_weight_drift(self):
        # const-pinned profiles: any drift from a frozen weight must be rejected.
        gov = load_governance()
        with open(GOV_SCHEMA, encoding="utf-8") as f:
            schema = json.load(f)
        gov["profiles"]["balanced"]["esp"] = 1.0          # drift from const 0.20
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(gov, schema)

    def test_active_weights_actually_differ_from_legacy(self):
        # the promotion is real: the active (balanced) weights are not the legacy weights.
        _, w = get_active_weights()
        self.assertNotEqual(w, LEGACY)

    def test_schema_rejects_deleted_or_fake_industry_heat_def(self):
        # R-EGS-INDHEAT-DEF-SCHEMA-UNPINNED: the production industry_heat definition is schema-pinned.
        with open(GOV_SCHEMA, encoding="utf-8") as f:
            schema = json.load(f)
        gone = load_governance()
        del gone["industry_heat_def"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(gone, schema)
        fake = load_governance()
        fake["industry_heat_def"] = {"level": "fake", "windows": ["future_return"], "l1_fallback": True}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(fake, schema)


class EgsBaseTests(unittest.TestCase):
    def test_legacy_byte_identical_even_with_industry_heat(self):
        df = _universe()
        df["industry_heat_score"] = compute_industry_heat_score(df)   # non-zero present
        got = egs_base(df, LEGACY)
        expect = df["esp_score"] * 0.20 + df["cat_score"] * 0.30 + df["l4_score"] * 0.50
        pd.testing.assert_series_equal(got, expect, check_names=False)

    def test_nan_industry_heat_does_not_poison(self):
        df = _df([{"ts_code": "U.SH", "l2_name": "未知", "esp_score": 50, "cat_score": 50,
                   "l4_score": 50, "pct_20d_n": 1.0, "pct_60d_n": 1.0, "q0_dt_yoy": 1.0}])
        df["industry_heat_score"] = compute_industry_heat_score(df)   # NaN
        self.assertFalse(np.isnan(egs_base(df, BALANCED).iloc[0]))    # fillna(0) → finite

    def test_balanced_changes_score_vs_legacy(self):
        df = _universe()
        df["industry_heat_score"] = compute_industry_heat_score(df)
        self.assertFalse(np.allclose(egs_base(df, LEGACY), egs_base(df, BALANCED)))


class TierTests(unittest.TestCase):
    def test_industry_heat_cannot_rescue_overheat(self):
        # A hot-industry stock flagged overheat must NOT end up Tier1 even when balanced boosts it.
        df = _universe()
        df.loc[df["ts_code"] == "HOT0.SH", "overheat_flag"] = True
        df["industry_heat_score"] = compute_industry_heat_score(df)
        out, _ = final_score_and_tier(df, BALANCED)
        self.assertNotEqual(out.loc[out["ts_code"] == "HOT0.SH", "tier"].iloc[0], "Tier1")

    def test_unknown_industry_not_tier1(self):
        df = _universe()
        df.loc[df["ts_code"] == "HOT1.SH", "l2_name"] = "未知"
        df["industry_heat_score"] = compute_industry_heat_score(df)
        out, _ = final_score_and_tier(df, BALANCED)
        self.assertNotEqual(out.loc[out["ts_code"] == "HOT1.SH", "tier"].iloc[0], "Tier1")

    def test_legacy_final_score_formula(self):
        df = _universe()
        df["industry_heat_score"] = compute_industry_heat_score(df)
        out, info = final_score_and_tier(df, LEGACY)
        # all clean (mult 1, deduct 0, val_bonus 0) → final == egs_base rounded
        expect = (df["esp_score"] * 0.20 + df["cat_score"] * 0.30 + df["l4_score"] * 0.50).round(2)
        pd.testing.assert_series_equal(out["final_score"], expect, check_names=False)
        self.assertIn("fin_coverage", info)


class SelectionDiffTests(unittest.TestCase):
    def test_diff_shape_and_hot_entry(self):
        df = _universe()
        df["industry_heat_score"] = compute_industry_heat_score(df)
        d = selection_diff(df, LEGACY, BALANCED)
        for k in ("base_tier1_n", "cand_tier1_n", "added", "removed", "kept_n",
                  "base_overheat_share", "cand_overheat_share"):
            self.assertIn(k, d)
        self.assertIsInstance(d["added"], list)


class ProfileWatchPoolTests(unittest.TestCase):
    def test_tier1_only_score_order_and_short_pool(self):
        df = _df([
            {"ts_code": "T2.SH", "tier": "Tier2", "final_score": 99.0, "l4_score": 99.0,
             "pct_20d_n": 99.0, "l1_name": "L1_A", "l2_name": "L2_A", "cat_score": 50},
            {"ts_code": "A.SH", "tier": "Tier1", "final_score": 90.0, "l4_score": 8.0,
             "pct_20d_n": 4.0, "l1_name": "L1_A", "l2_name": "L2_A", "cat_score": 50},
            {"ts_code": "B.SH", "tier": "Tier1", "final_score": 80.0, "l4_score": 9.0,
             "pct_20d_n": 3.0, "l1_name": "L1_B", "l2_name": "L2_B", "cat_score": 50},
            {"ts_code": "C.SH", "tier": "Tier1", "final_score": 70.0, "l4_score": 7.0,
             "pct_20d_n": 5.0, "l1_name": "L1_C", "l2_name": "L2_C", "cat_score": 50},
        ])
        pool = select_profile_watch_pool(df, top_n=15)
        self.assertEqual(pool["ts_code"].tolist(), ["A.SH", "B.SH", "C.SH"])
        self.assertTrue((pool["tier"] == "Tier1").all())
        self.assertEqual(
            select_profile_watch_pool(df, top_n=50).head(15)["ts_code"].tolist(),
            pool["ts_code"].tolist(),
        )

    def test_required_selection_fields_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "l1_name"):
            select_profile_watch_pool(_universe().drop(columns=["l1_name"]))

    def test_l2_overflow_cap_golden(self):
        rows = []
        rank = 1000.0
        for big_index in range(21):
            rows.append({
                "ts_code": f"BIG{big_index:02}.SH", "tier": "Tier1",
                "final_score": rank, "l4_score": 0.0, "pct_20d_n": 0.0,
                "l1_name": f"L1_BIG_{big_index:02}", "l2_name": "L2_BIG",
            })
            rank -= 1.0
            for peer_index in range(3):
                rows.append({
                    "ts_code": f"PEER{big_index:02}_{peer_index}.SH", "tier": "Tier1",
                    "final_score": rank, "l4_score": 0.0, "pct_20d_n": 0.0,
                    "l1_name": f"L1_PEER_{big_index:02}_{peer_index}",
                    "l2_name": f"L2_PEER_{big_index:02}_{peer_index}",
                })
                rank -= 1.0

        pool = select_profile_watch_pool(_df(rows), top_n=100)
        self.assertEqual(
            pool.loc[pool["l2_name"] == "L2_BIG", "ts_code"].tolist(),
            [f"BIG{index:02}.SH" for index in range(15)],
        )

    def test_incremental_concentration_golden(self):
        pool = select_profile_watch_pool(_df([
            {"ts_code": "A0.SH", "tier": "Tier1", "final_score": 100.0, "l4_score": 0.0,
             "pct_20d_n": 0.0, "l1_name": "L1_A", "l2_name": "L2_A"},
            {"ts_code": "B0.SH", "tier": "Tier1", "final_score": 99.0, "l4_score": 0.0,
             "pct_20d_n": 0.0, "l1_name": "L1_B", "l2_name": "L2_B"},
            {"ts_code": "A1.SH", "tier": "Tier1", "final_score": 98.0, "l4_score": 0.0,
             "pct_20d_n": 0.0, "l1_name": "L1_A", "l2_name": "L2_A"},
            {"ts_code": "C0.SH", "tier": "Tier1", "final_score": 97.0, "l4_score": 0.0,
             "pct_20d_n": 0.0, "l1_name": "L1_C", "l2_name": "L2_C"},
            {"ts_code": "A2.SH", "tier": "Tier1", "final_score": 96.0, "l4_score": 0.0,
             "pct_20d_n": 0.0, "l1_name": "L1_A", "l2_name": "L2_A"},
            {"ts_code": "D0.SH", "tier": "Tier1", "final_score": 95.0, "l4_score": 0.0,
             "pct_20d_n": 0.0, "l1_name": "L1_D", "l2_name": "L2_D"},
            {"ts_code": "A3.SH", "tier": "Tier1", "final_score": 94.0, "l4_score": 0.0,
             "pct_20d_n": 0.0, "l1_name": "L1_A", "l2_name": "L2_A"},
        ]), top_n=15)
        self.assertEqual(pool["ts_code"].tolist(), ["A0.SH", "B0.SH", "C0.SH", "D0.SH", "A3.SH"])

    def test_egs_uses_the_same_selector_for_top_pool_and_production_watch(self):
        source = (ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8")
        self.assertIn('top_df = select_profile_watch_pool(df, top_n=CONF["top_n"])', source)
        self.assertIn("watch_df  = select_profile_watch_pool(df_full, top_n=watch_n)", source)

    def test_active_balanced_profile_pool_matches_the_formal_watch_pool(self):
        df = _universe()
        # score_l5 calculates the production industry heat before it applies
        # the active profile; build_weight_comparison must receive that same
        # frozen run universe rather than derive a different cross-section.
        df["industry_heat_score"] = compute_industry_heat_score(df)
        active_profile, active_weights = get_active_weights()
        self.assertEqual(active_profile, "balanced")
        formal_scored, _ = final_score_and_tier(df, active_weights)
        formal_codes = select_profile_watch_pool(formal_scored, top_n=15)["ts_code"].tolist()

        comparison = build_weight_comparison(df)
        comparison_codes = [
            row["ts_code"]
            for row in comparison["profile_watch_pool_top15"]["profiles"][active_profile]
        ]
        self.assertEqual(comparison_codes, formal_codes)


class WeightComparisonTests(unittest.TestCase):
    def test_build_covers_all_nonlegacy_variants(self):
        df = _universe()
        out = build_weight_comparison(df)
        self.assertEqual(out["schema_name"], "egs_weight_comparison")
        self.assertFalse(any(out["boundary"].values()))
        self.assertEqual(set(out["legacy_vs"].keys()), {"balanced", "aggressive", "theme_double"})

    def test_variant_top_n_lists_all_profiles_comparison_only(self):
        df = _universe()
        out = build_weight_comparison(df, top_n=5)
        vt = out["variant_top_n"]
        self.assertEqual(set(vt["profiles"].keys()), {"legacy", "balanced", "aggressive", "theme_double"})
        for name, rows in vt["profiles"].items():
            self.assertLessEqual(len(rows), 5, name)
            for r in rows:
                self.assertIn("ts_code", r)
                self.assertIn("final_score", r)
        # comparison-only labelling must be present + variant lists explicitly non-tradeable
        self.assertIn("NOT tradeable", vt["_label"])
        self.assertFalse(out["boundary"]["variant_lists_are_tradeable"])

    def test_p5_watch_pool_lists_all_profiles_via_tier1_selector(self):
        out = build_weight_comparison(_universe())
        pools = out["profile_watch_pool_top15"]
        self.assertEqual(pools["top_n"], 15)
        self.assertEqual(set(pools["profiles"]), {"legacy", "balanced", "aggressive", "theme_double"})
        for rows in pools["profiles"].values():
            self.assertLessEqual(len(rows), 15)
            self.assertTrue(all(row["tier"] == "Tier1" for row in rows))

    def test_write_roundtrip_with_as_of(self):
        df = _universe()
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "wc.json"
            write_weight_comparison(df, str(p), as_of="20260611")
            loaded = json.loads(p.read_text(encoding="utf-8"))
        self.assertIn("balanced", loaded["legacy_vs"])
        self.assertEqual(loaded["universe_n"], len(df))
        self.assertEqual(loaded["as_of"], "20260611")


if __name__ == "__main__":
    unittest.main()
