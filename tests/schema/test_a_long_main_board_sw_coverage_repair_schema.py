from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from runners import a_long_main_board_sw_coverage_repair as runner
from tests.test_a_long_main_board_sw_coverage_repair import FakePassingRepairPro


SCHEMA_PATH = Path("schemas/a_long_main_board_sw_coverage_repair_execution_summary.schema.json")
SUMMARY_PATH = Path("docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json")


class ALongMainBoardSwCoverageRepairSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def _write_raw(self, root: Path, name: str, records: list[dict]) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8")

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
            [{"ts_code": symbol, "list_date": "19910403", "delist_date": ""} for symbol in covered_active]
            + [{"ts_code": "000004.SZ", "list_date": "19910114", "delist_date": ""}],
        )
        self._write_raw(
            root,
            "stock_basic_delisted_D.json",
            [{"ts_code": "000666.SZ", "list_date": "19961210", "delist_date": "20231026"}],
        )
        self._write_raw(
            root,
            "index_member_all_sw_membership.json",
            [
                {
                    "ts_code": symbol,
                    "l1_code": "801000.SI",
                    "l2_code": "801010.SI",
                    "in_date": "20180101",
                    "out_date": "",
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

    def _fake_summary(self) -> dict:
        source_root = self._source_root()
        raw_root = runner.RAW_ROOT / "schema_unit_test"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                return runner.execute_repair(
                    pro_factory=lambda: FakePassingRepairPro(),
                    raw_root=raw_root,
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
            shutil.rmtree(raw_root, ignore_errors=True)

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()
        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "a_long_main_board_sw_coverage_repair_execution_summary")
        self.assertIn("never authorizes signal search", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_fake_summary_validates_when_jsonschema_available(self) -> None:
        summary = self._fake_summary()
        self.assertEqual(self._validate(summary), [])
        self.assertIn("active_delisting_shell_boundary", summary)

    def test_actual_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            raise unittest.SkipTest("actual repair summary has not been generated")
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self._validate(summary), [])
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])
        self.assertFalse(summary["prohibited_claims"]["a_long_alpha_found"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._fake_summary())
        invalid["scope"]["signal_search_executed"] = True
        invalid["decision"]["data_can_be_used_for_alpha_now"] = True
        invalid["decision"]["signal_search_authorized_by_this_summary"] = True
        invalid["prohibited_claims"]["a_long_alpha_found"] = True
        invalid["active_delisting_shell_boundary"]["manual_industry_assignment_allowed"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
