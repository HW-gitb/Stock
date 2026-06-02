from __future__ import annotations

import copy
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from runners import us_egs_coverage_count_packet as coverage_packet


APPROVAL_PATH = Path("docs/provider_evidence_p1_us_coverage_count_access_packet_approval_20260602.json")
ROOT = Path(".").resolve()


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = coverage_packet.DEFAULT_TIMEOUT_SECONDS,
    ) -> tuple[object, int | None, bool, str | None]:
        del headers, timeout_seconds
        self.calls.append(url)
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        symbol = (query.get("symbol") or [""])[0].upper()
        if path.endswith("/stable/profile"):
            return [
                {
                    "symbol": symbol,
                    "companyName": f"{symbol} Inc.",
                    "sector": "Technology",
                    "industry": "Software",
                    "marketCap": 100,
                    "price": 10,
                    "volume": 1000,
                }
            ], 200, True, None
        if path.endswith("/stable/income-statement"):
            return [
                {
                    "date": "2026-03-31",
                    "filingDate": "2026-04-30",
                    "acceptedDate": "2026-04-30 18:00:00",
                    "period": "Q1",
                    "revenue": 1,
                    "netIncome": 1,
                }
            ], 200, True, None
        if path.endswith("/stable/balance-sheet-statement"):
            return [
                {
                    "date": "2026-03-31",
                    "filingDate": "2026-04-30",
                    "acceptedDate": "2026-04-30 18:00:00",
                    "totalAssets": 1,
                    "totalDebt": 0,
                }
            ], 200, True, None
        if path.endswith("/stable/cash-flow-statement"):
            return [
                {
                    "date": "2026-03-31",
                    "filingDate": "2026-04-30",
                    "acceptedDate": "2026-04-30 18:00:00",
                    "operatingCashFlow": 1,
                    "freeCashFlow": 1,
                }
            ], 200, True, None
        if path.endswith("/stable/key-metrics"):
            return [
                {
                    "date": "2026-03-31",
                    "marketCap": 100,
                    "peRatio": 20,
                    "revenuePerShare": 1,
                    "netIncomePerShare": 1,
                }
            ], 200, True, None
        if path.endswith("/stable/historical-price-eod/full"):
            return [
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
            ], 200, True, None
        return {"unexpected_url": url}, 404, False, "http_error"


class UsEgsCoverageCountPacketTest(unittest.TestCase):
    def _run_under_provider_samples(self, **kwargs: object) -> tuple[dict, FakeHttpClient, Path]:
        base = ROOT / "provider_samples" / "us_egs_coverage_count_20260602" / "fmp_stable" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="run_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "summary.json"
            raw_root = temp_root / "raw"
            with mock.patch.dict(
                coverage_packet.os.environ,
                {"FMP_API_KEY": "UNIT_TEST_FMP_SECRET"},
                clear=True,
            ), mock.patch.object(coverage_packet, "_read_windows_environment_value", return_value=None, create=True):
                summary = coverage_packet.run_coverage_count_packet(
                    approval_path=APPROVAL_PATH,
                    summary_path=summary_path,
                    raw_root=raw_root,
                    generated_at="2026-06-02T00:00:00+00:00",
                    client=client,
                    **kwargs,
                )
                if not kwargs.get("dry_run_env"):
                    summary_text = summary_path.read_text(encoding="utf-8")
                    self.assertNotIn("UNIT_TEST_FMP_SECRET", summary_text)
                    self.assertNotIn("apikey=", summary_text.lower())
                    self.assertTrue(summary_path.exists())
                    for endpoint in summary.get("endpoint_results", []):
                        self.assertTrue((ROOT / endpoint["raw_sample_ref"]).exists())
                return summary, client, temp_root

    def test_packet_fetches_only_approved_fmp_stable_calls_and_writes_no_secret_summary(self) -> None:
        summary, client, _ = self._run_under_provider_samples()

        self.assertEqual(summary["scope"]["validation_status"], "completed")
        self.assertEqual(summary["sample_universe"]["symbols"], ["AAPL", "MSFT", "NVDA", "JPM", "XOM"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 30)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        self.assertEqual(summary["aggregate_count_metrics"]["endpoint_success_count"], 30)
        self.assertEqual(summary["aggregate_count_metrics"]["endpoint_error_count"], 0)
        self.assertEqual(summary["aggregate_count_metrics"]["symbol_all_endpoint_success_count"], 5)
        self.assertFalse(summary["prohibited_claims"]["provider_selected"])
        self.assertFalse(summary["prohibited_claims"]["yfinance_used"])
        self.assertFalse(summary["prohibited_claims"]["sec_api_used"])
        self.assertFalse(summary["storage"]["tracked_summary_contains_raw_rows"])
        self.assertFalse(summary["environment"]["secrets_logged"])

        self.assertEqual(len(client.calls), 30)
        self.assertTrue(all("financialmodelingprep.com/stable/" in url for url in client.calls))
        self.assertFalse(any("sec.gov" in url.lower() for url in client.calls))
        self.assertFalse(any("yfinance" in url.lower() for url in client.calls))
        self.assertFalse(any("TSLA" in url for url in client.calls))
        self.assertTrue(any("symbol=NVDA" in url for url in client.calls))
        self.assertTrue(any("symbol=JPM" in url for url in client.calls))
        self.assertTrue(any("symbol=XOM" in url for url in client.calls))

        for endpoint in summary["endpoint_results"]:
            self.assertTrue(endpoint["raw_sample_ref"].startswith("provider_samples/"))
            self.assertIn("/us_egs_coverage_count_20260602/fmp_stable/raw/", endpoint["raw_sample_ref"])
            self.assertTrue(endpoint["raw_sample_ref_gitignored"])
            self.assertEqual(endpoint["status"], "ok")

    def test_dry_run_validates_env_without_fetching_or_writing(self) -> None:
        summary, client, temp_root = self._run_under_provider_samples(dry_run_env=True)

        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 0)
        self.assertEqual(client.calls, [])
        self.assertFalse((temp_root / "summary.json").exists())

    def test_runtime_approval_validation_rejects_scope_creep(self) -> None:
        approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(approval)
        invalid["scope"]["yfinance_allowed"] = True
        invalid["sample_universe"]["symbols"].append("TSLA")

        with tempfile.TemporaryDirectory(prefix="coverage_approval_", dir=ROOT) as tmp_dir:
            invalid_path = Path(tmp_dir) / "invalid_approval.json"
            invalid_path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "yfinance_allowed=false"):
                coverage_packet.load_and_validate_approval(invalid_path)

    def test_raw_root_must_stay_under_gitignored_provider_samples(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider_samples"):
            coverage_packet.validate_raw_root(ROOT / "docs")


if __name__ == "__main__":
    unittest.main()
