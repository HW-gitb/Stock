from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_corporate_action_manual_disposition.schema.json"


def valid_ticket():
    return {
        "schema_name": "us_short_corporate_action_manual_disposition",
        "schema_version": "1.0.0",
        "position_binding": {"ticker": "OLD", "shares": 5},
        "event_binding": {
            "event_id": "evt-001",
            "event_type": "stock_conversion",
            "old_ticker": "OLD",
            "effective_date": "20260720",
            "source_evidence_ref_sha256": "a" * 64,
            "source_confirmation": "manually_confirmed_source_bound",
            "successor_ticker": "NEW",
            "stock_ratio_numerator": 3,
            "stock_ratio_denominator": 2,
            "cash_per_old_share_cents": None,
        },
        "manual_disposition": {
            "action": "manual_convert_shares",
            "successor_ticker": "NEW",
            "successor_share_entitlement": {"numerator": 15, "denominator": 2},
            "cash_entitlement_cents": None,
            "manual_exit_required": False,
            "manual_confirmation_to_apply_required": True,
        },
        "boundary": {
            "account_state_read": False,
            "account_state_mutated": False,
            "broker_order_placed": False,
            "automatic_position_conversion_performed": False,
            "automatic_cash_booking_performed": False,
            "return_calculation_performed": False,
            "selection_or_ranking_changed": False,
            "ship_gate_evidence_claimed": False,
        },
    }


class CorporateActionManualDispositionSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.schema)
        cls.validator = Draft7Validator(cls.schema)

    def assert_valid(self, value):
        self.assertEqual(list(self.validator.iter_errors(value)), [])

    def assert_invalid(self, value):
        self.assertNotEqual(list(self.validator.iter_errors(value)), [])

    def test_valid_stock_conversion_ticket(self):
        self.assert_valid(valid_ticket())

    def test_all_event_instruction_shapes_accept_only_their_matching_form(self):
        cash = valid_ticket()
        cash["event_binding"].update(
            event_type="cash_consideration",
            successor_ticker=None,
            stock_ratio_numerator=None,
            stock_ratio_denominator=None,
            cash_per_old_share_cents=125,
        )
        cash["manual_disposition"].update(
            action="manual_record_cash_consideration",
            successor_ticker=None,
            successor_share_entitlement=None,
            cash_entitlement_cents=625,
            manual_exit_required=False,
        )
        self.assert_valid(cash)

        stock_cash = valid_ticket()
        stock_cash["event_binding"]["event_type"] = "stock_and_cash_consideration"
        stock_cash["event_binding"]["cash_per_old_share_cents"] = 125
        stock_cash["manual_disposition"].update(
            action="manual_convert_and_record_cash",
            cash_entitlement_cents=625,
        )
        self.assert_valid(stock_cash)

        forced_exit = valid_ticket()
        forced_exit["event_binding"].update(
            event_type="forced_exit",
            successor_ticker=None,
            stock_ratio_numerator=None,
            stock_ratio_denominator=None,
            cash_per_old_share_cents=None,
        )
        forced_exit["manual_disposition"].update(
            action="manual_exit_at_broker_confirmed_terms",
            successor_ticker=None,
            successor_share_entitlement=None,
            cash_entitlement_cents=None,
            manual_exit_required=True,
        )
        self.assert_valid(forced_exit)

    def test_source_confirmation_and_boundaries_are_const_pinned(self):
        value = valid_ticket()
        value["event_binding"]["source_confirmation"] = "inferred_from_inactive_status"
        self.assert_invalid(value)

        for field in ("account_state_mutated", "broker_order_placed", "automatic_position_conversion_performed", "selection_or_ranking_changed"):
            value = valid_ticket()
            value["boundary"][field] = True
            self.assert_invalid(value)

    def test_event_instruction_shapes_cannot_mix(self):
        value = valid_ticket()
        value["event_binding"]["event_type"] = "forced_exit"
        self.assert_invalid(value)

        value = valid_ticket()
        value["manual_disposition"]["cash_entitlement_cents"] = 100
        self.assert_invalid(value)


if __name__ == "__main__":
    unittest.main()
