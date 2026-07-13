from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_corporate_action_manual_event_record.schema.json"


def valid_confirmed() -> dict:
    return {
        "schema_name": "us_short_corporate_action_manual_event_record",
        "schema_version": "1.1.0",
        "record_status": "confirmed_event",
        "security_binding": {"security_id": "US-CIK-0001418091-COMMON", "issuer_cik": "0001418091", "current_ticker": "TWTR", "identity_ref_sha256": "a" * 64},
        "successor_security_binding": None,
        "source_binding": {"source_kind": "sec_manual_read", "sec_accession": "0001418091-22-000001", "evidence_issuer_cik": "0001418091", "source_evidence_ref_sha256": "b" * 64},
        "account_state_binding": {"schema_name": "us_short_account_state", "schema_version": "1.0.0", "as_of": "20260713", "account_state_ref_sha256": "c" * 64},
        "confirmed_event": {"event_id": "manual-sec-1234567890abcdef12345678", "event_type": "cash_consideration", "old_ticker": "TWTR", "effective_date": "20221028", "source_evidence_ref_sha256": "b" * 64, "source_confirmation": "manually_confirmed_source_bound", "successor_ticker": None, "stock_ratio_numerator": None, "stock_ratio_denominator": None, "cash_per_old_share_cents": 5420},
        "manual_review": {"reason": None, "ticker_scoped_freeze": None},
        "boundary": {"provider_call_performed": False, "raw_payload_read": False, "account_state_read": True, "account_state_mutated": False, "broker_order_placed": False, "selection_or_ranking_changed": False, "ship_gate_evidence_claimed": False},
    }


class CorporateActionManualEventRecordSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.schema)
        cls.validator = Draft7Validator(cls.schema)

    def assert_valid(self, value):
        self.assertEqual(list(self.validator.iter_errors(value)), [])

    def assert_invalid(self, value):
        self.assertNotEqual(list(self.validator.iter_errors(value)), [])

    def test_confirmed_and_manual_review_shapes(self):
        self.assert_valid(valid_confirmed())
        review = valid_confirmed()
        review["record_status"] = "manual_review"
        review["account_state_binding"] = None
        review["confirmed_event"] = None
        review["manual_review"] = {
            "reason": "unsupported_consideration_cvr",
            "ticker_scoped_freeze": {"schema_name": "us_short_ticker_scoped_source_freeze", "schema_version": "1.0.0", "frozen_security_id": "US-CIK-0001418091-COMMON", "frozen_tickers": ["TWTR"], "source_id": "sec_manual_entry", "failure_class": "source_contract_violation", "manual_review_required": True, "global_run_blocked": False, "boundary": {"provider_retry_performed": False, "unrelated_symbols_frozen": False, "selection_or_ranking_changed": False, "account_state_read": False, "broker_or_order_automation_allowed": False}},
        }
        review["boundary"]["account_state_read"] = False
        self.assert_valid(review)

    def test_stock_event_requires_a_successor_identity_binding(self):
        stock = valid_confirmed()
        stock["confirmed_event"].update(
            event_type="stock_conversion",
            successor_ticker="TMUS",
            stock_ratio_numerator=1,
            stock_ratio_denominator=10,
            cash_per_old_share_cents=None,
        )
        stock["successor_security_binding"] = {"security_id": "US-CIK-0001283699-COMMON", "issuer_cik": "0001283699", "current_ticker": "TMUS", "identity_ref_sha256": "c" * 64}
        stock["source_binding"]["evidence_issuer_cik"] = "0001283699"
        self.assert_valid(stock)

        stock["successor_security_binding"] = None
        self.assert_invalid(stock)

        stock["successor_security_binding"] = {"security_id": "US-CIK-0001283699-COMMON", "issuer_cik": "0001283699", "current_ticker": "TMUS", "identity_ref_sha256": "c" * 64}
        stock["confirmed_event"]["event_type"] = "stock_and_cash_consideration"
        stock["confirmed_event"]["cash_per_old_share_cents"] = 100
        self.assert_valid(stock)

    def test_confirmation_event_and_boundary_cannot_drift(self):
        for path, value in (
            (("confirmed_event", "source_confirmation"), "inferred_from_inactive_status"),
            (("manual_review", "reason"), "must_review"),
            (("boundary", "account_state_read"), False),
            (("confirmed_event", "event_type"), "forced_exit"),
        ):
            item = valid_confirmed()
            item[path[0]][path[1]] = value
            self.assert_invalid(item)

    def test_account_review_keeps_the_account_binding_private(self):
        review = valid_confirmed()
        review["record_status"] = "manual_review"
        review["account_state_binding"] = None
        review["confirmed_event"] = None
        review["successor_security_binding"] = None
        review["manual_review"] = {
            "reason": "no_position_for_ticker",
            "ticker_scoped_freeze": {
                "schema_name": "us_short_ticker_scoped_source_freeze", "schema_version": "1.0.0",
                "frozen_security_id": "US-CIK-0001418091-COMMON", "frozen_tickers": ["TWTR"],
                "source_id": "sec_manual_entry", "failure_class": "source_contract_violation",
                "manual_review_required": True, "global_run_blocked": False,
                "boundary": {"provider_retry_performed": False, "unrelated_symbols_frozen": False,
                             "selection_or_ranking_changed": False, "account_state_read": False,
                             "broker_or_order_automation_allowed": False},
            },
        }
        self.assert_valid(review)
        review["account_state_binding"] = valid_confirmed()["account_state_binding"]
        self.assert_invalid(review)


if __name__ == "__main__":
    unittest.main()
