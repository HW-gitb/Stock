from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/evidence_feasibility_controls.schema.json")
EXAMPLE_PATH = Path("schemas/examples/evidence_feasibility_controls.example.json")


class EvidenceFeasibilityControlsSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "evidence_feasibility_controls")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("Phase 7a-4", schema["description"])
        self.assertIn("does not select providers", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_scope_locks_phase7a4_boundaries(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        scope = schema["$defs"]["scope"]["properties"]

        self.assertEqual(scope["phase"]["const"], "7a-4")
        self.assertEqual(scope["purpose"]["const"], "evidence_feasibility_controls_contract")
        self.assertEqual(scope["contract_status"]["const"], "schema_first_contract_only")
        self.assertEqual(scope["provider_selection_allowed"]["const"], False)
        self.assertEqual(scope["data_fetch_allowed"]["const"], False)
        self.assertEqual(scope["provider_adapter_allowed"]["const"], False)
        self.assertEqual(scope["datahub_table_implementation_allowed"]["const"], False)
        self.assertEqual(scope["strategy_rule_change_allowed"]["const"], False)
        self.assertEqual(scope["broker_or_order_automation_allowed"]["const"], False)
        self.assertEqual(scope["manual_order_only"]["const"], True)
        self.assertEqual(scope["ship_gate_relaxed"]["const"], False)

    def test_policy_prevents_paper_ship_gate_and_capital_pooling(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        policy = schema["$defs"]["controlPolicy"]["properties"]

        self.assertEqual(policy["fixed_allocation_policy_unchanged"]["const"], True)
        self.assertEqual(policy["global_aum_pool_allowed"]["const"], False)
        self.assertEqual(policy["cross_market_pooling_allowed"]["const"], False)
        self.assertEqual(policy["liquidity_bucket_auto_borrowing_allowed"]["const"], False)
        self.assertEqual(policy["paper_ship_gate_claim_allowed"]["const"], False)
        self.assertEqual(policy["minimal_data_live_eligible_by_default"]["const"], False)
        self.assertEqual(policy["live_normalized_required_for_ship_gate"]["const"], True)
        self.assertEqual(policy["full_size_requires_existing_ship_gate"]["const"], True)
        self.assertEqual(policy["bucket_ceiling_required_before_live_observation"]["const"], True)
        self.assertEqual(policy["actual_position_reconciliation_required_for_live_normalized"]["const"], True)

    def test_lane_coverage_is_forced_by_contains_rules(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        lane_contains = schema["$defs"]["laneControls"]["allOf"]
        lane_ids = {
            rule["contains"]["properties"]["lane_id"]["const"]
            for rule in lane_contains
        }

        self.assertEqual(lane_ids, set(schema["$defs"]["laneId"]["enum"]))
        self.assertEqual(
            lane_ids,
            {
                "a_share_burst_minimal_data",
                "a_share_burst_full_data",
                "us_burst_minimal_data",
                "us_burst_full_data",
            },
        )

    def test_circuit_breaker_requires_all_tier_actions(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        tier_rules = schema["$defs"]["circuitBreakerPlaybook"]["properties"]["tiers"]["allOf"]
        required_actions = {
            rule["contains"]["properties"]["action"]["const"]
            for rule in tier_rules
        }

        self.assertEqual(
            required_actions,
            {
                "warn",
                "size_down",
                "pause_new_entries",
                "manual_review",
                "reactivation_cooldown",
            },
        )

    def test_example_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        errors = list(Draft7Validator(schema).iter_errors(example))

        self.assertEqual(errors, [])

    def test_example_locks_minimal_tiers_to_paper_only(self) -> None:
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        controls_by_lane = {control["lane_id"]: control for control in example["lane_controls"]}

        for lane_id in ("a_share_burst_minimal_data", "us_burst_minimal_data"):
            control = controls_by_lane[lane_id]
            self.assertEqual(control["live_eligibility_status"], "paper_only")
            self.assertEqual(control["exposure_limits"]["max_lane_minimal_live_short_bucket_pct"], 0)
            self.assertEqual(control["evidence_requirements"]["allowed_evidence_levels"], ["paper"])

        for lane_id in ("a_share_burst_full_data", "us_burst_full_data"):
            control = controls_by_lane[lane_id]
            self.assertEqual(control["live_eligibility_status"], "blocked_until_provider_ready")
            self.assertEqual(control["exposure_limits"]["max_lane_minimal_live_short_bucket_pct"], 10)
            self.assertIn("live_normalized", control["evidence_requirements"]["allowed_evidence_levels"])

    def test_missing_circuit_breaker_tier_fails(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        broken = copy.deepcopy(example)
        broken["lane_controls"][0]["circuit_breaker_playbook"]["tiers"] = [
            tier
            for tier in broken["lane_controls"][0]["circuit_breaker_playbook"]["tiers"]
            if tier["action"] != "manual_review"
        ]

        errors = list(Draft7Validator(schema).iter_errors(broken))

        self.assertNotEqual(errors, [])

    def test_paper_ship_gate_claim_fails(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        broken = copy.deepcopy(example)
        broken["control_policy"]["paper_ship_gate_claim_allowed"] = True

        errors = list(Draft7Validator(schema).iter_errors(broken))

        self.assertNotEqual(errors, [])

    def test_global_pooling_claim_fails(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        broken = copy.deepcopy(example)
        broken["lane_controls"][0]["exposure_limits"]["global_pooling_allowed"] = True

        errors = list(Draft7Validator(schema).iter_errors(broken))

        self.assertNotEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
