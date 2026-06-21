# -*- coding: utf-8 -*-
"""Tests for US-short position_sizing (engine/us_short_position_sizing.py) — §8 风险定仓 + 削减叠法.

Adversarial focus: the risk-based formula + floor, the HARSHEST-not-product discount (§8 取最狠不连乘),
the reduction stack (regime × discount → min caps → observe-if-below-min), and whole-class fail-closed
(every malformed input collapses toward a smaller position, never an inflated one).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_position_sizing as ps  # noqa: E402


class RiskBasedBaseTests(unittest.TestCase):
    def test_formula(self):
        # budget = 10000 * 0.0075 = 75; per-share risk = 100 - 95 = 5; base = floor(75/5) = 15
        self.assertEqual(ps.risk_based_base_shares(10000.0, 100.0, 95.0), 15)

    def test_floor_not_round(self):
        # 75 / 4 = 18.75 → 18
        self.assertEqual(ps.risk_based_base_shares(10000.0, 100.0, 96.0), 18)

    def test_non_positive_per_share_risk_fails_closed(self):
        self.assertEqual(ps.risk_based_base_shares(10000.0, 100.0, 100.0), 0)   # entry == stop
        self.assertEqual(ps.risk_based_base_shares(10000.0, 95.0, 100.0), 0)    # stop above entry (not a long)

    def test_malformed_inputs_fail_closed(self):
        for b, e, s in ((0.0, 100.0, 95.0), (-1.0, 100.0, 95.0), (float("nan"), 100.0, 95.0),
                        ("10000", 100.0, 95.0), (10000.0, None, 95.0), (10000.0, 100.0, "95"),
                        (10000.0, True, 95.0)):
            self.assertEqual(ps.risk_based_base_shares(b, e, s), 0, (b, e, s))

    def test_non_positive_prices_fail_closed_even_if_entry_gt_stop(self):
        # entry > stop but a non-positive entry/stop is malformed (no real long); base must be 0
        for e, s in ((0.0, -1.0), (-1.0, -2.0), (1.0, 0.0), (0.01, 0.0)):
            self.assertEqual(ps.risk_based_base_shares(10000.0, e, s), 0, (e, s))


class HarshestDiscountTests(unittest.TestCase):
    def test_takes_min_not_product(self):
        # harshest single, NOT 0.8*0.5*0.9 = 0.36
        self.assertEqual(ps.harshest_risk_discount([0.8, 0.5, 0.9]), 0.5)

    def test_explicit_empty_list_is_no_discount(self):
        # an EXPLICITLY empty list/tuple → no reduction (1.0); a malformed CONTAINER is handled separately
        self.assertEqual(ps.harshest_risk_discount([]), 1.0)
        self.assertEqual(ps.harshest_risk_discount(()), 1.0)

    def test_malformed_container_fails_closed_not_no_discount(self):
        # a non-list/tuple container must NOT silently mean "no discount" (that leaves the position un-reduced)
        for bad in (None, "0.5", 0.5, True, {"a": 1}, 3):
            self.assertEqual(ps.harshest_risk_discount(bad), 0.0, repr(bad))

    def test_single(self):
        self.assertEqual(ps.harshest_risk_discount([0.7]), 0.7)

    def test_legit_zero_is_full_kill(self):
        self.assertEqual(ps.harshest_risk_discount([0.0, 0.8]), 0.0)

    def test_malformed_multiplier_fails_closed_to_harshest(self):
        for bad in (float("nan"), 1.5, -0.1, "0.5", True, None):
            self.assertEqual(ps.harshest_risk_discount([0.9, bad]), 0.0, repr(bad))


class ReductionStackTests(unittest.TestCase):
    def _shares(self, **kw):
        return ps.reduction_stack(**kw)["shares"]

    def test_regime_multiplier_applied(self):
        out = ps.reduction_stack(100, 0.8, [], [10_000], min_executable=1)
        self.assertEqual(out["shares"], 80)
        self.assertEqual(out["status"], "sized")

    def test_harshest_discount_applied(self):
        self.assertEqual(self._shares(base_shares=100, regime_multiplier=1.0,
                                      discount_mults=[0.5, 0.9], cap_shares=[10_000]), 50)

    def test_caps_take_minimum(self):
        self.assertEqual(self._shares(base_shares=100, regime_multiplier=1.0,
                                      discount_mults=[], cap_shares=[40, 200]), 40)

    def test_never_exceeds_base_regime_discount_or_caps(self):
        out = ps.reduction_stack(100, 0.5, [0.8], [60, 30], min_executable=1)
        self.assertLessEqual(out["shares"], 30)            # tightest cap
        self.assertLessEqual(out["shares"], int(100 * 0.5 * 0.8))

    def test_below_min_executable_observes(self):
        # floor(1 * 0.5) = 0 → observe
        out = ps.reduction_stack(1, 0.5, [], [10_000], min_executable=1)
        self.assertEqual(out["status"], "observe")
        self.assertEqual(out["shares"], 0)
        self.assertEqual(out["reason"], "below_min_executable")

    def test_regime_zero_kills_position(self):
        out = ps.reduction_stack(100, 0.0, [], [10_000])
        self.assertEqual(out["status"], "observe")
        self.assertEqual(out["shares"], 0)

    def test_malformed_regime_fails_closed(self):
        for bad in (float("nan"), 1.5, -0.1, "0.8", True, None):
            out = ps.reduction_stack(100, bad, [], [10_000])
            self.assertEqual(out["shares"], 0, repr(bad))    # malformed regime → no position

    def test_malformed_cap_fails_closed_to_zero(self):
        out = ps.reduction_stack(100, 1.0, [], [40, float("nan")])   # one bad cap → 0
        self.assertEqual(out["shares"], 0)

    def test_malformed_or_empty_cap_container_observes(self):
        # a position MUST be cap-bounded; a missing / non-list / empty cap container fails closed to observe
        for caps in (None, "x", 100, True, {"a": 1}, []):
            out = ps.reduction_stack(100, 1.0, [], caps)
            self.assertEqual(out["status"], "observe", repr(caps))
            self.assertEqual(out["shares"], 0, repr(caps))

    def test_malformed_discount_container_kills_position(self):
        # a non-list discount container → harshest 0.0 → 0 shares (not silently un-discounted full size)
        for bad in (None, "0.5", 0.5, True):
            self.assertEqual(self._shares(base_shares=100, regime_multiplier=1.0,
                                          discount_mults=bad, cap_shares=[10_000]), 0, repr(bad))

    def test_empty_discount_list_is_no_reduction(self):
        # positive control: an explicit empty discount list → full sized (no reduction), cap/min still apply
        self.assertEqual(self._shares(base_shares=100, regime_multiplier=1.0,
                                      discount_mults=[], cap_shares=[10_000]), 100)

    def test_malformed_base_fails_closed(self):
        for bad in (2.5, -1, "100", True, None):
            self.assertEqual(self._shares(base_shares=bad, regime_multiplier=1.0,
                                          discount_mults=[], cap_shares=[10_000]), 0, repr(bad))

    def test_min_executable_malformed_uses_default(self):
        # a malformed min_executable must not let a sub-1 position slip through
        out = ps.reduction_stack(100, 0.0, [], [10_000], min_executable="bogus")
        self.assertEqual(out["status"], "observe")


if __name__ == "__main__":
    unittest.main()
