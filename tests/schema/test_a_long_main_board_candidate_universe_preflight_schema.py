from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from runners import a_long_main_board_candidate_universe_preflight as runner
from tests.test_a_long_main_board_candidate_universe_preflight import FakeBlockedProbePro


SCHEMA_PATH = Path("schemas/a_long_main_board_candidate_universe_preflight_execution_summary.schema.json")
SUMMARY_PATH = Path("docs/a_long_main_board_candidate_universe_preflight_execution_summary_20260604.json")


class ALongMainBoardCandidateUniversePreflightSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def _source_root(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "stock_basic_active_L.json").write_text(
            json.dumps(
                {
                    "records": [
                        {"ts_code": "000001.SZ", "list_date": "19910403", "delist_date": ""},
                        {"ts_code": "000004.SZ", "list_date": "19910114", "delist_date": ""},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (root / "stock_basic_delisted_D.json").write_text(
            json.dumps({"records": [{"ts_code": "000666.SZ", "list_date": "19961210", "delist_date": "20231026"}]}),
            encoding="utf-8",
        )
        (root / "index_member_all_sw_membership.json").write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "ts_code": "000001.SZ",
                            "l1_code": "801000.SI",
                            "l2_code": "801010.SI",
                            "in_date": "20180101",
                            "out_date": "",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return root

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "a_long_main_board_candidate_universe_preflight_execution_summary",
        )
        self.assertIn("Raw probe payloads must stay gitignored", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_fake_summary_validates_when_jsonschema_available(self) -> None:
        source_root = self._source_root()
        raw_root = runner.RAW_ROOT / "schema_unit_test"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = runner.execute_preflight(
                    pro_factory=lambda: FakeBlockedProbePro(),
                    source_raw_root=source_root,
                    raw_root=raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )
            self.assertEqual(self._validate(summary), [])
        finally:
            shutil.rmtree(source_root, ignore_errors=True)
            shutil.rmtree(raw_root, ignore_errors=True)

    def test_actual_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            raise unittest.SkipTest("actual preflight summary has not been generated")
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self._validate(summary), [])
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])
        self.assertFalse(summary["prohibited_claims"]["a_long_alpha_found"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        source_root = self._source_root()
        raw_root = runner.RAW_ROOT / "schema_scope_unit_test"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = runner.execute_preflight(
                    pro_factory=lambda: FakeBlockedProbePro(),
                    source_raw_root=source_root,
                    raw_root=raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )
        finally:
            shutil.rmtree(source_root, ignore_errors=True)
            shutil.rmtree(raw_root, ignore_errors=True)

        invalid = copy.deepcopy(summary)
        invalid["scope"]["signal_search_executed"] = True
        invalid["decision"]["data_can_be_used_for_alpha_now"] = True
        invalid["decision"]["signal_search_authorized_by_this_summary"] = True
        invalid["prohibited_claims"]["a_long_alpha_found"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
