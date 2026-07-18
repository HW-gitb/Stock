"""Huge-integer numeric inputs must fail through domain guards, never OverflowError."""
from __future__ import annotations

import unittest

from engine import us_short_forward_policy_comparison_ledger as comparison
from engine import us_short_forward_policy_order_snapshot as order_snapshot
from engine import us_short_forward_policy_outcome as outcome
from engine import us_short_forward_policy_weekly_evidence as weekly_evidence


class ForwardPolicyNumericGuardTests(unittest.TestCase):
    def test_huge_integer_is_rejected_by_every_forward_policy_finite_guard(self) -> None:
        huge = 10 ** 400
        self.assertFalse(comparison._finite(huge))
        self.assertFalse(order_snapshot._finite_positive(huge))
        self.assertFalse(outcome._finite(huge))
        self.assertFalse(outcome._finite_positive(huge))
        self.assertFalse(weekly_evidence._finite(huge))


if __name__ == "__main__":
    unittest.main()
