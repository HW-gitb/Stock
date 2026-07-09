from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_ohlcv_series_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_overextension_summary.schema.json"


def _valid_packet():
    return {
        "schema_name": "us_short_batch5_full_universe_ohlcv_series_packet",
        "schema_version": "1.0.0",
        "generated_at": "2026-07-09T00:00:00Z",
        "scope": {
            "market": "US", "lane": "us_short", "batch": "batch5_provider_live",
            "packet_status": "full_universe_per_ticker_ohlcv_series_ready_for_local_overextension_projection",
            "full_market_reconstruction": True,
            "network_access_performed_by_packet_producer": True,
            "provider_calls_performed_by_packet_producer": True,
            "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False, "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False, "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": "20260709", "candidate_price_basis_date": "20260708",
            "price_basis_date": "2026-07-08", "source_as_of": "2026-07-08",
        },
        "series_contract": {
            "session": "regular", "adjustment_mode": "split_adjusted",
            "as_of": "2026-07-08", "grouped_session_count": 70,
        },
        "provenance": {
            "provider_id": "massive_grouped_daily", "endpoint_or_family": "grouped_daily",
            "source_as_of": "2026-07-08", "observed_at": "2026-07-09T00:00:00Z",
            "coverage_status": "full", "parser_status": "ok",
        },
        "series_by_ticker": {
            "AAPL": {
                "as_of": "2026-07-08", "session": "regular", "adjustment_mode": "split_adjusted",
                "points": [{"date": "2026-07-07", "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}],
            },
        },
    }


def _valid_summary():
    return {
        "schema_name": "us_short_batch5_full_universe_overextension_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_universe_overextension_summary.schema.json",
        "generated_at": "2026-07-09T00:00:00Z",
        "scope": {
            "market": "US", "route": "US-short", "batch": "batch5",
            "purpose": "full_universe_ohlcv_series_packet_to_overextension_projection",
            "status": "full_universe_overextension_projection_written",
            "network_access_performed_by_runner": False, "provider_calls_performed_by_runner": False,
            "raw_payload_storage_performed_by_runner": False, "series_packet_consumed": True,
            "overextension_projection_written": True, "datahub_consumption_performed": False,
            "production_storage_performed": False, "full_market_call_performed": False,
            "yfinance_consumption_performed": False, "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False, "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": "20260709", "candidate_price_basis_date": "20260708",
            "price_basis_date": "2026-07-08", "source_as_of": "2026-07-08",
        },
        "candidate_universe": {
            "row_count": 2404, "eligible_count": 2404,
            "symbol_scope": "full_pass1_eligible_candidate_set", "full_market_sample": False,
        },
        "series_source": {
            "series_count": 2400, "eligible_with_series_count": 2400,
            "provider_ids": ["massive_grouped_daily"], "session": "regular",
            "adjustment_mode": "split_adjusted", "grouped_session_count": 70,
        },
        "projection_contract": {
            "target_count": 2404, "overextension_scored_count": 2380,
            "disposition_counts": {"scored": 2380, "insufficient_data": 24},
            "state_counts": {"none": 2350, "warning": 25, "chasing_extreme": 5},
            "coverage_exactly_matches_full_candidate_set": True,
            "real_ohlcv_source_consumed": True,
        },
        "paths": {
            "candidate_artifact_path": "state/us_short/candidate_universe_20260708.json",
            "series_packet_path": "state/us_short/us_short_batch5_full_universe_ohlcv_series_20260708_packet.json",
            "output_projection_path": "state/us_short/us_short_batch5_full_universe_overextension_20260708.json",
            "summary_path": "docs/us_short_batch5_full_universe_overextension_summary_20260709.json",
        },
        "storage": {
            "series_packet_path_gitignored": True, "output_projection_path_gitignored": True,
            "summary_path_gitignored": False, "summary_contains_ticker_lists": False,
            "summary_contains_price_rows": False, "summary_contains_raw_payload": False,
            "summary_contains_request_urls": False, "summary_contains_secrets": False,
        },
        "prohibited_claims": {
            "provider_selected": False, "full_market_download_performed": False, "yfinance_used": False,
            "paid_access_used": False, "datahub_consumed": False, "production_readiness_claimed": False,
            "ship_gate_evidence_claimed": False, "live_normalized_evidence_claimed": False,
            "broker_or_order_execution_performed": False, "a_share_crossing_performed": False,
        },
        "limitations": ["counts-only tracked summary; no ticker lists / price rows / raw payloads / secrets."],
    }


class _SchemaTestBase(unittest.TestCase):
    SCHEMA_PATH = None

    def _errors(self, payload):
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        self.assertTrue(self.SCHEMA_PATH.exists(), f"missing schema: {self.SCHEMA_PATH}")
        schema = json.loads(self.SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)   # the schema itself must be a valid Draft-07 schema
        return list(Draft7Validator(schema).iter_errors(payload))


class OhlcvSeriesPacketSchemaTest(_SchemaTestBase):
    SCHEMA_PATH = PACKET_SCHEMA_PATH

    def test_valid_packet_passes(self):
        self.assertEqual(self._errors(_valid_packet()), [])

    def test_unknown_top_level_key_rejected(self):
        p = _valid_packet(); p["surprise"] = 1
        self.assertTrue(self._errors(p))

    def test_point_missing_high_rejected(self):
        p = _valid_packet(); del p["series_by_ticker"]["AAPL"]["points"][0]["high"]
        self.assertTrue(self._errors(p))

    def test_point_missing_low_rejected(self):
        p = _valid_packet(); del p["series_by_ticker"]["AAPL"]["points"][0]["low"]
        self.assertTrue(self._errors(p))

    def test_benchmark_symbols_in_series_contract_rejected(self):
        # overextension has NO benchmarks — a leftover momentum-style benchmark field is an additionalProperty
        p = _valid_packet(); p["series_contract"]["benchmark_symbols"] = ["SPY", "QQQ"]
        self.assertTrue(self._errors(p))

    def test_empty_series_by_ticker_rejected(self):
        p = _valid_packet(); p["series_by_ticker"] = {}
        self.assertTrue(self._errors(p))

    def test_point_extra_key_rejected(self):
        p = _valid_packet(); p["series_by_ticker"]["AAPL"]["points"][0]["adjClose"] = 100.0
        self.assertTrue(self._errors(p))

    def test_forged_packet_status_rejected(self):
        p = _valid_packet(); p["scope"]["packet_status"] = "anything_else"
        self.assertTrue(self._errors(p))

    def test_datahub_allowed_claim_rejected(self):
        p = _valid_packet(); p["scope"]["datahub_consumption_allowed"] = True
        self.assertTrue(self._errors(p))


class OverextensionSummarySchemaTest(_SchemaTestBase):
    SCHEMA_PATH = SUMMARY_SCHEMA_PATH

    def test_valid_summary_passes(self):
        self.assertEqual(self._errors(_valid_summary()), [])

    def test_unknown_top_level_key_rejected(self):
        s = _valid_summary(); s["surprise"] = 1
        self.assertTrue(self._errors(s))

    def test_missing_state_counts_rejected(self):
        s = _valid_summary(); del s["projection_contract"]["state_counts"]
        self.assertTrue(self._errors(s))

    def test_state_counts_missing_chasing_rejected(self):
        s = _valid_summary(); del s["projection_contract"]["state_counts"]["chasing_extreme"]
        self.assertTrue(self._errors(s))

    def test_disposition_counts_missing_insufficient_rejected(self):
        s = _valid_summary(); del s["projection_contract"]["disposition_counts"]["insufficient_data"]
        self.assertTrue(self._errors(s))

    def test_provider_call_scope_claim_rejected(self):
        s = _valid_summary(); s["scope"]["provider_calls_performed_by_runner"] = True
        self.assertTrue(self._errors(s))

    def test_secret_storage_claim_rejected(self):
        s = _valid_summary(); s["storage"]["summary_contains_secrets"] = True
        self.assertTrue(self._errors(s))

    def test_bad_summary_path_rejected(self):
        s = _valid_summary(); s["paths"]["summary_path"] = "docs/somewhere_else.json"
        self.assertTrue(self._errors(s))

    def test_summary_path_traversal_rejected(self):
        s = _valid_summary()
        s["paths"]["summary_path"] = "provider_samples/us_short_batch5_full_universe_overextension_20260709/../x.json"
        self.assertTrue(self._errors(s))

    def test_non_state_state_path_rejected(self):
        s = _valid_summary(); s["paths"]["series_packet_path"] = "docs/not_state.json"
        self.assertTrue(self._errors(s))


if __name__ == "__main__":
    unittest.main()
