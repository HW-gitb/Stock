from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_capability_catalog.schema.json")
EXAMPLE_PATH = Path("schemas/examples/provider_capability_catalog.example.json")


class ProviderCapabilityCatalogSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "provider_capability_catalog")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("does not select a final provider", schema["description"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["required"],
            [
                "schema_name",
                "schema_version",
                "generated_at",
                "scope",
                "catalog_policy",
                "provider_profiles",
                "field_catalog",
                "deferred_decisions",
                "limitations",
            ],
        )

    def test_scope_locks_contract_only_boundaries(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        scope = schema["$defs"]["scope"]["properties"]

        self.assertEqual(scope["phase"]["const"], "7")
        self.assertEqual(scope["purpose"]["const"], "provider_capability_field_catalog_contract")
        self.assertEqual(scope["contract_status"]["const"], "schema_first_contract_only")
        self.assertEqual(scope["provider_selection_status"]["const"], "not_selected")
        self.assertEqual(scope["data_fetch_allowed"]["const"], False)
        self.assertEqual(scope["provider_adapter_allowed"]["const"], False)
        self.assertEqual(scope["datahub_table_implementation_allowed"]["const"], False)
        self.assertEqual(scope["production_strategy_rule_change_allowed"]["const"], False)
        self.assertEqual(scope["broker_or_order_automation_allowed"]["const"], False)
        self.assertEqual(scope["manual_order_only"]["const"], True)

    def test_requirement_labels_systems_and_data_classes_cover_audit(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            set(schema["$defs"]["requirementStatus"]["enum"]),
            {
                "structured_required",
                "structured_optional",
                "manual_evidence",
                "research_only",
                "deferred",
            },
        )
        self.assertIn("a_short_evidence", schema["$defs"]["systemId"]["enum"])
        self.assertIn("us_long", schema["$defs"]["systemId"]["enum"])
        self.assertIn("phase7_shared", schema["$defs"]["systemId"]["enum"])
        self.assertIn("financial_statements_filings", schema["$defs"]["dataClass"]["enum"])
        self.assertIn("news_legal_regulatory_short_reports", schema["$defs"]["dataClass"]["enum"])
        self.assertIn("ownership_borrow_short_options", schema["$defs"]["dataClass"]["enum"])

    def test_provider_evaluation_has_no_single_overall_score(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        evaluation_dimensions = schema["$defs"]["evaluationDimensions"]
        self.assertFalse(evaluation_dimensions["additionalProperties"])
        self.assertEqual(
            evaluation_dimensions["required"],
            [
                "coverage",
                "pit_support",
                "history_depth",
                "corporate_actions",
                "units_currency",
                "update_latency",
                "stability",
                "authorization",
                "cost",
                "fallback",
            ],
        )

        provider_policy = schema["$defs"]["providerEvaluationPolicy"]["properties"]
        self.assertEqual(provider_policy["overall_score_allowed"]["const"], False)
        self.assertEqual(provider_policy["field_level_blockers_required"]["const"], True)

    def test_field_contract_requires_lineage_provider_capability_and_no_default_policy(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        field_definition = schema["$defs"]["fieldDefinition"]
        self.assertIn("lineage_requirements", field_definition["required"])
        self.assertIn("provider_capabilities", field_definition["required"])
        self.assertIn("production_use_policy", field_definition["required"])

        production_use = schema["$defs"]["productionUsePolicy"]["properties"]
        self.assertEqual(production_use["silent_default_allowed"]["const"], False)
        self.assertEqual(production_use["latest_only_historical_evidence_allowed"]["const"], False)

        default_policy = schema["$defs"]["defaultValuePolicy"]["properties"]
        self.assertEqual(default_policy["silent_default_allowed"]["const"], False)
        self.assertEqual(default_policy["benchmark_missing_month_rule"]["const"], "do_not_fill_zero")

    def test_status_axes_are_documented_and_can_be_decoupled(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

        automation_status = schema["$defs"]["fieldDefinition"]["properties"]["automation_status"]
        self.assertIn("Technical automation readiness", automation_status["description"])
        self.assertIn("does not by itself authorize production use", automation_status["description"])

        use_status = schema["$defs"]["productionUsePolicy"]["properties"]["use_status"]
        self.assertIn("Policy/governance permission", use_status["description"])
        self.assertIn("veto", use_status["description"])

        missing_data_rule = schema["$defs"]["productionUsePolicy"]["properties"]["missing_data_rule"]
        self.assertIn("Runtime behavior", missing_data_rule["description"])

        fallback_path = schema["$defs"]["providerRequirements"]["properties"]["fallback_path"]
        self.assertIn("Design-time routing", fallback_path["description"])

        fields = {field["field_id"]: field for field in example["field_catalog"]["fields"]}
        decoupled_field = fields["a_industry.sw_l2_membership"]
        self.assertEqual(decoupled_field["automation_status"], "automatable_after_provider_review")
        self.assertEqual(
            decoupled_field["production_use_policy"]["use_status"],
            "blocked_until_provider_review",
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

    def test_example_keeps_provider_selection_unresolved(self) -> None:
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(example["scope"]["provider_selection_status"], "not_selected")
        self.assertTrue(example["provider_profiles"])
        self.assertTrue(
            all(profile["selection_status"] == "not_selected" for profile in example["provider_profiles"])
        )
        self.assertIn(
            "us_fundamentals_provider_tbd",
            {profile["provider_id"] for profile in example["provider_profiles"]},
        )

    def test_selected_provider_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["provider_profiles"][0]["selection_status"] = "selected"
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("not_selected" in error.message for error in errors))

    def test_silent_default_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["field_catalog"]["fields"][0]["production_use_policy"]["silent_default_allowed"] = True
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("False" in error.message or "false" in error.message for error in errors))

    def test_overall_provider_score_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["provider_profiles"][0]["evaluation_dimensions"]["overall_score"] = 0.7
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("overall_score" in error.message for error in errors))


if __name__ == "__main__":
    unittest.main()
