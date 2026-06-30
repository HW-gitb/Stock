import copy
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_provider_live_probe_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_provider_live_probe_summary_20260625.json"


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validator():
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
    return Draft7Validator(_load_schema())


def _valid_summary():
    def endpoint_result(provider, endpoint_family, symbol, fields):
        provider_dir = "financial_modeling_prep" if provider == "FMP" else "sec_edgar"
        safe_symbol = symbol or "_market"
        file_name = "submissions" if endpoint_family == "company_submissions" else endpoint_family
        return {
            "provider": provider,
            "endpoint_family": endpoint_family,
            "symbol": symbol,
            "status": "success",
            "http_status": 200,
            "error_type": None,
            "raw_sample_ref": f"provider_samples/us_short_batch5_v1_provider_live_20260625/raw/{provider_dir}/{safe_symbol}/{file_name}.json",
            "raw_sample_ref_gitignored": True,
            "payload_shape": {"kind": "list" if provider == "FMP" else "object", "row_count": 1 if provider == "FMP" else None},
            "field_presence": {field: True for field in fields},
            "missing_required_fields": [],
        }

    endpoints = [
        endpoint_result("SEC", "company_tickers_mapping", None, ["ticker", "cik_str"]),
    ]
    for symbol in ["AAPL", "MSFT", "JPM"]:
        endpoints.append(
            endpoint_result(
                "FMP",
                "profile_or_company_metadata",
                symbol,
                ["symbol", "companyName", "sector", "industry", "marketCap", "price", "volume"],
            )
        )
        endpoints.append(
            endpoint_result(
                "FMP",
                "historical_eod_price_volume",
                symbol,
                ["date", "open", "high", "low", "close", "volume", "change", "changePercent", "vwap"],
            )
        )
    for symbol in ["AAPL", "MSFT", "JPM"]:
        endpoints.append(
            endpoint_result(
                "SEC",
                "company_submissions",
                symbol,
                ["filings", "recent", "filingDate", "acceptanceDateTime", "accessionNumber", "form"],
            )
        )

    symbol_results = [
        {
            "symbol": symbol,
            "active_symbol_assumption": True,
            "sec_cik_found": True,
            "sec_cik10": cik10,
            "fmp_endpoint_status": {
                "profile_or_company_metadata": "success",
                "historical_eod_price_volume": "success",
            },
            "sec_endpoint_status": {"company_submissions": "success"},
            "observations": [],
        }
        for symbol, cik10 in [
            ("AAPL", "0000320193"),
            ("MSFT", "0000789019"),
            ("JPM", "0000019617"),
        ]
    ]

    return {
        "schema_name": "us_short_batch5_provider_live_probe_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_provider_live_probe_summary.schema.json",
        "packet_ref": "docs/us_short_batch5_provider_live_packet_20260625.json",
        "authorization_ref": "user_chat_20260625_batch5_provider_live_probe_10_call_boundary",
        "generated_at": "2026-06-25T00:00:00+08:00",
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "first_version_status": "provider_live_probe_executed_small_sample_only",
            "provider_live_probe_performed": True,
            "raw_payload_storage_performed": True,
            "validation_only_raw_parse_performed": True,
            "datahub_consumption_performed": False,
            "web_x_consumption_performed": False,
            "yfinance_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "broker_or_order_execution_performed": False,
            "manual_order_only": True,
            "ship_gate_or_live_normalized_evidence_claimed": False,
        },
        "pre_execution_checks": {
            "user_authorization_confirmed": True,
            "packet_contract_validated": True,
            "provider_samples_gitignore_confirmed": True,
            "environment_precheck_passed": True,
            "fmp_api_key_present": True,
            "sec_user_agent_present": True,
            "budget_precheck_passed": True,
            "no_yfinance": True,
            "no_web_x": True,
            "no_datahub": True,
            "no_full_market": True,
            "no_production_storage": True,
            "no_ship_gate_or_live_normalized_claim": True,
            "no_broker_or_order_execution": True,
        },
        "environment": {
            "fmp_api_key_present": True,
            "fmp_api_key_source": "process",
            "sec_user_agent_present": True,
            "sec_user_agent_source": "process",
            "environment_values_logged": False,
            "secrets_logged": False,
        },
        "storage": {
            "raw_payload_root": "provider_samples/us_short_batch5_v1_provider_live_20260625/raw",
            "raw_payload_root_gitignored": True,
            "tracked_summary_path": "docs/us_short_batch5_provider_live_probe_summary_20260625.json",
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_raw_payload": False,
            "secrets_in_summary": False,
            "request_urls_in_summary": False,
            "sec_user_agent_value_in_summary": False,
        },
        "sample_universe": {
            "symbol_source": "batch5_v1_packet_authorized_active_only_sample",
            "symbols": ["AAPL", "MSFT", "JPM"],
            "active_symbols_only": True,
            "max_symbols": 3,
            "full_market_sample": False,
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": 10,
            "planned_fmp_endpoint_calls": 6,
            "planned_sec_public_api_calls": 4,
            "actual_total_endpoint_calls": 10,
            "actual_fmp_endpoint_calls": 6,
            "actual_sec_public_api_calls": 4,
            "retry_count": 0,
            "within_budget": True,
        },
        "endpoint_results": endpoints,
        "symbol_results": symbol_results,
        "aggregate_validation_metrics": {
            "endpoint_success_count": 10,
            "endpoint_error_count": 0,
            "symbols_with_profile_shape": 3,
            "symbols_with_price_volume_shape": 3,
            "symbols_with_sec_cik": 3,
            "symbols_with_sec_submissions_shape": 3,
        },
        "validation_decision": {
            "status": "bounded_probe_completed",
            "sr_provider_001_remains_open": True,
            "provider_selection_allowed": False,
            "datahub_allowed": False,
            "production_storage_allowed": False,
            "full_market_fetch_allowed": False,
            "ship_gate_evidence_allowed": False,
        },
        "prohibited_claims": {
            "live_normalized_evidence_claimed": False,
            "ship_gate_evidence_claimed": False,
            "production_readiness_claimed": False,
            "provider_selected": False,
            "datahub_ready": False,
            "paper_result_relabelled_as_live": False,
        },
        "limitations": ["active-only three-symbol smoke; not production evidence"],
        "next_steps": ["Codex review before any commit or broader call boundary"],
    }


