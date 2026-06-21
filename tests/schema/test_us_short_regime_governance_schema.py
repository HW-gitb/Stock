# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_regime_governance
(US-short batch 1, design §7 two-axis market regime).

The contract freezes the market_risk_regime→position-cap ladder, the 3 worst_of input axes
(VIX provider-gate/unavailable policy; SPY+QQQ with QQQ required; base-universe breadth with no
paid industry ETF), the unknown-severity tiers, the upgrade-confirmation rule, the anti-worst_of
two-axis policy, and scope. Tests assert (a) the const-pins, (b) byte-faithful triangulation of the
caps, (c) threshold_calibration_item_id (#3) resolves against the lifecycle registry, (d) every
pinned mechanic's provenance phrase is in §7, and (e) negative schema cases incl. dropping QQQ,
dropping breadth, treating VIX-unavailable as aggressive, paid-ETF breadth, weakening the unknown
downgrade, and reducing upgrade confirmation to one week.
"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = ROOT / "schemas" / "us_short_regime_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_regime_governance_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_caps():
    line = next(ln for ln in _TEXT.splitlines() if "决定仓位上限" in ln)
    body = re.search(r"（(进攻[^）]+)）", line).group(1)
    out = []
    for chunk in body.split(" / "):
        regime, cap = chunk.rsplit(" ", 1)
        out.append({"regime": regime.strip(), "position_cap": float(cap)})
    return out


class UsShortRegimeGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)
        cls.caps = cls.preset["market_risk_regime_caps"]

    # --- structural / caps ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_regime_levels(self):
        self.assertEqual([c["regime"] for c in self.caps], ["进攻", "震荡", "防御", "极度防御"])

    def test_caps_strictly_descending(self):
        vals = [c["position_cap"] for c in self.caps]
        self.assertEqual(vals, [1.0, 0.8, 0.5, 0.0])
        self.assertTrue(all(a > b for a, b in zip(vals, vals[1:])), "caps must strictly descend by severity")

    def test_schema_const_equals_preset(self):
        self.assertEqual(self.schema["properties"]["market_risk_regime_caps"]["const"], self.caps)
        self.assertEqual(self.schema["properties"]["threshold_calibration_item_id"]["const"],
                         self.preset["threshold_calibration_item_id"])
        self.assertEqual(self.schema["properties"]["risk_axis_components"]["const"],
                         self.preset["risk_axis_components"])

    def test_caps_byte_faithful_to_design_7(self):
        self.assertEqual(self.caps, _design_caps())

    # --- cross-schema: §13 #3 route resolves ---
    def test_threshold_calibration_item_id_resolves(self):
        cid = self.preset["threshold_calibration_item_id"]
        self.assertEqual(cid, 3)
        items = _load(LIFECYCLE_PRESET)["calibration_items"]
        self.assertIn(cid, {it["number"] for it in items})
        title3 = next(it["title"] for it in items if it["number"] == 3)
        self.assertIn("环境阈值", title3)

    # --- input axes (the repaired under-pinning) ---
    def test_risk_axis_components(self):
        self.assertEqual(self.preset["risk_axis_components"], ["vix", "market_trend", "breadth"])

    def test_vix_axis_policy_pinned(self):
        v = self.preset["vix_axis_policy"]
        self.assertTrue(v["provider_authorization_gated"])
        self.assertTrue(v["unapproved_until_gate_passed"])
        self.assertTrue(v["unapproved_or_unavailable_becomes_unknown"])
        self.assertEqual(v["fallback_axes"], ["market_trend", "breadth"])
        self.assertTrue(v["conservative_downgrade_on_unavailable"])

    def test_market_trend_requires_qqq(self):
        m = self.preset["market_trend_axis"]
        self.assertEqual(m["components"], ["SPY", "QQQ"])
        self.assertTrue(m["qqq_required"])

    def test_breadth_from_base_universe_no_paid_etf(self):
        b = self.preset["breadth_axis"]
        self.assertEqual(b["source"], "base_universe_constituents")
        self.assertFalse(b["depends_on_paid_industry_etf"])

    def test_unknown_degradation_policy_pinned(self):
        u = self.preset["unknown_degradation_policy"]
        self.assertTrue(u["never_default_aggressive"])
        self.assertTrue(u["missing_one_downgrade"])
        self.assertTrue(u["missing_critical_at_least_defensive"])
        self.assertTrue(u["severe_restricted"])

    def test_anti_chatter_pinned(self):
        ac = self.preset["anti_chatter"]
        self.assertTrue(ac["downgrade_immediate"])
        self.assertTrue(ac["upgrade_requires_confirmation"])
        self.assertEqual(ac["upgrade_confirmation_weekly_runs"], 2)
        self.assertTrue(ac["upgrade_threshold_buffer_alternative"])

    def test_two_axis_policy_pinned(self):
        tp = self.preset["two_axis_policy"]
        self.assertTrue(tp["risk_regime_is_worst_of"])
        self.assertTrue(tp["risk_regime_decides_position_cap"])
        self.assertTrue(tp["theme_state_decides_opportunity_not_worst_of"])
        self.assertTrue(tp["weak_market_strong_theme_allows_probe"])

    def test_scope_pinned(self):
        sc = self.preset["scope"]
        self.assertTrue(sc["affects_position_size"])
        self.assertTrue(sc["affects_new_entry_permission"])
        self.assertTrue(sc["affects_action_confidence_optional"])
        self.assertTrue(sc["not_hard_veto"])
        self.assertTrue(sc["not_replace_stock_analysis"])

    def test_policy_provenance_in_design(self):
        # every pinned design-locked mechanic must trace to a verbatim §7 phrase (non-vacuous)
        for phrase in ("必须含 QQQ", "VIX 未授权 / unavailable", "unapproved", "基础 universe",
                       "行业 ETF 据公开档为付费、不依赖", "缺一项降级", "缺关键项至少防御", "严重 restricted",
                       "连续 2 次周跑更好", "站回阈值上方缓冲", "别只 worst_of", "快防守慢进攻",
                       "不影响 hard veto", "不替代个股分析"):
            self.assertIn(phrase, _TEXT, f"§7 provenance phrase missing: {phrase}")

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    # caps
    def test_schema_rejects_cap_value_drift(self):
        self._reject(lambda d: d["market_risk_regime_caps"][0].__setitem__("position_cap", 0.9))

    def test_schema_rejects_defensive_cap_nonzero(self):
        self._reject(lambda d: d["market_risk_regime_caps"][3].__setitem__("position_cap", 0.2))

    def test_schema_rejects_reordered_caps(self):
        def swap(d):
            c = d["market_risk_regime_caps"]
            c[0], c[1] = c[1], c[0]
        self._reject(swap)

    def test_schema_rejects_regime_rename(self):
        self._reject(lambda d: d["market_risk_regime_caps"][0].__setitem__("regime", "激进"))

    def test_schema_rejects_dropped_regime(self):
        self._reject(lambda d: d["market_risk_regime_caps"].pop())

    def test_schema_rejects_added_regime(self):
        self._reject(lambda d: d["market_risk_regime_caps"].append({"regime": "超进攻", "position_cap": 1.5}))

    # input axes (the exact Codex-requested negatives)
    def test_schema_rejects_dropped_qqq(self):
        self._reject(lambda d: d["market_trend_axis"].__setitem__("components", ["SPY"]))

    def test_schema_rejects_qqq_not_required(self):
        self._reject(lambda d: d["market_trend_axis"].__setitem__("qqq_required", False))

    def test_schema_rejects_dropped_breadth_component(self):
        self._reject(lambda d: d.__setitem__("risk_axis_components", ["vix", "market_trend"]))

    def test_schema_rejects_breadth_paid_etf(self):
        self._reject(lambda d: d["breadth_axis"].__setitem__("depends_on_paid_industry_etf", True))

    def test_schema_rejects_vix_unavailable_treated_aggressive(self):
        # treating VIX provider-unavailable as a normal/clean axis (not unknown) is the safety drift
        self._reject(lambda d: d["vix_axis_policy"].__setitem__("unapproved_or_unavailable_becomes_unknown", False))

    def test_schema_rejects_vix_not_conservative_on_unavailable(self):
        self._reject(lambda d: d["vix_axis_policy"].__setitem__("conservative_downgrade_on_unavailable", False))

    def test_schema_rejects_vix_not_authorization_gated(self):
        self._reject(lambda d: d["vix_axis_policy"].__setitem__("provider_authorization_gated", False))

    # unknown severity + upgrade confirmation
    def test_schema_rejects_unknown_downgrade_weakened(self):
        self._reject(lambda d: d["unknown_degradation_policy"].__setitem__("missing_critical_at_least_defensive", False))

    def test_schema_rejects_default_aggressive_allowed(self):
        self._reject(lambda d: d["unknown_degradation_policy"].__setitem__("never_default_aggressive", False))

    def test_schema_rejects_upgrade_confirmation_one_week(self):
        self._reject(lambda d: d["anti_chatter"].__setitem__("upgrade_confirmation_weekly_runs", 1))

    def test_schema_rejects_anti_chatter_downgrade_delayed(self):
        self._reject(lambda d: d["anti_chatter"].__setitem__("downgrade_immediate", False))

    # policy / scope / routing
    def test_schema_rejects_two_axis_flag_flip(self):
        self._reject(lambda d: d["two_axis_policy"].__setitem__("theme_state_decides_opportunity_not_worst_of", False))

    def test_schema_rejects_scope_hard_veto_leak(self):
        self._reject(lambda d: d["scope"].__setitem__("not_hard_veto", False))

    def test_schema_rejects_calibration_item_id_change(self):
        self._reject(lambda d: d.__setitem__("threshold_calibration_item_id", 4))

    def test_schema_rejects_scope_unknown_key(self):
        self._reject(lambda d: d["scope"].__setitem__("auto_trade", True))

    def test_schema_rejects_vix_axis_unknown_key(self):
        self._reject(lambda d: d["vix_axis_policy"].__setitem__("ignore_gate", True))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
