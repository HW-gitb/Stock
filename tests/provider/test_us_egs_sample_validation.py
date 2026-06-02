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
MAPPING_REVIEW_PATH = Path("docs/provider_evidence_p1_us_fmp_current_endpoint_mapping_review_20260602.json")
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
        query = urllib.parse.parse_qs(parsed.query)
        symbol = (query.get("symbol") or [path.rstrip("/").split("/")[-1]])[0].upper()

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

    def _run_stable_under_provider_samples(self, **kwargs: object) -> tuple[dict, FakeHttpClient, Path]:
        base = (
            ROOT
            / "provider_samples"
            / "us_egs_sample_validation_20260602"
            / "fmp_stable_retry"
            / "raw"
            / "_unit_tests"
        )
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="run_stable_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "summary.json"
            raw_root = temp_root / "raw"
            with mock.patch.dict(
                sample_validation.os.environ,
                {"FMP_API_KEY": "UNIT_TEST_FMP_SECRET"},
                clear=True,
            ), mock.patch.object(sample_validation, "_read_windows_environment_value", return_value=None):
                summary = sample_validation.run_fmp_stable_endpoint_retry(
                    approval_path=APPROVAL_PATH,
                    mapping_review_path=MAPPING_REVIEW_PATH,
                    summary_path=summary_path,
                    raw_root=raw_root,
                    generated_at="2026-06-02T00:00:00+00:00",
                    client=client,
                    **kwargs,
                )
                summary_text = summary_path.read_text(encoding="utf-8")
                self.assertNotIn("UNIT_TEST_FMP_SECRET", summary_text)
                self.assertNotIn("apikey=", summary_text.lower())
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

    def test_stable_retry_fetches_only_fmp_stable_endpoints_and_summary_has_no_secrets(self) -> None:
        summary, client, _ = self._run_stable_under_provider_samples()

        self.assertEqual(summary["scope"]["validation_status"], "completed")
        self.assertEqual(summary["scope"]["fmp_endpoint_mode"], "stable")
        self.assertTrue(summary["scope"]["data_fetch_performed"])
        self.assertTrue(summary["scope"]["fmp_live_retry_performed"])
        self.assertEqual(summary["sample_universe"]["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 12)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        self.assertFalse(summary["prohibited_claims"]["provider_selected"])
        self.assertFalse(summary["prohibited_claims"]["yfinance_used"])
        self.assertFalse(summary["storage"]["tracked_summary_contains_raw_rows"])
        self.assertFalse(summary["environment"]["secrets_logged"])

        urls = [url for url, _ in client.calls]
        self.assertEqual(len(urls), 12)
        self.assertTrue(all("financialmodelingprep.com/stable/" in url for url in urls))
        self.assertFalse(any("/api/v3/" in url for url in urls))
        self.assertFalse(any("sec.gov" in url for url in urls))
        self.assertFalse(any("TSLA" in url for url in urls))
        self.assertFalse(any("yfinance" in url.lower() for url in urls))

        for endpoint in summary["endpoint_results"]:
            self.assertEqual(endpoint["provider_id"], "financial_modeling_prep")
            self.assertEqual(endpoint["fmp_endpoint_mode"], "stable")
            self.assertTrue(endpoint["raw_sample_ref"].startswith("provider_samples/"))
            self.assertIn("/fmp_stable_retry/raw/", endpoint["raw_sample_ref"])
            self.assertTrue(endpoint["raw_sample_ref_gitignored"])
            self.assertEqual(endpoint["status"], "ok")

        profile = next(
            endpoint for endpoint in summary["endpoint_results"]
            if endpoint["endpoint_family"] == "profile_or_company_metadata"
        )
        self.assertTrue(profile["field_presence"]["marketCap"])
        self.assertTrue(profile["field_presence"]["volume"])
        self.assertNotIn("mktCap", profile["field_presence"])
        self.assertTrue(all(item["fmp"]["price_volume_fields_present"] for item in summary["symbol_results"]))

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

    def test_small_sample_budget_is_checked_before_next_fetch(self) -> None:
        approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
        approval["sample_universe"]["max_total_endpoint_calls"] = 1
        base = ROOT / "provider_samples" / "us_egs_sample_validation_20260602" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="budget_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            approval_path = temp_root / "approval.json"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            with mock.patch.dict(
                sample_validation.os.environ,
                {
                    "FMP_API_KEY": "UNIT_TEST_FMP_SECRET",
                    "SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com",
                },
                clear=True,
            ), mock.patch.object(sample_validation, "_read_windows_environment_value", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "before next fetch"):
                    sample_validation.run_sample_validation(
                        approval_path=approval_path,
                        summary_path=temp_root / "summary.json",
                        raw_root=temp_root / "raw",
                        generated_at="2026-06-02T00:00:00+00:00",
                        client=client,
                    )

        self.assertEqual(len(client.calls), 1)

    def test_stable_dry_run_validates_env_without_fetching_or_writing_summary(self) -> None:
        base = (
            ROOT
            / "provider_samples"
            / "us_egs_sample_validation_20260602"
            / "fmp_stable_retry"
            / "raw"
            / "_unit_tests"
        )
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="stable_dry_run_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "summary.json"
            raw_root = temp_root / "raw"
            with mock.patch.dict(
                sample_validation.os.environ,
                {"FMP_API_KEY": "UNIT_TEST_FMP_SECRET"},
                clear=True,
            ), mock.patch.object(sample_validation, "_read_windows_environment_value", return_value=None):
                summary = sample_validation.run_fmp_stable_endpoint_retry(
                    approval_path=APPROVAL_PATH,
                    mapping_review_path=MAPPING_REVIEW_PATH,
                    summary_path=summary_path,
                    raw_root=raw_root,
                    generated_at="2026-06-02T00:00:00+00:00",
                    client=client,
                    dry_run_env=True,
                )

        self.assertEqual(summary["scope"]["validation_status"], "dry_run_env_only")
        self.assertFalse(summary["scope"]["data_fetch_performed"])
        self.assertFalse(summary["scope"]["fmp_live_retry_performed"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 0)
        self.assertEqual(client.calls, [])
        self.assertFalse(summary_path.exists())

    def test_stable_retry_budget_is_checked_before_next_fetch(self) -> None:
        approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
        approval["sample_universe"]["max_total_endpoint_calls"] = 1
        base = (
            ROOT
            / "provider_samples"
            / "us_egs_sample_validation_20260602"
            / "fmp_stable_retry"
            / "raw"
            / "_unit_tests"
        )
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="stable_budget_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            approval_path = temp_root / "approval.json"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            with mock.patch.dict(
                sample_validation.os.environ,
                {"FMP_API_KEY": "UNIT_TEST_FMP_SECRET"},
                clear=True,
            ), mock.patch.object(sample_validation, "_read_windows_environment_value", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "before next fetch"):
                    sample_validation.run_fmp_stable_endpoint_retry(
                        approval_path=approval_path,
                        mapping_review_path=MAPPING_REVIEW_PATH,
                        summary_path=temp_root / "summary.json",
                        raw_root=temp_root / "raw",
                        generated_at="2026-06-02T00:00:00+00:00",
                        client=client,
                    )

        self.assertEqual(len(client.calls), 1)

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

    def test_mapping_review_validation_rejects_scope_creep(self) -> None:
        approval = sample_validation.load_and_validate_approval(APPROVAL_PATH)
        mapping = json.loads(MAPPING_REVIEW_PATH.read_text(encoding="utf-8"))
        mapping["scope"]["provider_selection_allowed"] = True
        mapping["mapping_review"]["endpoint_mappings"][0]["sample_live_validated"] = True

        with tempfile.TemporaryDirectory(prefix="mapping_", dir=ROOT) as tmp_dir:
            invalid_path = Path(tmp_dir) / "invalid_mapping.json"
            invalid_path.write_text(json.dumps(mapping), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "provider_selection_allowed=false"):
                sample_validation.load_and_validate_mapping_review(invalid_path, approval)

    def test_raw_root_must_stay_under_gitignored_provider_samples(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider_samples"):
            sample_validation.validate_raw_root(ROOT / "docs")


if __name__ == "__main__":
    unittest.main()
