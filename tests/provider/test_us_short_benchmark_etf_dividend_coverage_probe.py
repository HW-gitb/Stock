from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_benchmark_etf_dividend_coverage_probe as probe  # noqa: E402
from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from tests.provider.us_short_private_test_root_light import temporary_us_short_state_directory  # noqa: E402


_FAKE_KEY = "FAKE-MASSIVE-KEY-should-never-appear-in-tracked-summary"


def _dividend_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "ex_dividend_date": "2026-06-19",
        "cash_amount": 1.75,
        "pay_date": "2026-06-30",
        "record_date": "2026-06-22",
        "frequency": 4,
        "currency": "USD",
        "distribution_type": "CD",
    }


class _FakeMassiveClient:
    """Drives every branch of the probe. Asserts the api key IS in the request URL (so the secret-scan
    assertion is meaningful) while the URL itself must never reach the tracked summary.

    mode:
      - "covered"        : each ETF returns its own rows with the required fields
      - "ticker_ignored" : provider ignores the ticker filter and returns SOMEBODY ELSE's rows
      - "empty"          : HTTP 200 but zero rows (queried fine, no coverage)
      - "missing_fields" : rows for the right ticker but without ex_dividend_date / cash_amount
      - "paywall"        : HTTP 402 for every call
    """

    def __init__(self, mode: str = "covered"):
        self.mode = mode
        self.urls: list[str] = []

    def get_json(self, url, headers=None, timeout_seconds=30):
        self.urls.append(url)
        assert _FAKE_KEY in url  # the key travels in the URL -> must be scrubbed from the tracked summary
        assert "/stocks/v1/dividends" in url  # dividends-only allowlist
        symbol = url.split("ticker=")[1].split("&")[0]

        if self.mode == "paywall":
            return (None, 402, False, "http_error")
        if self.mode == "empty":
            return ({"results": [], "status": "OK"}, 200, True, None)
        if self.mode == "ticker_ignored":
            # market-wide rows leaked back despite the ticker filter -> must NOT read as covered
            payload = {"results": [_dividend_row("AAPL"), _dividend_row("MSFT")], "status": "OK"}
            return (payload, 200, True, None)
        if self.mode == "missing_fields":
            payload = {"results": [{"ticker": symbol, "pay_date": "2026-06-30"}], "status": "OK"}
            return (payload, 200, True, None)
        payload = {
            "results": [_dividend_row(symbol), _dividend_row(symbol)],
            "status": "OK",
            "next_url": "https://api.massive.com/stocks/v1/dividends?cursor=abc",
        }
        return (payload, 200, True, None)


class BenchmarkEtfDividendCoverageProbeTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._orig_summary = probe.SUMMARY_PATH
        self._orig_raw = probe.RAW_SAMPLE_ROOT
        self._orig_read_env = sample_validation.read_required_env
        self._orig_gitignored = probe._provider_samples_gitignored
        slug = f"etf_div_probe_{__import__('os').getpid()}"
        self.tmp_summary = self.state_root / f"{slug}_summary.json"
        self.tmp_raw = self.state_root / f"{slug}_raw"
        probe.SUMMARY_PATH = self.tmp_summary
        probe.RAW_SAMPLE_ROOT = self.tmp_raw
        probe._provider_samples_gitignored = lambda: True  # temp dir is not gitignored; bypass the check
        sample_validation.read_required_env = lambda name: sample_validation.EnvValue(
            value=_FAKE_KEY, source="test"
        )

    def tearDown(self):
        probe.SUMMARY_PATH = self._orig_summary
        probe.RAW_SAMPLE_ROOT = self._orig_raw
        probe._provider_samples_gitignored = self._orig_gitignored
        sample_validation.read_required_env = self._orig_read_env

    # ---- gates ----------------------------------------------------------------

    def test_dry_run_env_makes_no_network_call(self):
        self.assertEqual(probe.main(["--dry-run-env"]), 0)
        self.assertFalse(self.tmp_summary.exists())

    def test_missing_authorization_aborts_before_any_fetch(self):
        client = _FakeMassiveClient()
        with self.assertRaises(probe.BenchmarkEtfDividendCoverageProbeError):
            probe.run_probe(confirm_user_authorization=False, client=client)
        self.assertEqual(client.urls, [])
        self.assertFalse(self.tmp_summary.exists())

    def test_non_gitignored_raw_root_aborts_before_any_fetch(self):
        probe._provider_samples_gitignored = lambda: False
        client = _FakeMassiveClient()
        with self.assertRaises(probe.BenchmarkEtfDividendCoverageProbeError):
            probe.run_probe(confirm_user_authorization=True, client=client)
        self.assertEqual(client.urls, [])
        self.assertFalse(self.tmp_summary.exists())

    def test_off_allowlist_family_url_raises(self):
        with self.assertRaises(probe.BenchmarkEtfDividendCoverageProbeError):
            probe._url_for("splits", "SPY", _FAKE_KEY)

    def test_call_budget_is_exactly_the_planned_call_count(self):
        self.assertEqual(
            probe.MAX_TOTAL_ENDPOINT_CALLS,
            len(probe.BENCHMARK_ETF_SYMBOLS) * len(probe.ENDPOINT_FAMILY_ALLOWLIST),
        )

    # ---- the go/no-go finding --------------------------------------------------

    def test_covered_case_records_verdict_and_writes_a_clean_secret_free_summary(self):
        client = _FakeMassiveClient("covered")
        summary = probe.run_probe(confirm_user_authorization=True, client=client)

        self.assertEqual(summary["scope"]["actual_total_endpoint_calls"], 4)
        self.assertEqual(len(client.urls), 4)
        self.assertEqual(summary["coverage_findings"]["benchmark_dividend_source_viable"], "viable_all")
        self.assertEqual(summary["coverage_findings"]["covered_symbol_count"], 4)
        self.assertEqual(
            [r["symbol"] for r in summary["symbol_results"]], list(probe.BENCHMARK_ETF_SYMBOLS)
        )
        for result in summary["symbol_results"]:
            self.assertEqual(result["coverage_verdict"], "covered")
            self.assertEqual(result["rows_matching_queried_ticker"], result["row_count"])
            self.assertTrue(result["required_field_names_present"])
        # field NAMES captured so the later dividend leg can be built on the real shape
        self.assertIn("ex_dividend_date", summary["coverage_findings"]["observed_event_item_key_names"])
        self.assertIn("cash_amount", summary["coverage_findings"]["observed_event_item_key_names"])
        # gate flags all pinned closed
        self.assertFalse(any(summary["gate_flags"].values()))
        # tracked summary written, schema-valid, no secret / URL / raw payload
        text = self.tmp_summary.read_text(encoding="utf-8")
        self.assertNotIn(_FAKE_KEY, text)
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("https://", text.lower())
        self.assertNotIn('"payload"', text)
        # no VALUE from a dividend row leaked (only names/counts)
        self.assertNotIn("2026-06-19", text)
        self.assertNotIn("1.75", text)
        # raw payload IS stored under the (temp) gitignored root
        self.assertEqual(len(list(self.tmp_raw.rglob("*.json"))), 4)

    def test_provider_ignoring_the_ticker_filter_is_not_read_as_covered(self):
        """The false-positive guard: rows come back (row_count > 0) but they belong to other tickers."""
        summary = probe.run_probe(
            confirm_user_authorization=True, client=_FakeMassiveClient("ticker_ignored")
        )
        for result in summary["symbol_results"]:
            self.assertEqual(result["row_count"], 2)
            self.assertEqual(result["rows_matching_queried_ticker"], 0)
            self.assertEqual(result["coverage_verdict"], "rows_do_not_match_queried_ticker")
        self.assertEqual(summary["coverage_findings"]["benchmark_dividend_source_viable"], "not_viable")
        self.assertEqual(summary["coverage_findings"]["covered_symbol_count"], 0)
        # a foreign ticker seen in the raw rows must never reach the tracked summary
        text = self.tmp_summary.read_text(encoding="utf-8")
        self.assertNotIn("AAPL", text)
        self.assertNotIn("MSFT", text)

    def test_ok_but_zero_rows_is_not_viable_rather_than_covered(self):
        summary = probe.run_probe(confirm_user_authorization=True, client=_FakeMassiveClient("empty"))
        for result in summary["symbol_results"]:
            self.assertTrue(result["ok"])
            self.assertEqual(result["row_count"], 0)
            self.assertEqual(result["coverage_verdict"], "queried_ok_but_no_rows")
        self.assertEqual(summary["coverage_findings"]["benchmark_dividend_source_viable"], "not_viable")

    def test_rows_without_the_required_field_names_are_not_covered(self):
        summary = probe.run_probe(
            confirm_user_authorization=True, client=_FakeMassiveClient("missing_fields")
        )
        for result in summary["symbol_results"]:
            self.assertEqual(result["rows_matching_queried_ticker"], result["row_count"])
            self.assertFalse(result["required_field_names_present"])
            self.assertEqual(result["coverage_verdict"], "rows_missing_required_fields")
        self.assertEqual(summary["coverage_findings"]["benchmark_dividend_source_viable"], "not_viable")

    def test_paywalled_endpoint_is_recorded_as_endpoint_error(self):
        summary = probe.run_probe(confirm_user_authorization=True, client=_FakeMassiveClient("paywall"))
        for result in summary["symbol_results"]:
            self.assertFalse(result["ok"])
            self.assertEqual(result["http_status"], 402)
            self.assertIsNone(result["response_shape"])
            self.assertEqual(result["coverage_verdict"], "endpoint_error")
        self.assertEqual(summary["coverage_findings"]["benchmark_dividend_source_viable"], "endpoint_error")
        self.assertEqual(summary["coverage_findings"]["http_status_classes"], [402])

    # ---- the verdict helpers are fail-closed ----------------------------------

    def test_coverage_verdict_ordering_is_fail_closed(self):
        self.assertEqual(
            probe._coverage_verdict(ok=False, row_count=5, matched_rows=5, required_fields_present=True),
            "endpoint_error",
        )
        self.assertEqual(
            probe._coverage_verdict(ok=True, row_count=2, matched_rows=1, required_fields_present=True),
            "rows_do_not_match_queried_ticker",
        )
        self.assertEqual(
            probe._coverage_verdict(ok=True, row_count=2, matched_rows=2, required_fields_present=True),
            "covered",
        )

    def test_malformed_rows_never_count_as_matching(self):
        payload = {
            "results": [
                {"ticker": "SPY"},
                {"ticker": 123},
                {"no_ticker_key": True},
                "not-a-dict",
                None,
            ]
        }
        self.assertEqual(probe._rows_matching_queried_ticker(payload, "SPY"), 1)
        self.assertEqual(probe._rows_matching_queried_ticker({"results": []}, "SPY"), 0)
        self.assertEqual(probe._rows_matching_queried_ticker(None, "SPY"), 0)

    def test_partial_coverage_rolls_up_as_viable_partial(self):
        results = [
            {"coverage_verdict": "covered"},
            {"coverage_verdict": "queried_ok_but_no_rows"},
        ]
        self.assertEqual(probe._source_viability(results), "viable_partial")
        self.assertEqual(probe._source_viability([]), "endpoint_error")


if __name__ == "__main__":
    unittest.main()
