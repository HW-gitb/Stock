from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import a_long_full_main_board_materialization_packet as runner


class ALongFullMainBoardMaterializationPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = runner.RAW_ROOT / "unit_test"
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def test_call_plan_matches_reviewed_budget_formula(self) -> None:
        self.assertEqual(len(runner.base_call_plan()), 8)
        self.assertEqual(len(runner.symbol_call_plan(["000001.SZ"])), 7)
        self.assertEqual(len(runner.symbol_call_plan(["000001.SZ", "600001.SH"])), 14)
        self.assertEqual(runner.planned_total_call_count(3387), 23717)
        self.assertEqual(runner.planned_total_call_count(runner.EXPECTED_UNIVERSE_COUNT), runner.PLANNED_TOTAL_ENDPOINT_CALLS)

    def test_candidate_universe_helper_filters_main_board_and_delisted_window(self) -> None:
        active_records = [
            {"ts_code": "000001.SZ", "list_status": "L"},
            {"ts_code": "600001.SH", "list_status": "L"},
            {"ts_code": "300001.SZ", "list_status": "L"},
            {"ts_code": "688001.SH", "list_status": "L"},
        ]
        delisted_records = [
            {"ts_code": "000666.SZ", "list_date": "19961218", "delist_date": "20231026"},
            {"ts_code": "600001.SH", "list_date": "20000101", "delist_date": "20170101"},
            {"ts_code": "300002.SZ", "list_date": "20100101", "delist_date": "20220101"},
        ]

        universe = runner.build_candidate_universe_from_records(active_records, delisted_records)

        self.assertEqual(universe["main_board_active_count"], 2)
        self.assertEqual(universe["main_board_delisted_2018_2025_count"], 1)
        self.assertEqual(universe["candidate_universe_count"], 3)
        self.assertEqual(universe["symbols_for_materialization"], ["000001.SZ", "600001.SH", "000666.SZ"])
        self.assertFalse(universe["matches_reviewed_execution_packet"])

    def test_dry_run_missing_token_writes_no_network_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            with mock.patch.dict(os.environ, {}, clear=True):
                summary = runner.execute_full_main_board_materialization(
                    raw_root=self.raw_root,
                    summary_path=summary_path,
                    generated_at="2026-06-05T00:00:00+00:00",
                    dry_run_env=True,
                )

            self.assertEqual(summary["decision"]["materialization_status"], "not_executed_environment_missing")
            self.assertFalse(summary["scope"]["provider_call_executed"])
            self.assertFalse(summary["execution"]["network_call_attempted"])
            self.assertFalse(summary["endpoint_manifest"]["tracked_summary_embeds_endpoint_results"])
            self.assertIsNone(summary["endpoint_manifest"]["manifest_ref"])
            self.assertEqual(summary["table_rollup"][0]["status"], "not_tested")
            self.assertFalse(self._contains_key(summary, "records"))
            self.assertFalse(self._contains_key(summary, "endpoint_results"))
            self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8")), summary)

    def test_dry_run_ready_summary_validates_when_token_present(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            with mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "unit-test-token"}, clear=True):
                summary = runner.execute_full_main_board_materialization(
                    raw_root=self.raw_root,
                    summary_path=summary_path,
                    generated_at="2026-06-05T00:00:00+00:00",
                    dry_run_env=True,
                )

        schema = json.loads(Path("schemas/a_long_full_main_board_materialization_execution_summary.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft7Validator(schema).iter_errors(summary)), [])
        self.assertEqual(summary["decision"]["materialization_status"], "dry_run_environment_ready")
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])

    def test_live_execution_requires_review_and_execute_confirmations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                runner.execute_full_main_board_materialization(
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-05T00:00:00+00:00",
                )

    def test_raw_root_must_stay_under_approved_gitignored_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                runner.execute_full_main_board_materialization(
                    raw_root=Path(tmp) / "raw",
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-05T00:00:00+00:00",
                    dry_run_env=True,
                )

    def test_packet_loader_rejects_scope_creep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = copy.deepcopy(runner.read_json(runner.PACKET_PATH))
            packet["scope"]["production_use_allowed"] = True
            packet["data_pull_plan"]["retry_count_allowed"] = 1
            packet["execution_boundary"]["manual_industry_fill_allowed"] = True
            packet["prohibited_claims"]["a_long_alpha_found"] = True
            packet_path = Path(tmp) / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")

            with self.assertRaises(ValueError):
                runner.load_and_validate_packet(packet_path)

    def test_schema_rejects_summary_scope_creep_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            with mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "unit-test-token"}, clear=True):
                summary = runner.execute_full_main_board_materialization(
                    raw_root=self.raw_root,
                    summary_path=summary_path,
                    generated_at="2026-06-05T00:00:00+00:00",
                    dry_run_env=True,
                )
        invalid = copy.deepcopy(summary)
        invalid["scope"]["signal_search_executed"] = True
        invalid["decision"]["data_can_be_used_for_alpha_now"] = True
        invalid["prohibited_claims"]["ship_gate_evidence"] = True

        schema = json.loads(Path("schemas/a_long_full_main_board_materialization_execution_summary.schema.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(list(Draft7Validator(schema).iter_errors(invalid))), 3)

    def _contains_key(self, payload, needle: str) -> bool:
        if isinstance(payload, dict):
            return any(key == needle or self._contains_key(value, needle) for key, value in payload.items())
        if isinstance(payload, list):
            return any(self._contains_key(item, needle) for item in payload)
        return False


if __name__ == "__main__":
    unittest.main()
