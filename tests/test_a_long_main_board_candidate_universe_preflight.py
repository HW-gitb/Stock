from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import a_long_main_board_candidate_universe_preflight as runner


class FakeBlockedProbePro:
    def index_member_all(self, **kwargs):
        return []

    def stock_basic(self, **kwargs):
        return []


class FakePassingProbePro:
    def index_member_all(self, **kwargs):
        if kwargs.get("ts_code"):
            return [
                {
                    "ts_code": kwargs["ts_code"],
                    "name": "fixture",
                    "l1_code": "801000.SI",
                    "l1_name": "fixture L1",
                    "l2_code": "801010.SI",
                    "l2_name": "fixture L2",
                    "in_date": "20180101",
                    "out_date": "",
                    "is_new": "Y",
                }
            ]
        return [
            {
                "ts_code": "000001.SZ",
                "name": "fixture",
                "l1_code": "801000.SI",
                "l1_name": "fixture L1",
                "l2_code": "801010.SI",
                "l2_name": "fixture L2",
                "in_date": "20180101",
                "out_date": "",
                "is_new": "Y",
            }
        ]

    def stock_basic(self, **kwargs):
        return [
            {"ts_code": "000001.SZ", "name": "Ping An Bank", "industry": "bank", "area": "Shenzhen"},
            {"ts_code": "000004.SZ", "name": "Fixture", "industry": "software", "area": "Shenzhen"},
        ]


class ALongMainBoardCandidateUniversePreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = runner.RAW_ROOT / "unit_test"
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def _write_raw(self, root: Path, name: str, records: list[dict]) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(
            json.dumps({"call_status": "success", "records": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _source_root(self, *, missing_active: bool = True, include_delisted: bool = True) -> Path:
        root = Path(tempfile.mkdtemp())
        active = [
            {"ts_code": "000001.SZ", "name": "Ping An Bank", "list_date": "19910403", "delist_date": ""},
            {"ts_code": "000004.SZ", "name": "Fixture", "list_date": "19910114", "delist_date": ""},
            {"ts_code": "300750.SZ", "name": "ChiNext", "list_date": "20180611", "delist_date": ""},
        ]
        delisted = []
        if include_delisted:
            delisted.append(
                {"ts_code": "000666.SZ", "name": "Delisted", "list_date": "19961210", "delist_date": "20231026"}
            )
        membership = [
            {
                "ts_code": "000001.SZ",
                "name": "Ping An Bank",
                "l1_code": "801000.SI",
                "l1_name": "fixture L1",
                "l2_code": "801010.SI",
                "l2_name": "fixture L2",
                "in_date": "20180101",
                "out_date": "",
                "is_new": "Y",
            }
        ]
        if not missing_active:
            membership.append(
                {
                    "ts_code": "000004.SZ",
                    "name": "Fixture",
                    "l1_code": "801000.SI",
                    "l1_name": "fixture L1",
                    "l2_code": "801010.SI",
                    "l2_name": "fixture L2",
                    "in_date": "20180101",
                    "out_date": "",
                    "is_new": "Y",
                }
            )
        if include_delisted:
            membership.append(
                {
                    "ts_code": "000666.SZ",
                    "name": "Delisted",
                    "l1_code": "801000.SI",
                    "l1_name": "fixture L1",
                    "l2_code": "801010.SI",
                    "l2_name": "fixture L2",
                    "in_date": "20180101",
                    "out_date": "20231026",
                    "is_new": "N",
                }
            )
        self._write_raw(root, "stock_basic_active_L.json", active)
        self._write_raw(root, "stock_basic_delisted_D.json", delisted)
        self._write_raw(root, "index_member_all_sw_membership.json", membership)
        return root

    def test_missing_sw_membership_blocks_full_alpha_and_writes_gitignored_raw(self) -> None:
        source_root = self._source_root(missing_active=True, include_delisted=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = runner.execute_preflight(
                    pro_factory=lambda: FakeBlockedProbePro(),
                    raw_root=self.raw_root,
                    source_raw_root=source_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

        self.assertEqual(
            summary["decision"]["preflight_status"],
            "blocked_sw_industry_coverage_for_full_universe_signal_search",
        )
        self.assertFalse(summary["decision"]["candidate_universe_ready_for_signal_search"])
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(summary["scope"]["signal_search_executed"])
        self.assertEqual(summary["candidate_universe"]["main_board_active_count"], 2)
        self.assertEqual(summary["candidate_universe"]["active_missing_sw_membership_count"], 1)
        self.assertFalse(summary["probe_interpretation"]["active_ts_code_filter_can_supplement_missing_sw"])
        self.assertFalse(self._contains_key(summary, "records"))
        for result in summary["endpoint_results"]:
            raw_ref = Path(result["raw_payload_ref"])
            self.assertTrue(raw_ref.as_posix().startswith("data/a_long/raw/tushare/main_board_candidate_universe_preflight_20260604/"))
            self.assertTrue((runner.ROOT / raw_ref).exists())

    def test_pass_candidate_universe_does_not_claim_alpha(self) -> None:
        source_root = self._source_root(missing_active=False, include_delisted=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = runner.execute_preflight(
                    pro_factory=lambda: FakePassingProbePro(),
                    raw_root=self.raw_root,
                    source_raw_root=source_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

        self.assertEqual(summary["decision"]["preflight_status"], "candidate_universe_preflight_passed")
        self.assertTrue(summary["decision"]["candidate_universe_ready_for_signal_search"])
        self.assertTrue(summary["probe_interpretation"]["active_ts_code_filter_can_supplement_missing_sw"])
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])
        self.assertFalse(summary["prohibited_claims"]["a_long_alpha_found"])

    def test_missing_token_records_no_network_execution(self) -> None:
        source_root = self._source_root(missing_active=True, include_delisted=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch.dict(os.environ, {}, clear=True):
                    summary = runner.execute_preflight(
                        raw_root=self.raw_root,
                        source_raw_root=source_root,
                        summary_path=Path(tmp) / "summary.json",
                        generated_at="2026-06-04T00:00:00+00:00",
                        confirm_independent_review_pass=True,
                        confirm_post_review_execute=True,
                    )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

        if summary["execution"]["environment_precheck_passed"]:
            raise unittest.SkipTest("TUSHARE_TOKEN is present in this test environment")
        self.assertEqual(summary["decision"]["preflight_status"], "not_executed_environment_missing")
        self.assertEqual(summary["endpoint_results"], [])
        self.assertFalse(summary["execution"]["network_call_attempted"])

    def test_live_execution_requires_double_confirmation(self) -> None:
        source_root = self._source_root(missing_active=True, include_delisted=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(RuntimeError):
                    runner.execute_preflight(
                        pro_factory=lambda: FakeBlockedProbePro(),
                        raw_root=self.raw_root,
                        source_raw_root=source_root,
                        summary_path=Path(tmp) / "summary.json",
                        generated_at="2026-06-04T00:00:00+00:00",
                    )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

    def test_raw_root_must_stay_under_preflight_root(self) -> None:
        source_root = self._source_root(missing_active=True, include_delisted=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    runner.execute_preflight(
                        pro_factory=lambda: FakeBlockedProbePro(),
                        raw_root=Path(tmp) / "raw",
                        source_raw_root=source_root,
                        summary_path=Path(tmp) / "summary.json",
                        generated_at="2026-06-04T00:00:00+00:00",
                        confirm_independent_review_pass=True,
                        confirm_post_review_execute=True,
                    )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

    def _contains_key(self, payload, needle: str) -> bool:
        if isinstance(payload, dict):
            return any(key == needle or self._contains_key(value, needle) for key, value in payload.items())
        if isinstance(payload, list):
            return any(self._contains_key(item, needle) for item in payload)
        return False


if __name__ == "__main__":
    unittest.main()
