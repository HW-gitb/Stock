"""Draft-07 contract checks for the A1 Cut-D statistical-plan manifest."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/us_short_forward_policy_statistical_plan.schema.json").read_text(encoding="utf-8"))
PLAN = json.loads((ROOT / "presets/us_short_forward_policy_statistical_plan_20260716.json").read_text(encoding="utf-8"))


class ForwardPolicyStatisticalPlanSchemaTests(unittest.TestCase):
    def test_frozen_plan_validates(self):
        jsonschema.Draft7Validator(SCHEMA).validate(PLAN)

    def test_rejects_margin_placebo_or_second_wave_drift(self):
        margin = copy.deepcopy(PLAN)
        margin["statistics"]["comparison_win_margin"] = 0.01
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(SCHEMA).validate(margin)

        placebo = copy.deepcopy(PLAN)
        placebo["statistics"]["placebo"]["seed_end_inclusive"] = 1
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(SCHEMA).validate(placebo)

        second_wave = copy.deepcopy(PLAN)
        second_wave["policy_scope"]["selection_policies"].append("overextension_execution_off")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(SCHEMA).validate(second_wave)

    def test_rejects_backfill_and_ship_gate_drift(self):
        replay = copy.deepcopy(PLAN)
        replay["weekly_manifest"]["historical_replay_counts_as_forward"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(SCHEMA).validate(replay)

        ship_gate = copy.deepcopy(PLAN)
        ship_gate["boundary"]["shadow_counts_ship_gate"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(SCHEMA).validate(ship_gate)

    def test_rejects_common_pool_horizon_question_or_formal_gate_drift(self):
        pool = copy.deepcopy(PLAN)
        pool["weekly_manifest"]["common_selection_pool_basis"] = "pre_pass2_candidates"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(SCHEMA).validate(pool)

        horizon = copy.deepcopy(PLAN)
        horizon["outcome_contract"]["selection_attribution"]["primary_horizon_trading_sessions"] = 5
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(SCHEMA).validate(horizon)

        question = copy.deepcopy(PLAN)
        question["policy_scope"]["factor_questions"]["theme_weight_choice"].remove("theme_off")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(SCHEMA).validate(question)

        formal = copy.deepcopy(PLAN)
        formal["statistics"]["minimum_divergence_weeks_before_formal_recommendation"] = 12
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(SCHEMA).validate(formal)


if __name__ == "__main__":
    unittest.main()
