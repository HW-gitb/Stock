from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

SCHEMA_PATH = Path("schemas/us_short_batch5_bankruptcy_8k_probe_summary.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_bankruptcy_8k_probe_summary_20260703.json")


def valid_summary_fixture() -> dict:
    return {
        "schema_name": "us_short_batch5_bankruptcy_8k_probe_summary",
        "schema_version": "1.0.0",
        "generated_at": "2026-07-03T00:00:00+00:00",
        "access_packet_ref": "docs/us_short_batch5_bankruptcy_8k_access_packet_20260703.json",
        "authorization_ref": "user_chat_20260703_execute_after_claude_pass",
        "schema_ref": "schemas/us_short_batch5_bankruptcy_8k_probe_summary.schema.json",
        "status_as_of": "2026-07-06",
        "source_observed_at": "2026-07-02T23:50:43-04:00",
        "source_parser_ref": "engine.us_short_status_source.build_bankruptcy_screen_from_sec_submissions",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "purpose": "small_sample_bankruptcy_8k_company_submissions_shape_probe",
            "probe_status": "completed",
            "bankruptcy_8k_probe_performed": True,
            "status_source_calls_performed": True,
            "sec_company_submissions_calls_performed": True,
            "validation_only_parse_performed": True,
            "raw_storage_performed": True,
            "tracked_summary_written": True,
            "status_records_written": False,
            "run_fetch_bankruptcy_wiring_performed": False,
            "full_market_application_performed": False,
            "candidate_artifact_written": False,
            "candidate_artifact_schema_changed": False,
            "runner_consumption_allowed": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "provider_selection_allowed": False,
            "live_normalized_evidence_claimed": False,
            "ship_gate_evidence_claimed": False,
            "production_ready_claimed": False,
            "broker_or_order_automation": False,
        },
        "pre_execution_checks": {
            "access_packet_validated": True,
            "offline_preflight_reused": True,
            "user_authorization_confirmed": True,
            "post_preflight_execute_confirmed": True,
            "provider_samples_gitignore_confirmed": True,
            "raw_root_under_approved_provider_samples": True,
            "environment_precheck_passed": True,
            "sec_fair_access_user_agent_present": True,
            "exact_endpoint_confirmation_passed": True,
            "budget_precheck_passed": True,
            "parser_shape_validation_passed": True,
            "no_full_market_application_guard_passed": True,
            "no_run_fetch_wiring_guard_passed": True,
            "no_datahub_consumption_guard_passed": True,
            "no_ship_gate_claim_guard_passed": True,
        },
        "environment": {
            "sec_fair_access_user_agent_present": True,
            "sec_fair_access_user_agent_source": "process",
            "environment_values_logged": False,
            "secrets_logged": False,
            "sec_credentials_required": False,
        },
        "sample_universe": {
            "symbols": ["AAPL", "MSFT", "JPM"],
            "cik_by_symbol": {"AAPL": 320193, "MSFT": 789019, "JPM": 19617},
            "max_symbols": 3,
            "universe_role": "bounded_shape_validation_sample_not_runner_consumable",
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": 3,
            "planned_total_endpoint_calls": 3,
            "actual_total_endpoint_calls": 3,
            "sec_company_submissions_calls": 3,
            "bankruptcy_8k_calls": 3,
            "retry_count_allowed": 0,
            "retry_count_used": 0,
            "within_budget": True,
        },
        "exact_endpoint_confirmation": [
            {
                "symbol": "AAPL",
                "cik": 320193,
                "source_id": "sec_8k_item_103",
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions_recent_filings",
                "request_url_in_summary": False,
            },
            {
                "symbol": "MSFT",
                "cik": 789019,
                "source_id": "sec_8k_item_103",
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions_recent_filings",
                "request_url_in_summary": False,
            },
            {
                "symbol": "JPM",
                "cik": 19617,
                "source_id": "sec_8k_item_103",
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions_recent_filings",
                "request_url_in_summary": False,
            },
        ],
        "storage": {
            "raw_sample_storage_path": "provider_samples/us_short_batch5_bankruptcy_8k_20260703/",
            "raw_samples_gitignored": True,
            "tracked_summary_path": "docs/us_short_batch5_bankruptcy_8k_probe_summary_20260703.json",
            "tracked_summary_contains_raw_payloads": False,
            "tracked_summary_contains_request_urls": False,
            "secrets_in_summary": False,
        },
        "endpoint_results": [
            {
                "symbol": "AAPL",
                "cik": 320193,
                "source_id": "sec_8k_item_103",
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions_recent_filings",
                "status": "ok",
                "http_status": 200,
                "error_type": None,
                "raw_sample_ref": "provider_samples/us_short_batch5_bankruptcy_8k_20260703/raw/sec_edgar/AAPL/company_submissions_recent_filings.json",
                "raw_sample_ref_gitignored": True,
                "payload_shape": {
                    "payload_type": "dict",
                    "top_level_key_count": 1,
                    "recent_row_count": 1,
                    "recent_arrays_equal_length": True,
                    "required_recent_fields_present": {
                        "form": True,
                        "filingDate": True,
                        "accessionNumber": True,
                        "items": True,
                    },
                },
                "shape_validation_status": "ok",
            },
            {
                "symbol": "MSFT",
                "cik": 789019,
                "source_id": "sec_8k_item_103",
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions_recent_filings",
                "status": "ok",
                "http_status": 200,
                "error_type": None,
                "raw_sample_ref": "provider_samples/us_short_batch5_bankruptcy_8k_20260703/raw/sec_edgar/MSFT/company_submissions_recent_filings.json",
                "raw_sample_ref_gitignored": True,
                "payload_shape": {
                    "payload_type": "dict",
                    "top_level_key_count": 1,
                    "recent_row_count": 1,
                    "recent_arrays_equal_length": True,
                    "required_recent_fields_present": {
                        "form": True,
                        "filingDate": True,
                        "accessionNumber": True,
                        "items": True,
                    },
                },
                "shape_validation_status": "ok",
            },
            {
                "symbol": "JPM",
                "cik": 19617,
                "source_id": "sec_8k_item_103",
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions_recent_filings",
                "status": "ok",
                "http_status": 200,
                "error_type": None,
                "raw_sample_ref": "provider_samples/us_short_batch5_bankruptcy_8k_20260703/raw/sec_edgar/JPM/company_submissions_recent_filings.json",
                "raw_sample_ref_gitignored": True,
                "payload_shape": {
                    "payload_type": "dict",
                    "top_level_key_count": 1,
                    "recent_row_count": 0,
                    "recent_arrays_equal_length": True,
                    "required_recent_fields_present": {
                        "form": True,
                        "filingDate": True,
                        "accessionNumber": True,
                        "items": True,
                    },
                },
                "shape_validation_status": "ok",
            },
        ],
        "sample_shape_results": {
            "by_symbol": {
                "AAPL": {
                    "submission_shape_valid": True,
                    "recent_fields_present": {
                        "form": True,
                        "filingDate": True,
                        "accessionNumber": True,
                        "items": True,
                    },
                    "recent_array_lengths_equal": True,
                    "recent_row_count": 1,
                    "form_8k_count": 1,
                    "item_103_candidate_count": 1,
                    "parser_status": "ok",
                    "bankruptcy_screen_status": "bankrupt_8k_found",
                    "filing_accession_if_found": "0000320193-26-000001",
                },
                "MSFT": {
                    "submission_shape_valid": True,
                    "recent_fields_present": {
                        "form": True,
                        "filingDate": True,
                        "accessionNumber": True,
                        "items": True,
                    },
                    "recent_array_lengths_equal": True,
                    "recent_row_count": 1,
                    "form_8k_count": 1,
                    "item_103_candidate_count": 0,
                    "parser_status": "ok",
                    "bankruptcy_screen_status": "screened_no_filing",
                    "filing_accession_if_found": None,
                },
                "JPM": {
                    "submission_shape_valid": True,
                    "recent_fields_present": {
                        "form": True,
                        "filingDate": True,
                        "accessionNumber": True,
                        "items": True,
                    },
                    "recent_array_lengths_equal": True,
                    "recent_row_count": 0,
                    "form_8k_count": 0,
                    "item_103_candidate_count": 0,
                    "parser_status": "ok",
                    "bankruptcy_screen_status": "screened_no_filing",
                    "filing_accession_if_found": None,
                },
            }
        },
        "aggregate_shape_metrics": {
            "endpoint_success_count": 3,
            "endpoint_error_count": 0,
            "shape_valid_symbol_count": 3,
            "parser_ok_symbol_count": 3,
            "bankruptcy_8k_positive_count": 1,
        },
        "validation_decision": {
            "decision": "bounded_bankruptcy_8k_shape_probe_completed_keep_sr_provider_001_open",
            "sr_provider_001_closed": False,
            "runner_consumption_allowed": False,
            "rationale": "Bounded three-symbol company-submissions shape probe only; no runner consumption or clean-universe claim.",
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_application_performed": False,
            "bankruptcy_8k_full_universe_scanned": False,
            "status_records_runner_consumable": False,
            "candidate_artifact_written": False,
            "datahub_or_adapter_implemented": False,
            "production_runner_consumption_authorized": False,
            "live_normalized_evidence_claimed": False,
            "ship_gate_evidence_claimed": False,
            "production_ready_claimed": False,
            "broker_or_order_automation": False,
        },
        "limitations": ["Shape-only sample; not a full-market bankruptcy screen."],
        "next_steps": ["Review the tracked summary and raw-path boundary before any runner wiring."],
    }


