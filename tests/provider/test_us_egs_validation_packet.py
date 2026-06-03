from __future__ import annotations

import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from runners import us_egs_validation_packet as validation_packet


ROOT = Path(".").resolve()
EXECUTION_PACKET_PATH = Path("docs/provider_evidence_p1_us_validation_execution_packet_20260603.json")


class FakeHttpClient:
    def __init__(self, *, include_inactive_ciks: bool = True) -> None:
        self.include_inactive_ciks = include_inactive_ciks
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = validation_packet.sample_validation.DEFAULT_TIMEOUT_SECONDS,
    ) -> tuple[object, int | None, bool, str | None]:
        del timeout_seconds
        self.calls.append((url, headers))
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        symbol = (query.get("symbol") or [path.rstrip("/").split("/")[-1]])[0].upper()

        if path.endswith("/company_tickers.json"):
            payload = {
                "0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
                "1": {"ticker": "MSFT", "cik_str": 789019, "title": "Microsoft Corp."},
                "2": {"ticker": "JPM", "cik_str": 19617, "title": "JPMorgan Chase & Co."},
            }
            if self.include_inactive_ciks:
                payload.update(
                    {
                        "3": {"ticker": "TWTR", "cik_str": 1418091, "title": "Twitter Inc."},
                        "4": {"ticker": "SIVB", "cik_str": 719739, "title": "SVB Financial Group"},
                    }
                )
            return payload, 200, True, None
        if "/submissions/CIK" in path:
            return (
                {
                    "filings": {
                        "recent": {
                            "filingDate": ["2026-04-30"],
                            "acceptanceDateTime": ["2026-04-30T18:00:00.000Z"],
                            "accessionNumber": ["0000000000-26-000001"],
                            "form": ["10-Q"],
                        }
                    }
                },
                200,
                True,
                None,
            )
        if "/api/xbrl/companyfacts/CIK" in path:
            return (
                {
                    "facts": {
                        "us-gaap": {
                            "RevenueFromContractWithCustomerExcludingAssessedTax": {},
                            "NetIncomeLoss": {},
                            "Assets": {},
                        },
                        "dei": {"EntityCommonStockSharesOutstanding": {}},
                    }
                },
                200,
                True,
                None,
            )
        if path.endswith("/stable/profile"):
            return (
                [
                    {
                        "symbol": symbol,
                        "companyName": f"{symbol} Inc.",
                        "sector": "Technology",
                        "industry": "Software",
                        "marketCap": 100,
                        "price": 10,
                        "volume": 1000,
                    }
                ],
                200,
                True,
                None,
            )
        if path.endswith("/stable/income-statement"):
            return (
                [
                    {
                        "date": "2026-03-31",
                        "filingDate": "2026-04-30",
                        "acceptedDate": "2026-04-30 18:00:00",
                        "period": "Q1",
                        "revenue": 1,
                        "netIncome": 1,
                    }
                ],
                200,
                True,
                None,
            )
        if path.endswith("/stable/balance-sheet-statement"):
            return (
                [
                    {
                        "date": "2026-03-31",
                        "filingDate": "2026-04-30",
                        "acceptedDate": "2026-04-30 18:00:00",
                        "totalAssets": 1,
                        "totalDebt": 0,
                    }
                ],
                200,
                True,
                None,
            )
        if path.endswith("/stable/cash-flow-statement"):
            return (
                [
                    {
                        "date": "2026-03-31",
                        "filingDate": "2026-04-30",
                        "acceptedDate": "2026-04-30 18:00:00",
                        "operatingCashFlow": 1,
                        "freeCashFlow": 1,
                    }
                ],
                200,
                True,
                None,
            )
        if path.endswith("/stable/key-metrics"):
            return (
                [
                    {
                        "date": "2026-03-31",
                        "marketCap": 100,
                        "peRatio": 20,
                        "revenuePerShare": 1,
                        "netIncomePerShare": 1,
                    }
                ],
                200,
                True,
                None,
            )
        if path.endswith("/stable/historical-price-eod/full"):
            return (
                [
                    {
                        "date": "2026-05-29",
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 11,
                        "volume": 1000,
                        "change": 1,
                        "changePercent": 10,
                        "vwap": 10.5,
                    }
                ],
                200,
                True,
                None,
            )
        return {"unexpected_url": url}, 404, False, "http_error"


