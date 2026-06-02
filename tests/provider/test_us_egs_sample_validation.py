from __future__ import annotations

import copy
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from runners import us_egs_sample_validation as sample_validation


APPROVAL_PATH = Path("docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json")
ROOT = Path(".").resolve()


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = sample_validation.DEFAULT_TIMEOUT_SECONDS,
    ) -> tuple[object, int | None, bool, str | None]:
        del timeout_seconds
        self.calls.append((url, headers))
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        symbol = path.rstrip("/").split("/")[-1].upper()

        if path.endswith("/company_tickers.json"):
            return (
                {
                    "0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
                    "1": {"ticker": "MSFT", "cik_str": 789019, "title": "Microsoft Corp."},
                },
                200,
                True,
                None,
            )
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
        if "/profile/" in path:
            return (
                [
                    {
                        "symbol": symbol,
                        "companyName": f"{symbol} Inc.",
                        "sector": "Technology",
                        "industry": "Software",
                        "mktCap": 100,
                        "price": 10,
                        "volAvg": 1000,
                    }
                ],
                200,
                True,
                None,
            )
        if "/income-statement/" in path:
            return (
                [
                    {
                        "date": "2026-03-31",
                        "fillingDate": "2026-04-30",
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
        if "/balance-sheet-statement/" in path:
            return (
                [
                    {
                        "date": "2026-03-31",
                        "fillingDate": "2026-04-30",
                        "acceptedDate": "2026-04-30 18:00:00",
                        "totalAssets": 1,
                        "totalDebt": 0,
                    }
                ],
                200,
                True,
                None,
            )
        if "/cash-flow-statement/" in path:
            return (
                [
                    {
                        "date": "2026-03-31",
                        "fillingDate": "2026-04-30",
                        "acceptedDate": "2026-04-30 18:00:00",
                        "operatingCashFlow": 1,
                        "freeCashFlow": 1,
                    }
                ],
                200,
                True,
                None,
            )
        if "/key-metrics/" in path:
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
        if "/historical-price-full/" in path:
            return (
                {
                    "historical": [
                        {
                            "date": "2026-05-29",
                            "open": 10,
                            "close": 11,
                            "adjClose": 11,
                            "volume": 1000,
                        }
                    ]
                },
                200,
                True,
                None,
            )
        return {"unexpected_url": url}, 404, False, "http_error"


class UsEgsSampleValidationTest(unittest.TestCase):
    def _run_under_provider_samples(self, **kwargs: object) -> tuple[dict, FakeHttpClient, Path]:
        base = ROOT / "provider_samples" / "us_egs_sample_validation_20260602" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="run_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "summary.json"
            raw_root = temp_root / "raw"
            with mock.patch.dict(
                sample_validation.os.environ,
                {
                    "FMP_API_KEY": "UNIT_TEST_FMP_SECRET",
                    "SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com",
                },
                clear=True,
            ), mock.patch.object(sample_validation, "_read_windows_environment_value", return_value=None):
                summary = sample_validation.run_sample_validation(
                    approval_path=APPROVAL_PATH,
                    summary_path=summary_path,
                    raw_root=raw_root,
                    generated_at="2026-06-02T00:00:00+00:00",
                    client=client,
                    **kwargs,
                )
                summary_text = summary_path.read_text(encoding="utf-8")
                self.assertNotIn("UNIT_TEST_FMP_SECRET", summary_text)
                self.assertNotIn("UnitTest/0.1 contact:test@example.com", summary_text)
                self.assertTrue(summary_path.exists())
                for endpoint in summary.get("endpoint_results", []):
                    self.assertTrue((ROOT / endpoint["raw_sample_ref"]).exists())
                return summary, client, temp_root

    def test_small_sample_fetch_uses_only_approved_universe_and_summary_has_no_secrets(self) -> None:
        summary, client, _ = self._run_under_provider_samples()

        self.assertEqual(summary["scope"]["validation_status"], "completed")
        self.assertEqual(summary["sample_universe"]["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 17)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        self.assertFalse(summary["prohibited_claims"]["provider_selected"])
        self.assertFalse(summary["prohibited_claims"]["yfinance_used"])
        self.assertFalse(summary["storage"]["tracked_summary_contains_raw_rows"])
        self.assertFalse(summary["environment"]["secrets_logged"])

        urls = [url for url, _ in client.calls]
        self.assertEqual(len(urls), 17)
        self.assertTrue(any("profile/AAPL" in url for url in urls))
        self.assertTrue(any("profile/MSFT" in url for url in urls))
        self.assertFalse(any("TSLA" in url for url in urls))
        self.assertFalse(any("yfinance" in url.lower() for url in urls))

        for endpoint in summary["endpoint_results"]:
            self.assertTrue(endpoint["raw_sample_ref"].startswith("provider_samples/"))
            self.assertTrue(endpoint["raw_sample_ref_gitignored"])
            self.assertEqual(endpoint["status"], "ok")

    def test_sec_requests_do_not_request_compressed_payloads(self) -> None:
        _, client, _ = self._run_under_provider_samples()
        sec_headers = [
            headers or {}
            for url, headers in client.calls
            if "sec.gov" in urllib.parse.urlparse(url).netloc
        ]

        self.assertTrue(sec_headers)
        self.assertFalse(any("Accept-Encoding" in headers for headers in sec_headers))
        self.assertIn("www.sec.gov", {headers.get("Host") for headers in sec_headers})
        self.assertIn("data.sec.gov", {headers.get("Host") for headers in sec_headers})

    def test_dry_run_validates_env_without_fetching(self) -> None:
        summary, client, _ = self._run_under_provider_samples(dry_run_env=True)

        self.assertEqual(summary["scope"]["validation_status"], "dry_run_env_only")
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 0)
        self.assertEqual(client.calls, [])

    def test_runtime_approval_validation_rejects_scope_creep(self) -> None:
        approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(approval)
        invalid["approval_boundary"]["yfinance_allowed"] = True
        invalid["provider_roles"][2]["allowed_in_sample_validation"] = True

        with tempfile.TemporaryDirectory(prefix="approval_", dir=ROOT) as tmp_dir:
            invalid_path = Path(tmp_dir) / "invalid_approval.json"
            invalid_path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "yfinance_allowed=false"):
                sample_validation.load_and_validate_approval(invalid_path)

    def test_raw_root_must_stay_under_gitignored_provider_samples(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider_samples"):
            sample_validation.validate_raw_root(ROOT / "docs")


if __name__ == "__main__":
    unittest.main()
