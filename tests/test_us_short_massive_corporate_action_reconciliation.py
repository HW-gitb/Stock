from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_massive_corporate_action_reconciliation as reconciliation  # noqa: E402


def source_refs():
    return {
        "splits": "a" * 64,
        "dividends": "b" * 64,
        "daily_adjusted": "c" * 64,
        "daily_unadjusted": "d" * 64,
    }


def events():
    return [
        {
            "event_id": "AAPL-split-20200831",
            "symbol": "AAPL",
            "event_type": "split",
            "event_date": "2020-08-31",
            "source_family": "splits",
        },
        {
            "event_id": "AAPL-dividend-20210507",
            "symbol": "AAPL",
            "event_type": "dividend",
            "event_date": "2021-05-07",
            "source_family": "dividends",
        },
    ]


def prices():
    return [
        {"symbol": "AAPL", "session_date": "2020-08-28", "adjustment_mode": "adjusted", "source_family": "daily_adjusted", "close": 25.25},
        {"symbol": "AAPL", "session_date": "2020-08-31", "adjustment_mode": "adjusted", "source_family": "daily_adjusted", "close": 26.50},
        {"symbol": "AAPL", "session_date": "2020-08-28", "adjustment_mode": "unadjusted", "source_family": "daily_unadjusted", "close": 101.00},
        {"symbol": "AAPL", "session_date": "2020-08-31", "adjustment_mode": "unadjusted", "source_family": "daily_unadjusted", "close": 26.50},
        {"symbol": "AAPL", "session_date": "2021-05-06", "adjustment_mode": "adjusted", "source_family": "daily_adjusted", "close": 130.10},
        {"symbol": "AAPL", "session_date": "2021-05-07", "adjustment_mode": "adjusted", "source_family": "daily_adjusted", "close": 131.00},
        {"symbol": "AAPL", "session_date": "2021-05-06", "adjustment_mode": "unadjusted", "source_family": "daily_unadjusted", "close": 131.20},
        {"symbol": "AAPL", "session_date": "2021-05-07", "adjustment_mode": "unadjusted", "source_family": "daily_unadjusted", "close": 130.00},
    ]


class MassiveCorporateActionReconciliationTest(unittest.TestCase):
    def build(self, *, event_rows=None, price_rows=None, refs=None):
        return reconciliation.build_event_price_reconciliation_evidence(
            decision_date="20260712",
            symbol="AAPL",
            normalized_event_rows=events() if event_rows is None else event_rows,
            normalized_price_rows=prices() if price_rows is None else price_rows,
            source_ref_sha256=source_refs() if refs is None else refs,
        )

    def test_complete_two_mode_windows_bind_each_event_but_never_claim_reconciliation(self):
        evidence = self.build()

        self.assertEqual(evidence["coverage"], {
            "split_event_count": 1,
            "dividend_event_count": 1,
            "complete_two_mode_window_count": 2,
            "insufficient_price_window_count": 0,
        })
        self.assertEqual(
            [window["assessment_status"] for window in evidence["event_price_windows"]],
            ["pending_price_reconciliation", "pending_price_reconciliation"],
        )
        for window in evidence["event_price_windows"]:
            self.assertEqual(window["adjusted"]["window_status"], "complete")
            self.assertEqual(window["unadjusted"]["window_status"], "complete")
        self.assertFalse(any(evidence["boundary"].values()))

        serialized = json.dumps(evidence, sort_keys=True)
        self.assertNotIn("101.0", serialized)
        self.assertNotIn("131.2", serialized)
        self.assertNotIn("price_reconciliation_consistent", serialized)

    def test_missing_one_mode_event_session_stays_insufficient_and_fail_closed(self):
        price_rows = [
            row
            for row in prices()
            if not (row["adjustment_mode"] == "adjusted" and row["session_date"] == "2021-05-07")
        ]
        evidence = self.build(price_rows=price_rows)
        dividend = evidence["event_price_windows"][1]

        self.assertEqual(dividend["adjusted"]["window_status"], "missing_event_session")
        self.assertEqual(dividend["assessment_status"], "insufficient_price_window")
        self.assertEqual(evidence["coverage"]["complete_two_mode_window_count"], 1)
        self.assertEqual(evidence["coverage"]["insufficient_price_window_count"], 1)
        self.assertFalse(evidence["boundary"]["paper_gate_evaluable_claimed"])

    def test_wrong_symbol_source_binding_or_duplicate_bar_rejects_before_evidence_exists(self):
        bad_events = events()
        bad_events[0]["symbol"] = "MSFT"
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.build(event_rows=bad_events)

        bad_refs = source_refs()
        del bad_refs["dividends"]
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.build(refs=bad_refs)

        duplicated_prices = prices() + [dict(prices()[0])]
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.build(price_rows=duplicated_prices)

    def test_unknown_row_fields_and_nonpositive_close_fail_closed(self):
        bad_events = events()
        bad_events[0]["provider_url"] = "not-allowed"
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.build(event_rows=bad_events)

        bad_prices = prices()
        bad_prices[0]["close"] = 0
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.build(price_rows=bad_prices)


if __name__ == "__main__":
    unittest.main()
