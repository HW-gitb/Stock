from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from runners import a_long_main_board_sw_coverage_repair as runner


class FakePassingRepairPro:
    def index_member_all(self, **kwargs):
        symbol = kwargs.get("ts_code")
        if symbol == "000004.SZ":
            return [
                {
                    "ts_code": symbol,
                    "name": "fixture active",
                    "l1_code": "801000.SI",
                    "l1_name": "fixture L1",
                    "l2_code": "801010.SI",
                    "l2_name": "fixture L2",
                    "in_date": "20180101",
                    "out_date": "",
                    "is_new": "Y",
                }
            ]
        return []

    def stock_basic(self, **kwargs):
        return [
            {
                "ts_code": "000666.SZ",
                "symbol": "000666",
                "name": "fixture delisted",
                "list_status": "D",
                "list_date": "19961210",
                "delist_date": "20231026",
                "industry": "",
                "area": "",
            }
        ]


class FakeBlockedRepairPro(FakePassingRepairPro):
    def index_member_all(self, **kwargs):
        return []


class ALongMainBoardSwCoverageRepairTest(unittest.TestCase):
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

    def _source_root(self) -> Path:
        root = Path(tempfile.mkdtemp())
        covered_active = [
            "000001.SZ",
            "000002.SZ",
            "600000.SH",
            "600001.SH",
            "600002.SH",
            "600003.SH",
            "600004.SH",
            "600005.SH",
        ]
        self._write_raw(
            root,
            "stock_basic_active_L.json",
            [{"ts_code": symbol, "name": "has SW", "list_date": "19910403", "delist_date": ""} for symbol in covered_active]
            + [
                {"ts_code": "000004.SZ", "name": "missing SW", "list_date": "19910114", "delist_date": ""},
                {"ts_code": "300750.SZ", "name": "ChiNext", "list_date": "20180611", "delist_date": ""},
            ],
        )
        self._write_raw(
            root,
            "stock_basic_delisted_D.json",
            [{"ts_code": "000666.SZ", "name": "delisted", "list_date": "19961210", "delist_date": "20231026"}],
        )
        self._write_raw(
            root,
            "index_member_all_sw_membership.json",
            [
                {
                    "ts_code": symbol,
                    "name": "has SW",
                    "l1_code": "801000.SI",
                    "l1_name": "fixture L1",
                    "l2_code": "801010.SI",
                    "l2_name": "fixture L2",
                    "in_date": "20180101",
                    "out_date": "",
                    "is_new": "Y",
                }
                for symbol in covered_active
            ],
        )
        return root

    def _source_root_with_delisting_shell_gap(self) -> Path:
        root = Path(tempfile.mkdtemp())
        covered_active = [
            "000001.SZ",
            "000002.SZ",
            "600000.SH",
            "600001.SH",
            "600002.SH",
            "600003.SH",
            "600004.SH",
            "600005.SH",
        ]
        self._write_raw(
            root,
            "stock_basic_active_L.json",
            [{"ts_code": symbol, "name": "has SW", "list_date": "19910403", "delist_date": ""} for symbol in covered_active]
            + [
                {
                    "ts_code": "600421.SH",
                    "name": "\u9000\u5e02\u534e\u5d58",
                    "list_status": "L",
                    "list_date": "20040607",
                    "delist_date": "",
                }
            ],
        )
        self._write_raw(
            root,
            "stock_basic_delisted_D.json",
            [{"ts_code": "000666.SZ", "name": "delisted", "list_date": "19961210", "delist_date": "20231026"}],
        )
        self._write_raw(
            root,
            "index_member_all_sw_membership.json",
            [
                {
                    "ts_code": symbol,
                    "name": "has SW",
                    "l1_code": "801000.SI",
                    "l1_name": "fixture L1",
                    "l2_code": "801010.SI",
                    "l2_name": "fixture L2",
                    "in_date": "20180101",
                    "out_date": "",
                    "is_new": "Y",
                }
                for symbol in covered_active
            ],
        )
        return root

    def _preflight_summary(self, path: Path) -> Path:
        payload = {
            "schema_name": "a_long_main_board_candidate_universe_preflight_execution_summary",
            "decision": {
                "preflight_status": "blocked_sw_industry_coverage_for_full_universe_signal_search",
                "signal_search_authorized_by_this_summary": False,
            },
            "probe_interpretation": {"active_ts_code_filter_can_supplement_missing_sw": True},
            "candidate_universe": {
                "active_missing_sw_membership_count": 1,
                "delisted_missing_sw_membership_count": 2,
            },
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_repair_passes_when_active_supplement_succeeds_and_delisted_boundary_has_evidence(self) -> None:
        source_root = self._source_root()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = runner.execute_repair(
                    pro_factory=lambda: FakePassingRepairPro(),
                    raw_root=self.raw_root,
                    source_raw_root=source_root,
                    preflight_summary_path=self._preflight_summary(Path(tmp) / "preflight.json"),
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    sleep_seconds=0,
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

        self.assertEqual(summary["decision"]["repair_status"], "passed_candidate_universe_sw_coverage_repair")
        self.assertTrue(summary["decision"]["candidate_universe_ready_for_next_full_alpha_package"])
        self.assertEqual(summary["active_sw_supplement"]["unresolved_count"], 0)
        self.assertEqual(summary["active_delisting_shell_boundary"]["detected_count"], 0)
        self.assertEqual(summary["delisted_no_industry_boundary"]["no_usable_sw_source_evidence_count"], 1)
        self.assertTrue(summary["delisted_no_industry_boundary"]["threshold_passed"])
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])
        self.assertFalse(summary["prohibited_claims"]["a_long_alpha_found"])
        self.assertFalse(self._contains_key(summary, "records"))
        for item in summary["active_sw_supplement"]["symbol_results"]:
            self.assertTrue((runner.ROOT / item["raw_payload_ref"]).exists())
        for item in summary["delisted_no_industry_boundary"]["symbol_results"]:
            self.assertTrue((runner.ROOT / item["raw_payload_ref"]).exists())

    def test_active_unresolved_keeps_alpha_blocked(self) -> None:
        source_root = self._source_root()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = runner.execute_repair(
                    pro_factory=lambda: FakeBlockedRepairPro(),
                    raw_root=self.raw_root,
                    source_raw_root=source_root,
                    preflight_summary_path=self._preflight_summary(Path(tmp) / "preflight.json"),
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    sleep_seconds=0,
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

        self.assertEqual(summary["decision"]["repair_status"], "active_supplement_or_delisted_boundary_incomplete")
        self.assertFalse(summary["decision"]["candidate_universe_ready_for_next_full_alpha_package"])
        self.assertEqual(summary["active_sw_supplement"]["unresolved_symbols"], ["000004.SZ"])
        self.assertEqual(summary["active_delisting_shell_boundary"]["active_investable_unresolved_symbols"], ["000004.SZ"])
        self.assertFalse(summary["candidate_universe_after"]["candidate_universe_industry_gate_passed"])

    def test_delisting_shell_keeps_gate_blocked_without_scaled_boundary_approval(self) -> None:
        source_root = self._source_root_with_delisting_shell_gap()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = runner.execute_repair(
                    pro_factory=lambda: FakeBlockedRepairPro(),
                    raw_root=self.raw_root,
                    source_raw_root=source_root,
                    preflight_summary_path=self._preflight_summary(Path(tmp) / "preflight.json"),
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-05T00:00:00+00:00",
                    sleep_seconds=0,
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

        self.assertEqual(
            summary["decision"]["repair_status"],
            "active_delisting_shell_boundary_pending_approval",
        )
        self.assertFalse(summary["decision"]["candidate_universe_ready_for_next_full_alpha_package"])
        self.assertEqual(summary["active_sw_supplement"]["unresolved_symbols"], ["600421.SH"])
        self.assertEqual(summary["active_delisting_shell_boundary"]["detected_symbols"], ["600421.SH"])
        self.assertEqual(summary["active_delisting_shell_boundary"]["active_investable_unresolved_count"], 0)
        self.assertEqual(summary["active_delisting_shell_boundary"]["pending_scaled_delisted_no_source_count_if_approved"], 2)
        self.assertFalse(summary["active_delisting_shell_boundary"]["manual_industry_assignment_allowed"])
        self.assertEqual(summary["candidate_universe_after"]["active_missing_sw_membership_count"], 1)
        self.assertEqual(summary["candidate_universe_after"]["active_delisting_shell_count"], 1)
        self.assertEqual(summary["candidate_universe_after"]["active_investable_unresolved_count"], 0)
        self.assertFalse(summary["candidate_universe_after"]["candidate_universe_industry_gate_passed"])
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(summary["prohibited_claims"]["a_long_alpha_found"])

    def test_live_execution_requires_double_confirmation(self) -> None:
        source_root = self._source_root()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(RuntimeError):
                    runner.execute_repair(
                        pro_factory=lambda: FakePassingRepairPro(),
                        raw_root=self.raw_root,
                        source_raw_root=source_root,
                        preflight_summary_path=self._preflight_summary(Path(tmp) / "preflight.json"),
                        summary_path=Path(tmp) / "summary.json",
                        generated_at="2026-06-04T00:00:00+00:00",
                        sleep_seconds=0,
                    )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

    def test_raw_root_must_stay_under_repair_root(self) -> None:
        source_root = self._source_root()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    runner.execute_repair(
                        pro_factory=lambda: FakePassingRepairPro(),
                        raw_root=Path(tmp) / "raw",
                        source_raw_root=source_root,
                        preflight_summary_path=self._preflight_summary(Path(tmp) / "preflight.json"),
                        summary_path=Path(tmp) / "summary.json",
                        generated_at="2026-06-04T00:00:00+00:00",
                        sleep_seconds=0,
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
