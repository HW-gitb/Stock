from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import us_short_batch5_provider_live_preflight as preflight


ROOT = Path(".").resolve()
PACKET_PATH = Path("docs/us_short_batch5_provider_live_packet_20260625.json")


class UsShortBatch5ProviderLivePreflightTest(unittest.TestCase):
    def test_preflight_validates_packet_without_fetching_or_writing(self) -> None:
        future_raw_root = ROOT / "provider_samples" / "us_short_batch5_v1_provider_live_20260625"
        before_raw_refs = sorted(
            path.relative_to(future_raw_root).as_posix()
            for path in future_raw_root.rglob("*")
            if path.is_file()
        ) if future_raw_root.exists() else []

        with mock.patch.dict(
            preflight.os.environ,
            {
                "FMP_API_KEY": "UNIT_TEST_FMP_SECRET",
                "SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com",
            },
            clear=True,
        ):
            result = preflight.run_preflight(
                packet_path=PACKET_PATH,
                generated_at="2026-06-25T00:00:00+00:00",
            )

        self.assertEqual(result["schema_name"], "us_short_batch5_provider_live_preflight_result")
        self.assertEqual(result["scope"]["preflight_status"], "offline_preflight_passed_provider_authorization_required")
        self.assertFalse(result["scope"]["provider_calls_performed"])
        self.assertFalse(result["scope"]["network_access_required"])
        self.assertFalse(result["scope"]["raw_payloads_written"])
        self.assertFalse(result["scope"]["tracked_summary_written"])
        self.assertTrue(result["scope"]["future_provider_live_probe_requires_explicit_user_authorization"])
        self.assertEqual(result["future_provider_live_probe_boundary"]["sample_universe"]["symbols"], ["AAPL", "MSFT", "JPM"])
        self.assertEqual(result["future_provider_live_probe_boundary"]["endpoint_call_budget"]["max_total_endpoint_calls"], 10)
        self.assertFalse(result["environment"]["environment_values_read"])
        self.assertFalse(result["environment"]["secrets_logged"])
        after_raw_refs = sorted(
            path.relative_to(future_raw_root).as_posix()
            for path in future_raw_root.rglob("*")
            if path.is_file()
        ) if future_raw_root.exists() else []
        self.assertEqual(after_raw_refs, before_raw_refs)

        result_text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("UNIT_TEST_FMP_SECRET", result_text)
        self.assertNotIn("UnitTest/0.1 contact:test@example.com", result_text)
        self.assertNotIn("apikey=", result_text.lower())
        self.assertNotIn("financialmodelingprep.com/", result_text.lower())
        self.assertNotIn("sec.gov/", result_text.lower())

    def test_packet_scope_creep_is_rejected_before_any_side_effect(self) -> None:
        packet = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(packet)
        invalid["scope"]["provider_calls_allowed_without_future_authorization"] = True
        invalid["scope"]["full_market_or_broad_universe_allowed"] = True
        invalid["future_provider_live_probe_boundary"]["endpoint_call_budget"]["max_total_endpoint_calls"] = 11
        invalid["future_provider_live_probe_boundary"]["sample_universe"]["symbols"].append("NVDA")

        with tempfile.TemporaryDirectory(prefix="batch5_packet_", dir=ROOT) as tmp_dir:
            packet_path = Path(tmp_dir) / "packet.json"
            packet_path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "provider_calls_allowed|full_market|endpoint|symbols"):
                preflight.run_preflight(packet_path=packet_path, generated_at="2026-06-25T00:00:00+00:00")

    def test_storage_boundary_creep_is_rejected(self) -> None:
        packet = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(packet)
        invalid["storage_and_secret_boundary"]["future_raw_sample_storage_path"] = "docs/raw_provider_payloads/"
        invalid["storage_and_secret_boundary"]["tracked_summary_must_exclude_request_urls"] = False

        with tempfile.TemporaryDirectory(prefix="batch5_storage_", dir=ROOT) as tmp_dir:
            packet_path = Path(tmp_dir) / "packet.json"
            packet_path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "provider_samples|request_urls"):
                preflight.run_preflight(packet_path=packet_path, generated_at="2026-06-25T00:00:00+00:00")

    def test_provider_samples_must_be_gitignored(self) -> None:
        with mock.patch.object(preflight, "provider_samples_gitignored", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "provider_samples"):
                preflight.run_preflight(packet_path=PACKET_PATH, generated_at="2026-06-25T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
