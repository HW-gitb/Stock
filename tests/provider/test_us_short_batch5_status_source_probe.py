from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import us_short_batch5_status_source_probe as probe
from tests.provider.us_short_private_test_root import temporary_us_short_directory


ROOT = Path(".").resolve()
PACKET_PATH = Path("docs/us_short_batch5_status_source_access_packet_20260630.json")


class FakeStatusHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = probe.DEFAULT_TIMEOUT_SECONDS,
    ) -> tuple[bytes, str | None, int | None, bool, str | None]:
        del timeout_seconds
        self.calls.append((url, dict(headers or {})))
        if url == probe.SEC_TICKER_REFERENCE_URL:
            payload = {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                    [789019, "Microsoft Corp.", "MSFT", "Nasdaq"],
                    [19617, "JPMorgan Chase & Co.", "JPM", "NYSE"],
                ],
            }
            return json.dumps(payload).encode("utf-8"), "application/json", 200, True, None
        if url == probe.NASDAQ_TRADE_HALTS_RSS_URL:
            rss = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<rss><channel><title>Trade Halts</title>"
                "<item><title>HALT</title><description>Symbol: HALT</description></item>"
                "</channel></rss>"
            )
            return rss.encode("utf-8"), "application/rss+xml", 200, True, None
        return b"{}", "application/json", 404, False, "unexpected_url"


