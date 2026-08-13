from __future__ import annotations

import json
import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_corporate_action_disposition as disposition  # noqa: E402
from engine import us_short_corporate_action_event_recorder as recorder  # noqa: E402
from engine import us_short_security_identity as identity  # noqa: E402
from runners import us_short_account_state_from_manual_tables as account_converter  # noqa: E402


def security(ticker: str, *, cik: str = "1418091") -> dict:
    return identity.record_security_identity(
        issuer_cik=cik,
        security_class="COMMON",
        current_ticker=ticker,
        issuer_name="Example Issuer",
        primary_exchange="NYSE",
        observed_as_of="20260713",
        source_id="manual_seed",
        source_ref_sha256="a" * 64,
    )


def manual_input(ticker: str, event_type: str) -> dict:
    accession = "0001418091-22-000001"
    return {
        "security_identity": security(ticker),
        "old_ticker": ticker,
        "event_type": event_type,
        "successor_ticker": None,
        "successor_security_identity": None,
        "stock_ratio_numerator": None,
        "stock_ratio_denominator": None,
        "cash_per_old_share_usd": None,
        "effective_date": "2022-10-28",
        "sec_accession": accession,
        "sec_url": f"https://www.sec.gov/Archives/edgar/data/1418091/{accession.replace('-', '')}/event.htm",
        "unsupported_consideration": None,
    }


def account_state(*positions: dict) -> dict:
    state = {
        "schema_name": "us_short_account_state",
        "schema_version": "1.0.0",
        "as_of": "20260713",
        "us_market_equity": 30000.0,
        "us_short_bucket_capital": 10000.0,
        "us_short_available_cash": 4000.0,
        "portfolio_total_equity": None,
        "positions": list(positions),
        "symbol_cooldown_reconciliation": {
            "schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
            "as_of": "20260713", "events": []},
        "manual_order_only": True,
        "broker_connection_allowed": False,
    }
    return state


def holding(ticker: str, shares: int = 5, *, direction: str = "long") -> dict:
    return {
        "ticker": ticker,
        "direction": direction,
        "shares": shares,
        "avg_cost_usd": 10.0,
        "entry_date": "20260601",
        "current_stop": None,
        "notes": None,
    }


