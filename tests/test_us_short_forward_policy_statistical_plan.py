"""Cut-D statistical-plan manifest guards for the A1 Path-A policy grid."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from engine import us_short_forward_policy_statistical_plan as plan


class ForwardPolicyStatisticalPlanTests(unittest.TestCase):
    def test_loads_the_frozen_same_week_policy_plan(self):
        result = plan.load_forward_policy_statistical_plan()

        self.assertEqual(result["policy_scope"]["selection_policies"], list(plan.SELECTION_POLICY_IDS))
        self.assertEqual(result["statistics"]["primary_metric"], "net_benchmark_excess")
        self.assertEqual(result["statistics"]["minimum_forward_weeks_before_promotion_review"], 12)
        self.assertEqual(result["statistics"]["comparison_win_margin"], 0.001)
        self.assertEqual(result["boundary"]["shadow_counts_ship_gate"], False)

    def test_plan_matches_grid_lifecycle_and_design_authorities(self):
        result = plan.load_forward_policy_statistical_plan()
        authority = json.loads(plan.LIFECYCLE_THRESHOLD_AUTHORITY_PATH.read_text(encoding="utf-8"))
        design = (Path(__file__).resolve().parents[1] / "docs" / "us_short_system_design.md").read_text(encoding="utf-8")
        item_28_category = authority["item_category"]["28"]

        self.assertEqual(
            result["statistics"]["minimum_forward_weeks_before_promotion_review"],
            authority["category_thresholds"][item_28_category]["min_count"],
        )
        self.assertIn("us_short_forward_policy_statistical_plan_20260712.json", design)

    def test_rejects_second_wave_and_selection_grid_drift(self):
        result = plan.load_forward_policy_statistical_plan()

        second_wave = copy.deepcopy(result)
        second_wave["policy_scope"]["selection_policies"].append("overextension_execution_off")
        with self.assertRaises(plan.ForwardPolicyStatisticalPlanError):
            plan.validate_forward_policy_statistical_plan(second_wave)

        missing = copy.deepcopy(result)
        missing["policy_scope"]["selection_policies"].pop()
        with self.assertRaises(plan.ForwardPolicyStatisticalPlanError):
            plan.validate_forward_policy_statistical_plan(missing)

    def test_rejects_backfill_or_replay_as_forward(self):
        result = plan.load_forward_policy_statistical_plan()

        replay = copy.deepcopy(result)
        replay["weekly_manifest"]["historical_replay_counts_as_forward"] = True
        with self.assertRaises(plan.ForwardPolicyStatisticalPlanError):
            plan.validate_forward_policy_statistical_plan(replay)

        backfill = copy.deepcopy(result)
        backfill["weekly_manifest"]["backfill_allowed"] = True
        with self.assertRaises(plan.ForwardPolicyStatisticalPlanError):
            plan.validate_forward_policy_statistical_plan(backfill)

    def test_rejects_statistical_threshold_or_placebo_drift(self):
        result = plan.load_forward_policy_statistical_plan()

        margin = copy.deepcopy(result)
        margin["statistics"]["comparison_win_margin"] = 0.01
        with self.assertRaises(plan.ForwardPolicyStatisticalPlanError):
            plan.validate_forward_policy_statistical_plan(margin)

        placebo = copy.deepcopy(result)
        placebo["statistics"]["placebo"]["seed_start"] += 1
        with self.assertRaises(plan.ForwardPolicyStatisticalPlanError):
            plan.validate_forward_policy_statistical_plan(placebo)

        as_of = copy.deepcopy(result)
        as_of["as_of"] = "20260713"
        with self.assertRaises(plan.ForwardPolicyStatisticalPlanError):
            plan.validate_forward_policy_statistical_plan(as_of)

        divergence = copy.deepcopy(result)
        divergence["statistics"]["selection_divergence"]["membership_symmetric_difference_at_least"] = 0
        with self.assertRaises(plan.ForwardPolicyStatisticalPlanError):
            plan.validate_forward_policy_statistical_plan(divergence)

        promotion_gate = copy.deepcopy(result)
        promotion_gate["statistics"]["elimination_rule"]["promotion_gate"]["paired_win_consistency_fraction"][0] = 1
        with self.assertRaises(plan.ForwardPolicyStatisticalPlanError):
            plan.validate_forward_policy_statistical_plan(promotion_gate)


if __name__ == "__main__":
    unittest.main()
