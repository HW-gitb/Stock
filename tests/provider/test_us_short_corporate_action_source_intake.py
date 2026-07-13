from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_security_identity as identity  # noqa: E402
from runners import us_short_sec_corporate_action_fetch_parse as sec_runner  # noqa: E402
from runners import us_short_yfinance_corporate_action_alarm as yf_runner  # noqa: E402


def security(ticker: str = "OLD", cik: str = "101830") -> dict:
    return identity.record_security_identity(
        issuer_cik=cik,
        security_class="COMMON",
        current_ticker=ticker,
        issuer_name=f"{ticker} issuer",
        primary_exchange="NASDAQ",
        observed_as_of="20260713",
        source_id="manual_seed",
        source_ref_sha256="a" * 64,
    )


class FakeSecClient:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def get_text(self, url, *, headers):
        self.calls += 1
        self.last_url = url
        self.last_headers = headers
        return self.text


class FakeHistory:
    empty = False

    def iterrows(self):
        return iter((("2026-07-10", {"Close": 200.0, "Stock Splits": 4.0, "Dividends": 0.0}),))


class FakeTicker:
    ticker = "AAPL"

    def history(self, **kwargs):
        self.kwargs = kwargs
        return FakeHistory()


class FakeYFinance:
    def Ticker(self, ticker):
        self.requested = ticker
        return FakeTicker()


