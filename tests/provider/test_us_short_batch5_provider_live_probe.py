import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from runners import us_short_batch5_provider_live_probe as probe


class FakeJsonClient:
    def __init__(self):
        self.urls = []

    def get_json(self, url, headers=None, timeout_seconds=30):
        self.urls.append(url)
        parsed = urlparse(url)
        if "financialmodelingprep.com" in parsed.netloc:
            symbol = parse_qs(parsed.query)["symbol"][0]
            if parsed.path.endswith("/profile"):
                return (
                    [
                        {
                            "symbol": symbol,
                            "companyName": f"{symbol} Inc.",
                            "sector": "Technology",
                            "industry": "Software",
                            "marketCap": 100,
                            "price": 10.0,
                            "volume": 1000,
                        }
                    ],
                    200,
                    True,
                    None,
                )
            if parsed.path.endswith("/historical-price-eod/full"):
                return (
                    [
                        {
                            "date": "2026-06-24",
                            "open": 10.0,
                            "high": 11.0,
                            "low": 9.5,
                            "close": 10.5,
                            "volume": 1000,
                        }
                    ],
                    200,
                    True,
                    None,
                )
        if parsed.netloc == "www.sec.gov" and parsed.path.endswith("/company_tickers.json"):
            return (
                {
                    "0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
                    "1": {"ticker": "MSFT", "cik_str": 789019, "title": "Microsoft Corp"},
                    "2": {"ticker": "JPM", "cik_str": 19617, "title": "JPMorgan Chase & Co"},
                },
                200,
                True,
                None,
            )
        if parsed.netloc == "data.sec.gov" and parsed.path.startswith("/submissions/"):
            return (
                {
                    "filings": {
                        "recent": {
                            "filingDate": ["2026-01-31"],
                            "acceptanceDateTime": ["2026-01-31T12:00:00.000Z"],
                            "accessionNumber": ["0000000000-26-000001"],
                            "form": ["10-K"],
                        }
                    }
                },
                200,
                True,
                None,
            )
        raise AssertionError(f"unexpected URL: {url}")


class UsShortBatch5ProviderLiveProbeTests(unittest.TestCase):
    def _paths(self):
        raw_parent = probe.ROOT / "provider_samples" / "us_short_batch5_v1_provider_live_20260625"
        raw_parent.mkdir(parents=True, exist_ok=True)
        raw_tmp = tempfile.TemporaryDirectory(prefix="test_raw_", dir=raw_parent)
        summary_tmp = tempfile.TemporaryDirectory(prefix="batch5_summary_", dir=probe.ROOT)
        self.addCleanup(raw_tmp.cleanup)
        self.addCleanup(summary_tmp.cleanup)
        return Path(raw_tmp.name) / "raw", Path(summary_tmp.name) / "summary.json"

    def _env(self):
        return mock.patch.dict(
            probe.sample_validation.os.environ,
            {
                "FMP_API_KEY": "UNIT_TEST_FMP_SECRET",
                "SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com",
            },
            clear=False,
        )

    def test_authorized_probe_stays_within_ten_calls_and_writes_private_raw_only(self):
        raw_root, summary_path = self._paths()
        client = FakeJsonClient()

        with self._env(), mock.patch.object(
            probe.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = probe.run_probe(
                packet_path=probe.PACKET_PATH,
                summary_path=summary_path,
                raw_root=raw_root,
                client=client,
                confirm_user_authorization=True,
                dry_run_env=False,
                generated_at="2026-06-25T00:00:00+08:00",
                sec_sleep_seconds=0,
            )

        self.assertEqual(len(client.urls), 10)
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 10)
        self.assertEqual(summary["endpoint_call_budget"]["actual_fmp_endpoint_calls"], 6)
        self.assertEqual(summary["endpoint_call_budget"]["actual_sec_public_api_calls"], 4)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        self.assertEqual(len(summary["endpoint_results"]), 10)
        submission_results = [
            item
            for item in summary["endpoint_results"]
            if item["endpoint_family"] == "company_submissions"
        ]
        self.assertEqual(len(submission_results), 3)
        for result in submission_results:
            for field in ["filings", "recent", "filingDate", "acceptanceDateTime", "accessionNumber", "form"]:
                self.assertIn(field, result["field_presence"])
                self.assertTrue(result["field_presence"][field], field)
        self.assertTrue(summary_path.exists())
        self.assertEqual(len(list(raw_root.rglob("*.json"))), 10)

        text = summary_path.read_text(encoding="utf-8")
        self.assertNotIn("UNIT_TEST_FMP_SECRET", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn("UnitTest/0.1", text)
        self.assertFalse(summary["storage"]["tracked_summary_contains_raw_rows"])
        self.assertFalse(summary["storage"]["request_urls_in_summary"])
        self.assertFalse(summary["prohibited_claims"]["ship_gate_evidence_claimed"])

    def test_missing_authorization_flag_aborts_before_network_or_writes(self):
        raw_root, summary_path = self._paths()
        client = FakeJsonClient()

        with self.assertRaisesRegex(RuntimeError, "authorization"):
            probe.run_probe(
                packet_path=probe.PACKET_PATH,
                summary_path=summary_path,
                raw_root=raw_root,
                client=client,
                confirm_user_authorization=False,
                dry_run_env=False,
                generated_at="2026-06-25T00:00:00+08:00",
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(summary_path.exists())
        self.assertEqual(list(raw_root.glob("*.json")), [])

    def test_dry_run_env_checks_without_network_or_writes(self):
        raw_root, summary_path = self._paths()
        client = FakeJsonClient()

        with self._env(), mock.patch.object(
            probe.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = probe.run_probe(
                packet_path=probe.PACKET_PATH,
                summary_path=summary_path,
                raw_root=raw_root,
                client=client,
                confirm_user_authorization=False,
                dry_run_env=True,
                generated_at="2026-06-25T00:00:00+08:00",
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(summary_path.exists())
        self.assertFalse(summary["scope"]["provider_live_probe_performed"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 0)

    def test_scope_mutation_rejected_before_network(self):
        raw_root, summary_path = self._paths()
        client = FakeJsonClient()
        packet = json.loads(probe.PACKET_PATH.read_text(encoding="utf-8"))
        packet["future_provider_live_probe_boundary"]["endpoint_call_budget"]["max_total_endpoint_calls"] = 11
        packet_path = summary_path.parent / "mutated_packet.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")

        with self._env(), self.assertRaises(ValueError):
            probe.run_probe(
                packet_path=packet_path,
                summary_path=summary_path,
                raw_root=raw_root,
                client=client,
                confirm_user_authorization=True,
                dry_run_env=False,
                generated_at="2026-06-25T00:00:00+08:00",
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(summary_path.exists())

    def test_raw_root_must_remain_under_authorized_provider_samples_path(self):
        with tempfile.TemporaryDirectory(prefix="outside_raw_", dir=probe.ROOT) as tmpdir:
            raw_root = Path(tmpdir) / "raw"
            summary_path = Path(tmpdir) / "summary.json"
            with self.assertRaises(ValueError):
                probe.run_probe(
                    packet_path=probe.PACKET_PATH,
                    summary_path=summary_path,
                    raw_root=raw_root,
                    client=FakeJsonClient(),
                    confirm_user_authorization=True,
                    dry_run_env=False,
                    generated_at="2026-06-25T00:00:00+08:00",
                    sec_sleep_seconds=0,
                )


if __name__ == "__main__":
    unittest.main()
