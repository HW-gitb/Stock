# -*- coding: utf-8 -*-
"""Tests for the US-short hard-veto layering classifier (engine/us_short_hard_veto.py) — §5.

Adversarial focus (fewer FAIL->修复 rounds): the load-bearing safety gates are §5.3 never-solo
(no single SI / web-heat / tech-indicator / target<price / crowding / high-vol may produce a hard
veto), the §5.1a SEC-offering recency/materiality gate (a stale shelf is not a hard veto), and the
§5.1b advisory-first semantic rule (unavailable / high-confidence adverse never hard-block in v1).
Conformance triangulates the tier ladder + effects + must-not-solo set against the frozen preset.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_hard_veto as hv  # noqa: E402

_GOV = ROOT / "presets" / "us_short_hard_veto_governance_20260620.json"
_ACT = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
_HARD = ("entry_hard_veto", "position_hard_veto")

# Golden §5.1a reliable boolean hard-risk triggers, anchored to docs/us_short_system_design.md §5.1a
# (退市/停牌/破产/OTC/严重流动性/严重spread/关键数据缺失) — NOT derived from hv._RELIABLE_HARD, so a
# design-required trigger missing from the implementation fails these tests.
GOLDEN_RELIABLE = {
    "delisted": "退市", "halted": "停牌", "bankruptcy": "破产", "otc": "OTC",
    "severe_liquidity": "流动性枯竭", "severe_spread": "严重spread", "critical_data_missing": "关键数据缺失",
}

# Golden §5.3 must-not-solo mapping: each preset design item ↔ the English input key the engine guards.
SOLO_MEMBER_MAP = {
    "单独高 SI": "high_si", "单独网络热度": "web_heat", "单个技术指标": "single_tech_indicator",
    "目标价低于现价": "target_below_price", "主题拥挤": "theme_crowded", "高波动": "high_vol",
}


class ReliableHardVetoGoldenTests(unittest.TestCase):
    def test_every_design_required_trigger_hard_vetoes_both_contexts(self):
        # anchored to the design set, NOT hv._RELIABLE_HARD -> a missing required trigger fails here
        for key in GOLDEN_RELIABLE:
            self.assertEqual(hv.classify_hard_veto({key: True}, "candidate")["veto_tier"], "entry_hard_veto", key)
            self.assertEqual(hv.classify_hard_veto({key: True}, "holding")["veto_tier"], "position_hard_veto", key)

    def test_implementation_covers_the_golden_set(self):
        impl = {k for k, _ in hv._RELIABLE_HARD}
        self.assertTrue(set(GOLDEN_RELIABLE).issubset(impl),
                        f"missing design-required reliable triggers: {set(GOLDEN_RELIABLE) - impl}")

    def test_liquidity_spread_is_a_reliable_hard_trigger(self):
        # explicit positive control for the previously-missing §5.1a 严重流动性/spread category
        self.assertEqual(hv.classify_hard_veto({"severe_liquidity": True}, "candidate")["veto_tier"], "entry_hard_veto")
        self.assertEqual(hv.classify_hard_veto({"severe_spread": True}, "holding")["veto_tier"], "position_hard_veto")


class RowContextValidationTests(unittest.TestCase):
    def test_invalid_context_fails_closed_not_silent_candidate(self):
        # REVERSE-FAILURE control: a bad / row-source-like / holding-ish context must NOT silently become
        # entry_hard_veto — it must fail closed so a holding hard-risk can't be downgraded to entry-only.
        for bad in ("position", "holding_in_top15", "", None, "candidates"):
            with self.assertRaises(ValueError):
                hv.classify_hard_veto({"delisted": True}, bad)

    def test_row_source_to_context_maps_frozen_values(self):
        self.assertEqual(hv.row_source_to_context("top15_candidate"), "candidate")
        for rs in ("holding_in_top15", "holding_pass2_only", "holding_account_only"):
            self.assertEqual(hv.row_source_to_context(rs), "holding")

    def test_row_source_to_context_rejects_unknown(self):
        with self.assertRaises(ValueError):
            hv.row_source_to_context("bogus")

    def test_row_source_mapper_covers_frozen_action_table_enum(self):
        act = json.loads(_ACT.read_text(encoding="utf-8"))
        self.assertEqual(set(hv._ROW_SOURCE_TO_CONTEXT), set(act["design_locked_enums"]["row_source"]))


class ReliableHardVetoTests(unittest.TestCase):
    def test_each_reliable_signal_hard_vetoes_candidate(self):
        # class coverage: every §5.1a reliable trigger -> entry_hard_veto for a candidate row
        for key, _ in hv._RELIABLE_HARD:
            out = hv.classify_hard_veto({key: True}, "candidate")
            self.assertEqual(out["veto_tier"], "entry_hard_veto", key)

    def test_reliable_signal_uses_position_tier_for_holding(self):
        out = hv.classify_hard_veto({"delisted": True}, "holding")
        self.assertEqual(out["veto_tier"], "position_hard_veto")
        self.assertEqual(out["effect"], "持仓强制重评/减/清（不是沉默）")

    def test_no_signals_is_none(self):
        out = hv.classify_hard_veto({}, "candidate")
        self.assertEqual(out["veto_tier"], "none")


class SecOfferingRecencyMaterialityTests(unittest.TestCase):
    def test_recent_active_material_hard_vetoes(self):
        out = hv.classify_hard_veto(
            {"active_offering": {"recency": "recent", "status": "active", "materiality": "material"}}, "candidate")
        self.assertEqual(out["veto_tier"], "entry_hard_veto")

    def test_stale_or_inactive_or_small_offering_is_not_hard_veto(self):
        # REVERSE-FAILURE control: a hung shelf / stale / small offering must NOT hard-veto (§5.1a)
        for off in (
            {"recency": "stale", "status": "active", "materiality": "material"},
            {"recency": "recent", "status": "inactive", "materiality": "material"},
            {"recency": "recent", "status": "active", "materiality": "small"},
        ):
            out = hv.classify_hard_veto({"active_offering": off}, "candidate")
            self.assertEqual(out["veto_tier"], "soft_risk_tag", off)
            self.assertNotIn(out["veto_tier"], _HARD)


class SemanticAdvisoryFirstTests(unittest.TestCase):
    def test_unavailable_is_downgrade_not_hard_block(self):
        out = hv.classify_hard_veto({"semantic_audit": {"available": False}}, "candidate")
        self.assertEqual(out["veto_tier"], "soft_risk_tag")
        self.assertNotIn(out["veto_tier"], _HARD)

    def test_high_confidence_adverse_is_strong_downgrade_not_hard(self):
        out = hv.classify_hard_veto(
            {"semantic_audit": {"available": True, "adverse": True, "confidence": "high"}}, "candidate")
        self.assertEqual(out["veto_tier"], "strong_downgrade")
        self.assertNotIn(out["veto_tier"], _HARD)

    def test_low_confidence_adverse_is_soft(self):
        out = hv.classify_hard_veto(
            {"semantic_audit": {"available": True, "adverse": True, "confidence": "low"}}, "candidate")
        self.assertEqual(out["veto_tier"], "soft_risk_tag")


class NeverSoloVetoTests(unittest.TestCase):
    def test_every_solo_signal_alone_never_hard_vetoes(self):
        # THE §5.3 guard: each must-not-solo signal ALONE reaches at most soft_risk_tag
        for key in hv.MUST_NOT_SOLO_VETO:
            for ctx in ("candidate", "holding"):
                out = hv.classify_hard_veto({key: True}, ctx)
                self.assertEqual(out["veto_tier"], "soft_risk_tag", f"{key}/{ctx}")
                self.assertNotIn(out["veto_tier"], _HARD)

    def test_solo_signal_does_not_downgrade_a_real_hard_veto(self):
        # severity-max: a reliable hard veto + a solo signal stays a hard veto (solo never weakens it)
        out = hv.classify_hard_veto({"delisted": True, "high_si": True}, "candidate")
        self.assertEqual(out["veto_tier"], "entry_hard_veto")

    def test_multiple_solo_signals_still_only_soft(self):
        out = hv.classify_hard_veto({k: True for k in hv.MUST_NOT_SOLO_VETO}, "candidate")
        self.assertEqual(out["veto_tier"], "soft_risk_tag")


class ContractConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gov = json.loads(_GOV.read_text(encoding="utf-8"))

    def test_tier_ladder_order_matches_preset(self):
        preset_order = tuple(t["tier"] for t in self.gov["veto_tiers"])
        self.assertEqual(preset_order, hv.VETO_TIERS)   # severity order is design-locked

    def test_tier_effects_match_preset(self):
        preset_effect = {t["tier"]: t["effect"] for t in self.gov["veto_tiers"]}
        self.assertEqual(preset_effect, hv.TIER_EFFECT)

    def test_must_not_solo_count_matches_preset(self):
        # same enumerable-set-coverage discipline: engine must handle exactly the 6 preset solo items
        self.assertEqual(len(hv.MUST_NOT_SOLO_VETO), len(self.gov["must_not_solo_veto"]))
        self.assertEqual(len(hv.MUST_NOT_SOLO_VETO), 6)

    def test_must_not_solo_exact_member_mapping(self):
        # exact member coverage (not count-only): every preset solo item maps to exactly one engine key,
        # and those keys are exactly MUST_NOT_SOLO_VETO — so a design item can't silently go unguarded.
        self.assertEqual(set(SOLO_MEMBER_MAP), set(self.gov["must_not_solo_veto"]))
        self.assertEqual(set(SOLO_MEMBER_MAP.values()), set(hv.MUST_NOT_SOLO_VETO))

    def test_emitted_tiers_are_in_frozen_ladder(self):
        samples = [
            hv.classify_hard_veto({"delisted": True}, "candidate"),
            hv.classify_hard_veto({"delisted": True}, "holding"),
            hv.classify_hard_veto({"semantic_audit": {"available": True, "adverse": True, "confidence": "high"}}, "candidate"),
            hv.classify_hard_veto({"high_si": True}, "candidate"),
            hv.classify_hard_veto({}, "candidate"),
        ]
        allowed = set(hv.VETO_TIERS) | {hv.NONE}
        for r in samples:
            self.assertIn(r["veto_tier"], allowed)


if __name__ == "__main__":
    unittest.main()