class CorporateActionSourceIntakeTests(unittest.TestCase):
    def _write(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_sec_live_gate_precedes_client_and_output_has_no_url_or_raw_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_path = root / "identity.json"
            request_path = root / "request.json"
            output_path = root / "result.json"
            self._write(identity_path, security())
            self._write(request_path, {
                "schema_name": "us_short_sec_corporate_action_fetch_request",
                "schema_version": "1.0.0",
                "provider_id": "sec_edgar",
                "document_url": "https://www.sec.gov/Archives/edgar/data/101830/000010183026000001/old-20260710.htm",
                "issuer_cik": "0000101830",
                "form_type": "8-K",
                "accession_number": "0000101830-26-000001",
                "filed_date": "2026-07-10",
                "accepted_at": "2026-07-10T12:00:00Z",
                "max_provider_calls": 1,
                "raw_document_persist_allowed": False,
                "automatic_confirmation_allowed": False,
            })
            client = FakeSecClient(
                "The merger became effective on July 10, 2026. Each share was converted into the right "
                "to receive $54.20 in cash."
            )
            with self.assertRaises(sec_runner.SecCorporateActionFetchParseError):
                sec_runner.run_sec_fetch_parse(
                    identity_path=identity_path,
                    source_request_path=request_path,
                    output_path=output_path,
                    confirm_user_authorization=False,
                    sec_user_agent="operator@example.com",
                    client=client,
                )
            self.assertEqual(client.calls, 0)
            result = sec_runner.run_sec_fetch_parse(
                identity_path=identity_path,
                source_request_path=request_path,
                output_path=output_path,
                confirm_user_authorization=True,
                sec_user_agent="operator@example.com",
                observed_at="2026-07-10T12:05:00Z",
                client=client,
            )
            self.assertEqual(client.calls, 1)
            self.assertEqual(result["parse_status"], "candidate_terms_extracted")
            stored = output_path.read_text(encoding="utf-8")
            self.assertNotIn("https://", stored)
            self.assertNotIn("The merger", stored)
            self.assertNotIn("operator@example.com", stored)
            self.assertTrue(result["boundary"]["provider_call_performed"])
            self.assertFalse(result["boundary"]["raw_document_persisted"])

    def test_sec_url_mismatch_rejects_before_client(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_path = root / "identity.json"
            request_path = root / "request.json"
            output_path = root / "result.json"
            self._write(identity_path, security())
            self._write(request_path, {
                "schema_name": "us_short_sec_corporate_action_fetch_request", "schema_version": "1.0.0",
                "provider_id": "sec_edgar",
                "document_url": "https://evil.example/Archives/edgar/data/101830/000010183026000001/x.htm",
                "issuer_cik": "0000101830", "form_type": "8-K",
                "accession_number": "0000101830-26-000001", "filed_date": "2026-07-10",
                "accepted_at": "2026-07-10T12:00:00Z",
                "max_provider_calls": 1, "raw_document_persist_allowed": False,
                "automatic_confirmation_allowed": False,
            })
            client = FakeSecClient("irrelevant")
            with self.assertRaises(sec_runner.SecCorporateActionFetchParseError):
                sec_runner.run_sec_fetch_parse(
                    identity_path=identity_path, source_request_path=request_path, output_path=output_path,
                    confirm_user_authorization=True, sec_user_agent="operator@example.com", client=client,
                )
            self.assertEqual(client.calls, 0)

    def test_sec_unbound_identity_or_bad_chronology_rejects_before_client(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_path = root / "identity.json"
            request_path = root / "request.json"
            output_path = root / "result.json"
            self._write(identity_path, security())
            base = {
                "schema_name": "us_short_sec_corporate_action_fetch_request", "schema_version": "1.0.0",
                "provider_id": "sec_edgar",
                "document_url": "https://www.sec.gov/Archives/edgar/data/1418091/000141809126000001/x.htm",
                "issuer_cik": "0001418091", "form_type": "8-K",
                "accession_number": "0001418091-26-000001", "filed_date": "2026-07-10",
                "accepted_at": "2026-07-10T12:00:00Z", "max_provider_calls": 1,
                "raw_document_persist_allowed": False, "automatic_confirmation_allowed": False,
            }
            self._write(request_path, base)
            client = FakeSecClient("irrelevant")
            with self.assertRaises(sec_runner.SecCorporateActionFetchParseError):
                sec_runner.run_sec_fetch_parse(
                    identity_path=identity_path, source_request_path=request_path, output_path=output_path,
                    observed_at="2026-07-10T12:05:00Z", confirm_user_authorization=True,
                    sec_user_agent="operator@example.com", client=client,
                )
            self.assertEqual(client.calls, 0)
            base["document_url"] = "https://www.sec.gov/Archives/edgar/data/101830/000010183026000001/x.htm"
            base["issuer_cik"] = "0000101830"
            base["accession_number"] = "0000101830-26-000001"
            self._write(request_path, base)
            with self.assertRaises(sec_runner.SecCorporateActionFetchParseError):
                sec_runner.run_sec_fetch_parse(
                    identity_path=identity_path, source_request_path=request_path, output_path=output_path,
                    observed_at="2026-07-10T11:59:00Z", confirm_user_authorization=True,
                    sec_user_agent="operator@example.com", client=client,
                )
            self.assertEqual(client.calls, 0)

    def test_yfinance_default_gate_and_fake_split_alarm(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_path = root / "identity.json"
            output_path = root / "alarm.json"
            self._write(identity_path, security("AAPL", "320193"))
            calls = []

            def importer(name):
                calls.append(name)
                return FakeYFinance()

            with self.assertRaises(yf_runner.YFinanceCorporateActionFetchError):
                yf_runner.run_yfinance_alarm(
                    identity_path=identity_path,
                    output_path=output_path,
                    expected_price_date="2026-07-10",
                    confirm_user_authorization=False,
                    importer=importer,
                )
            self.assertEqual(calls, [])
            result = yf_runner.run_yfinance_alarm(
                identity_path=identity_path,
                output_path=output_path,
                expected_price_date="2026-07-10",
                observed_at="2026-07-10T22:00:00Z",
                confirm_user_authorization=True,
                importer=importer,
            )
            self.assertEqual(calls, ["yfinance"])
            self.assertEqual(result["alarm_reasons"], ["split_reported"])
            self.assertTrue(result["boundary"]["provider_call_performed"])
            self.assertFalse(result["boundary"]["provider_health_gate_use_allowed"])

    def test_yfinance_provider_error_is_sanitized_source_unavailable(self):
        class BrokenTicker:
            ticker = "AAPL"

            def history(self, **kwargs):
                raise RuntimeError("secret=https://query1.finance.yahoo.com/?crumb=private")

        class BrokenYFinance:
            def Ticker(self, ticker):
                return BrokenTicker()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_path = root / "identity.json"
            output_path = root / "alarm.json"
            self._write(identity_path, security("AAPL", "320193"))
            result = yf_runner.run_yfinance_alarm(
                identity_path=identity_path, output_path=output_path, expected_price_date="2026-07-10",
                observed_at="2026-07-10T22:00:00Z", confirm_user_authorization=True,
                importer=lambda _: BrokenYFinance(),
            )
            self.assertEqual(result["alarm_status"], "source_unavailable")
            stored = output_path.read_text(encoding="utf-8")
            self.assertNotIn("crumb", stored)
            self.assertNotIn("query1", stored)

    def test_yfinance_malformed_provider_row_neutralizes_to_source_unavailable(self):
        class BadHistory(FakeHistory):
            def iterrows(self):
                return iter((("2026-07-10", {"Close": float("nan"), "Stock Splits": -1.0, "Dividends": 0.0}),))

        class BadTicker(FakeTicker):
            def history(self, **kwargs):
                return BadHistory()

        class BadYFinance:
            def Ticker(self, ticker):
                return BadTicker()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_path = root / "identity.json"
            output_path = root / "alarm.json"
            self._write(identity_path, security("AAPL", "320193"))
            result = yf_runner.run_yfinance_alarm(
                identity_path=identity_path, output_path=output_path, expected_price_date="2026-07-10",
                observed_at="2026-07-10T22:00:00Z", confirm_user_authorization=True,
                importer=lambda _: BadYFinance(),
            )
            self.assertEqual(result["alarm_status"], "source_unavailable")
            self.assertFalse(result["failure_isolation"]["global_run_blocked"])


if __name__ == "__main__":
    unittest.main()
