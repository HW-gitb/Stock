from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from runners import us_egs_sivb_reprobe_packet as sivb_reprobe


SCHEMA_PATH = Path("schemas/provider_p1_sivb_reprobe_execution_summary.schema.json")
PACKET_PATH = Path("docs/provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json")
SUMMARY_PATH = Path("docs/provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json")


def minimal_valid_summary() -> dict:
    payload = {
        "non_json_response_bytes": 50,
        "non_json_response_body_text": "Payment Required: Upgrade plan for historical endpoint",
        "non_json_response_body_encoding": "utf-8-replacement",
    }
    records = [
        sivb_reprobe.sample_validation.FetchRecord(
            provider_id="financial_modeling_prep",
            endpoint_family=family,
            symbol="SIVB",
            raw_sample_ref=(
                "provider_samples/us_egs_sivb_reprobe_20260603/"
                f"raw/financial_modeling_prep/SIVB/{family}.json"
            ),
            ok=False,
            http_status=402,
            error_type="http_error",
            payload=payload,
        )
        for family in sivb_reprobe.EXPECTED_FMP_ENDPOINT_FAMILIES
    ]
    packet = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
    return sivb_reprobe.build_summary(
        packet=packet,
        generated_at="2026-06-03T00:00:00+00:00",
        env_summary={
            "fmp_api_key_present": True,
            "fmp_api_key_source": "process",
            "environment_values_logged": False,
            "secrets_logged": False,
        },
        pre_execution_checks={
            "independent_review_pass_confirmed": True,
            "post_review_execute_command_confirmed": True,
            "provider_samples_gitignore_confirmed": True,
            "environment_precheck_passed": True,
            "fmp_api_key_present": True,
            "budget_precheck_passed": True,
            "exact_symbol_and_family_fixed": True,
            "no_new_token_trial_paid_or_contact_used": True,
            "yfinance_not_used": True,
            "full_market_fetch_not_used": True,
        },
        endpoint_records=records,
        dry_run_env=False,
    )


class ProviderP1SivbReprobeExecutionSummarySchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

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
        self.assertEqual(schema["properties"]["schema_name"]["const"], "provider_p1_sivb_reprobe_execution_summary")
        self.assertIn("does not prove paid-wall status", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_minimal_summary_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(minimal_valid_summary()), [])

    def test_generated_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            raise unittest.SkipTest("SIVB re-probe execution summary has not been generated yet")

        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self._validate(summary), [])
        summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
        for forbidden in ["apikey=", "financialmodelingprep.com/", "sec.gov/"]:
            self.assertNotIn(forbidden, summary_text.lower())
        for forbidden in ["FMP_API_KEY", "SEC_USER_AGENT", "Bearer ", "Payment Required:"]:
            self.assertNotIn(forbidden, summary_text)

    def test_scope_locks_block_implementation_and_overclaims(self) -> None:
        summary = minimal_valid_summary()
        scope = summary["scope"]
        self.assertFalse(scope["sec_edgar_public_api_calls_performed"])
        self.assertFalse(scope["retry_performed"])
        self.assertFalse(scope["fmp_split_or_dividend_endpoint_calls_performed"])
        for field in [
            "fixture_generation_performed",
            "return_calculation_performed",
            "corporate_action_reconciliation_performed",
            "field_mapping_or_parser_implementation_performed",
            "provider_selection_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_summary",
            "ship_gate_evidence_claimed",
            "production_ready_claim_allowed",
            "broker_or_order_automation_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_response_body_text_is_excluded_from_minimal_summary(self) -> None:
        text = json.dumps(minimal_valid_summary(), ensure_ascii=False)
        self.assertNotIn("Payment Required: Upgrade plan for historical endpoint", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com/", text.lower())
        for endpoint in minimal_valid_summary()["endpoint_results"]:
            self.assertTrue(endpoint["body_capture"]["non_json_response_body_captured_in_raw"])
            self.assertFalse(endpoint["body_capture"]["body_text_in_summary"])
            self.assertFalse(endpoint["classification_signal"]["paid_wall_proven"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(minimal_valid_summary())
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["scope"]["phase7c_authorized_by_this_summary"] = True
        invalid["scope"]["sec_edgar_public_api_calls_performed"] = True
        invalid["endpoint_call_budget"]["retry_count_used"] = 1
        invalid["sample_universe"]["symbols"] = ["SIVB", "TWTR"]
        invalid["prohibited_claims"]["response_body_text_in_tracked_summary"] = True
        invalid["classification_decision"]["sivb_402_paid_wall_proven"] = True
        invalid["endpoint_results"][0]["classification_signal"]["paid_wall_proven"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
