# -*- coding: utf-8 -*-
"""Tests for US-short action_rank (engine/us_short_action_rank.py) — §9 操作排名 (保命优先 5 组骨架).

Adversarial focus: GROUPING-not-weighting (a must-act holding can NEVER rank below a new buy), the
final_action→group map, within-group ordering by selection_rank, frozen-vocab strictness, and conformance
to the frozen skeleton / vocab.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_action_rank as ar  # noqa: E402

_GOV = ROOT / "presets" / "us_short_action_governance_20260620.json"


class ActionGroupTests(unittest.TestCase):
    def test_each_action_maps_to_expected_group(self):
        cases = {"减仓": 1, "清仓-止损": 1, "清仓-止盈": 1, "清仓-事件": 1,
                 "建仓": 2, "加仓": 3, "持有": 4, "观察": 4, "否决/避开": 5}
        for action, group in cases.items():
            self.assertEqual(ar.action_group(action), group, action)

    def test_unknown_final_action_raises(self):
        for bad in ("bogus", "buy", "建仓 ", "", None, 1, True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ar.action_group(bad)


class RankActionsTests(unittest.TestCase):
    def test_holding_reduce_clear_always_outranks_new_buy(self):
        # the load-bearing §9 rule: a must-act holding (group 1) precedes a new buy (group 2) even when the
        # buy has the better selection_rank — grouping not weighting
        rows = [{"final_action": "建仓", "selection_rank": 1},
                {"final_action": "清仓-止损", "selection_rank": 99}]
        out = ar.rank_actions(rows)
        self.assertEqual(out[1]["action_rank"], 1)   # the stop-clear holding
        self.assertEqual(out[1]["action_group"], 1)
        self.assertEqual(out[0]["action_rank"], 2)   # the new buy, despite selection_rank 1
        self.assertEqual(out[0]["action_group"], 2)

    def test_within_group_two_ordered_by_selection_rank(self):
        rows = [{"final_action": "建仓", "selection_rank": 3},
                {"final_action": "建仓", "selection_rank": 1},
                {"final_action": "建仓", "selection_rank": 2}]
        out = ar.rank_actions(rows)
        self.assertEqual([o["action_rank"] for o in out], [3, 1, 2])

    def test_malformed_selection_rank_sorts_last_in_group(self):
        rows = [{"final_action": "建仓", "selection_rank": "bogus"},
                {"final_action": "建仓", "selection_rank": 1}]
        out = ar.rank_actions(rows)
        self.assertEqual(out[1]["action_rank"], 1)   # valid rank first
        self.assertEqual(out[0]["action_rank"], 2)   # malformed rank last

    def test_full_group_major_ordering(self):
        rows = [{"final_action": "否决/避开"}, {"final_action": "持有"}, {"final_action": "加仓"},
                {"final_action": "建仓", "selection_rank": 1}, {"final_action": "清仓-止损"}]
        out = ar.rank_actions(rows)
        groups_in_rank_order = [r["action_group"] for r in sorted(out, key=lambda r: r["action_rank"])]
        self.assertEqual(groups_in_rank_order, [1, 2, 3, 4, 5])

    def test_results_aligned_with_input_order(self):
        rows = [{"final_action": "建仓", "selection_rank": 5}, {"final_action": "清仓-止损"}]
        out = ar.rank_actions(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["action_group"], 2)   # aligned to rows[0]
        self.assertEqual(out[1]["action_group"], 1)

    def test_non_dict_row_and_unknown_action_raise(self):
        with self.assertRaises(ValueError):
            ar.rank_actions([{"final_action": "建仓"}, "notadict"])
        with self.assertRaises(ValueError):
            ar.rank_actions([{"final_action": "bogus"}])
        with self.assertRaises(ValueError):
            ar.rank_actions("notalist")


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gov = json.loads(_GOV.read_text(encoding="utf-8"))

    def test_mapping_covers_exactly_the_frozen_vocab(self):
        vocab = {e["final_action"] for e in self.gov["final_action_price_map"]}
        self.assertEqual(set(ar.FINAL_ACTION_GROUP.keys()), vocab)

    def test_groups_are_within_the_frozen_skeleton(self):
        skeleton = {g["group"] for g in self.gov["action_rank_skeleton"]}
        self.assertTrue(set(ar.FINAL_ACTION_GROUP.values()).issubset(skeleton))

    def test_holding_exit_actions_map_to_group_1(self):
        # every final_action whose price_target is a holding-exit field (减仓 / 清仓-*) is a group-1 reduce/clear
        holding_exit = {f["field"] for f in self.gov["holding_exit_price_fields"]}
        for e in self.gov["final_action_price_map"]:
            if e["price_target"] in holding_exit:
                self.assertEqual(ar.FINAL_ACTION_GROUP[e["final_action"]], 1, e["final_action"])

    def test_policy_is_grouping_not_weighting(self):
        self.assertTrue(self.gov["action_rank_policy"]["grouping_not_weighting"])
        self.assertTrue(self.gov["action_rank_policy"]["survival_first"])


if __name__ == "__main__":
    unittest.main()
