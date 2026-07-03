from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import us_short_batch5_bankruptcy_8k_preflight as preflight


ROOT = Path(".").resolve()
PACKET_PATH = Path("docs/us_short_batch5_bankruptcy_8k_access_packet_20260703.json")


class UsShortBatch5Bankruptcy8kPreflightTest(unittest.TestCase):
    def test_preflight_validates_packet_without_fetching_reading_env_or_writing(self) -> None:
        future_raw_root = ROOT / "provider_samples" / "us_short_batch5_bankruptcy_8k_20260703"
        before_raw_refs = sorted(
            path.relative_to(future_raw_root).as_posix()
            for path in future_raw_root.rglob("*")
            if path.is_file()
        ) if future_raw_root.exists() else []

        with mock.patch.dict(
            os.environ,
            {
                "SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com",
                "STATUS_SOURCE_SECRET": "UNIT_TEST_STATUS_SECRET",
            },
            clear=True,
        ):
            result = preflight.run_preflight(
                packet_path=PACKET_PATH,
                generated_at="2026-07-03T00:00:00+00:00",
            )

        self.assertEqual(result["schema_name"], "us_short_batch5_bankruptcy_8k_preflight_result")
        self.assertEqual(
            result["scope"]["preflight_status"],
            "offline_preflight_passed_bankruptcy_8k_authorization_required",
        )
        self.assertFalse(result["scope"]["status_source_calls_performed"])
        self.assertFalse(result["scope"]["network_access_required"])
        self.assertFalse(result["scope"]["raw_payloads_read"])
        self.assertFalse(result["scope"]["raw_payloads_written"])
        self.assertFalse(result["scope"]["tracked_summary_written"])
        self.assertTrue(result["scope"]["future_bankruptcy_scan_requires_explicit_user_authorization"])
        self.assertTrue(result["scope"]["future_bankruptcy_scan_requires_user_execute"])
        self.assertEqual(
            result["bankruptcy_8k_scan_boundary"]["sample_universe"]["symbols"],
            ["AAPL", "MSFT", "JPM"],
        )
        self.assertEqual(
            result["bankruptcy_8k_scan_boundary"]["endpoint_call_budget"]["max_total_endpoint_calls"],
            3,
        )
        self.assertEqual(
            [item["source_id"] for item in result["bankruptcy_8k_scan_boundary"]["endpoint_families"]],
            ["sec_8k_item_103"],
        )
        self.assertFalse(result["environment"]["environment_values_read"])
        self.assertFalse(result["environment"]["secrets_logged"])

        after_raw_refs = sorted(
            path.relative_to(future_raw_root).as_posix()
            for path in future_raw_root.rglob("*")
            if path.is_file()
        ) if future_raw_root.exists() else []
        self.assertEqual(after_raw_refs, before_raw_refs)

        result_text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("UnitTest/0.1 contact:test@example.com", result_text)
        self.assertNotIn("UNIT_TEST_STATUS_SECRET", result_text)
        self.assertNotIn("https://", result_text.lower())
        self.assertNotIn("sec.gov", result_text.lower())
        self.assertNotIn("apikey=", result_text.lower())

    def test_packet_scope_creep_is_rejected_before_any_side_effect(self) -> None:
        packet = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(packet)
        invalid["scope"]["bankruptcy_8k_calls_allowed_without_future_authorization"] = True
        invalid["scope"]["full_market_or_per_symbol_fetch_allowed"] = True
        invalid["bankruptcy_8k_scan_boundary"]["endpoint_call_budget"]["max_total_endpoint_calls"] = 4
        invalid["bankruptcy_8k_scan_boundary"]["sample_universe"]["symbols"].append("NVDA")

        with tempfile.TemporaryDirectory(prefix="bankruptcy_8k_packet_", dir=ROOT) as tmp_dir:
            packet_path = Path(tmp_dir) / "packet.json"
            packet_path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "bankruptcy_8k_calls_allowed|full_market|endpoint|symbols"):
                preflight.run_preflight(
                    packet_path=packet_path,
                    generated_at="2026-07-03T00:00:00+00:00",
                )

    def test_storage_boundary_creep_is_rejected(self) -> None:
        packet = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(packet)
        invalid["storage_and_secret_boundary"]["future_raw_sample_storage_path"] = "docs/raw_bankruptcy_payloads/"
        invalid["storage_and_secret_boundary"]["tracked_summary_must_exclude_request_urls"] = False
        invalid["storage_and_secret_boundary"]["production_storage_authorized"] = True

        with tempfile.TemporaryDirectory(prefix="bankruptcy_8k_storage_", dir=ROOT) as tmp_dir:
            packet_path = Path(tmp_dir) / "packet.json"
            packet_path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "provider_samples|request_urls|production"):
                preflight.run_preflight(
                    packet_path=packet_path,
                    generated_at="2026-07-03T00:00:00+00:00",
                )

    def test_provider_samples_must_be_gitignored(self) -> None:
        with mock.patch.object(preflight, "provider_samples_gitignored", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "provider_samples"):
                preflight.run_preflight(
                    packet_path=PACKET_PATH,
                    generated_at="2026-07-03T00:00:00+00:00",
                )


if __name__ == "__main__":
    unittest.main()
