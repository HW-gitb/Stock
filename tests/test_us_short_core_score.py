# -*- coding: utf-8 -*-
"""Tests for US-short core_score assembly (engine/us_short_core_score.py) — §4.2.

Adversarial focus (the prior slices' lessons applied up front): a missing block scores neutral and is
NOT re-normalised into the others, every public input is validated fail-closed (strict number / bool /
profile), the returned weights are copy-safe, and the score never goes negative. Conformance triangulates
the weight profiles against the frozen scoring_profile governance preset.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_core_score as cs  # noqa: E402

_GOV = ROOT / "presets" / "us_short_scoring_profile_governance_20260620.json"


class AssemblyTests(unittest.TestCase):
    def test_balanced_weighted_sum(self):
        out = cs.core_score({"momentum": 80.0, "theme": 60.0, "catalyst": 40.0}, profile="balanced")
        self.assertAlmostEqual(out["core_score"], 0.40 * 80 + 0.35 * 60 + 0.25 * 40)   # 63.0
        self.assertEqual(out["missing_blocks"], [])

    def test_risk_downgrade_is_subtracted(self):
        out = cs.core_score({"momentum": 80.0, "theme": 60.0, "catalyst": 40.0}, risk_downgrade_points=20.0)
        self.assertAlmostEqual(out["core_score"], 63.0 - 20.0)

    def test_score_never_negative(self):
        out = cs.core_score({"momentum": 80.0, "theme": 60.0, "catalyst": 40.0}, risk_downgrade_points=100.0)
        self.assertEqual(out["core_score"], 0.0)

    def test_block_clamped_0_100(self):
        out = cs.core_score({"momentum": 150.0, "theme": -10.0, "catalyst": 40.0}, profile="balanced")
        self.assertEqual(out["blocks_used"]["momentum"], 100.0)
        self.assertEqual(out["blocks_used"]["theme"], 0.0)

    def test_theme_off_profile_zeroes_theme(self):
        out = cs.core_score({"momentum": 80.0, "theme": 99.0, "catalyst": 40.0}, profile="theme_off")
        w = cs.profile_weights("theme_off")
        self.assertEqual(w["theme"], 0.0)
        self.assertAlmostEqual(out["core_score"], w["momentum"] * 80 + 0.0 * 99 + w["catalyst"] * 40)


class MissingBlockNeutralTests(unittest.TestCase):
    def test_missing_block_is_neutral_not_renormalised(self):
        # REVERSE-FAILURE control: a missing catalyst scores NEUTRAL (50) with momentum/theme weights
        # UNCHANGED — it must not silently amplify the present blocks (§4.2 不偷偷重新归一放大权重).
        out = cs.core_score({"momentum": 80.0, "theme": 60.0}, profile="balanced")   # catalyst missing
        self.assertEqual(out["missing_blocks"], ["catalyst"])
        self.assertEqual(out["blocks_used"]["catalyst"], cs.NEUTRAL_BLOCK)
        self.assertAlmostEqual(out["core_score"], 0.40 * 80 + 0.35 * 60 + 0.25 * cs.NEUTRAL_BLOCK)  # 65.5, not re-normalised

    def test_malformed_block_is_treated_as_missing(self):
        for bad in ("80", True, float("nan"), float("inf"), None):
            out = cs.core_score({"momentum": bad, "theme": 60.0, "catalyst": 40.0}, profile="balanced")
            self.assertIn("momentum", out["missing_blocks"], repr(bad))
            self.assertEqual(out["blocks_used"]["momentum"], cs.NEUTRAL_BLOCK, repr(bad))


class BadInputTests(unittest.TestCase):
    def test_malformed_risk_downgrade_fails_closed_to_zero(self):
        for bad in ("20", True, float("nan"), float("inf"), -50.0, None):
            out = cs.core_score({"momentum": 80.0, "theme": 60.0, "catalyst": 40.0}, risk_downgrade_points=bad)
            self.assertEqual(out["risk_downgrade"], 0.0, repr(bad))
            self.assertAlmostEqual(out["core_score"], 63.0, msg=repr(bad))

    def test_unknown_profile_fails_closed(self):
        with self.assertRaises(KeyError):
            cs.core_score({"momentum": 80.0, "theme": 60.0, "catalyst": 40.0}, profile="bogus")
        with self.assertRaises(KeyError):
            cs.profile_weights("bogus")

    def test_non_dict_blocks_all_neutral(self):
        out = cs.core_score(None, profile="balanced")
        self.assertEqual(sorted(out["missing_blocks"]), sorted(cs.CORE_COMPONENTS))


class ContractConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gov = json.loads(_GOV.read_text(encoding="utf-8"))

    def test_all_profile_weights_match_preset(self):
        for name, spec in self.gov["profiles"].items():
            self.assertEqual(cs.profile_weights(name), spec["weights"], name)

    def test_balanced_is_primary_40_35_25(self):
        self.assertEqual(cs.PRIMARY_PROFILE, self.gov["primary_profile"])
        self.assertEqual(cs.profile_weights("balanced"), {"momentum": 0.40, "theme": 0.35, "catalyst": 0.25})

    def test_components_match_preset(self):
        self.assertEqual(cs.CORE_COMPONENTS, tuple(self.gov["core_score_components"]))

    def test_returned_weights_are_copy_safe(self):
        # mutating the returned weights must not corrupt the single-source governance table
        w = cs.profile_weights("balanced")
        w["momentum"] = 99.0
        self.assertEqual(cs.profile_weights("balanced")["momentum"], 0.40)


class NeutralBlockValidationTests(unittest.TestCase):
    """REVERSE-FAILURE class: the public `neutral_block` fallback is a numeric input too — a malformed
    or out-of-domain override must not crash, propagate NaN/Inf, or inflate a missing-data row above
    the 0-100 scoring domain. It fails closed to the frozen NEUTRAL_BLOCK; a legitimate in-domain
    override still applies."""

    def _missing_catalyst(self, neutral_block):
        out = cs.core_score({"momentum": 80.0, "theme": 60.0}, neutral_block=neutral_block)   # catalyst missing
        return out["blocks_used"]["catalyst"], out["core_score"]

    def test_malformed_or_out_of_domain_neutral_fails_closed_to_frozen(self):
        for bad in ("50", None, True, False, float("nan"), float("inf"), 1000.0, -10.0):
            val, score = self._missing_catalyst(bad)
            self.assertEqual(val, cs.NEUTRAL_BLOCK, repr(bad))     # frozen 50 — no crash / NaN / Inf / inflation
            self.assertGreaterEqual(score, 0.0, repr(bad))
            self.assertLessEqual(score, 100.0, repr(bad))         # stays inside the 0-100 scoring domain

    def test_legitimate_in_domain_neutral_override_applies(self):  # positive control
        val, _ = self._missing_catalyst(40.0)
        self.assertEqual(val, 40.0)


if __name__ == "__main__":
    unittest.main()
