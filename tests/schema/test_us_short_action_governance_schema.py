# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_action_governance
(US-short batch 1, design §9 action_rank + §6.1 holding price fields).

The contract freezes the final_action→price one-to-one map (§9 '避免状态/价位脱钩'), the §6.1
holding-exit price field meanings, the §9 survival-first 5-group action_rank skeleton, and the
§9 observe_reason_type vocab. Tests assert (a) the const-pins, (b) byte-faithful single-source
triangulation schema==preset==design, (c) cross-schema integrity (final_action == action_table ==
converter TRADE_ACTIONS; sell price targets ⊆ holding fields ⊆ action_table columns; observe_reason
== action_table), and (d) negative schema cases incl. the action→wrong-price decoupling drift.
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

import runners.us_short_account_state_from_manual_tables as conv  # noqa: E402

SCHEMA = ROOT / "schemas" / "us_short_action_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_action_governance_20260620.json"
ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")
BT = re.compile(r"`([^`]+)`")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _line(contains):
    for ln in _TEXT.splitlines():
        if contains in ln:
            return ln
    raise AssertionError(f"design line not found: {contains}")


# --- re-extractors (identical logic to the generator) for single-source triangulation ---
def _design_price_map():
    after = _line("final_action` 词表（与 §6.1 价位一一对应").split("：", 1)[1]
    out = []
    for seg in after.split("、"):
        actions = BT.findall(seg.split("（")[0])
        mfield = re.search(r"→\s*`([a-z_]+)`", seg)
        target = mfield.group(1) if mfield else ("entry" if "entry 价" in seg else None)
        observe = "observe_reason_type" in seg
        for a in actions:
            out.append({"final_action": a, "price_target": target, "carries_observe_reason": observe})
    return out


def _design_holding_fields_legacy():
    body = _line("holding_exit_engine` 的被动 levels").split("：", 1)[1]
    return [{"field": f, "meaning": m} for f, m in re.findall(r"`([a-z_]+)`（([^）]+)）", body)]


def _design_holding_fields():
    body = _line("holding_exit_engine` 给基础价位")
    expected = [
        {"field": "stop_clear_price", "meaning": "止损清仓价"},
        {"field": "take_profit_reduce_price", "meaning": "盈一减仓价"},
        {"field": "take_profit_exit_price", "meaning": "盈二/跟踪止盈价"},
        {"field": "event_clear_reference_price", "meaning": "事件硬风险清仓参考价，标\"人工执行、非技术价\""},
    ]
    for item in expected:
        assert "`%s`" % item["field"] in body and item["meaning"] in body
    return expected


def _design_skeleton():
    circled = "①②③④⑤"
    body = _line("5 组骨架（保命优先）").split("：", 1)[1].split("。")[0]
    return [{"group": circled.index(p.strip()[0]) + 1, "label": p.strip()[1:].strip()} for p in body.split("→")]


def _design_observe_reasons():
    span = next(s for s in BT.findall(_line("观察必拆原因").split("：", 1)[1]) if "/" in s)
    return [v.strip() for v in span.split("/")]


class UsShortActionGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)
        cls.pmap = cls.preset["final_action_price_map"]
        cls.at = _load(ACTION_TABLE_PRESET)

    # --- structural ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_price_map_count_and_unique(self):
        self.assertEqual(len(self.pmap), 9)
        actions = [e["final_action"] for e in self.pmap]
        self.assertEqual(len(actions), len(set(actions)), "duplicate final_action")

    def test_skeleton_groups_1_to_5(self):
        self.assertEqual([s["group"] for s in self.preset["action_rank_skeleton"]], [1, 2, 3, 4, 5])

    def test_holding_fields_count(self):
        self.assertEqual(len(self.preset["holding_exit_price_fields"]), 4)

    def test_observe_reason_count(self):
        self.assertEqual(len(self.preset["observe_reason_types"]), 8)

    # --- triangulation: schema-const == preset == design ---
    def test_schema_const_equals_preset(self):
        p = self.schema["properties"]
        self.assertEqual(p["final_action_price_map"]["const"], self.pmap)
        self.assertEqual(p["holding_exit_price_fields"]["const"], self.preset["holding_exit_price_fields"])
        self.assertEqual(p["holding_action_policy"]["properties"]["tp1_reduce_fraction"]["const"], 0.10)
        self.assertEqual(p["action_rank_skeleton"]["const"], self.preset["action_rank_skeleton"])
        self.assertEqual(p["observe_reason_types"]["const"], self.preset["observe_reason_types"])

    def test_price_map_byte_faithful_to_design_9(self):
        self.assertEqual(self.pmap, _design_price_map())

    def test_holding_fields_byte_faithful_to_design_6_1(self):
        self.assertEqual(self.preset["holding_exit_price_fields"], _design_holding_fields())

    def test_first_cut_holding_action_policy_is_frozen(self):
        self.assertEqual(self.preset["holding_action_policy"], {
            "tp1_reduce_fraction": 0.10, "tp1_reduce_basis": "remaining_shares",
            "tp2_action": "清仓-止盈", "state_completion_source": "manual_executed_trade_only",
            "add_position_enabled": False,
            "deferred": ["move_stop_to_breakeven", "ratchet", "multi_day_active_management"],
        })

    def test_skeleton_byte_faithful_to_design_9(self):
        self.assertEqual(self.preset["action_rank_skeleton"], _design_skeleton())

    def test_observe_reason_byte_faithful_to_design_9(self):
        self.assertEqual(self.preset["observe_reason_types"], _design_observe_reasons())

    # --- cross-schema integrity ---
    def test_final_action_set_matches_action_table_and_converter(self):
        actions = [e["final_action"] for e in self.pmap]
        at_final = self.at["design_locked_enums"]["final_action"]
        self.assertEqual(actions, at_final)                       # same set AND order as action_table
        self.assertEqual(set(actions), set(conv.TRADE_ACTIONS))   # == converter trade actions
        self.assertEqual(len(actions), len(conv.TRADE_ACTIONS))

    def test_sell_price_targets_subset_of_holding_fields_and_columns(self):
        sell_fields = {e["price_target"] for e in self.pmap if e["price_target"] not in (None, "entry")}
        holding = {f["field"] for f in self.preset["holding_exit_price_fields"]}
        self.assertEqual(sell_fields, holding)                    # exactly the 4 holding-exit levels
        self.assertTrue(sell_fields <= set(self.at["core_columns"]))   # all are real action_table columns

    def test_observe_reason_matches_action_table(self):
        self.assertEqual(self.preset["observe_reason_types"], self.at["design_locked_enums"]["observe_reason_type"])

    def test_only_observe_carries_observe_reason(self):
        for e in self.pmap:
            self.assertEqual(e["carries_observe_reason"], e["final_action"] == "观察", e["final_action"])

    def test_entry_actions_use_entry_marker(self):
        entry = {e["final_action"] for e in self.pmap if e["price_target"] == "entry"}
        self.assertEqual(entry, {"建仓", "加仓"})

    def test_action_rank_policy_provenance_in_design(self):
        self.assertIn("用分组不用加权", _TEXT)
        self.assertIn("保命优先", _TEXT)

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_action_price_decoupling(self):
        # the core decoupling bug: 减仓 wrongly mapped to the stop-loss price
        self._reject(lambda d: d["final_action_price_map"][2].__setitem__("price_target", "stop_clear_price"))

    def test_schema_rejects_dropped_action(self):
        self._reject(lambda d: d["final_action_price_map"].pop())

    def test_schema_rejects_added_action(self):
        self._reject(lambda d: d["final_action_price_map"].append({"final_action": "建底仓", "price_target": "entry", "carries_observe_reason": False}))

    def test_schema_rejects_reordered_price_map(self):
        def swap(d):
            m = d["final_action_price_map"]
            m[0], m[1] = m[1], m[0]
        self._reject(swap)

    def test_schema_rejects_observe_flag_flip(self):
        self._reject(lambda d: d["final_action_price_map"][7].__setitem__("carries_observe_reason", False))

    def test_schema_rejects_skeleton_reorder(self):
        def swap(d):
            s = d["action_rank_skeleton"]
            s[0], s[1] = s[1], s[0]
        self._reject(swap)   # survival-first order is const

    def test_schema_rejects_skeleton_label_drift(self):
        self._reject(lambda d: d["action_rank_skeleton"][2].__setitem__("label", "加仓加仓"))

    def test_schema_rejects_dropped_skeleton_group(self):
        self._reject(lambda d: d["action_rank_skeleton"].pop())

    def test_schema_rejects_holding_field_drift(self):
        self._reject(lambda d: d["holding_exit_price_fields"][0].__setitem__("field", "stop_price"))

    def test_schema_rejects_tp1_fraction_drift(self):
        self._reject(lambda d: d["holding_action_policy"].__setitem__("tp1_reduce_fraction", 0.20))

    def test_schema_rejects_observe_reason_drift(self):
        self._reject(lambda d: d["observe_reason_types"].__setitem__(0, "signal_ready"))

    def test_schema_rejects_policy_flag_flip(self):
        self._reject(lambda d: d["action_rank_policy"].__setitem__("grouping_not_weighting", False))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
