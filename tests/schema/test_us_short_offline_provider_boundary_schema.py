from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_offline_provider_boundary.schema.json"


def valid_boundary():
    return {
        "schema_name": "us_short_offline_provider_boundary",
        "schema_version": "1.0.0",
        "security_binding": {"security_id": "US-CIK-0000320193-COMMON", "current_ticker": "AAPL", "identity_ref_sha256": "a" * 64},
        "yfinance_smoke_alarm": {
            "status": "not_executed_offline",
            "package_import_attempted": False,
            "network_access_performed": False,
            "failure_disposition": "ticker_scoped_freeze",
            "selection_use_allowed": False,
        },
        "sec_corporate_event_interface": {
            "fetch_mode": "offline_default",
            "fetch_invoked": False,
            "raw_payload_read": False,
            "parser_entry_status": "awaits_separately_authorized_source_bound_payload",
            "corporate_event_semantics_confirmed": False,
        },
        "failure_isolation": {
            "global_run_blocked": False,
            "unrelated_symbols_frozen": False,
            "manual_review_required": True,
        },
        "boundary": {
            "provider_selected": False,
            "provider_call_performed": False,
            "account_state_read": False,
            "broker_order_placed": False,
            "return_calculation_performed": False,
            "selection_or_ranking_changed": False,
            "ship_gate_evidence_claimed": False,
        },
    }


class OfflineProviderBoundarySchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.schema)
        cls.validator = Draft7Validator(cls.schema)

    def assert_valid(self, value):
        self.assertEqual(list(self.validator.iter_errors(value)), [])

    def assert_invalid(self, value):
        self.assertNotEqual(list(self.validator.iter_errors(value)), [])

    def test_valid_boundary(self):
        self.assert_valid(valid_boundary())

    def test_network_selection_and_global_freeze_claims_reject(self):
        for path, value in (
            (("yfinance_smoke_alarm", "network_access_performed"), True),
            (("sec_corporate_event_interface", "fetch_invoked"), True),
            (("failure_isolation", "global_run_blocked"), True),
            (("boundary", "selection_or_ranking_changed"), True),
        ):
            item = valid_boundary()
            item[path[0]][path[1]] = value
            self.assert_invalid(item)