class UsEgsValidationPacketTest(unittest.TestCase):
    def _run_under_provider_samples(
        self,
        *,
        include_inactive_ciks: bool = True,
        dry_run_env: bool = False,
        confirm_independent_review_pass: bool = True,
        confirm_post_review_execute: bool = True,
    ) -> tuple[dict, FakeHttpClient, Path]:
        base = ROOT / "provider_samples" / "us_egs_validation_packet_20260603" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient(include_inactive_ciks=include_inactive_ciks)
        with tempfile.TemporaryDirectory(prefix="run_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "summary.json"
            raw_root = temp_root / "raw"
            with mock.patch.dict(
                validation_packet.sample_validation.os.environ,
                {
                    "FMP_API_KEY": "UNIT_TEST_FMP_SECRET",
                    "SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com",
                },
                clear=True,
            ), mock.patch.object(validation_packet.sample_validation, "_read_windows_environment_value", return_value=None):
                summary = validation_packet.run_validation_packet(
                    execution_packet_path=EXECUTION_PACKET_PATH,
                    summary_path=summary_path,
                    raw_root=raw_root,
                    generated_at="2026-06-03T00:00:00+00:00",
                    client=client,
                    dry_run_env=dry_run_env,
                    confirm_independent_review_pass=confirm_independent_review_pass,
                    confirm_post_review_execute=confirm_post_review_execute,
                    sec_sleep_seconds=0.0,
                )
                if not dry_run_env:
                    summary_text = summary_path.read_text(encoding="utf-8")
                    self.assertNotIn("UNIT_TEST_FMP_SECRET", summary_text)
                    self.assertNotIn("UnitTest/0.1 contact:test@example.com", summary_text)
                    self.assertNotIn("apikey=", summary_text.lower())
                    self.assertNotIn("financialmodelingprep.com/", summary_text)
                    self.assertNotIn("sec.gov/", summary_text)
                    self.assertTrue(summary_path.exists())
                    for endpoint in summary.get("endpoint_results", []):
                        self.assertTrue((ROOT / endpoint["raw_sample_ref"]).exists())
                return summary, client, temp_root

    def test_packet_fetches_only_reviewed_fmp_and_sec_calls_and_writes_no_secret_summary(self) -> None:
        summary, client, _ = self._run_under_provider_samples()

        self.assertEqual(summary["scope"]["validation_status"], "completed")
        self.assertEqual(summary["sample_universe"]["symbols"], ["AAPL", "MSFT", "JPM", "TWTR", "SIVB"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 41)
        self.assertEqual(summary["endpoint_call_budget"]["actual_fmp_endpoint_calls"], 30)
        self.assertEqual(summary["endpoint_call_budget"]["actual_sec_endpoint_calls"], 11)
        self.assertEqual(summary["endpoint_call_budget"]["retry_count_used"], 0)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        self.assertEqual(summary["aggregate_validation_metrics"]["corporate_action_endpoint_call_count"], 0)
        self.assertFalse(summary["prohibited_claims"]["provider_selected"])
        self.assertFalse(summary["prohibited_claims"]["yfinance_used"])
        self.assertFalse(summary["prohibited_claims"]["phase7c_authorized"])
        self.assertFalse(summary["storage"]["tracked_summary_contains_raw_rows"])
        self.assertFalse(summary["environment"]["secrets_logged"])

        urls = [url for url, _ in client.calls]
        self.assertEqual(len(urls), 41)
        self.assertEqual(sum("financialmodelingprep.com/stable/" in url for url in urls), 30)
        self.assertEqual(sum("sec.gov" in urllib.parse.urlparse(url).netloc for url in urls), 11)
        self.assertFalse(any("yfinance" in url.lower() for url in urls))
        self.assertFalse(any("TSLA" in url for url in urls))
        self.assertFalse(any("split" in url.lower() for url in urls))
        self.assertFalse(any("dividend" in url.lower() for url in urls))

        sec_headers = [
            headers or {}
            for url, headers in client.calls
            if "sec.gov" in urllib.parse.urlparse(url).netloc
        ]
        self.assertTrue(sec_headers)
        self.assertTrue(all(headers.get("User-Agent") for headers in sec_headers))
        self.assertIn("www.sec.gov", {headers.get("Host") for headers in sec_headers})
        self.assertIn("data.sec.gov", {headers.get("Host") for headers in sec_headers})

        for endpoint in summary["endpoint_results"]:
            self.assertTrue(endpoint["raw_sample_ref"].startswith("provider_samples/us_egs_validation_packet_20260603/raw/"))
            self.assertTrue(endpoint["raw_sample_ref_gitignored"])
            self.assertEqual(endpoint["status"], "ok")

    def test_missing_inactive_sec_ciks_skips_sec_followup_without_exceeding_budget(self) -> None:
        summary, client, _ = self._run_under_provider_samples(include_inactive_ciks=False)

        self.assertEqual(summary["scope"]["validation_status"], "completed_with_skips")
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 37)
        self.assertEqual(summary["endpoint_call_budget"]["actual_fmp_endpoint_calls"], 30)
        self.assertEqual(summary["endpoint_call_budget"]["actual_sec_endpoint_calls"], 7)
        self.assertEqual(summary["aggregate_validation_metrics"]["sec_cik_missing_count"], 2)
        self.assertEqual(summary["aggregate_validation_metrics"]["skipped_endpoint_count"], 6)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        urls = [url for url, _ in client.calls]
        self.assertFalse(any("CIK0001418091" in url for url in urls))
        self.assertFalse(any("CIK0000719739" in url for url in urls))

    def test_live_execution_requires_review_and_execute_confirmations_before_fetch(self) -> None:
        base = ROOT / "provider_samples" / "us_egs_validation_packet_20260603" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="confirm_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            with mock.patch.dict(
                validation_packet.sample_validation.os.environ,
                {
                    "FMP_API_KEY": "UNIT_TEST_FMP_SECRET",
                    "SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com",
                },
                clear=True,
            ), mock.patch.object(validation_packet.sample_validation, "_read_windows_environment_value", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "confirm-independent-review-pass"):
                    validation_packet.run_validation_packet(
                        execution_packet_path=EXECUTION_PACKET_PATH,
                        summary_path=temp_root / "summary.json",
                        raw_root=temp_root / "raw",
                        generated_at="2026-06-03T00:00:00+00:00",
                        client=client,
                        confirm_independent_review_pass=False,
                        confirm_post_review_execute=True,
                    )

        self.assertEqual(client.calls, [])

    def test_dry_run_validates_env_without_fetching_or_writing(self) -> None:
        summary, client, temp_root = self._run_under_provider_samples(dry_run_env=True)

        self.assertEqual(summary["scope"]["validation_status"], "dry_run_env_only")
        self.assertFalse(summary["scope"]["provider_validation_execution_performed"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 0)
        self.assertEqual(client.calls, [])
        self.assertFalse((temp_root / "summary.json").exists())

    def test_missing_environment_aborts_before_fetch(self) -> None:
        base = ROOT / "provider_samples" / "us_egs_validation_packet_20260603" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="missing_env_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            with mock.patch.dict(validation_packet.sample_validation.os.environ, {}, clear=True), mock.patch.object(
                validation_packet.sample_validation,
                "_read_windows_environment_value",
                return_value=None,
            ):
                with self.assertRaisesRegex(RuntimeError, "FMP_API_KEY"):
                    validation_packet.run_validation_packet(
                        execution_packet_path=EXECUTION_PACKET_PATH,
                        summary_path=temp_root / "summary.json",
                        raw_root=temp_root / "raw",
                        generated_at="2026-06-03T00:00:00+00:00",
                        client=client,
                        confirm_independent_review_pass=True,
                        confirm_post_review_execute=True,
                    )

        self.assertEqual(client.calls, [])

    def test_raw_root_must_stay_under_packet_provider_samples_dir(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider_samples"):
            validation_packet.validate_raw_root(ROOT / "provider_samples" / "other_packet" / "raw")


if __name__ == "__main__":
    unittest.main()
