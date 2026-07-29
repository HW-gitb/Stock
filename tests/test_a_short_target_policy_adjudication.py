"""Knife-8B target-exit adjudication contract tests."""
from __future__ import annotations

import copy
import unittest

from engine.a_short_experiment_admission_registry import get_admission
from engine.a_short_target_policy_adjudication import adjudicate_target_exit


def _records(weeks: int = 12, entries: int = 2, delta: float = 0.5):
    rows = []
    for week in range(weeks):
        items = []
        for _ in range(entries):
            baseline = {"net_return_pct": 1.0, "diagnostics": {"h5": {"net_return_pct": 0.1}, "h10": {"net_return_pct": 0.2}}}
            challenger = {"net_return_pct": 1.0 + delta, "diagnostics": {"h5": {"net_return_pct": 0.1 + delta}, "h10": {"net_return_pct": 0.2 + delta}}}
            items.append({"changed": True, "outcomes": {"status": "settled", "net_delta_pct": delta,
                                                            "baseline": baseline, "challenger": challenger}})
        rows.append({"decision_date": f"20260{week // 9 + 1}{week % 9 + 1:02d}", "forward_eligible": True,
                     "target_difference": True, "target_entries": items})
    return rows


class TargetPolicyAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.contract = get_admission("p2_target_exit_policy")["statistical_contract"]["definition"]

    def test_no_formal_verdict_before_all_three_evidence_minimums(self):
        verdict = adjudicate_target_exit(_records(weeks=11), self.contract, evidence_counts=True)
        self.assertEqual(verdict["verdict"], "not_adjudicated")

    def test_all_sealed_target_gates_produce_positive_verdict(self):
        verdict = adjudicate_target_exit(_records(), self.contract, evidence_counts=True)
        self.assertEqual(verdict["verdict"], "edge_positive")
        self.assertTrue(verdict["comparison_only"])

    def test_changing_sealed_threshold_changes_the_verdict(self):
        stricter = copy.deepcopy(self.contract)
        stricter["mean_net_improvement_pp_min"] = 0.6
        self.assertEqual(adjudicate_target_exit(_records(), stricter, evidence_counts=True)["verdict"],
                         "edge_not_supported")

    def test_prefreeze_remains_not_adjudicated_even_with_evidence(self):
        self.assertEqual(adjudicate_target_exit(_records(), self.contract, evidence_counts=False)["verdict"],
                         "not_adjudicated")