class UsShortBatch5ProviderLiveProbeSummarySchemaTests(unittest.TestCase):
    def test_valid_fixture_validates(self):
        _validator().validate(_valid_summary())

    def test_rejects_budget_overrun(self):
        summary = _valid_summary()
        summary["endpoint_call_budget"]["actual_total_endpoint_calls"] = 11
        self.assertFalse(_validator().is_valid(summary))

    def test_rejects_secret_or_url_storage_claims(self):
        for path, value in [
            (("storage", "secrets_in_summary"), True),
            (("storage", "request_urls_in_summary"), True),
            (("storage", "tracked_summary_contains_raw_payload"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
        ]:
            summary = copy.deepcopy(_valid_summary())
            summary[path[0]][path[1]] = value
            self.assertFalse(_validator().is_valid(summary))

    def test_rejects_raw_ref_outside_authorized_provider_samples_root(self):
        summary = _valid_summary()
        summary["endpoint_results"][0]["raw_sample_ref"] = "docs/raw_payload.json"
        self.assertFalse(_validator().is_valid(summary))

    def test_rejects_raw_ref_with_parent_dir_traversal(self):
        # F6 (cc_r1_v1): even WITHIN the authorized prefix a `..` traversal must be rejected (the sibling
        # incident-record schema already blocks `..`; this closes the asymmetry).
        summary = copy.deepcopy(_valid_summary())
        summary["endpoint_results"][0]["raw_sample_ref"] = (
            "provider_samples/us_short_batch5_v1_provider_live_20260625/../../etc/passwd"
        )
        self.assertFalse(_validator().is_valid(summary))

    def test_rejects_missing_or_partial_trace_when_counts_claim_completed_probe(self):
        for field in ["endpoint_results", "symbol_results"]:
            summary = copy.deepcopy(_valid_summary())
            summary[field] = []
            self.assertFalse(_validator().is_valid(summary), field)

            summary = copy.deepcopy(_valid_summary())
            summary[field] = summary[field][:-1]
            self.assertFalse(_validator().is_valid(summary), field)

    def test_rejects_duplicate_endpoint_instead_of_required_fixed_family_symbol_combo(self):
        summary = copy.deepcopy(_valid_summary())
        summary["endpoint_results"][-1] = copy.deepcopy(summary["endpoint_results"][1])
        self.assertFalse(_validator().is_valid(summary))

    def test_rejects_duplicate_symbol_instead_of_three_symbol_trace(self):
        summary = copy.deepcopy(_valid_summary())
        summary["symbol_results"][-1] = copy.deepcopy(summary["symbol_results"][0])
        self.assertFalse(_validator().is_valid(summary))

    def test_accepts_error_branch_not_only_all_success(self):
        # R-USSHORT-BATCH5-RUNTIME-SCHEMA-ENFORCEMENT-GAP: the runtime contract must accept the legal ERROR branch
        # (an endpoint errored), not only the all-success committed example — the full per-endpoint/per-symbol
        # trace is still present, so the anti-spoof invariant holds while the status/counts reflect the error.
        err = copy.deepcopy(_valid_summary())
        err["validation_decision"]["status"] = "bounded_probe_completed_with_endpoint_errors"
        err["endpoint_results"][1]["status"] = "error"
        err["aggregate_validation_metrics"]["endpoint_error_count"] = 1
        err["aggregate_validation_metrics"]["endpoint_success_count"] = 9
        _validator().validate(err)   # accepted (raises on any error)

    def test_summary_artifact_validates_when_present(self):
        if not SUMMARY_PATH.exists():
            self.skipTest("batch5 provider-live summary has not been generated yet")
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        _validator().validate(summary)

    def test_summary_artifact_static_invariants_when_present(self):
        if not SUMMARY_PATH.exists():
            self.skipTest("batch5 provider-live summary has not been generated yet")
        summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
        summary = json.loads(summary_text)

        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 10)
        self.assertEqual(summary["endpoint_call_budget"]["actual_fmp_endpoint_calls"], 6)
        self.assertEqual(summary["endpoint_call_budget"]["actual_sec_public_api_calls"], 4)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        self.assertEqual(summary["aggregate_validation_metrics"]["endpoint_success_count"], 10)
        self.assertEqual(summary["aggregate_validation_metrics"]["endpoint_error_count"], 0)
        self.assertEqual(summary["validation_decision"]["status"], "bounded_probe_completed")
        self.assertTrue(summary["validation_decision"]["sr_provider_001_remains_open"])
        self.assertFalse(summary["validation_decision"]["provider_selection_allowed"])
        self.assertFalse(summary["scope"]["datahub_consumption_performed"])
        self.assertFalse(summary["scope"]["ship_gate_or_live_normalized_evidence_claimed"])
        for field, value in summary["prohibited_claims"].items():
            self.assertFalse(value, field)
        for result in summary["endpoint_results"]:
            self.assertTrue(result["raw_sample_ref"].startswith("provider_samples/us_short_batch5_v1_provider_live_20260625/raw/"))
            self.assertTrue(result["raw_sample_ref_gitignored"])
            if result["endpoint_family"] == "company_submissions":
                for field in ["filings", "recent", "filingDate", "acceptanceDateTime", "accessionNumber", "form"]:
                    self.assertTrue(result["field_presence"][field], field)
        for forbidden in [
            "apikey=",
            "financialmodelingprep.com",
            "data.sec.gov",
            "www.sec.gov",
            "\"payload\"",
            "\"request_url\"",
            "\"raw_payload\"",
        ]:
            self.assertNotIn(forbidden, summary_text.lower())


if __name__ == "__main__":
    unittest.main()
