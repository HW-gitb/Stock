# -*- coding: utf-8 -*-
"""Tests for US-short macro_cluster (engine/us_short_macro_cluster.py) — §8 宏观集群集中度.

Adversarial focus: a malformed / out-of-domain exposure fails CLOSED to a soft warning (`elevated`,
never the lenient `none`), v1 NEVER applies a hard cap, and the high-warning effects are copy-safe.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_macro_cluster as mc  # noqa: E402

_GOV = ROOT / "presets" / "us_short_macro_cluster_governance_20260620.json"


class ClassifyTests(unittest.TestCase):
    def test_levels_by_exposure(self):
        self.assertEqual(mc.classify_macro_cluster_warning(0.50), "high")
        self.assertEqual(mc.classify_macro_cluster_warning(0.30), "elevated")
        self.assertEqual(mc.classify_macro_cluster_warning(0.10), "none")

    def test_boundaries_inclusive(self):
        self.assertEqual(mc.classify_macro_cluster_warning(mc.HIGH_FRAC), "high")
        self.assertEqual(mc.classify_macro_cluster_warning(mc.ELEVATED_FRAC), "elevated")
        self.assertEqual(mc.classify_macro_cluster_warning(mc.HIGH_FRAC - 1e-9), "elevated")

    def test_malformed_fails_closed_to_elevated_not_none(self):
        # cannot measure concentration → conservative soft warning, NEVER the lenient `none`
        for bad in (None, "0.5", True, False, float("nan"), float("inf"), -0.1, 1.5, [0.5]):
            self.assertEqual(mc.classify_macro_cluster_warning(bad), "elevated", repr(bad))


class EffectsTests(unittest.TestCase):
    def test_v1_never_hard_caps(self):
        self.assertTrue(mc.NO_HARD_CAP)  # preset declares soft-only
        for lvl in ("none", "elevated", "high"):
            self.assertFalse(mc.macro_cluster_effects_for(lvl)["hard_cap"], lvl)

    def test_high_effects_present_and_soft(self):
        e = mc.macro_cluster_effects_for("high")
        self.assertFalse(e["hard_cap"])
        self.assertTrue(any(k for k in e))  # has soft effect keys from preset

    def test_elevated_is_banner_only(self):
        e = mc.macro_cluster_effects_for("elevated")
        self.assertFalse(e["shrink_model_position_size"])
        self.assertTrue(e["report_banner"])

    def test_unknown_level_fails_closed(self):
        with self.assertRaises(ValueError):
            mc.macro_cluster_effects_for("bogus")

    def test_high_effects_copy_safe(self):
        e = mc.macro_cluster_high_effects()
        if isinstance(e, dict):
            e["__injected__"] = True
            self.assertNotIn("__injected__", mc.macro_cluster_high_effects())


class ContractTests(unittest.TestCase):
    def test_vocab_and_policy_match_preset(self):
        gov = json.loads(_GOV.read_text(encoding="utf-8"))
        self.assertEqual(mc.WARNING_LEVELS, tuple(gov["warning_levels"]))
        self.assertTrue(gov["v1_policy"]["no_hard_cap"])
        self.assertTrue(gov["macro_cluster_vocab_is_open"])


if __name__ == "__main__":
    unittest.main()
