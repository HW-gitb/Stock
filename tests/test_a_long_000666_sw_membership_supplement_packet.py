from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import a_long_000666_sw_membership_supplement_packet as runner


class FakeFoundMembershipPro:
    def stock_basic(self, **kwargs):
        return [
            {
                "ts_code": "000666.SZ",
                "symbol": "000666",
                "name": "Jingwei Textile",
                "exchange": "SZSE",
                "market": "Main",
                "list_status": "D",
                "list_date": "19961210",
                "delist_date": "20231026",
            }
        ]

    def index_member(self, **kwargs):
        return [
            {
                "index_code": "801000.SI",
                "con_code": "000666.SZ",
                "in_date": "20100101",
                "out_date": "20231026",
                "is_new": "N",
            }
        ]

    def index_member_all(self, **kwargs):
        return []


class FakeNoMembershipPro(FakeFoundMembershipPro):
    def index_member(self, **kwargs):
        return []


class FakeErrorMembershipPro(FakeFoundMembershipPro):
    def index_member(self, **kwargs):
        raise RuntimeError("fixture failure token=TOKEN_FIXTURE_VALUE")


class ALong000666SwMembershipSupplementPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = runner.RAW_ROOT / "unit_test"
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def test_fake_client_writes_candidate_summary_and_gitignored_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"

            summary = runner.execute_supplement(
                pro_factory=lambda: FakeFoundMembershipPro(),
                raw_root=self.raw_root,
                summary_path=summary_path,
                generated_at="2026-06-04T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

        self.assertEqual(summary["decision"]["supplement_status"], "candidate_sw_membership_source_found")
        self.assertTrue(summary["decision"]["candidate_sw_membership_source_found"])
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(summary["decision"]["audit_rerun_authorized_by_this_summary"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])
        self.assertEqual(summary["execution"]["actual_call_count"], 3)
        self.assertTrue(summary["execution"]["network_call_attempted"])
        self.assertFalse(self._contains_key(summary, "records"))

        membership = [item for item in summary["endpoint_results"] if item["call_id"] == "index_member_000666_ts_code_filter"][0]
        self.assertEqual(membership["target_match_count"], 1)
        self.assertEqual(membership["required_fields_missing"], [])
        for result in summary["endpoint_results"]:
            raw_ref = Path(result["raw_payload_ref"])
            self.assertTrue(raw_ref.as_posix().startswith("data/a_long/raw/tushare/000666_sw_membership_supplement_20260604/"))
            self.assertTrue((runner.ROOT / raw_ref).exists())

    def test_no_candidate_keeps_alpha_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = runner.execute_supplement(
                pro_factory=lambda: FakeNoMembershipPro(),
                raw_root=self.raw_root,
                summary_path=Path(tmp) / "summary.json",
                generated_at="2026-06-04T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

        self.assertEqual(summary["decision"]["supplement_status"], "no_candidate_sw_membership_source_found")
        self.assertFalse(summary["decision"]["candidate_sw_membership_source_found"])
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])

    def test_error_result_is_redacted_and_keeps_alpha_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "TOKEN_FIXTURE_VALUE"}):
                summary = runner.execute_supplement(
                    pro_factory=lambda: FakeErrorMembershipPro(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

        result = [item for item in summary["endpoint_results"] if item["call_id"] == "index_member_000666_ts_code_filter"][0]
        self.assertEqual(summary["decision"]["supplement_status"], "partial_or_failed_supplement_probe")
        self.assertEqual(result["call_status"], "error")
        self.assertNotIn("TOKEN_FIXTURE_VALUE", result["error_message_redacted"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])

    def test_live_execution_requires_review_and_execute_confirmations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                runner.execute_supplement(
                    pro_factory=lambda: FakeFoundMembershipPro(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                )

    def test_missing_token_records_no_execution_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True):
                summary = runner.execute_supplement(
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

        self.assertEqual(summary["decision"]["supplement_status"], "not_executed_environment_missing")
        self.assertFalse(summary["scope"]["provider_call_executed"])
        self.assertFalse(summary["execution"]["network_call_attempted"])
        self.assertEqual(summary["execution"]["actual_call_count"], 0)
        self.assertEqual(summary["endpoint_results"], [])

    def test_dry_run_with_token_does_not_claim_no_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "TOKEN_FIXTURE_VALUE"}):
                summary = runner.execute_supplement(
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    dry_run_env=True,
                )

        self.assertEqual(summary["decision"]["supplement_status"], "dry_run_environment_ready")
        self.assertFalse(summary["execution"]["network_call_attempted"])
        self.assertEqual(summary["endpoint_results"], [])

    def test_raw_root_must_stay_under_gitignored_supplement_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                runner.execute_supplement(
                    pro_factory=lambda: FakeFoundMembershipPro(),
                    raw_root=Path(tmp) / "raw",
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

    def test_packet_loader_rejects_scope_creep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = runner.read_json(runner.PACKET_PATH)
            packet["scope"]["signal_search_allowed"] = True
            packet["target"]["symbol"] = "600519.SH"
            packet["call_budget"]["planned_total_endpoint_calls"] = 4
            packet["prohibited_claims"]["a_long_alpha_found"] = True
            packet_path = Path(tmp) / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")

            with self.assertRaises(ValueError):
                runner.load_and_validate_packet(packet_path)

    def test_call_plan_is_fixed_to_000666_and_three_endpoint_families(self) -> None:
        calls = runner.supplement_call_plan()

        self.assertEqual(len(calls), 3)
        self.assertEqual([call["api_family"] for call in calls], ["stock_basic", "index_member", "index_member_all"])
        self.assertEqual(calls[0]["kwargs"]["list_status"], "D")
        self.assertEqual(calls[1]["kwargs"]["ts_code"], "000666.SZ")
        self.assertEqual(calls[2]["kwargs"]["ts_code"], "000666.SZ")
        self.assertTrue(all(call["component_id"] in {"delisted_symbol_context", "sw_membership_candidate"} for call in calls))

    def _contains_key(self, payload, needle: str) -> bool:
        if isinstance(payload, dict):
            return any(key == needle or self._contains_key(value, needle) for key, value in payload.items())
        if isinstance(payload, list):
            return any(self._contains_key(item, needle) for item in payload)
        return False


if __name__ == "__main__":
    unittest.main()
