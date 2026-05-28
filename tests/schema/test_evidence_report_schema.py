from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/evidence_report.schema.json")
EXAMPLE_PATH = Path("schemas/examples/evidence_report.example.json")


class EvidenceReportSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "evidence_report")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("Phase 7a-5", schema["description"])
        self.assertIn("does not select providers", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_scope_locks_phase7a5_boundaries(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        scope = schema["$defs"]["scope"]["properties"]

        self.assertEqual(scope["phase"]["const"], "7a-5")
        self.assertEqual(scope["purpose"]["const"], "evidence_report_schema_contract")
        self.assertEqual(scope["contract_status"]["const"], "schema_first_contract_only")
        self.assertEqual(scope["provider_selection_allowed"]["const"], False)
        self.assertEqual(scope["data_fetch_allowed"]["const"], False)
        self.assertEqual(scope["provider_adapter_allowed"]["const"], False)
        self.assertEqual(scope["datahub_table_implementation_allowed"]["const"], False)
        self.assertEqual(scope["strategy_rule_change_allowed"]["const"], False)
        self.assertEqual(scope["broker_or_order_automation_allowed"]["const"], False)
        self.assertEqual(scope["manual_order_only"]["const"], True)
        self.assertEqual(scope["ship_gate_relaxed"]["const"], False)

    def test_required_sections_cover_phase7a5_workflow_closure(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        required = set(schema["required"])

        for field_name in {
            "immutable_decision_packet",
            "cost_adjusted_return",
            "cash_drag",
            "manual_override_log",
            "minimal_reconciliation",
            "thesis_outcome_log",
            "research_experiment_log",
        }:
            self.assertIn(field_name, required)

    def test_policy_links_prior_contracts_and_prevents_pooling(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        policy = schema["$defs"]["evidencePolicy"]["properties"]
        provider_context = schema["$defs"]["providerBenchmarkContext"]["properties"]
        feasibility_context = schema["$defs"]["evidenceFeasibilityContext"]["properties"]
        ship_gate_claim = schema["$defs"]["shipGateClaim"]["properties"]

        self.assertEqual(policy["fixed_allocation_policy_unchanged"]["const"], True)
        self.assertEqual(policy["global_aum_pool_allowed"]["const"], False)
        self.assertEqual(policy["cross_market_pooling_allowed"]["const"], False)
        self.assertEqual(policy["paper_ship_gate_claim_allowed"]["const"], False)
        self.assertEqual(provider_context["provider_priority_contract_ref"]["const"], "docs/provider_priority_benchmark_contract.md")
        self.assertEqual(provider_context["benchmark_set_source"]["const"], "docs/provider_priority_benchmark_contract.md")
        self.assertEqual(provider_context["provider_selection_made_by_this_report"]["const"], False)
        self.assertEqual(feasibility_context["feasibility_controls_doc_ref"]["const"], "docs/evidence_feasibility_controls.md")
        self.assertEqual(feasibility_context["feasibility_controls_schema_ref"]["const"], "schemas/evidence_feasibility_controls.schema.json")
        self.assertEqual(ship_gate_claim["paper_evidence_used_for_ship_gate"]["const"], False)
        self.assertEqual(ship_gate_claim["full_size_manual_use_authorized_by_this_report"]["const"], False)
        self.assertEqual(ship_gate_claim["existing_ship_gate_policy_ref"]["const"], "AGENTS.md#项目背景")

    def test_decision_packet_immutability_is_locked(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        immutability = schema["$defs"]["decisionPacketImmutability"]["properties"]

        self.assertEqual(immutability["mutation_after_issue_allowed"]["const"], False)
        self.assertEqual(immutability["append_only_corrections_required"]["const"], True)
        self.assertEqual(immutability["decision_timestamp_before_outcome_required"]["const"], True)
        self.assertEqual(immutability["parameter_hash_required"]["const"], True)

    def test_cost_components_are_full_reporting_surface(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cost_components = set(schema["$defs"]["costComponents"]["required"])

        self.assertEqual(
            cost_components,
            {
                "commissions_pct",
                "taxes_pct",
                "stamp_duty_pct",
                "slippage_pct",
                "spread_pct",
                "borrow_fee_pct",
                "fx_conversion_pct",
                "dividends_pct",
                "withholding_tax_pct",
                "adr_fee_pct",
                "market_impact_pct",
                "cash_drag_pct",
                "missed_trade_opportunity_cost_pct",
                "other_costs_pct",
            },
        )

    def test_circuit_breaker_action_set_consumes_phase7a4_controls(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        rules = schema["$defs"]["evidenceFeasibilityContext"]["properties"]["circuit_breaker_action_set"]["allOf"]
        actions = {rule["contains"]["const"] for rule in rules}

        self.assertEqual(
            actions,
            {"warn", "size_down", "pause_new_entries", "manual_review", "reactivation_cooldown"},
        )

    def test_research_experiment_cannot_directly_feed_production(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        promotion = schema["$defs"]["researchPromotionPolicy"]["properties"]

        self.assertEqual(promotion["no_direct_production_feed"]["const"], True)
        self.assertEqual(promotion["requires_schema_review"]["const"], True)
        self.assertEqual(promotion["requires_claude_review"]["const"], True)
        self.assertEqual(promotion["requires_user_approval"]["const"], True)

    def test_example_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        errors = list(Draft7Validator(schema).iter_errors(example))

        self.assertEqual(errors, [])

    def test_paper_ship_gate_claim_fails(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        broken = copy.deepcopy(example)
        broken["ship_gate_claim"]["claim_status"] = "claimed"

        errors = list(Draft7Validator(schema).iter_errors(broken))

        self.assertNotEqual(errors, [])

    def test_research_only_ship_gate_claim_fails(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        broken = copy.deepcopy(example)
        broken["evidence_level"] = "research_only"
        broken["ship_gate_claim"]["evidence_level_used"] = "research_only"
        broken["ship_gate_claim"]["claim_status"] = "claimed"

        errors = list(Draft7Validator(schema).iter_errors(broken))

        self.assertNotEqual(errors, [])

    def test_live_normalized_without_reconciliation_fails(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        broken = copy.deepcopy(example)
        broken["evidence_level"] = "live_normalized"
        broken["minimal_reconciliation"]["reconciliation_status"] = "reconciliation_pending"
        broken["minimal_reconciliation"]["actual_position_reconciliation_available"] = False

        errors = list(Draft7Validator(schema).iter_errors(broken))

        self.assertNotEqual(errors, [])

    def test_direct_research_promotion_fails(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        broken = copy.deepcopy(example)
        broken["research_experiment_log"]["production_promotion"]["no_direct_production_feed"] = False

        errors = list(Draft7Validator(schema).iter_errors(broken))

        self.assertNotEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
