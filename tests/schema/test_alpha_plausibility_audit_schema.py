from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/alpha_plausibility_audit.schema.json")
EXAMPLE_PATH = Path("schemas/examples/alpha_plausibility_audit.example.json")
PROVIDER_STATUS_SNAPSHOT_PATH = Path("docs/phase7a_provider_status_snapshot.json")


class AlphaPlausibilityAuditSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "alpha_plausibility_audit")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("does not select providers", schema["description"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["required"],
            [
                "schema_name",
                "schema_version",
                "generated_at",
                "scope",
                "audit_run_id",
                "audit_date",
                "next_review_date",
                "rerun_trigger",
                "audit_policy",
                "provider_status_snapshot",
                "lane_records",
                "portfolio_synthesis",
                "deferred_decisions",
                "limitations",
            ],
        )

    def test_scope_locks_phase7a_boundaries(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        scope = schema["$defs"]["scope"]["properties"]

        self.assertEqual(scope["phase"]["const"], "7a-1")
        self.assertEqual(scope["purpose"]["const"], "alpha_plausibility_audit_contract")
        self.assertEqual(scope["audit_status"]["const"], "schema_first_contract_only")
        self.assertEqual(scope["provider_selection_allowed"]["const"], False)
        self.assertEqual(scope["data_fetch_allowed"]["const"], False)
        self.assertEqual(scope["provider_adapter_allowed"]["const"], False)
        self.assertEqual(scope["datahub_table_implementation_allowed"]["const"], False)
        self.assertEqual(scope["strategy_rule_change_allowed"]["const"], False)
        self.assertEqual(scope["broker_or_order_automation_allowed"]["const"], False)
        self.assertEqual(scope["manual_order_only"]["const"], True)
        self.assertEqual(scope["ship_gate_relaxed"]["const"], False)

    def test_policy_prevents_paper_ship_gate_and_global_capital_pool(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        policy = schema["$defs"]["auditPolicy"]["properties"]

        self.assertEqual(
            policy["detailed_field_inventory_owner"]["const"],
            "docs/ALPHA_VALIDATION_ACTION_GUIDE.md#3-10",
        )
        self.assertEqual(policy["lane_coverage_required"]["const"], 11)
        self.assertEqual(policy["parent_lane_coverage_required"]["const"], 6)
        self.assertEqual(policy["paper_ship_gate_claim_allowed"]["const"], False)
        self.assertEqual(policy["live_normalized_required_for_ship_gate"]["const"], True)
        self.assertEqual(policy["global_aum_pool_allowed"]["const"], False)
        self.assertEqual(policy["fixed_allocation_policy_unchanged"]["const"], True)

    def test_lane_and_parent_coverage_is_forced_by_contains_rules(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        lane_contains = schema["$defs"]["laneRecords"]["allOf"]
        lane_ids = {
            rule["contains"]["properties"]["lane_id"]["const"]
            for rule in lane_contains
        }
        self.assertEqual(lane_ids, set(schema["$defs"]["laneId"]["enum"]))

        parent_contains = schema["$defs"]["parentLanes"]["allOf"]
        parent_ids = {
            rule["contains"]["properties"]["parent_lane_id"]["const"]
            for rule in parent_contains
        }
        self.assertEqual(parent_ids, set(schema["$defs"]["parentLaneId"]["enum"]))

    def test_lane_record_contains_phase7a_mandatory_field_groups(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        required = set(schema["$defs"]["laneRecord"]["required"])

        for field_name in {
            "parent_lane_id",
            "parent_aggregation_rule",
            "provider_readiness",
            "hypothesis_registration",
            "evidence_integrity",
            "pit_survivorship_security_master",
            "regime_factor_exposure",
            "cost_execution_feasibility",
            "capital_deployment_effect",
            "portfolio_correlation_assumption",
        }:
            self.assertIn(field_name, required)

        provider_readiness = schema["$defs"]["providerReadiness"]["required"]
        self.assertEqual(
            provider_readiness,
            [
                "provider_status_snapshot_ref",
                "provider_readiness_confidence",
                "provider_status_source",
                "provider_status_limitations",
            ],
        )

        evidence_integrity = schema["$defs"]["evidenceIntegrity"]["required"]
        self.assertIn("tests_performed_count", evidence_integrity)
        self.assertIn("multiple_testing_notes", evidence_integrity)
        self.assertIn("adjustment_method", evidence_integrity)
        self.assertIn("power_status", evidence_integrity)

    def test_example_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        errors = list(Draft7Validator(schema).iter_errors(example))

        self.assertEqual(errors, [])

    def test_phase7a_provider_status_snapshot_can_drive_example(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        snapshot = json.loads(PROVIDER_STATUS_SNAPSHOT_PATH.read_text(encoding="utf-8"))

        example["provider_status_snapshot"] = snapshot
        for lane_record in example["lane_records"]:
            lane_record["provider_readiness"]["provider_status_snapshot_ref"] = snapshot["snapshot_id"]
            lane_record["provider_readiness"]["provider_status_source"] = snapshot["provider_status_source"]
            lane_record["provider_readiness"]["provider_status_limitations"] = snapshot[
                "provider_status_limitations"
            ]

        errors = list(Draft7Validator(schema).iter_errors(example))

        self.assertEqual(errors, [])

    def test_phase7a_provider_status_snapshot_remains_lightweight(self) -> None:
        snapshot = json.loads(PROVIDER_STATUS_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        status_by_area = {item["area"]: item["status"] for item in snapshot["status_items"]}

        self.assertEqual(snapshot["snapshot_id"], "provider_status_snapshot_20260527_phase7a1")
        self.assertEqual(snapshot["provider_readiness_confidence"], "medium")
        self.assertIn("schemas/provider_capability_catalog.schema.json", snapshot["provider_status_source"])
        self.assertTrue(any("does not select a final provider" in item for item in snapshot["provider_status_limitations"]))
        self.assertEqual(status_by_area["Provider capability and field catalog contract"], "ready")
        self.assertEqual(
            status_by_area[
                "US fundamentals, SEC filings, filing dates, restatements, cash-flow fields, corporate actions, buybacks, dilution, and dividends"
            ],
            "unknown",
        )
        self.assertEqual(
            status_by_area["A/US burst full-data event, flow, options, borrow, and catalyst tier"],
            "blocked",
        )

    def test_missing_required_lane_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["lane_records"] = [
            lane for lane in invalid["lane_records"] if lane["lane_id"] != "us_long_re_rating_catalyst"
        ]
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(errors)
        self.assertTrue(any(list(error.path) == ["lane_records"] for error in errors))

    def test_risk_filter_decision_requires_effectiveness_evidence_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["lane_records"][0].pop("risk_filter_effectiveness_evidence")
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("risk_filter_effectiveness_evidence" in error.message for error in errors))

    def test_long_lane_requires_fraud_accounting_red_flags_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        long_lane = next(lane for lane in invalid["lane_records"] if lane["lane_id"] == "a_long_core_quality")
        long_lane.pop("fraud_accounting_red_flags")
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("fraud_accounting_red_flags" in error.message for error in errors))

    def test_scope_creep_flags_are_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["audit_policy"]["paper_ship_gate_claim_allowed"] = True
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("False" in error.message or "false" in error.message for error in errors))


if __name__ == "__main__":
    unittest.main()