class UsShortBatch5StatusSourceProbeTest(unittest.TestCase):
    def _run_under_provider_samples(self, **kwargs: object) -> tuple[dict, FakeStatusHttpClient, Path]:
        root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_status_source_20260630" / "raw"
        )
        private_root = Path(root_context.__enter__())
        base = private_root / "_unit_tests"
        self.addCleanup(root_context.__exit__, None, None, None)
        base.mkdir(parents=True, exist_ok=True)
        client = FakeStatusHttpClient()
        temp_dir = tempfile.TemporaryDirectory(prefix="run_", dir=base)
        self.addCleanup(temp_dir.cleanup)
        temp_root = Path(temp_dir.name)
        summary_path = temp_root / "summary.json"
        raw_root = temp_root / "raw"
        with mock.patch.dict(
            probe.os.environ,
            {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
            clear=True,
        ), mock.patch.object(probe.sample_validation, "_read_windows_environment_value", return_value=None):
            summary = probe.run_status_source_probe(
                access_packet_path=PACKET_PATH,
                summary_path=summary_path,
                raw_root=raw_root,
                generated_at="2026-07-03T00:00:00+00:00",
                client=client,
                confirm_user_authorization=True,
                confirm_post_preflight_execute=True,
                **kwargs,
            )
        return summary, client, temp_root

    def test_shape_probe_fetches_only_two_public_bulk_feeds_and_summary_is_sanitized(self) -> None:
        summary, client, temp_root = self._run_under_provider_samples()
        summary_path = temp_root / "summary.json"

        self.assertEqual(summary["schema_name"], "us_short_batch5_status_source_probe_summary")
        self.assertEqual(summary["scope"]["probe_status"], "completed")
        self.assertTrue(summary["scope"]["status_source_probe_performed"])
        self.assertFalse(summary["scope"]["runner_consumption_allowed"])
        self.assertFalse(summary["scope"]["datahub_consumption_allowed"])
        self.assertFalse(summary["scope"]["bankruptcy_8k_scan_performed"])
        self.assertFalse(summary["scope"]["status_records_written"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 2)
        self.assertEqual(summary["endpoint_call_budget"]["retry_count_used"], 0)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])

        self.assertEqual(
            [url for url, _ in client.calls],
            [probe.SEC_TICKER_REFERENCE_URL, probe.NASDAQ_TRADE_HALTS_RSS_URL],
        )
        self.assertEqual(
            [item["source_id"] for item in summary["endpoint_results"]],
            ["ticker_reference", "exchange_halt_feed"],
        )
        for endpoint in summary["endpoint_results"]:
            self.assertEqual(endpoint["status"], "ok")
            self.assertTrue(endpoint["raw_sample_ref"].startswith("provider_samples/"))
            self.assertTrue((ROOT / endpoint["raw_sample_ref"]).exists())

        ticker_shape = summary["sample_shape_results"]["ticker_reference"]
        self.assertTrue(ticker_shape["feed_shape_valid"])
        self.assertEqual(set(ticker_shape["sample_symbol_presence"]), {"AAPL", "MSFT", "JPM"})
        self.assertTrue(all(row["row_present"] for row in ticker_shape["sample_symbol_presence"].values()))
        halt_shape = summary["sample_shape_results"]["exchange_halt_feed"]
        self.assertTrue(halt_shape["feed_shape_valid"])
        self.assertEqual(halt_shape["sample_symbols_checked"], ["AAPL", "MSFT", "JPM"])

        summary_text = summary_path.read_text(encoding="utf-8")
        self.assertNotIn("UnitTest/0.1 contact:test@example.com", summary_text)
        self.assertNotIn("https://", summary_text.lower())
        self.assertNotIn("sec.gov", summary_text.lower())
        self.assertNotIn("nasdaqtrader", summary_text.lower())
        self.assertNotIn("rss.aspx", summary_text.lower())
        self.assertNotIn("apikey=", summary_text.lower())
        self.assertNotIn("raw_payload", summary_text.lower())

    def test_live_probe_requires_confirmations_before_fetch_or_write(self) -> None:
        root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_status_source_20260630" / "raw"
        )
        private_root = Path(root_context.__enter__())
        base = private_root / "_unit_tests"
        self.addCleanup(root_context.__exit__, None, None, None)
        base.mkdir(parents=True, exist_ok=True)
        client = FakeStatusHttpClient()
        with tempfile.TemporaryDirectory(prefix="missing_confirm_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            with mock.patch.dict(
                probe.os.environ,
                {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "confirm-user-authorization"):
                    probe.run_status_source_probe(
                        access_packet_path=PACKET_PATH,
                        summary_path=temp_root / "summary.json",
                        raw_root=temp_root / "raw",
                        generated_at="2026-07-03T00:00:00+00:00",
                        client=client,
                        confirm_user_authorization=False,
                        confirm_post_preflight_execute=True,
                    )

            self.assertEqual(client.calls, [])
            self.assertFalse((temp_root / "summary.json").exists())

    def test_dry_run_env_checks_boundary_without_fetching_or_writing(self) -> None:
        root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_status_source_20260630" / "raw"
        )
        private_root = Path(root_context.__enter__())
        base = private_root / "_unit_tests"
        self.addCleanup(root_context.__exit__, None, None, None)
        base.mkdir(parents=True, exist_ok=True)
        client = FakeStatusHttpClient()
        with tempfile.TemporaryDirectory(prefix="dry_run_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            with mock.patch.dict(
                probe.os.environ,
                {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
                clear=True,
            ), mock.patch.object(probe.sample_validation, "_read_windows_environment_value", return_value=None):
                summary = probe.run_status_source_probe(
                    access_packet_path=PACKET_PATH,
                    summary_path=temp_root / "summary.json",
                    raw_root=temp_root / "raw",
                    generated_at="2026-07-03T00:00:00+00:00",
                    client=client,
                    dry_run_env=True,
                )

            self.assertEqual(summary["scope"]["probe_status"], "dry_run_env_only")
            self.assertFalse(summary["scope"]["status_source_probe_performed"])
            self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 0)
            self.assertEqual(client.calls, [])
            self.assertFalse((temp_root / "summary.json").exists())

    def test_schema_invalid_summary_is_not_written(self) -> None:
        root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_status_source_20260630" / "raw"
        )
        private_root = Path(root_context.__enter__())
        base = private_root / "_unit_tests"
        self.addCleanup(root_context.__exit__, None, None, None)
        base.mkdir(parents=True, exist_ok=True)
        client = FakeStatusHttpClient()
        original_build_summary = probe.build_summary

        def invalid_build_summary(**kwargs: object) -> dict:
            summary = original_build_summary(**kwargs)
            summary["scope"]["runner_consumption_allowed"] = True
            return summary

        with tempfile.TemporaryDirectory(prefix="invalid_summary_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "summary.json"
            with mock.patch.dict(
                probe.os.environ,
                {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
                clear=True,
            ), mock.patch.object(probe.sample_validation, "_read_windows_environment_value", return_value=None), \
                    mock.patch.object(probe, "build_summary", side_effect=invalid_build_summary):
                with self.assertRaisesRegex(RuntimeError, "schema validation failed"):
                    probe.run_status_source_probe(
                        access_packet_path=PACKET_PATH,
                        summary_path=summary_path,
                        raw_root=temp_root / "raw",
                        generated_at="2026-07-03T00:00:00+00:00",
                        client=client,
                        confirm_user_authorization=True,
                        confirm_post_preflight_execute=True,
                    )

            self.assertEqual(len(client.calls), 2)
            self.assertFalse(summary_path.exists())
            self.assertFalse(summary_path.with_name("summary.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
