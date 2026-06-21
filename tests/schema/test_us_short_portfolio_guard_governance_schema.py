# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_portfolio_guard_governance
(US-short batch 1, design §8 组合级熔断 / portfolio_guard).

The contract freezes the portfolio_guard_status state set, the per-state design-locked effects,
the model_paper_track trigger model, and the 'no data is not safe' fail-safe. Tests assert (a) the
const-pins, (b) byte-faithful triangulation of the states + cross-check vs action_table, (c)
threshold_calibration_item_id (#22) resolves against the lifecycle registry, (d) each pinned
mechanic's provenance is in §8, and (e) negative schema cases incl. cooldown not blocking entries
and the fail-safe being weakened to clean.
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

SCHEMA = ROOT / "schemas" / "us_short_portfolio_guard_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_portfolio_guard_governance_20260620.json"
ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")
EFFECT_KEYS = {"block_new_entry", "block_add", "reduce_position_size", "reduce_weekly_new_count",
               "holding_risk_control_only", "only_few_high_confidence_new"}


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_states():
    line = next(ln for ln in _TEXT.splitlines() if "组合级熔断" in ln)
    return [s.strip() for s in re.search(r"portfolio_guard_status ∈ \{([^}]+)\}", line).group(1).split(",")]


class UsShortPortfolioGuardGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)
        cls.states = cls.preset["portfolio_guard_states"]
        cls.eff = {s["state"]: s["effects"] for s in cls.preset["state_effects"]}

    # --- structural ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_states(self):
        self.assertEqual(self.states, ["normal", "caution", "cooldown", "recovery"])

    def test_state_effects_cover_all_states_with_full_key_set(self):
        self.assertEqual([s["state"] for s in self.preset["state_effects"]], self.states)
        for s in self.preset["state_effects"]:
            self.assertEqual(set(s["effects"]), EFFECT_KEYS, s["state"])   # every state pins every effect key

    # --- triangulation / cross-schema ---
    def test_schema_const_equals_preset(self):
        p = self.schema["properties"]
        self.assertEqual(p["portfolio_guard_states"]["const"], self.states)
        self.assertEqual(p["state_effects"]["const"], self.preset["state_effects"])
        self.assertEqual(p["threshold_calibration_item_id"]["const"], self.preset["threshold_calibration_item_id"])

    def test_states_byte_faithful_to_design_8(self):
        self.assertEqual(self.states, _design_states())

    def test_states_match_action_table(self):
        at = _load(ACTION_TABLE_PRESET)["design_locked_enums"]["portfolio_guard_status"]
        self.assertEqual(self.states, at)

    def test_threshold_calibration_item_id_resolves(self):
        cid = self.preset["threshold_calibration_item_id"]
        self.assertEqual(cid, 22)
        items = _load(LIFECYCLE_PRESET)["calibration_items"]
        self.assertIn(cid, {it["number"] for it in items})
        self.assertIn("组合熔断", next(it["title"] for it in items if it["number"] == 22))

    # --- per-state design-locked effects (safety-critical) ---
    def test_cooldown_blocks_new_add_and_holding_only(self):
        c = self.eff["cooldown"]
        self.assertTrue(c["block_new_entry"])
        self.assertTrue(c["block_add"])
        self.assertTrue(c["holding_risk_control_only"])

    def test_caution_reduces_size_and_weekly(self):
        c = self.eff["caution"]
        self.assertTrue(c["reduce_position_size"])
        self.assertTrue(c["reduce_weekly_new_count"])
        self.assertFalse(c["block_new_entry"])   # caution restricts, does not block

    def test_recovery_only_few_high_confidence(self):
        r = self.eff["recovery"]
        self.assertTrue(r["only_few_high_confidence_new"])
        self.assertFalse(r["block_new_entry"])

    def test_normal_is_baseline(self):
        self.assertFalse(any(self.eff["normal"].values()))

    # --- triggers / fail-safe / advisory ---
    def test_triggers_pinned(self):
        t = self.preset["triggers"]
        self.assertEqual(t["primary_source"], "model_paper_track")
        self.assertTrue(t["primary_evaluable_required"])
        self.assertEqual(t["primary_conditions"], ["consecutive_stops", "paper_account_drawdown_over_threshold"])
        self.assertEqual(t["secondary_source"], "manual_actual_account")
        self.assertTrue(t["secondary_is_advisory"])

    def test_fail_safe_pinned(self):
        f = self.preset["fail_safe"]
        self.assertTrue(f["paper_not_evaluable_forbids_clean"])
        self.assertTrue(f["no_data_is_not_safe"])
        self.assertEqual(f["default_when_not_evaluable"], "restricted_caution_or_holding_risk_only")

    def test_advisory_only(self):
        self.assertTrue(self.preset["advisory_only"])

    def test_provenance_in_design(self):
        for phrase in ("组合级熔断", "model_paper_track", "连续止损", "纸面账户回撤超阈值", "不得 clean",
                       "没数据不当", "禁新建/加仓", "只持仓风控", "降仓+减每周新增数", "只少量高置信新仓",
                       "只影响建议、不自动交易"):
            self.assertIn(phrase, _TEXT, f"§8 provenance phrase missing: {phrase}")

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_state_rename(self):
        self._reject(lambda d: d["portfolio_guard_states"].__setitem__(2, "halt"))

    def test_schema_rejects_dropped_state(self):
        self._reject(lambda d: d["portfolio_guard_states"].pop())

    def test_schema_rejects_added_state(self):
        self._reject(lambda d: d["portfolio_guard_states"].append("frozen"))

    def test_schema_rejects_reordered_states(self):
        def swap(d):
            s = d["portfolio_guard_states"]
            s[1], s[2] = s[2], s[1]
        self._reject(swap)

    def test_schema_rejects_cooldown_allows_new_entry(self):
        # safety drift: cooldown must block new entry
        self._reject(lambda d: d["state_effects"][2]["effects"].__setitem__("block_new_entry", False))

    def test_schema_rejects_caution_effect_drift(self):
        self._reject(lambda d: d["state_effects"][1]["effects"].__setitem__("reduce_position_size", False))

    def test_schema_rejects_failsafe_allows_clean(self):
        # the core fail-safe: paper not_evaluable must NOT be clean
        self._reject(lambda d: d["fail_safe"].__setitem__("paper_not_evaluable_forbids_clean", False))

    def test_schema_rejects_advisory_only_flip(self):
        self._reject(lambda d: d.__setitem__("advisory_only", False))

    def test_schema_rejects_trigger_source_drift(self):
        self._reject(lambda d: d["triggers"].__setitem__("primary_source", "manual_actual_account"))

    def test_schema_rejects_calibration_item_id_change(self):
        self._reject(lambda d: d.__setitem__("threshold_calibration_item_id", 23))

    def test_schema_rejects_effects_unknown_key(self):
        self._reject(lambda d: d["state_effects"][0]["effects"].__setitem__("auto_liquidate", True))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
