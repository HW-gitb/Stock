# -*- coding: utf-8 -*-
"""Source-gated private accumulation tests for US-short A1 comparison v2."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from engine import us_short_forward_policy_comparison_ledger as comparison  # noqa: E402
import test_us_short_forward_policy_weekly_evidence as fixture  # noqa: E402


class ForwardPolicyComparisonLedgerTests(unittest.TestCase):
    def _ready_week_and_receipt(self):
        week = fixture._private_record()
        receipt = comparison.build_same_run_source_receipt(week, run_id="weekly-run-20260731", source_packet_sha256="c" * 64)
        return week, receipt

    def test_only_exact_same_run_source_receipt_can_advance_the_private_clock(self):
        week, receipt = self._ready_week_and_receipt()
        ledger = comparison.append_source_bound_forward_policy_week(
            ledger=comparison.empty_forward_policy_comparison_ledger(), private_week_record=week, source_receipt=receipt,
        )

        self.assertEqual(len(ledger["records"]), 1)
        self.assertEqual(ledger["records"][0]["decision_date"], "20260713")
        adjudication = comparison.evaluate_forward_policy_comparison_ledger(ledger)
        self.assertEqual(adjudication["counted_week_count"], 1)
        self.assertTrue(all(block["status"] == "continue_accumulation" for block in adjudication["questions"].values()))
        self.assertIn("仅建议，不自动切换 balanced", comparison.render_forward_policy_comparison_banner(adjudication))

    def test_receipt_cannot_bind_a_different_price_window_or_be_replaced_for_same_week(self):
        week, receipt = self._ready_week_and_receipt()
        bad = copy.deepcopy(receipt)
        bad["price_window_sha256"] = "d" * 64
        with self.assertRaises(comparison.ForwardPolicyComparisonLedgerError):
            comparison.append_source_bound_forward_policy_week(
                ledger=comparison.empty_forward_policy_comparison_ledger(), private_week_record=week, source_receipt=bad,
            )

        ledger = comparison.append_source_bound_forward_policy_week(
            ledger=comparison.empty_forward_policy_comparison_ledger(), private_week_record=week, source_receipt=receipt,
        )
        conflict = copy.deepcopy(receipt); conflict["run_id"] = "different-run"
        with self.assertRaises(comparison.ForwardPolicyComparisonLedgerError):
            comparison.append_source_bound_forward_policy_week(ledger=ledger, private_week_record=week, source_receipt=conflict)

    def test_a_whole_week_no_count_cannot_be_smuggled_into_the_evidence_clock(self):
        week = fixture._private_record(no_count=True)
        with self.assertRaises(comparison.ForwardPolicyComparisonLedgerError):
            comparison.build_same_run_source_receipt(week, run_id="weekly-run", source_packet_sha256="c" * 64)

    def test_a_fabricated_user_receipt_is_rejected_and_cannot_switch_balanced(self):
        week, receipt = self._ready_week_and_receipt()
        ledger = comparison.append_source_bound_forward_policy_week(
            ledger=comparison.empty_forward_policy_comparison_ledger(), private_week_record=week, source_receipt=receipt,
        )
        pending = {
            "question_id": "theme_weight_choice", "arm_id": "theme_plus", "status": "recommend_adopt_arm",
            "verdict_sha256": "e" * 64, "contract_sha256": ledger["comparison_contract_sha256"],
            "decision": None, "decided_at": None,
        }
        with self.assertRaises(comparison.ForwardPolicyComparisonLedgerError):
            comparison.record_forward_policy_user_decision(
                ledger=ledger, receipt=pending, decision="accept", decided_at="20260801",
            )
        self.assertFalse(ledger["boundary"]["automatic_production_switch"])

    def test_coverage_incomplete_is_inconclusive_not_a_retain_recommendation(self):
        plan = comparison.load_forward_policy_statistical_plan()
        base = {"divergence_weeks": 24, "formal_coverage_ready": False, "formal_pass": False}
        self.assertEqual(comparison._question_status({"theme_plus": base}, plan), ("inconclusive", None))
        covered = dict(base, formal_coverage_ready=True)
        self.assertEqual(comparison._question_status({"theme_plus": covered}, plan), ("recommend_retain_balanced", None))
        winner = dict(covered, formal_pass=True)
        self.assertEqual(comparison._question_status({"theme_plus": winner}, plan), ("recommend_adopt_arm", "theme_plus"))


if __name__ == "__main__":
    unittest.main()
