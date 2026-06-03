from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_fmp_paid_tier_license_public_docs_review.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_fmp_paid_tier_license_public_docs_review_20260603.json")


class ProviderP1FmpPaidTierLicensePublicDocsReviewSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_artifact(self) -> dict:
        return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "provider_p1_fmp_paid_tier_license_public_docs_review",
        )
        self.assertIn("no-access public-docs review", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_docs_only_no_cost_no_access_and_no_phase7c(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertEqual(scope["contract_status"], "public_docs_review_only_no_access")
        self.assertTrue(scope["docs_only_public_web_review"])
        self.assertTrue(scope["fmp_public_web_pages_read"])
        self.assertTrue(scope["zero_usd_spend"])
        for field in [
            "data_fetch_allowed",
            "api_call_allowed",
            "signup_allowed",
            "purchase_allowed",
            "trial_allowed",
            "account_change_allowed",
            "provider_contact_allowed",
            "raw_parse_allowed",
            "raw_payload_read_allowed",
            "provider_selection_allowed",
            "provider_ranking_allowed",
            "datahub_allowed",
            "runner_consumption_allowed",
            "phase7c_authorized",
            "ship_gate_evidence_allowed",
            "production_ready_claim_allowed",
            "legal_advice_claimed",
        ]:
            self.assertFalse(scope[field], field)

    def test_public_sources_include_pricing_terms_docs_and_prior_evidence(self) -> None:
        source_ids = {item["source_id"] for item in self._load_artifact()["source_refs"]}

        self.assertIn("fmp_pricing_plans_public_page", source_ids)
        self.assertIn("fmp_terms_of_service_public_page", source_ids)
        self.assertIn("fmp_faq_public_page", source_ids)
        self.assertIn("fmp_delisted_companies_doc", source_ids)
        self.assertIn("fmp_stock_split_details_doc", source_ids)
        self.assertIn("fmp_dividends_company_doc", source_ids)
        self.assertIn("fmp_key_metrics_doc", source_ids)
        self.assertIn("fmp_financial_ratios_doc", source_ids)
        self.assertIn("p1_fmp_entitlement_corporate_action_diagnostic_20260603", source_ids)
        self.assertIn("p1_license_storage_retention_review_20260602", source_ids)
        self.assertIn("p1_sivb_reprobe_execution_summary_20260603", source_ids)

    def test_pricing_plans_record_cost_depth_features_without_coverage_proof(self) -> None:
        review = self._load_artifact()["public_pricing_review"]
        plans = {item["plan_id"]: item for item in review["plans"]}

        self.assertEqual(review["review_status"], "public_pricing_page_reviewed_not_entitlement_validation")
        self.assertFalse(review["pricing_page_is_binding_contract_terms"])
        self.assertEqual(set(plans), {"basic", "starter", "premium", "ultimate"})
        self.assertIn("Free", plans["basic"]["public_page_price_summary"])
        self.assertIn("250 Calls / Day", plans["basic"]["public_page_call_limit"])
        self.assertIn("$22.00/mo.", plans["starter"]["public_page_price_summary"])
        self.assertIn("$59.00/mo.", plans["premium"]["public_page_price_summary"])
        self.assertIn("$149.00/mo.", plans["ultimate"]["public_page_price_summary"])
        self.assertIn("30 Years", plans["premium"]["public_page_history_depth"])
        self.assertIn("Full Historical Access", plans["ultimate"]["public_page_history_depth"])

        for plan in plans.values():
            self.assertFalse(plan["feature_listed_is_verified_for_delisted"])
            self.assertFalse(plan["paid_tier_coverage_proven"])
            feature_areas = {item["feature_area"] for item in plan["listed_feature_signals"]}
            self.assertIn("inactive_delisted_companies", feature_areas)
            self.assertIn("fundamentals_ratios_key_metrics", feature_areas)
            for feature in plan["listed_feature_signals"]:
                self.assertTrue(feature["feature_listed_is_not_access_validation"])
                self.assertFalse(feature["endpoint_access_verified"])
                self.assertFalse(feature["delisted_or_sivb_coverage_proven"])

    def test_endpoint_docs_are_listed_but_not_called_or_entitled(self) -> None:
        docs = self._load_artifact()["public_endpoint_docs_review"]
        families = {item["family_id"]: item for item in docs["endpoint_families"]}

        self.assertEqual(docs["review_status"], "endpoint_templates_listed_not_called_not_entitled")
        self.assertFalse(docs["endpoint_docs_listed_is_access_validation"])
        self.assertEqual(
            set(families),
            {
                "delisted_companies",
                "stock_split_details",
                "dividends_company",
                "key_metrics",
                "financial_ratios",
                "historical_eod_price_volume",
            },
        )
        self.assertEqual(
            families["delisted_companies"]["endpoint_template"],
            "https://financialmodelingprep.com/stable/delisted-companies?page=0&limit=100",
        )
        self.assertEqual(
            families["stock_split_details"]["endpoint_template"],
            "https://financialmodelingprep.com/stable/splits?symbol={symbol}",
        )
        for family in families.values():
            self.assertTrue(family["public_docs_listed"])
            self.assertFalse(family["access_verified"])
            self.assertFalse(family["entitlement_verified"])
            self.assertFalse(family["coverage_or_correctness_proven"])

    def test_terms_review_does_not_clear_license_storage_or_legal_use(self) -> None:
        terms = self._load_artifact()["public_terms_storage_review"]
        observations = {item["topic"]: item for item in terms["observations"]}

        self.assertEqual(terms["review_status"], "public_terms_review_only_needs_user_or_legal_decision")
        self.assertFalse(terms["legal_advice_claimed"])
        self.assertFalse(terms["terms_cleared"])
        self.assertFalse(terms["license_approved"])
        self.assertIn("actual Terms", terms["binding_terms_source_note"])
        self.assertIn("license_scope", observations)
        self.assertIn("redistribution_or_display", observations)
        self.assertIn("data_retention_after_termination", observations)
        self.assertIn("data_deletion_and_audit", observations)
        for observation in observations.values():
            self.assertTrue(observation["requires_user_or_legal_judgment"])
            self.assertFalse(observation["clears_use"])

    def test_decision_routes_compare_options_without_selecting_provider(self) -> None:
        summary = self._load_artifact()["decision_routing_summary"]
        routes = {item["route_id"]: item for item in summary["routes"]}

        self.assertEqual(summary["summary_status"], "routes_compared_no_decision_made")
        self.assertFalse(summary["provider_selected_by_this_artifact"])
        self.assertEqual(
            set(routes),
            {"continue_basic_active_only", "upgrade_fmp_paid_tier", "replace_or_add_specialized_source"},
        )
        self.assertIn("cannot claim inactive / delisted coverage", routes["continue_basic_active_only"]["plain_result"])
        self.assertIn("public page does not prove it", routes["upgrade_fmp_paid_tier"]["plain_result"])
        self.assertIn("new provider review", routes["replace_or_add_specialized_source"]["plain_result"])
        for route in routes.values():
            self.assertFalse(route["selected_by_this_artifact"])
            self.assertFalse(route["authorizes_provider_selection"])
            self.assertFalse(route["authorizes_api_call"])
            self.assertFalse(route["authorizes_phase7c"])

    def test_no_silent_default_and_prohibited_claims_stay_false(self) -> None:
        artifact = self._load_artifact()
        policy = artifact["no_silent_default_policy"]
        claims = artifact["prohibited_claims"]

        self.assertTrue(policy["marketing_pricing_page_is_not_binding_contract_terms"])
        self.assertTrue(policy["feature_listed_is_not_verified_for_delisted"])
        self.assertTrue(policy["public_terms_review_is_not_legal_clearance"])
        for field in [
            "terms_cleared",
            "license_approved",
            "paid_tier_delisted_coverage_proven",
            "paid_tier_sivb_access_proven",
            "current_artifact_authorizes_paid_upgrade",
            "current_artifact_authorizes_datahub",
        ]:
            self.assertFalse(policy[field], field)
        for value in claims.values():
            self.assertFalse(value)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["api_call_allowed"] = True
        invalid["scope"]["purchase_allowed"] = True
        invalid["scope"]["phase7c_authorized"] = True
        invalid["public_pricing_review"]["pricing_page_is_binding_contract_terms"] = True
        invalid["public_pricing_review"]["plans"][1]["paid_tier_coverage_proven"] = True
        invalid["public_endpoint_docs_review"]["endpoint_families"][0]["access_verified"] = True
        invalid["public_terms_storage_review"]["terms_cleared"] = True
        invalid["decision_routing_summary"]["provider_selected_by_this_artifact"] = True
        invalid["decision_routing_summary"]["routes"][1]["selected_by_this_artifact"] = True
        invalid["no_silent_default_policy"]["current_artifact_authorizes_paid_upgrade"] = True
        invalid["prohibited_claims"]["provider_selected"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
