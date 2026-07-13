from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_security_identity as identity  # noqa: E402
from engine import us_short_yfinance_corporate_action_alarm as alarm  # noqa: E402


def security() -> dict:
    return identity.record_security_identity(
        issuer_cik="320193",
        security_class="COMMON",
        current_ticker="AAPL",
        issuer_name="Apple",
        primary_exchange="NASDAQ",
        observed_as_of="20260713",
        source_id="manual_seed",
        source_ref_sha256="a" * 64,
    )


def observation(**updates) -> dict:
    value = {
        "source_ticker": "AAPL",
        "returned_ticker": "AAPL",
        "expected_price_date": "2026-07-10",
        "observed_at": "2026-07-10T22:00:00Z",
        "fetch_status": "ok",
        "price_date": "2026-07-10",
        "close": 200.0,
        "stock_splits": 0.0,
        "dividends": 0.0,
        "network_access_performed": False,
    }
    value.update(updates)
    return value


class YFinanceCorporateActionAlarmTests(unittest.TestCase):
    def test_clear_row_is_advisory_only_and_does_not_freeze(self):
        result = alarm.evaluate_yfinance_daily_alarm(security(), observation())
        self.assertEqual(result["alarm_status"], "clear")
        self.assertFalse(result["ticker_scoped_freeze_required"])
        self.assertFalse(result["boundary"]["selection_use_allowed"])
        self.assertFalse(result["boundary"]["corporate_event_semantics_confirmed"])

    def test_split_and_dividend_are_alarm_only_not_semantics(self):
        result = alarm.evaluate_yfinance_daily_alarm(
            security(), observation(stock_splits=4.0, dividends=0.25)
        )
        self.assertEqual(result["alarm_status"], "advisory_alarm")
        self.assertEqual(result["alarm_reasons"], ["dividend_reported", "split_reported"])
        self.assertTrue(result["ticker_scoped_freeze_required"])
        self.assertFalse(result["boundary"]["corporate_event_semantics_confirmed"])

    def test_missing_source_and_ticker_mismatch_freeze_one_ticker(self):
        for item, reason in (
            (observation(fetch_status="empty", returned_ticker=None, price_date=None, close=None,
                         stock_splits=None, dividends=None), "source_unavailable"),
            (observation(returned_ticker="MSFT"), "returned_ticker_mismatch"),
            (observation(price_date="2026-07-09"), "missing_expected_bar"),
        ):
            with self.subTest(reason=reason):
                result = alarm.evaluate_yfinance_daily_alarm(security(), item)
                self.assertIn(reason, result["alarm_reasons"])
                self.assertTrue(result["ticker_scoped_freeze_required"])
                self.assertFalse(result["failure_isolation"]["global_run_blocked"])

    def test_nonfinite_or_negative_values_fail_closed(self):
        for field, value in (("close", float("nan")), ("stock_splits", -1), ("dividends", -0.01)):
            with self.subTest(field=field):
                with self.assertRaises(alarm.YFinanceCorporateActionAlarmError):
                    alarm.evaluate_yfinance_daily_alarm(security(), observation(**{field: value}))


if __name__ == "__main__":
    unittest.main()
