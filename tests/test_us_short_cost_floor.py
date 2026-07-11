# -*- coding: utf-8 -*-
"""Tests for US-short cost_floor (engine/us_short_cost_floor.py) — §8 最小仓成本地板 (P0 真拦单).

Adversarial focus: the cost-efficiency gate actually BLOCKS (hard zero-share observe, not a tag), the
≤ boundary, whole-class fail-closed (malformed shares / prices / cost → blocked), and the frozen
observe_reason_type.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_cost_floor as cf  # noqa: E402

_GOV = ROOT / "schemas" / "us_short_action_governance.schema.json"


class RoundTripCostTests(unittest.TestCase):
    def test_sums_components(self):
        self.assertEqual(cf.round_trip_cost(1.0, 2.0, 3.0), 6.0)

    def test_malformed_or_negative_component_fails_closed(self):
        for c, s, p in ((float("nan"), 1.0, 1.0), ("1", 1.0, 1.0), (True, 1.0, 1.0),
                        (None, 1.0, 1.0), (-1.0, 1.0, 1.0), (1.0, 1.0, -0.01)):
            self.assertIsNone(cf.round_trip_cost(c, s, p), (c, s, p))


class CostFloorGateTests(unittest.TestCase):
    def test_clears_when_profit_far_exceeds_cost(self):
        out = cf.apply_cost_floor(1000, 10.0, 20.0, 1.0, 1.0, 1.0)   # gross 10000 >> cost 3
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["shares"], 1000)
        self.assertIsNone(out["observe_reason_type"])

    def test_blocks_when_profit_below_floor_hard_zero(self):
        out = cf.apply_cost_floor(1, 10.0, 10.01, 1.0, 1.0, 1.0)     # gross 0.01 <= 9
        self.assertEqual(out["status"], "observe")
        self.assertEqual(out["shares"], 0)                           # 真拦单: hard zero, not a tag
        self.assertEqual(out["observe_reason_type"], "cost_inefficient_min_size")
        self.assertEqual(out["reason"], "profit_below_cost_floor")

    def test_boundary_is_inclusive_block(self):
        # §8 口径 = NET profit (gross − round-trip cost) exactly == cost × COST_SAFETY_MULT → blocked (≤); just
        # above → cleared. cost=1, mult=3: block when net ≤ 3, i.e. gross ≤ 4; clear when gross > 4.
        cost = 1.0  # commission 1 + slippage 0 + spread 0
        at = cf.apply_cost_floor(1, 10.0, 10.0 + cost * (cf.COST_SAFETY_MULT + 1), 1.0, 0.0, 0.0)   # net == threshold
        above = cf.apply_cost_floor(1, 10.0, 10.0 + cost * (cf.COST_SAFETY_MULT + 1) + 0.5, 1.0, 0.0, 0.0)
        self.assertEqual(at["status"], "observe", "net == cost*mult must block")
        self.assertEqual(above["status"], "ok")

    def test_gate_is_on_net_not_gross(self):
        # regression (cc_r1): the gate is on NET profit, not gross. A gross between cost*mult and cost*(mult+1)
        # would CLEAR on the (wrong) gross rule but must BLOCK on the (correct) net rule.
        # cost=1, mult=3: gross 3.5 → net 2.5 ≤ 3 → block.
        out = cf.apply_cost_floor(1, 10.0, 13.5, 1.0, 0.0, 0.0)
        self.assertEqual(out["status"], "observe")
        self.assertEqual(out["reason"], "profit_below_cost_floor")
        # gross 5 → net 4 > 3 → clears (proves it's not just "always block")
        self.assertEqual(cf.apply_cost_floor(1, 10.0, 15.0, 1.0, 0.0, 0.0)["status"], "ok")

    def test_malformed_inputs_fail_closed_to_block(self):
        base = dict(entry_price=10.0, tp1_price=12.0, commission_round_trip=1.0,
                    slippage_dollars=1.0, spread_dollars=1.0)
        # malformed shares
        for sh in (2.5, 0, -1, "100", True, None):
            out = cf.apply_cost_floor(sh, **base)
            self.assertEqual(out["status"], "observe", repr(sh))
            self.assertEqual(out["shares"], 0, repr(sh))
            self.assertEqual(out["observe_reason_type"], "cost_inefficient_min_size", repr(sh))
            self.assertEqual(out["reason"], "unverifiable_cost_inputs", repr(sh))

    def test_non_positive_or_inverted_prices_block(self):
        for entry, tp1 in ((0.0, 12.0), (-1.0, 12.0), (10.0, 0.0), (10.0, 10.0), (10.0, 9.0)):
            out = cf.apply_cost_floor(100, entry, tp1, 1.0, 1.0, 1.0)
            self.assertEqual(out["status"], "observe", (entry, tp1))
            self.assertEqual(out["reason"], "unverifiable_cost_inputs", (entry, tp1))

    def test_malformed_cost_component_blocks(self):
        out = cf.apply_cost_floor(1000, 10.0, 20.0, float("nan"), 1.0, 1.0)   # gross huge but cost unverifiable
        self.assertEqual(out["status"], "observe")
        self.assertEqual(out["shares"], 0)

    def test_huge_integer_inputs_block_not_bare_crash(self):
        big = 10 ** 400
        for args in ((big, 10.0, 20.0, 1.0, 1.0, 1.0),
                     (1, big, 20.0, 1.0, 1.0, 1.0),
                     (1, 10.0, big, 1.0, 1.0, 1.0),
                     (1, 10.0, 20.0, big, 1.0, 1.0)):
            out = cf.apply_cost_floor(*args)
            self.assertEqual(out["status"], "observe")
            self.assertEqual(out["reason"], "unverifiable_cost_inputs")


class ContractTests(unittest.TestCase):
    def test_observe_reason_in_frozen_vocab(self):
        gov = json.loads(_GOV.read_text(encoding="utf-8"))
        vocab = gov["properties"]["observe_reason_types"]["const"]
        self.assertIn(cf.OBSERVE_REASON_COST, vocab)


if __name__ == "__main__":
    unittest.main()
