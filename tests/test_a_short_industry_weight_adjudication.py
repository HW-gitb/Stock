"""Knife 8D1 synthetic closure tests for the pure P5b adjudicator."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_experiment_admission_registry import get_admission
from engine.a_short_industry_weight_adjudication import adjudicate_question, holm_bonferroni
from engine.a_short_industry_weight_comparison import load_governance


def _question(question_id: str, *, evidence_counts: bool = True) -> dict:
    governance = load_governance()
    raw = next(row for row in governance["questions"] if row["question_id"] == question_id)
    admission = get_admission(f"p5_{question_id}")
    return {**raw, "evidence_counts": evidence_counts,
            "p5b_adjudication_governance": admission["statistical_contract"]["definition"]["p5b_adjudication_governance"]}


def _rows(count: int, *, differences: int, effect: float) -> list[dict]:
    return [{"decision_date": f"2026{index + 1:04d}", "same_list": index >= differences,
             "effect_pct": effect, "exit_date": f"2027{index + 1:04d}",
             "challenger_ticket_returns": [1.0], "challenger_close_drawdown_pct": 0.0,
             "relative_close_drawdown_worsening_pct": 0.0}
            for index in range(count)]


class IndustryWeightAdjudicationTests(unittest.TestCase):
    def test_12_weeks_and_six_difference_weeks_can_issue_preliminary_permission(self):
        governance = load_governance(); question = _question("balanced_vs_legacy")
        result = adjudicate_question(_rows(12, differences=6, effect=1.0), mature=12, no_count=0,
                                     governance=governance, question=question, holm_rejected=set())
        self.assertEqual(result["checkpoint_stage"], "preliminary")
        self.assertEqual(result["verdict"], "retain_balanced_only")

    def test_terminal_difference_gate_blocks_positive_and_negative_terminal_branches(self):
        governance = load_governance(); question = _question("aggressive_vs_balanced")
        for effect, holm in ((1.0, {"aggressive_vs_balanced"}), (-1.0, set())):
            result = adjudicate_question(_rows(36, differences=12, effect=effect), mature=36, no_count=0,
                                         governance=governance, question=question, holm_rejected=holm)
            self.assertEqual(result["verdict"], "continue_accumulating")
            self.assertEqual(result["reason"], "insufficient_policy_separation")

    def test_holm_bonferroni_matches_manual_step_down_rejection_set(self):
        self.assertEqual(holm_bonferroni({"a": 0.005, "b": 0.012, "c": 0.03}, 0.025), {"a", "b"})

    def test_nonfinite_effect_cannot_issue_positive_permission(self):
        governance = load_governance(); question = _question("balanced_vs_legacy")
        rows = _rows(12, differences=6, effect=1.0)
        rows[0]["effect_pct"] = float("inf")
        result = adjudicate_question(rows, mature=12, no_count=0, governance=governance, question=question,
                                     holm_rejected=set())
        self.assertEqual(result["verdict"], "continue_accumulating")
        self.assertEqual(result["reason"], "nonfinite_effect_evidence")

    def test_missing_close_drawdown_cannot_default_to_zero_for_positive_permission(self):
        governance = load_governance(); question = _question("balanced_vs_legacy")
        rows = _rows(12, differences=6, effect=1.0)
        for row in rows:
            row.pop("challenger_close_drawdown_pct")
        result = adjudicate_question(rows, mature=12, no_count=0, governance=governance, question=question,
                                     holm_rejected=set())
        self.assertFalse(result["metrics"]["risk_ok"])
        self.assertNotEqual(result["verdict"], "retain_balanced_only")

    def test_zero_evidence_reports_not_reached_not_preliminary(self):
        governance = load_governance(); question = _question("balanced_vs_legacy")
        result = adjudicate_question([], mature=0, no_count=0, governance=governance, question=question,
                                     holm_rejected=set())
        self.assertEqual(result["checkpoint_stage"], "not_reached")
        self.assertEqual(result["reason"], "checkpoint_not_reached")
