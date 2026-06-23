# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 shadow scoring_profile selection comparison (engine/us_short_shadow_compare.py).

Covers: deterministic FIXED top_n selection per frozen profile (core_score desc, ticker asc tie-break, 禁止挑样本);
theme_off attribution baseline marginal — balanced − theme_off selection diff computable + non-degenerate (#24);
ship-gate isolation boundary + balanced = sole primary (#13); reproducibility; empty / undersized pool edges; the
whole malformed-input class (pool / row / ticker / blocks / top_n); the frozen-profile contract lock — weights /
role / live_eligible / shadow_only enforced on the loaded preset, the SCORER dependency (core_score), AND the
emitted artifact (governance-drift: second primary / shadow turned live / no primary / runtime weight drift /
scorer-dependency weight drift; output tamper: weight / role / flag); and the output-contract validator rejecting
tampered artifacts. Pure/offline; no provider/live; no A-share crossing.
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_shadow_compare as sc  # noqa: E402
import engine.us_short_core_score as cs  # noqa: E402

# A small deterministic pool with hand-computable core_score under each frozen profile. blocks are 0-100.
POOL = [
    {"ticker": "AAA", "blocks": {"momentum": 90, "theme": 10, "catalyst": 50}},  # momentum-heavy
    {"ticker": "BBB", "blocks": {"momentum": 10, "theme": 90, "catalyst": 50}},  # theme-heavy
    {"ticker": "CCC", "blocks": {"momentum": 50, "theme": 50, "catalyst": 50}},  # neutral
    {"ticker": "DDD", "blocks": {"momentum": 20, "theme": 20, "catalyst": 90}},  # catalyst-heavy
    {"ticker": "EEE", "blocks": {"momentum": 60, "theme": 60, "catalyst": 20}},  # momentum+theme
]
# balanced(.40/.35/.25): AAA 52, CCC 50, EEE 50, BBB 48, DDD 37.5 → top3 {AAA,CCC,EEE}
# theme_off(.6154/0/.3846): AAA 74.6, CCC 50, DDD 46.9, EEE 44.6, BBB 25.4 → top3 {AAA,CCC,DDD}
# theme_plus(.30/.50/.20): BBB 58, EEE 52, CCC 50, AAA 42, DDD 34 → top3 {BBB,EEE,CCC}


class Selection(unittest.TestCase):
    def test_balanced_topn_is_deterministic_with_ticker_tiebreak(self):
        r = sc.build_shadow_comparison(POOL, top_n=3)
        sel = r["profiles"]["balanced"]["selection"]
        self.assertEqual([row["ticker"] for row in sel], ["AAA", "CCC", "EEE"])  # CCC<EEE tie broken by ticker asc
        self.assertEqual([row["rank"] for row in sel], [1, 2, 3])
        self.assertAlmostEqual(sel[0]["core_score"], 52.0)
        self.assertAlmostEqual(sel[1]["core_score"], 50.0)
        self.assertAlmostEqual(sel[2]["core_score"], 50.0)

    def test_theme_plus_reweights_selection(self):
        r = sc.build_shadow_comparison(POOL, top_n=3)
        self.assertEqual({row["ticker"] for row in r["profiles"]["theme_plus"]["selection"]}, {"BBB", "EEE", "CCC"})

    def test_all_frozen_profiles_present(self):
        r = sc.build_shadow_comparison(POOL, top_n=3)
        self.assertEqual(set(r["profiles"]), {"balanced", "theme_plus", "theme_aggressive", "theme_off"})

    def test_fixed_topn_full_output_not_cherrypicked(self):
        # every profile emits exactly top_n rows in rank order — no subset of after-the-fact winners
        r = sc.build_shadow_comparison(POOL, top_n=4)
        for name in r["profiles"]:
            sel = r["profiles"][name]["selection"]
            self.assertEqual(len(sel), 4)
            self.assertEqual([row["rank"] for row in sel], [1, 2, 3, 4])

    def test_reproducible(self):
        self.assertEqual(sc.build_shadow_comparison(POOL, top_n=3), sc.build_shadow_comparison(POOL, top_n=3))


class ThemeOffMarginal(unittest.TestCase):
    """#24 — theme_off (theme weight = 0) is the attribution baseline; balanced − theme_off = theme marginal."""

    def test_theme_off_weight_is_zero(self):
        r = sc.build_shadow_comparison(POOL, top_n=3)
        self.assertEqual(r["profiles"]["theme_off"]["weights"]["theme"], 0.0)

    def test_balanced_minus_theme_off_is_computable_and_nondegenerate(self):
        r = sc.build_shadow_comparison(POOL, top_n=3)
        diff = r["vs_balanced"]["theme_off"]
        self.assertEqual(diff["balanced_only"], ["EEE"])   # 35% theme weight pulled EEE into balanced
        self.assertEqual(diff["shadow_extra"], ["DDD"])    # theme_off (catalyst gets more) pulls DDD in
        self.assertEqual(diff["overlap_count"], 2)         # {AAA, CCC}
        self.assertTrue(diff["balanced_only"])             # marginal contribution is non-empty (the test #24 asks for)

    def test_vs_balanced_covers_only_shadow_profiles(self):
        r = sc.build_shadow_comparison(POOL, top_n=3)
        self.assertEqual(set(r["vs_balanced"]), {"theme_plus", "theme_aggressive", "theme_off"})


class ShipGateIsolation(unittest.TestCase):
    """#13 — shadow profiles never count ship-gate; balanced is the sole primary / live track."""

    def test_boundary_block_is_frozen(self):
        r = sc.build_shadow_comparison(POOL, top_n=3)
        self.assertEqual(r["boundary"], {"production": False, "is_buy_advice": False,
                                         "shadow_counts_ship_gate": False, "changes_primary_selection": False})
        self.assertEqual(r["track"], "comparison_non_production")

    def test_balanced_is_sole_primary_live(self):
        r = sc.build_shadow_comparison(POOL, top_n=3)
        self.assertEqual(r["primary_profile"], "balanced")
        bal = r["profiles"]["balanced"]
        self.assertEqual((bal["role"], bal["live_eligible"], bal["shadow_only"]), ("primary", True, False))
        for name in ("theme_plus", "theme_aggressive", "theme_off"):
            p = r["profiles"][name]
            self.assertTrue(p["shadow_only"])
            self.assertFalse(p["live_eligible"])

    def test_min_comparison_weeks_surfaced(self):
        r = sc.build_shadow_comparison(POOL, top_n=3)
        self.assertEqual(r["min_comparison_weeks"], 12)


class PoolEdges(unittest.TestCase):
    def test_topn_larger_than_pool_selects_all(self):
        small = POOL[:2]
        r = sc.build_shadow_comparison(small, top_n=5)
        self.assertEqual(r["pool_size"], 2)
        for name in r["profiles"]:
            self.assertEqual(len(r["profiles"][name]["selection"]), 2)

    def test_empty_pool(self):
        r = sc.build_shadow_comparison([], top_n=3)
        self.assertEqual(r["pool_size"], 0)
        for name in r["profiles"]:
            self.assertEqual(r["profiles"][name]["selection"], [])
        for name in r["vs_balanced"]:
            self.assertEqual(r["vs_balanced"][name], {"balanced_only": [], "shadow_extra": [], "overlap_count": 0})


class MalformedInput(unittest.TestCase):
    def test_pool_not_list(self):
        with self.assertRaises(sc.ShadowCompareError):
            sc.build_shadow_comparison({"ticker": "AAA"}, top_n=3)

    def test_row_not_dict(self):
        with self.assertRaises(sc.ShadowCompareError):
            sc.build_shadow_comparison(["AAA"], top_n=3)

    def test_ticker_missing_or_blank(self):
        for bad in ({"blocks": {}}, {"ticker": "  ", "blocks": {}}, {"ticker": 123, "blocks": {}}):
            with self.assertRaises(sc.ShadowCompareError):
                sc.build_shadow_comparison([bad], top_n=3)

    def test_duplicate_ticker(self):
        with self.assertRaises(sc.ShadowCompareError):
            sc.build_shadow_comparison([{"ticker": "AAA", "blocks": {}}, {"ticker": "AAA", "blocks": {}}], top_n=3)

    def test_blocks_not_dict(self):
        with self.assertRaises(sc.ShadowCompareError):
            sc.build_shadow_comparison([{"ticker": "AAA", "blocks": [1, 2]}], top_n=3)

    def test_topn_not_positive_int(self):
        for bad in (0, -1, 3.0, True, "3", None):
            with self.assertRaises(sc.ShadowCompareError):
                sc.build_shadow_comparison(POOL, top_n=bad)


class GovernanceDrift(unittest.TestCase):
    """The frozen scoring_profile governance is the single source; a post-review drift must fail closed."""

    def _run_with_profiles(self, mutate):
        saved = sc._PROFILES
        drifted = copy.deepcopy(saved)
        mutate(drifted)
        sc._PROFILES = drifted
        try:
            sc.build_shadow_comparison(POOL, top_n=3)
        finally:
            sc._PROFILES = saved

    def test_second_primary_rejected(self):
        def mutate(p):
            p["theme_plus"]["role"] = "primary"
            p["theme_plus"]["live_eligible"] = True
            p["theme_plus"]["shadow_only"] = False
        with self.assertRaises(sc.ShadowCompareError):
            self._run_with_profiles(mutate)

    def test_shadow_turned_live_rejected(self):
        with self.assertRaises(sc.ShadowCompareError):
            self._run_with_profiles(lambda p: p["theme_plus"].__setitem__("live_eligible", True))

    def test_no_primary_rejected(self):
        with self.assertRaises(sc.ShadowCompareError):
            self._run_with_profiles(lambda p: p["balanced"].__setitem__("live_eligible", False))

    def test_runtime_weight_drift_rejected(self):
        # theme_off weights drift while role/live/shadow flags stay superficially valid — the #24 theme-weight-0
        # baseline would silently break; the const-pin must catch the loaded-preset weight drift
        with self.assertRaises(sc.ShadowCompareError):
            self._run_with_profiles(lambda p: p["theme_off"].__setitem__(
                "weights", {"momentum": 0.50, "theme": 0.25, "catalyst": 0.25}))

    def test_scorer_weight_drift_rejected(self):
        # drift the SCORER's weights (core_score's OWN _PROFILES) independently of shadow_compare's _PROFILES —
        # the build must REJECT, not emit a frozen-looking artifact whose selection was scored with drifted
        # weights (the scorer-dependency drift gap, distinct from this module's own _PROFILES)
        saved = cs._PROFILES
        drifted = copy.deepcopy(saved)
        drifted["theme_off"]["weights"] = {"momentum": 0.0, "theme": 1.0, "catalyst": 0.0}
        cs._PROFILES = drifted
        try:
            with self.assertRaises(sc.ShadowCompareError):
                sc.build_shadow_comparison(POOL, top_n=3)
        finally:
            cs._PROFILES = saved


class OutputValidator(unittest.TestCase):
    """validate_shadow_comparison self-checks the artifact; tampered fields must be rejected."""

    def setUp(self):
        self.good = sc.build_shadow_comparison(POOL, top_n=3)

    def _tamper(self, mutate):
        bad = copy.deepcopy(self.good)
        mutate(bad)
        with self.assertRaises(sc.ShadowCompareError):
            sc.validate_shadow_comparison(bad)

    def test_good_passes(self):
        sc.validate_shadow_comparison(self.good)  # no raise

    def test_boundary_tampered(self):
        self._tamper(lambda b: b["boundary"].__setitem__("shadow_counts_ship_gate", True))

    def test_track_tampered(self):
        self._tamper(lambda b: b.__setitem__("track", "production"))

    def test_min_weeks_tampered(self):
        self._tamper(lambda b: b.__setitem__("min_comparison_weeks", 1))

    def test_selection_length_tampered(self):
        self._tamper(lambda b: b["profiles"]["balanced"]["selection"].pop())

    def test_selection_order_tampered(self):
        # bump a lower-ranked score above its predecessor (ranks stay 1..k) → breaks the score-desc invariant
        self._tamper(lambda b: b["profiles"]["balanced"]["selection"][2].__setitem__("core_score", 999.0))

    def test_rank_tampered(self):
        self._tamper(lambda b: b["profiles"]["balanced"]["selection"][0].__setitem__("rank", 9))

    def test_missing_profile(self):
        self._tamper(lambda b: b["profiles"].pop("theme_off"))

    def test_vs_balanced_inconsistent(self):
        self._tamper(lambda b: b["vs_balanced"]["theme_off"].__setitem__("balanced_only", ["ZZZ"]))

    def test_duplicate_ticker_in_selection(self):
        def mutate(b):
            s = b["profiles"]["balanced"]["selection"]
            s[1]["ticker"] = s[0]["ticker"]
        self._tamper(mutate)

    def test_output_weight_tampered(self):
        # the emitted contract must be locked to the frozen weights, not just trusted from the deriver
        self._tamper(lambda b: b["profiles"]["theme_off"]["weights"].__setitem__("theme", 0.99))

    def test_output_role_tampered(self):
        self._tamper(lambda b: b["profiles"]["theme_plus"].__setitem__("role", "primary_shadow_weird"))

    def test_output_shadow_flag_tampered(self):
        self._tamper(lambda b: b["profiles"]["theme_plus"].__setitem__("shadow_only", "yes"))


if __name__ == "__main__":
    unittest.main()
