"""Unit tests for the Rule6 producer inventory and completion gate."""

from __future__ import annotations

import unittest

from engine.a_short_rule6_contract import (
    RULE6_CHECKS,
    RULE6_CONDITIONAL_NA_REASONS,
    RULE6_D_TIER_REASONS,
    assess_rule6_checks,
    render_rule6_d_tier_banner,
    validate_rule6_check_contract,
)


def _checks(status="pass"):
    return [
        {"id": check_id, "group": group,
         "status": "not_applicable" if check_id in RULE6_D_TIER_REASONS else status,
         "notes": RULE6_D_TIER_REASONS.get(check_id)}
        for check_id, group in RULE6_CHECKS
    ]


class Rule6ContractTests(unittest.TestCase):
    def test_complete_clear_inventory_is_clear(self):
        checks = _checks()
        validate_rule6_check_contract(checks)
        gate = assess_rule6_checks(checks)
        self.assertEqual(gate["disposition"], "clear")
        self.assertEqual(
            {item["id"] for item in gate["not_applicable_checks"]},
            set(RULE6_D_TIER_REASONS),
        )
        self.assertIn("仅人工核查", render_rule6_d_tier_banner(gate))

    def test_missing_or_pending_check_requires_manual_review(self):
        missing = _checks()[1:]
        with self.assertRaises(ValueError):
            validate_rule6_check_contract(missing)
        self.assertEqual(assess_rule6_checks(missing)["disposition"], "manual_review")

        pending = _checks()
        pending[0]["status"] = "pending_data"
        with self.assertRaisesRegex(ValueError, "pass, fail, or unknown"):
            validate_rule6_check_contract(pending)
        self.assertEqual(assess_rule6_checks(pending)["disposition"], "manual_review")

    def test_failed_check_is_hard_veto_even_with_other_pending_checks(self):
        checks = _checks("pending_data")
        checks[4]["status"] = "fail"
        gate = assess_rule6_checks(checks)
        self.assertEqual(gate["disposition"], "hard_veto")
        self.assertEqual(gate["hard_veto_check_ids"], ["rule6_cash_debt_double_high"])

    def test_only_d_tier_may_be_not_applicable_with_canonical_reason(self):
        checks = _checks()
        checks[0]["status"] = "not_applicable"
        with self.assertRaises(ValueError):
            validate_rule6_check_contract(checks)
        self.assertEqual(assess_rule6_checks(checks)["disposition"], "manual_review")

    def test_malformed_or_drifting_inventory_is_manual_review(self):
        cases = {
            "not_a_list": {"id": "rule6_holder_reduction"},
            "non_object_row": [None],
            "unknown_id": [dict(_checks()[0], id="rule6_unknown")],
            "duplicate": _checks() + [dict(_checks()[0])],
        }
        group_mismatch = _checks()
        group_mismatch[0]["group"] = "post_veto"
        cases["group_mismatch"] = group_mismatch
        d_tier_as_pass = _checks()
        next(item for item in d_tier_as_pass if item["id"] == "rule6_regulatory_48h")["status"] = "pass"
        cases["d_tier_pass"] = d_tier_as_pass

        for name, checks in cases.items():
            with self.subTest(name=name):
                gate = assess_rule6_checks(checks)
                self.assertEqual(gate["disposition"], "manual_review")
                self.assertEqual(gate["hard_veto_check_ids"], [])

        checks = _checks()
        d_tier = next(check for check in checks if check["id"] == "rule6_regulatory_48h")
        d_tier["notes"] = "unapproved override"
        with self.assertRaises(ValueError):
            validate_rule6_check_contract(checks)
        self.assertEqual(assess_rule6_checks(checks)["disposition"], "manual_review")


class Rule6ConditionalNATests(unittest.TestCase):
    """Margin/short checks may be not_applicable for non-margin stocks only with
    the frozen reason; the loosening must not let arbitrary checks self-clear."""

    def _with_conditional_na(self, margin_notes=None, short_notes=None):
        checks = _checks()
        for item in checks:
            if item["id"] == "rule6_margin_extreme_accumulation":
                item["status"] = "not_applicable"
                item["notes"] = (margin_notes if margin_notes is not None
                                 else RULE6_CONDITIONAL_NA_REASONS[item["id"]])
            elif item["id"] == "rule6_short_selling_surge":
                item["status"] = "not_applicable"
                item["notes"] = (short_notes if short_notes is not None
                                 else RULE6_CONDITIONAL_NA_REASONS[item["id"]])
        return checks

    def test_conditional_na_with_frozen_reason_is_clear(self):
        checks = self._with_conditional_na()
        validate_rule6_check_contract(checks)  # must not raise
        gate = assess_rule6_checks(checks)
        self.assertEqual(gate["disposition"], "clear")
        self.assertEqual(
            {c["id"] for c in gate["conditional_na_checks"]},
            {"rule6_margin_extreme_accumulation", "rule6_short_selling_surge"})
        # conditional-NA must NOT leak into the D-tier banner list
        self.assertEqual({c["id"] for c in gate["not_applicable_checks"]}, set(RULE6_D_TIER_REASONS))
        banner = render_rule6_d_tier_banner(gate)
        self.assertNotIn("rule6_margin_extreme_accumulation", banner)
        self.assertNotIn("rule6_short_selling_surge", banner)

    def test_conditional_na_with_wrong_reason_is_manual_review(self):
        checks = self._with_conditional_na(margin_notes="fabricated reason")
        with self.assertRaises(ValueError):
            validate_rule6_check_contract(checks)
        gate = assess_rule6_checks(checks)
        self.assertEqual(gate["disposition"], "manual_review")
        self.assertIn("conditional_na_disposition:rule6_margin_extreme_accumulation",
                      gate["manual_review_check_ids"])

    def test_other_computable_check_still_cannot_be_not_applicable(self):
        checks = _checks()
        for item in checks:
            if item["id"] == "rule6_volume_stall":
                item["status"] = "not_applicable"
                item["notes"] = RULE6_CONDITIONAL_NA_REASONS["rule6_margin_extreme_accumulation"]
        with self.assertRaises(ValueError):
            validate_rule6_check_contract(checks)
        self.assertEqual(assess_rule6_checks(checks)["disposition"], "manual_review")


if __name__ == "__main__":
    unittest.main()
