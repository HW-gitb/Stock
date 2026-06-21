# -*- coding: utf-8 -*-
"""Tests for US-short cash_allocation (engine/us_short_cash_allocation.py) — §8 全局现金分配.

Adversarial focus: sequential funding at the conservative valid_entry_high, no over-allocation (insufficient
cash → observe, no spend), rank order respected, and whole-class fail-closed inputs (bad row / cash / rank).
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_cash_allocation as ca  # noqa: E402

_GOV = ROOT / "presets" / "us_short_cash_allocation_governance_20260620.json"


def _row(rank, shares=10, entry=5.0, **kw):
    r = {"rank": rank, "desired_model_shares": shares, "valid_entry_high": entry, "final_action": "建仓"}
    r.update(kw)
    return r


class SequentialFundingTests(unittest.TestCase):
    def test_funds_in_rank_order_until_cash_runs_out(self):
        # cash for exactly 2 of 3 equal 50-dollar positions; 3rd downgrades to observe
        out = ca.allocate_cash([_row(1), _row(2), _row(3)], available_cash=120.0)
        self.assertEqual([o["cash_allocation_status"] for o in out], ["allocated", "allocated", "observe"])
        self.assertEqual(out[2]["reason"], "insufficient_cash")
        self.assertEqual([o["allocated_model_shares"] for o in out], [10, 10, 0])

    def test_conservative_basis_is_entry_high(self):
        out = ca.allocate_cash([_row(1, shares=4, entry=7.5)], available_cash=1000.0)
        self.assertEqual(out[0]["cash_required_at_entry_high"], 30.0)  # 4 * 7.5

    def test_rank_order_respected_regardless_of_input_order(self):
        # input out of order; only 2 positions affordable -> the two best RANKS win, worst observes
        out = ca.allocate_cash([_row(3), _row(1), _row(2)], available_cash=120.0)
        self.assertEqual(out[0]["cash_allocation_status"], "observe")        # rank 3
        self.assertEqual(out[1]["cash_allocation_status"], "allocated")      # rank 1
        self.assertEqual(out[2]["cash_allocation_status"], "allocated")      # rank 2
        self.assertEqual(out[1]["cash_allocation_rank"], 1)
        self.assertEqual(out[0]["cash_allocation_rank"], 3)

    def test_no_over_allocation(self):
        rows = [_row(i) for i in range(1, 6)]
        out = ca.allocate_cash(rows, available_cash=175.0)               # room for 3 (150) not 4 (200)
        spent = sum(o["cash_required_at_entry_high"] for o in out if o["cash_allocation_status"] == "allocated")
        self.assertLessEqual(spent, 175.0)
        self.assertEqual(sum(o["cash_allocation_status"] == "allocated" for o in out), 3)

    def test_insufficient_row_does_not_consume_cash(self):
        # an unaffordable high-rank row must not block a later affordable cheaper row
        out = ca.allocate_cash([_row(1, shares=10, entry=100.0), _row(2, shares=1, entry=5.0)],
                               available_cash=50.0)
        self.assertEqual(out[0]["cash_allocation_status"], "observe")    # needs 1000
        self.assertEqual(out[1]["cash_allocation_status"], "allocated")  # needs 5, still affordable
        self.assertEqual(out[1]["allocated_model_shares"], 1)


class FailClosedTests(unittest.TestCase):
    def test_malformed_row_observes_without_spending(self):
        for bad in (_row(1, shares=2.5), _row(1, shares=0), _row(1, entry=0.0), _row(1, entry="5"), "notadict"):
            out = ca.allocate_cash([bad, _row(2)], available_cash=1000.0)
            self.assertEqual(out[0]["cash_allocation_status"], "observe", repr(bad))
            self.assertEqual(out[0]["reason"], "invalid_row", repr(bad))
            self.assertEqual(out[0]["allocated_model_shares"], 0, repr(bad))
            self.assertEqual(out[1]["cash_allocation_status"], "allocated", repr(bad))  # valid row still funded

    def test_malformed_cash_makes_everything_observe(self):
        for bad in (-10.0, float("nan"), "100", None, True):
            out = ca.allocate_cash([_row(1), _row(2)], available_cash=bad)
            self.assertTrue(all(o["cash_allocation_status"] == "observe" for o in out), repr(bad))

    def test_malformed_rank_never_jumps_rank_one(self):
        # numeric-but-invalid ranks (negative / zero / fractional / NaN / bool / numeric-string) must NOT
        # be treated as better-than-1 priorities; they sink behind a valid rank-1 row
        for bad in (-10, -1, 0, 0.5, float("nan"), True, "1", "bogus", None):
            out = ca.allocate_cash([_row(bad), _row(1)], available_cash=50.0)   # room for one
            self.assertEqual(out[1]["cash_allocation_status"], "allocated", repr(bad))   # rank 1 funded
            self.assertEqual(out[0]["cash_allocation_status"], "observe", repr(bad))     # bad rank observes

    def test_legal_ranks_fund_in_order(self):
        out = ca.allocate_cash([_row(2), _row(1), _row(3)], available_cash=100.0)   # room for two
        self.assertEqual(out[1]["cash_allocation_status"], "allocated")   # rank 1
        self.assertEqual(out[0]["cash_allocation_status"], "allocated")   # rank 2
        self.assertEqual(out[2]["cash_allocation_status"], "observe")     # rank 3

    def test_malformed_tiebreak_loses_but_never_jumps_better_rank(self):
        # a malformed confidence on a rank-1 row must not demote it below a rank-2 row
        out = ca.allocate_cash([_row(2, confidence=0.9), _row(1, confidence=float("nan"))],
                               available_cash=50.0)
        self.assertEqual(out[1]["cash_allocation_status"], "allocated")   # rank 1 still wins
        self.assertEqual(out[0]["cash_allocation_status"], "observe")     # rank 2

    def test_non_list_returns_empty(self):
        self.assertEqual(ca.allocate_cash("notalist", 100.0), [])


class BuildableBoundaryTests(unittest.TestCase):
    # the authoritative frozen final_action vocab (us_short_action_table_contract); only 建仓/加仓 deploy cash
    NON_BUILDABLE_ACTIONS = ("减仓", "清仓-止损", "清仓-止盈", "清仓-事件", "持有", "观察", "否决/避开")

    def test_chinese_non_buildable_actions_never_funded(self):
        # §8 never_rescue_non_buildable against the AUTHORITATIVE Chinese final_action vocabulary
        for action in self.NON_BUILDABLE_ACTIONS:
            out = ca.allocate_cash([_row(1, final_action=action), _row(2)], available_cash=1000.0)
            self.assertEqual(out[0]["cash_allocation_status"], "observe", action)
            self.assertEqual(out[0]["reason"], "not_buildable", action)
            self.assertEqual(out[0]["allocated_model_shares"], 0, action)
            self.assertEqual(out[1]["cash_allocation_status"], "allocated", action)  # buildable row still funded

    def test_unknown_or_malformed_action_fails_closed(self):
        # missing / English placeholder / typo / case-drift / whitespace / non-string → not buildable
        for bad in ({"desired_model_shares": 10, "valid_entry_high": 5.0, "rank": 1},   # no final_action
                    _row(1, final_action="observe"), _row(1, final_action="buy"),
                    _row(1, final_action="建仓 "), _row(1, final_action="加 仓"),
                    _row(1, final_action=None), _row(1, final_action=1)):
            out = ca.allocate_cash([bad, _row(2)], available_cash=1000.0)
            self.assertEqual(out[0]["cash_allocation_status"], "observe", repr(bad.get("final_action")))
            self.assertEqual(out[0]["reason"], "not_buildable", repr(bad.get("final_action")))
            self.assertEqual(out[1]["cash_allocation_status"], "allocated")

    def test_hard_veto_overrides_even_a_buildable_action(self):
        out = ca.allocate_cash([_row(1, final_action="建仓", hard_veto=True), _row(2)], available_cash=50.0)
        self.assertEqual(out[0]["reason"], "not_buildable")
        self.assertEqual(out[1]["cash_allocation_status"], "allocated")          # cash not consumed by the vetoed row

    def test_both_build_and_add_actions_fund(self):
        out = ca.allocate_cash([_row(1, final_action="建仓"), _row(2, final_action="加仓")], available_cash=100.0)
        self.assertEqual([o["cash_allocation_status"] for o in out], ["allocated", "allocated"])

    def test_buildable_actions_subset_of_action_table_contract(self):
        contract = json.loads((ROOT / "schemas" / "us_short_action_table_contract.schema.json").read_text(encoding="utf-8"))
        vocab = set(contract["properties"]["design_locked_enums"]["properties"]["final_action"]["const"])
        self.assertTrue(set(ca._BUILDABLE_FINAL_ACTIONS).issubset(vocab))


class ContractTests(unittest.TestCase):
    def test_result_carries_frozen_fields(self):
        out = ca.allocate_cash([_row(1)], available_cash=1000.0)
        for f in ca.CASH_ALLOCATION_FIELDS:
            self.assertIn(f, out[0], f)

    def test_buildable_only_scope_from_preset(self):
        gov = json.loads(_GOV.read_text(encoding="utf-8"))
        self.assertTrue(gov["allocation_scope"]["only_buildable_tickers"])
        self.assertTrue(gov["allocation_scope"]["never_rescue_non_buildable"])
        self.assertEqual(ca.CONSERVATIVE_ENTRY_BASIS, "valid_entry_high")


if __name__ == "__main__":
    unittest.main()
