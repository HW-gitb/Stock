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

SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_universe_snapshot.schema.json"


def _valid_snapshot():
    return {
        "schema_name": "us_short_forward_universe_snapshot",
        "schema_version": "1.0.0",
        "generated_at": "2026-07-06T00:00:00Z",
        "forward_start_date": "20260706",
        "provider_as_of": "2026-07-06",
        "provider_label": "local_reviewed_active_listing",
        "source_refs": [
            {"role": "active_listing_input", "path": "state/us_short/test_forward_universe_input.json"}
        ],
        "scope": {
            "market": "US",
            "lane": "us_short",
            "artifact_status": "forward_universe_snapshot_frozen_offline",
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_capture_performed": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "row_count": 2,
        "active_symbols": ["AAPL", "MSFT"],
        "active_universe": [
            {
                "ticker": "AAPL",
                "listing_status": "active",
                "primary_exchange": "NASDAQ",
                "provider_as_of": "2026-07-06",
                "cik": "0000320193",
            },
            {
                "ticker": "MSFT",
                "listing_status": "active",
                "primary_exchange": "NASDAQ",
                "provider_as_of": "2026-07-06",
                "cik": "0000789019",
            },
        ],
        "hashes": {
            "algorithm": "sha256",
            "active_symbols_sha256": "0" * 64,
            "active_universe_rows_sha256": "1" * 64,
        },
        "retention_policy": {
            "delist_events_retained": True,
            "halt_events_retained": True,
            "merger_events_retained": True,
            "bankruptcy_events_retained": True,
            "no_trade_events_retained": True,
            "post_forward_start_deletion_allowed": False,
        },
        "prohibited_claims": {
            "provider_selection_complete": False,
            "live_normalized_evidence": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "datahub_consumed": False,
        },
    }


class UsShortForwardUniverseSnapshotSchemaTest(unittest.TestCase):
    def _schema(self) -> dict:
        self.assertTrue(SCHEMA_PATH.exists(), f"missing schema: {SCHEMA_PATH}")
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _errors(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._schema()).iter_errors(payload))

    def test_valid_snapshot_passes(self):
        self.assertEqual(self._errors(_valid_snapshot()), [])

    def test_unknown_top_level_key_rejected(self):
        payload = _valid_snapshot()
        payload["surprise"] = 1
        self.assertTrue(self._errors(payload))

    def test_provider_call_scope_claim_rejected(self):
        payload = _valid_snapshot()
        payload["scope"]["provider_calls_performed"] = True
        self.assertTrue(self._errors(payload))

    def test_missing_retention_policy_rejected(self):
        payload = _valid_snapshot()
        del payload["retention_policy"]
        self.assertTrue(self._errors(payload))

    def test_source_ref_url_rejected(self):
        payload = _valid_snapshot()
        payload["source_refs"][0]["path"] = "https://example.com/universe.json"
        self.assertTrue(self._errors(payload))

    def test_non_active_row_rejected(self):
        payload = _valid_snapshot()
        payload["active_universe"][0]["listing_status"] = "delisted"
        self.assertTrue(self._errors(payload))

    def test_bad_hash_rejected(self):
        payload = _valid_snapshot()
        payload["hashes"]["active_symbols_sha256"] = "not-a-hash"
        self.assertTrue(self._errors(payload))

    def test_forged_schema_version_rejected(self):
        payload = _valid_snapshot()
        payload["schema_version"] = "9.9.9"
        self.assertTrue(self._errors(payload))

    def test_post_start_deletion_cannot_be_allowed(self):
        payload = _valid_snapshot()
        payload["retention_policy"]["post_forward_start_deletion_allowed"] = True
        self.assertTrue(self._errors(payload))

    def test_missing_prohibited_claim_rejected(self):
        payload = _valid_snapshot()
        del payload["prohibited_claims"]["ship_gate_evidence"]
        self.assertTrue(self._errors(payload))


if __name__ == "__main__":
    unittest.main()