class UsShortBatch5Bankruptcy8kProbeSummarySchemaTest(unittest.TestCase):
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
        self.assertEqual(schema["properties"]["schema_name"]["const"], "us_short_batch5_bankruptcy_8k_probe_summary")
        self.assertIn("bankruptcy 8-K", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_valid_fixture_validates(self) -> None:
        self.assertEqual(self._validate(valid_summary_fixture()), [])

    def test_tracked_artifact_validates_after_execution(self) -> None:
        if not ARTIFACT_PATH.exists():
            self.skipTest("live execution summary has not been written yet")
        artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self._validate(artifact), [])

    def test_scope_creep_is_rejected(self) -> None:
        invalid = copy.deepcopy(valid_summary_fixture())
        invalid["scope"]["runner_consumption_allowed"] = True
        invalid["scope"]["ship_gate_evidence_claimed"] = True
        invalid["endpoint_call_budget"]["actual_total_endpoint_calls"] = 4
        invalid["storage"]["tracked_summary_contains_request_urls"] = True
        invalid["prohibited_claims"]["status_records_runner_consumable"] = True
        invalid["exact_endpoint_confirmation"].append(copy.deepcopy(invalid["exact_endpoint_confirmation"][0]))

        self.assertNotEqual(self._validate(invalid), [])

    def test_hostile_accession_shape_is_rejected(self) -> None:
        invalid = copy.deepcopy(valid_summary_fixture())
        invalid["sample_shape_results"]["by_symbol"]["AAPL"]["filing_accession_if_found"] = "sk-live-token@example.com"

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
