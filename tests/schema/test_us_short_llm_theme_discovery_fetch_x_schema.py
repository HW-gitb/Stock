from __future__ import annotations

import unittest
from unittest import mock

from jsonschema import Draft7Validator

from runners import us_short_llm_theme_discovery_fetch_x as xfetch


class XFetchSchemaTests(unittest.TestCase):
    def test_offline_receipt_conforms_to_x_schema(self):
        rows = [{"url": "https://x.example/post/schema", "title": "Schema", "text": "AAPL", "created_at": "2026-07-24T10:00:00Z"}]
        response = '{"themes":[{"theme_id":"power_demand","display_name":"Power","summary":"Power","observed_at":"2026-07-24T12:00:00Z","source_ref_ids":["x:' + '0' * 64 + '"],"members":[{"ticker":"AAPL","source_ref_ids":["x:' + '0' * 64 + '"]}]}]}'
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=rows,
            grok_response=response.replace("x:" + "0" * 64, xfetch._source_id(rows[0]["url"])),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        schema = xfetch.web._read_json(xfetch.SCHEMA_PATH)
        self.assertEqual(list(Draft7Validator(schema).iter_errors(receipt)), [])

    def test_validate_schema_actually_rejects_an_invalid_receipt(self):
        """The existing guard test only patches `_validate_schema` to raise, which pins the call ORDER,
        not the validation. This one dies if the validator itself is neutered."""
        receipt = {
            "schema_name": "us_short_llm_theme_discovery_fetch_x", "schema_version": "1.0.0",
            "generated_at": "2026-07-25T08:00:00Z",
            "decision_clock": {"expected_decision_date": "20260725", "cutoff_policy": "before_decision_open_et", "pit_enforced": True},
            "fetch_contract": {
                "producer_kind": "grok_native_x_fetch", "execution_mode": "offline_fake_client",
                "network_access_performed": False, "provider_calls_performed": False,
                "network_call_count": 0, "provider_call_count": 0,
                "scoring_eligible": False, "top15_effect_enabled": True,   # must be const false
                "operation_advice_effect_enabled": False, "dynamic_seats_enabled": False,
                "theme_probe_enabled": False, "lifecycle_actions_enabled": False,
            },
            "queries": ["q"], "source_refs": [], "discovery_artifact_sha256": "a" * 64,
            "drop_ledger": [], "raw_receipts_written": False,
            "summary": {"query_count": 1, "accepted_source_count": 0, "validated_theme_count": 0,
                        "validated_member_count": 0, "dropped_result_count": 0},
        }
        with self.assertRaises(xfetch.XThemeDiscoveryError):
            xfetch._validate_schema(receipt)

    def test_receipt_schema_guard_is_not_optional(self):
        with mock.patch.object(xfetch, "_validate_schema", side_effect=xfetch.XThemeDiscoveryError("forced schema failure")):
            with self.assertRaises(xfetch.XThemeDiscoveryError):
                xfetch.build_x_fetch_packet(
                    queries=["power"], results=[], grok_response='{"themes":[]}',
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
