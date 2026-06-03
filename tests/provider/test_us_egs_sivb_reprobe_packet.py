from __future__ import annotations

import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from runners import us_egs_sivb_reprobe_packet as sivb_reprobe


ROOT = Path(".").resolve()
EXECUTION_PACKET_PATH = Path("docs/provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json")


class FakeHttpClient:
    def __init__(self, *, body_text: str = "Payment Required: Upgrade plan for historical endpoint") -> None:
        self.body_text = body_text
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = sivb_reprobe.sample_validation.DEFAULT_TIMEOUT_SECONDS,
    ) -> tuple[object, int | None, bool, str | None]:
        del timeout_seconds
        self.calls.append((url, headers))
        return (
            {
                "non_json_response_bytes": len(self.body_text.encode("utf-8")),
                "non_json_response_body_text": self.body_text,
                "non_json_response_body_encoding": "utf-8-replacement",
            },
            402,
            False,
            "http_error",
        )


class UsEgsSivbReprobePacketTest(unittest.TestCase):
    def _run_under_provider_samples(
        self,
        *,
        dry_run_env: bool = False,
        confirm_independent_review_pass: bool = True,
        confirm_post_review_execute: bool = True,
        client: FakeHttpClient | None = None,
    ) -> tuple[dict, FakeHttpClient, Path]:
        base = ROOT / "provider_samples" / "us_egs_sivb_reprobe_20260603" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        client = client or FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="run_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "summary.json"
            raw_root = temp_root / "raw"
            with mock.patch.dict(
                sivb_reprobe.sample_validation.os.environ,
                {"FMP_API_KEY": "UNIT_TEST_FMP_SECRET"},
                clear=True,
            ), mock.patch.object(sivb_reprobe.sample_validation, "_read_windows_environment_value", return_value=None):
                summary = sivb_reprobe.run_sivb_reprobe_packet(
                    execution_packet_path=EXECUTION_PACKET_PATH,
                    summary_path=summary_path,
                    raw_root=raw_root,
                    generated_at="2026-06-03T00:00:00+00:00",
                    client=client,
                    dry_run_env=dry_run_env,
                    confirm_independent_review_pass=confirm_independent_review_pass,
                    confirm_post_review_execute=confirm_post_review_execute,
                )
                if not dry_run_env:
                    summary_text = summary_path.read_text(encoding="utf-8")
                    self.assertNotIn("UNIT_TEST_FMP_SECRET", summary_text)
                    self.assertNotIn("apikey=", summary_text.lower())
                    self.assertNotIn("financialmodelingprep.com/", summary_text.lower())
                    self.assertNotIn(client.body_text, summary_text)
                    self.assertTrue(summary_path.exists())
                    for endpoint in summary.get("endpoint_results", []):
                        raw_path = ROOT / endpoint["raw_sample_ref"]
                        self.assertTrue(raw_path.exists())
                        raw_text = raw_path.read_text(encoding="utf-8")
                        self.assertIn(client.body_text, raw_text)
                        self.assertNotIn("apikey=", raw_text.lower())
                return summary, client, temp_root

    def test_reprobe_fetches_only_sivb_five_failed_fmp_families_and_writes_no_secret_summary(self) -> None:
        summary, client, _ = self._run_under_provider_samples()

        self.assertEqual(summary["scope"]["validation_status"], "completed_with_endpoint_errors")
        self.assertTrue(summary["scope"]["provider_reprobe_execution_performed"])
        self.assertEqual(summary["sample_universe"]["symbols"], ["SIVB"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 5)
        self.assertEqual(summary["endpoint_call_budget"]["actual_fmp_endpoint_calls"], 5)
        self.assertEqual(summary["endpoint_call_budget"]["actual_sec_endpoint_calls"], 0)
        self.assertEqual(summary["endpoint_call_budget"]["retry_count_used"], 0)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        self.assertEqual(summary["aggregate_reprobe_metrics"]["endpoint_error_count"], 5)
        self.assertEqual(summary["aggregate_reprobe_metrics"]["http_402_count"], 5)
        self.assertEqual(summary["aggregate_reprobe_metrics"]["non_json_body_captured_count"], 5)
        self.assertEqual(
            summary["aggregate_reprobe_metrics"]["classification_signal_counts"]["historical_or_delisted_paid_tier"],
            5,
        )
        self.assertFalse(summary["classification_decision"]["sivb_402_paid_wall_proven"])
        self.assertFalse(summary["prohibited_claims"]["phase7c_authorized"])
        self.assertFalse(summary["storage"]["response_body_text_in_summary"])
        self.assertFalse(summary["storage"]["request_urls_in_summary"])

        urls = [url for url, _ in client.calls]
        self.assertEqual(len(urls), 5)
        self.assertTrue(all("financialmodelingprep.com/stable/" in url for url in urls))
        self.assertTrue(all("symbol=SIVB" in url for url in urls))
        self.assertFalse(any("/stable/profile" in url for url in urls))
        self.assertFalse(any("sec.gov" in urllib.parse.urlparse(url).netloc for url in urls))
        self.assertFalse(any("TWTR" in url or "AAPL" in url for url in urls))
        self.assertFalse(any("split" in url.lower() or "dividend" in url.lower() for url in urls))

        endpoint_families = {endpoint["endpoint_family"] for endpoint in summary["endpoint_results"]}
        self.assertEqual(endpoint_families, set(sivb_reprobe.EXPECTED_FMP_ENDPOINT_FAMILIES))
        for endpoint in summary["endpoint_results"]:
            self.assertEqual(endpoint["symbol"], "SIVB")
            self.assertEqual(endpoint["http_status"], 402)
            self.assertTrue(endpoint["raw_sample_ref"].startswith("provider_samples/us_egs_sivb_reprobe_20260603/raw/"))
            self.assertTrue(endpoint["raw_sample_ref_gitignored"])
            self.assertTrue(endpoint["body_capture"]["non_json_response_body_captured_in_raw"])
            self.assertFalse(endpoint["body_capture"]["body_text_in_summary"])
            self.assertFalse(endpoint["classification_signal"]["paid_wall_proven"])

    def test_live_execution_requires_review_and_execute_confirmations_before_fetch(self) -> None:
        base = ROOT / "provider_samples" / "us_egs_sivb_reprobe_20260603" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="confirm_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            with mock.patch.dict(
                sivb_reprobe.sample_validation.os.environ,
                {"FMP_API_KEY": "UNIT_TEST_FMP_SECRET"},
                clear=True,
            ), mock.patch.object(sivb_reprobe.sample_validation, "_read_windows_environment_value", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "confirm-independent-review-pass"):
                    sivb_reprobe.run_sivb_reprobe_packet(
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
        self.assertFalse(summary["scope"]["provider_reprobe_execution_performed"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 0)
        self.assertEqual(client.calls, [])
        self.assertFalse((temp_root / "summary.json").exists())

    def test_missing_environment_aborts_before_fetch(self) -> None:
        base = ROOT / "provider_samples" / "us_egs_sivb_reprobe_20260603" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        client = FakeHttpClient()
        with tempfile.TemporaryDirectory(prefix="missing_env_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            with mock.patch.dict(sivb_reprobe.sample_validation.os.environ, {}, clear=True), mock.patch.object(
                sivb_reprobe.sample_validation,
                "_read_windows_environment_value",
                return_value=None,
            ):
                with self.assertRaisesRegex(RuntimeError, "FMP_API_KEY"):
                    sivb_reprobe.run_sivb_reprobe_packet(
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
            sivb_reprobe.validate_raw_root(ROOT / "provider_samples" / "other_packet" / "raw")

    def test_packet_validation_rejects_scope_creep(self) -> None:
        packet = json.loads(EXECUTION_PACKET_PATH.read_text(encoding="utf-8"))
        packet["sample_universe"]["symbols"] = ["SIVB", "TWTR"]
        packet["endpoint_call_budget"]["max_total_endpoint_calls"] = 6
        packet["scope"]["provider_selection_allowed"] = True
        base = ROOT / "provider_samples" / "us_egs_sivb_reprobe_20260603" / "raw" / "_unit_tests"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="packet_", dir=base) as tmp_dir:
            packet_path = Path(tmp_dir) / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "provider_selection_allowed|symbol"):
                sivb_reprobe.load_and_validate_execution_packet(packet_path)


if __name__ == "__main__":
    unittest.main()
