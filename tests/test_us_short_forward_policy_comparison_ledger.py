# -*- coding: utf-8 -*-
"""Source-gated private accumulation tests for US-short A1 comparison v2."""
from __future__ import annotations

import copy
import sys
import unittest
from unittest import mock
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

    def test_fixed_formal_looks_and_direct_multi_passer_final_are_not_continuous_peeking(self):
        plan = comparison.load_forward_policy_statistical_plan()
        self.assertEqual(comparison._formal_look_alpha(plan, 24), 0.0125)
        self.assertEqual(comparison._formal_look_alpha(plan, 36), 0.0125)
        self.assertEqual(comparison._latest_reached_formal_look({"theme_plus": 23}, plan), None)
        self.assertEqual(comparison._latest_reached_formal_look({"theme_plus": 24}, plan), 24)
        self.assertEqual(comparison._latest_reached_formal_look({"theme_plus": 35}, plan), 24)
        self.assertEqual(comparison._latest_reached_formal_look({"theme_plus": 37}, plan), 36)
        passer = {"divergence_weeks": 24, "formal_coverage_ready": True, "formal_pass": True}
        self.assertEqual(
            comparison._question_status({"theme_plus": passer, "theme_aggressive": passer}, plan),
            ("inconclusive", None),
        )
        self.assertEqual(
            comparison._question_status(
                {"theme_plus": passer, "theme_aggressive": passer}, plan, direct_pairwise_winner="theme_plus",
            ),
            ("recommend_adopt_arm", "theme_plus"),
        )

    def test_prior_epoch_segment_remains_counted_when_current_code_epoch_changes(self):
        week, receipt = self._ready_week_and_receipt()
        ledger = comparison.append_source_bound_forward_policy_week(
            ledger=comparison.empty_forward_policy_comparison_ledger(), private_week_record=week, source_receipt=receipt,
        )
        with mock.patch.object(comparison, "baseline_epoch_sha256", return_value="f" * 64):
            adjudication = comparison.evaluate_forward_policy_comparison_ledger(ledger)
        self.assertEqual(adjudication["counted_week_count"], 1)
        self.assertEqual(adjudication["archived_epoch_counted_week_count"], 0)
        self.assertEqual(adjudication["segments"][0]["counted_week_count"], 1)
        self.assertTrue(all(
            len(value) == 64 for value in adjudication["segments"][0]["orthogonality_invariants"].values()
        ))

    def test_segment_random_effects_keeps_compatible_segments_in_one_formal_estimate(self):
        result = comparison._segment_random_effects({"old": [0.01, 0.02], "new": [0.03, 0.04]})
        self.assertEqual(result["method"], "reml_random_effects")
        self.assertEqual(result["segment_count"], 2)
        self.assertGreater(result["mean_advantage"], 0.01)
        self.assertGreaterEqual(result["tau_squared"], 0.0)

    def test_multi_segment_counted_window_defers_cross_epoch_adjudication_to_inconclusive(self):
        # Option (ii), user-ratified 2026-07-18 (register R-RE): once the counted window spans >=2
        # effect-surface segments the pooled CI/placebo are still fixed-effect (no Hartung-Knapp /
        # heterogeneity gate), so cross-epoch adjudication is DEFERRED -> every question emits
        # inconclusive and never a cross-epoch adopt/discard, even at a reached formal look.
        week, receipt = self._ready_week_and_receipt()
        ledger = comparison.append_source_bound_forward_policy_week(
            ledger=comparison.empty_forward_policy_comparison_ledger(), private_week_record=week, source_receipt=receipt,
        )
        two_segments = [
            {"baseline_epoch_sha256": "a" * 64, "counted_week_count": 24, "orthogonality_invariants": {}},
            {"baseline_epoch_sha256": "b" * 64, "counted_week_count": 24, "orthogonality_invariants": {}},
        ]
        with mock.patch.object(comparison, "_segment_orthogonality_summary", return_value=two_segments), \
                mock.patch.object(comparison, "_latest_reached_formal_look", return_value=24), \
                mock.patch.object(comparison, "_arm_summary", return_value={"available_divergence_weeks": 24}), \
                mock.patch.object(comparison, "_apply_formal_gates"):
            adjudication = comparison.evaluate_forward_policy_comparison_ledger(ledger)
        self.assertTrue(adjudication["multi_segment_cross_epoch_adjudication_deferred"])
        self.assertTrue(adjudication["questions"])  # questions were actually evaluated
        for question, block in adjudication["questions"].items():
            self.assertEqual(block["status"], "inconclusive", question)
            self.assertTrue(block["cross_epoch_adjudication_deferred"], question)
            self.assertIsNone(block["recommended_arm"], question)
            self.assertFalse(block["requires_user_decision"], question)

    def test_single_segment_is_not_forced_inconclusive_by_the_multi_segment_gate(self):
        # Control: a single-epoch counted window is NOT deferred; the real gates decide, and a
        # single-arm question with a formal pass still reaches a recommendation.
        week, receipt = self._ready_week_and_receipt()
        ledger = comparison.append_source_bound_forward_policy_week(
            ledger=comparison.empty_forward_policy_comparison_ledger(), private_week_record=week, source_receipt=receipt,
        )
        one_segment = [{"baseline_epoch_sha256": "a" * 64, "counted_week_count": 24, "orthogonality_invariants": {}}]
        passer = {"available_divergence_weeks": 24, "divergence_weeks": 24, "formal_coverage_ready": True, "formal_pass": True}
        with mock.patch.object(comparison, "_segment_orthogonality_summary", return_value=one_segment), \
                mock.patch.object(comparison, "_latest_reached_formal_look", return_value=24), \
                mock.patch.object(comparison, "_arm_summary", return_value=dict(passer)), \
                mock.patch.object(comparison, "_apply_formal_gates"), \
                mock.patch.object(comparison, "_direct_pairwise_winner", return_value=(None, [])):
            adjudication = comparison.evaluate_forward_policy_comparison_ledger(ledger)
        self.assertFalse(adjudication["multi_segment_cross_epoch_adjudication_deferred"])
        for block in adjudication["questions"].values():
            self.assertFalse(block["cross_epoch_adjudication_deferred"])
        # a single-arm question (catalyst / overextension) with a formal pass adopts under one segment
        self.assertEqual(adjudication["questions"]["catalyst_weight_choice"]["status"], "recommend_adopt_arm")


if __name__ == "__main__":
    unittest.main()
