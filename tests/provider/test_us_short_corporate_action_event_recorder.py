from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_security_identity as identity  # noqa: E402
from runners import us_short_corporate_action_event_recorder as runner  # noqa: E402


def input_payload() -> dict:
    accession = "0001418091-22-000001"
    return {
        "security_identity": identity.record_security_identity(issuer_cik="1418091", security_class="COMMON", current_ticker="TWTR", issuer_name="Example Issuer", primary_exchange="NYSE", observed_as_of="20260713", source_id="manual_seed", source_ref_sha256="a" * 64),
        "old_ticker": "TWTR",
        "event_type": "cash_consideration",
        "successor_ticker": None,
        "successor_security_identity": None,
        "stock_ratio_numerator": None,
        "stock_ratio_denominator": None,
        "cash_per_old_share_usd": "54.20",
        "effective_date": "2022-10-28",
        "sec_accession": accession,
        "sec_url": f"https://www.sec.gov/Archives/edgar/data/1418091/{accession.replace('-', '')}/event.htm",
        "unsupported_consideration": None,
    }


def account_state_payload() -> dict:
    return {
        "schema_name": "us_short_account_state",
        "schema_version": "1.0.0",
        "as_of": "20260713",
        "us_market_equity": 30000.0,
        "us_short_bucket_capital": 10000.0,
        "us_short_available_cash": 4000.0,
        "portfolio_total_equity": None,
        "positions": [{"ticker": "TWTR", "direction": "long", "shares": 5, "avg_cost_usd": 10.0, "entry_date": "20260601", "current_stop": None, "notes": None}],
        "symbol_cooldown_reconciliation": {
            "schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
            "as_of": "20260713", "events": []},
        "manual_order_only": True,
        "broker_connection_allowed": False,
    }


class CorporateActionEventRecorderRunnerTest(unittest.TestCase):
    def test_confirm_flag_is_required_and_runner_never_fetches(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "manual_input.json"
            account_path = Path(tmp) / "account_state.json"
            ticket_path = Path(tmp) / "manual_disposition.json"
            input_path.write_text(json.dumps(input_payload()), encoding="utf-8")
            account_path.write_text(json.dumps(account_state_payload()), encoding="utf-8")
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main([
                    "--manual-input", str(input_path), "--account-state", str(Path(tmp) / "missing.json"),
                    "--private-disposition-out", str(ticket_path),
                ]), 0)
            self.assertEqual(json.loads(captured.getvalue())["manual_review"]["reason"], "manual_confirmation_missing")
            self.assertFalse(ticket_path.exists())

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main([
                    "--manual-input", str(input_path), "--account-state", str(account_path),
                    "--private-disposition-out", str(ticket_path), "--confirm",
                ]), 0)
            self.assertEqual(json.loads(captured.getvalue())["manual_review"]["reason"], "account_read_confirmation_missing")
            self.assertFalse(ticket_path.exists())

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main([
                    "--manual-input", str(input_path), "--account-state", str(account_path),
                    "--private-disposition-out", str(ticket_path), "--confirm", "--confirm-account-read",
                ]), 0)
            output = captured.getvalue()
            self.assertEqual(json.loads(output)["record_status"], "confirmed_event")
            self.assertNotIn("shares", output)
            self.assertNotIn("cash_entitlement_cents", output)
            self.assertNotIn("27100", output)
            self.assertEqual(json.loads(ticket_path.read_text(encoding="utf-8"))["manual_disposition"]["cash_entitlement_cents"], 27100)
            self.assertNotIn("yfinance", sys.modules)

    def test_runner_refuses_a_tracked_ticket_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "manual_input.json"
            account_path = Path(tmp) / "account_state.json"
            input_path.write_text(json.dumps(input_payload()), encoding="utf-8")
            account_path.write_text(json.dumps(account_state_payload()), encoding="utf-8")
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main([
                    "--manual-input", str(input_path), "--account-state", str(account_path),
                    "--private-disposition-out", str(ROOT / "docs" / "forbidden_private_ticket.json"),
                    "--confirm", "--confirm-account-read",
                ]), 2)
            self.assertEqual(captured.getvalue().strip(), "ERROR: private disposition output path is unsafe")


if __name__ == "__main__":
    unittest.main()