class CorporateActionEventRecorderTest(unittest.TestCase):
    def test_cash_stock_and_forced_events_round_trip_to_manual_disposition(self):
        cash_input = manual_input("TWTR", "cash_consideration")
        cash_input["cash_per_old_share_usd"] = "54.20"
        cash_state = account_state(holding("TWTR"))
        cash = recorder.record_manual_corporate_action(cash_input, account_state=cash_state, confirm=True)
        self.assertEqual(cash["record_status"], "confirmed_event")
        self.assertEqual(cash["confirmed_event"]["cash_per_old_share_cents"], 5420)
        cash_ticket = recorder.build_private_disposition(cash_state, cash)
        self.assertEqual(cash_ticket["manual_disposition"]["cash_entitlement_cents"], 27100)
        changed_state = account_state(holding("TWTR", shares=6))
        with self.assertRaises(recorder.CorporateActionEventRecorderError):
            recorder.build_private_disposition(changed_state, cash)

        stock_input = manual_input("S", "stock_conversion")
        stock_input.update(
            successor_ticker="TMUS",
            successor_security_identity=security("TMUS", cik="1283699"),
            stock_ratio_numerator=1,
            stock_ratio_denominator=10,
        )
        stock_state = account_state(holding("S"))
        stock = recorder.record_manual_corporate_action(stock_input, account_state=stock_state, confirm=True)
        self.assertEqual(stock["record_status"], "confirmed_event")
        stock_ticket = recorder.build_private_disposition(stock_state, stock)
        self.assertEqual(stock_ticket["manual_disposition"]["successor_share_entitlement"], {"numerator": 1, "denominator": 2})

        forced_input = manual_input("OLD", "forced_exit")
        forced_state = account_state(holding("OLD"))
        forced = recorder.record_manual_corporate_action(forced_input, account_state=forced_state, confirm=True)
        self.assertEqual(forced["record_status"], "confirmed_event")
        forced_ticket = recorder.build_private_disposition(forced_state, forced)
        self.assertTrue(forced_ticket["manual_disposition"]["manual_exit_required"])

    def test_cvr_or_missing_confirmation_becomes_single_ticker_manual_review(self):
        cvr_input = manual_input("CELG", "stock_and_cash_consideration")
        cvr_input.update(
            successor_ticker="BMY",
            successor_security_identity=security("BMY", cik="14272"),
            stock_ratio_numerator=1,
            stock_ratio_denominator=10,
            cash_per_old_share_usd="50.00",
            unsupported_consideration="cvr",
        )
        cvr = recorder.record_manual_corporate_action(cvr_input, account_state=None, confirm=True)
        self.assertEqual(cvr["record_status"], "manual_review")
        self.assertEqual(cvr["manual_review"]["reason"], "unsupported_consideration_cvr")
        self.assertIsNone(cvr["confirmed_event"])
        self.assertEqual(cvr["manual_review"]["ticker_scoped_freeze"]["frozen_tickers"], ["CELG"])
        self.assertFalse(cvr["manual_review"]["ticker_scoped_freeze"]["global_run_blocked"])

        unconfirmed = manual_input("TWTR", "cash_consideration")
        unconfirmed["cash_per_old_share_usd"] = "54.20"
        result = recorder.record_manual_corporate_action(
            unconfirmed, account_state=account_state(holding("TWTR")), confirm=False
        )
        self.assertEqual(result["record_status"], "manual_review")
        self.assertEqual(result["manual_review"]["reason"], "manual_confirmation_missing")
        self.assertIsNone(result["confirmed_event"])

    def test_malformed_or_mismatched_manual_input_fails_closed_to_bound_ticker(self):
        bad_cash = manual_input("TWTR", "cash_consideration")
        bad_cash["cash_per_old_share_usd"] = "54.2"
        result = recorder.record_manual_corporate_action(bad_cash, account_state=account_state(holding("TWTR")), confirm=True)
        self.assertEqual(result["record_status"], "manual_review")
        self.assertEqual(result["manual_review"]["reason"], "confirmed_event_input_invalid")

        bad_ratio = manual_input("S", "stock_conversion")
        bad_ratio.update(successor_ticker="TMUS", stock_ratio_numerator="0.1", stock_ratio_denominator=1)
        result = recorder.record_manual_corporate_action(bad_ratio, account_state=account_state(holding("S")), confirm=True)
        self.assertEqual(result["record_status"], "manual_review")

        mismatch = manual_input("TWTR", "cash_consideration")
        mismatch.update(old_ticker="MSFT", cash_per_old_share_usd="54.20")
        result = recorder.record_manual_corporate_action(mismatch, account_state=account_state(holding("TWTR")), confirm=True)
        self.assertEqual(result["record_status"], "manual_review")
        self.assertEqual(result["manual_review"]["ticker_scoped_freeze"]["frozen_tickers"], ["TWTR"])

    def test_source_evidence_is_hashed_not_emitted_and_bad_identity_is_rejected(self):
        item = manual_input("TWTR", "cash_consideration")
        item["cash_per_old_share_usd"] = "54.20"
        result = recorder.record_manual_corporate_action(item, account_state=account_state(holding("TWTR")), confirm=True)
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn(item["sec_url"], rendered)
        self.assertEqual(result["source_binding"]["sec_accession"], item["sec_accession"])
        self.assertEqual(len(result["source_binding"]["source_evidence_ref_sha256"]), 64)

        tampered = copy.deepcopy(result)
        tampered["security_binding"]["security_id"] = "not-a-security-id"
        with self.assertRaises(recorder.CorporateActionEventRecorderError):
            recorder.validate_manual_event_record(tampered)

        tampered = copy.deepcopy(result)
        tampered["source_binding"]["evidence_issuer_cik"] = "0000000000"
        with self.assertRaises(recorder.CorporateActionEventRecorderError):
            recorder.validate_manual_event_record(tampered)

        item["security_identity"]["security_id"] = "US-CIK-0000000000-COMMON"
        with self.assertRaises(recorder.CorporateActionEventRecorderError):
            recorder.record_manual_corporate_action(item, account_state=account_state(holding("TWTR")), confirm=True)

    def test_sec_evidence_cik_must_bind_the_old_or_successor_security(self):
        item = manual_input("S", "stock_conversion")
        item.update(
            successor_ticker="TMUS",
            successor_security_identity=security("TMUS", cik="1283699"),
            stock_ratio_numerator=1,
            stock_ratio_denominator=10,
        )
        accession = item["sec_accession"].replace("-", "")
        item["sec_url"] = f"https://www.sec.gov/Archives/edgar/data/1283699/{accession}/completion-8k.htm"
        self.assertEqual(recorder.record_manual_corporate_action(item, account_state=account_state(holding("S")), confirm=True)["record_status"], "confirmed_event")

        item["sec_url"] = f"https://www.sec.gov/Archives/edgar/data/1652044/{accession}/wrong-issuer.htm"
        rejected = recorder.record_manual_corporate_action(item, account_state=account_state(holding("S")), confirm=True)
        self.assertEqual(rejected["record_status"], "manual_review")
        self.assertEqual(rejected["manual_review"]["ticker_scoped_freeze"]["frozen_tickers"], ["S"])

    def test_both_stock_event_types_require_an_identity_bound_successor(self):
        item = manual_input("S", "stock_and_cash_consideration")
        item.update(
            successor_ticker="TMUS",
            stock_ratio_numerator=1,
            stock_ratio_denominator=10,
            cash_per_old_share_usd="1.00",
        )
        missing = recorder.record_manual_corporate_action(item, account_state=account_state(holding("S")), confirm=True)
        self.assertEqual(missing["record_status"], "manual_review")
        self.assertEqual(missing["manual_review"]["ticker_scoped_freeze"]["frozen_tickers"], ["S"])

        item["successor_security_identity"] = security("TMUS", cik="1283699")
        accession = item["sec_accession"].replace("-", "")
        item["sec_url"] = f"https://www.sec.gov/Archives/edgar/data/1283699/{accession}/completion-8k.htm"
        self.assertEqual(recorder.record_manual_corporate_action(item, account_state=account_state(holding("S")), confirm=True)["record_status"], "confirmed_event")

    def test_account_state_is_the_only_position_source_and_fails_closed(self):
        item = manual_input("TWTR", "cash_consideration")
        item["cash_per_old_share_usd"] = "54.20"

        no_position = recorder.record_manual_corporate_action(
            item, account_state=account_state(holding("MSFT")), confirm=True
        )
        self.assertEqual(no_position["record_status"], "manual_review")
        self.assertEqual(no_position["manual_review"]["reason"], "no_position_for_ticker")
        self.assertTrue(no_position["boundary"]["account_state_read"])
        self.assertIsNone(no_position["account_state_binding"])

        malformed = account_state(holding("TWTR"))
        malformed["positions"].append(holding("TWTR"))
        invalid = recorder.record_manual_corporate_action(item, account_state=malformed, confirm=True)
        self.assertEqual(invalid["record_status"], "manual_review")
        self.assertEqual(invalid["manual_review"]["reason"], "account_state_invalid")

        nonlong = recorder.record_manual_corporate_action(
            item, account_state=account_state(holding("TWTR", direction="short")), confirm=True
        )
        self.assertEqual(nonlong["record_status"], "manual_review")
        self.assertEqual(nonlong["manual_review"]["reason"], "account_state_invalid")

        stale_manual_position = manual_input("TWTR", "cash_consideration")
        stale_manual_position.update(cash_per_old_share_usd="54.20", position=holding("TWTR"))
        stale = recorder.record_manual_corporate_action(
            stale_manual_position, account_state=account_state(holding("TWTR")), confirm=True
        )
        self.assertEqual(stale["record_status"], "manual_review")
        self.assertEqual(stale["manual_review"]["reason"], "confirmed_event_input_invalid")
        self.assertFalse(stale["boundary"]["account_state_read"])

        converter_state, _ = account_converter.build_account_state(
            {
                "account": [{"as_of": "20260713", "us_market_equity": "30000", "us_short_available_cash": "4000", "manual_order_only": "TRUE", "broker_connection_allowed": "FALSE"}],
                "positions": [{"ticker": "TWTR", "shares": "5", "avg_cost_usd": "10", "entry_date": "20260601"}],
            },
            "20260713",
        )
        confirmed = recorder.record_manual_corporate_action(item, account_state=converter_state, confirm=True)
        self.assertEqual(confirmed["record_status"], "confirmed_event")
        self.assertTrue(confirmed["boundary"]["account_state_read"])
        self.assertNotIn("shares", json.dumps(confirmed, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
