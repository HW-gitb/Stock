from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_corporate_action_disposition as disposition  # noqa: E402


def position(*, ticker: str = "OLD", shares: int = 5) -> dict:
    return {"ticker": ticker, "direction": "long", "shares": shares}


def event(kind: str = "stock_conversion") -> dict:
    base = {
        "event_id": "evt-001",
        "event_type": kind,
        "old_ticker": "OLD",
        "effective_date": "20260720",
        "source_evidence_ref_sha256": "a" * 64,
        "source_confirmation": "manually_confirmed_source_bound",
        "successor_ticker": None,
        "stock_ratio_numerator": None,
        "stock_ratio_denominator": None,
        "cash_per_old_share_cents": None,
    }
    if kind == "stock_conversion":
        base.update(successor_ticker="NEW", stock_ratio_numerator=3, stock_ratio_denominator=2)
    elif kind == "cash_consideration":
        base.update(cash_per_old_share_cents=125)
    elif kind == "stock_and_cash_consideration":
        base.update(
            successor_ticker="NEW",
            stock_ratio_numerator=3,
            stock_ratio_denominator=2,
            cash_per_old_share_cents=125,
        )
    return base


class CorporateActionDispositionTest(unittest.TestCase):
    def test_all_event_kinds_emit_manual_only_tickets_with_exact_entitlements(self):
        stock = disposition.build_manual_disposition(position(), event("stock_conversion"))
        self.assertEqual(stock["manual_disposition"]["action"], "manual_convert_shares")
        self.assertEqual(stock["manual_disposition"]["successor_share_entitlement"], {"numerator": 15, "denominator": 2})
        self.assertIsNone(stock["manual_disposition"]["cash_entitlement_cents"])

        cash = disposition.build_manual_disposition(position(), event("cash_consideration"))
        self.assertEqual(cash["manual_disposition"]["action"], "manual_record_cash_consideration")
        self.assertIsNone(cash["manual_disposition"]["successor_share_entitlement"])
        self.assertEqual(cash["manual_disposition"]["cash_entitlement_cents"], 625)

        stock_cash = disposition.build_manual_disposition(position(), event("stock_and_cash_consideration"))
        self.assertEqual(stock_cash["manual_disposition"]["action"], "manual_convert_and_record_cash")
        self.assertEqual(stock_cash["manual_disposition"]["successor_share_entitlement"], {"numerator": 15, "denominator": 2})
        self.assertEqual(stock_cash["manual_disposition"]["cash_entitlement_cents"], 625)

        exit_ticket = disposition.build_manual_disposition(position(), event("forced_exit"))
        self.assertEqual(exit_ticket["manual_disposition"]["action"], "manual_exit_at_broker_confirmed_terms")
        self.assertTrue(exit_ticket["manual_disposition"]["manual_exit_required"])
        self.assertIsNone(exit_ticket["manual_disposition"]["cash_entitlement_cents"])

        for ticket in (stock, cash, stock_cash, exit_ticket):
            self.assertTrue(ticket["manual_disposition"]["manual_confirmation_to_apply_required"])
            self.assertFalse(ticket["boundary"]["account_state_mutated"])
            self.assertFalse(ticket["boundary"]["broker_order_placed"])
            self.assertFalse(ticket["boundary"]["return_calculation_performed"])

    def test_unconfirmed_or_mismatched_or_malformed_event_rejects(self):
        bad = event()
        bad["source_confirmation"] = "inferred_from_inactive_status"
        with self.assertRaises(disposition.CorporateActionDispositionError):
            disposition.build_manual_disposition(position(), bad)

        bad = event()
        bad["old_ticker"] = "OTHER"
        with self.assertRaises(disposition.CorporateActionDispositionError):
            disposition.build_manual_disposition(position(), bad)

        bad = event()
        bad["stock_ratio_denominator"] = 0
        with self.assertRaises(disposition.CorporateActionDispositionError):
            disposition.build_manual_disposition(position(), bad)

        bad = event("forced_exit")
        bad["cash_per_old_share_cents"] = 1
        with self.assertRaises(disposition.CorporateActionDispositionError):
            disposition.build_manual_disposition(position(), bad)

        for kind in ("cash_consideration", "forced_exit"):
            for field, value in (
                ("successor_ticker", "NEW"),
                ("stock_ratio_numerator", 3),
                ("stock_ratio_denominator", 2),
            ):
                bad = event(kind)
                bad[field] = value
                with self.subTest(non_stock_event=kind, stray_stock_field=field):
                    with self.assertRaises(disposition.CorporateActionDispositionError):
                        disposition.build_manual_disposition(position(), bad)

        bad = event()
        bad["unexpected"] = True
        with self.assertRaises(disposition.CorporateActionDispositionError):
            disposition.build_manual_disposition(position(), bad)

        bad = event()
        bad["event_id"] = "event id with spaces"
        with self.assertRaises(disposition.CorporateActionDispositionError):
            disposition.build_manual_disposition(position(), bad)

    def test_output_validator_rejects_boundary_or_semantics_tampering(self):
        ticket = disposition.build_manual_disposition(position(), event())
        for path, value in (
            (("boundary", "account_state_mutated"), True),
            (("boundary", "broker_order_placed"), True),
            (("manual_disposition", "manual_confirmation_to_apply_required"), False),
            (("event_binding", "source_confirmation"), "inferred_from_inactive_status"),
        ):
            tampered = copy.deepcopy(ticket)
            tampered[path[0]][path[1]] = value
            with self.assertRaises(disposition.CorporateActionDispositionError):
                disposition.validate_manual_disposition(tampered)


if __name__ == "__main__":
    unittest.main()
