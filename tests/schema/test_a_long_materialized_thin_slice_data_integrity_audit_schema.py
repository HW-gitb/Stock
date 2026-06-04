from __future__ import annotations

import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path

from runners import a_long_materialized_thin_slice_data_integrity_audit as runner
import tests.test_a_long_materialized_thin_slice_data_integrity_audit as audit_fixture


SCHEMA_PATH = Path("schemas/a_long_materialized_thin_slice_data_integrity_audit_report.schema.json")
REPORT_PATH = Path("research/results/a_long_materialized_thin_slice_data_integrity_audit_20260604/audit_report.json")


class ALongMaterializedThinSliceDataIntegrityAuditSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def _build_valid_report(self) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fixture = audit_fixture.ALongMaterializedThinSliceDataIntegrityAuditTest()
            summary_path, raw_root = fixture.build_fixture(tmp_path)
            return runner.run(
                argparse.Namespace(
                    materialization_summary=summary_path,
                    raw_root=raw_root,
                    output_dir=tmp_path / "out",
                    generated_at="2026-06-04T00:00:00Z",
                )
            )

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "a_long_materialized_thin_slice_data_integrity_audit_report",
        )
        self.assertIn("not alpha readiness", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_minimal_runner_report_validates_when_jsonschema_available(self) -> None:
        report = self._build_valid_report()

        self.assertEqual(self._validate(report), [])
        self.assertEqual(report["decision"]["audit_status"], "passed_thin_slice_data_integrity_not_alpha_ready")
        self.assertFalse(report["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(report["decision"]["signal_search_authorized_by_this_report"])

    def test_generated_report_validates_when_present(self) -> None:
        if not REPORT_PATH.exists():
            raise unittest.SkipTest("materialized thin-slice audit report has not been generated yet")

        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self._validate(report), [])
        report_text = REPORT_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"records"', report_text)
        self.assertNotIn("TUSHARE_TOKEN", report_text)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._build_valid_report())
        invalid["scope"]["provider_call_executed"] = True
        invalid["scope"]["raw_rows_in_tracked_report"] = True
        invalid["scope"]["signal_search_executed"] = True
        invalid["decision"]["data_can_be_used_for_alpha_now"] = True
        invalid["decision"]["signal_search_authorized_by_this_report"] = True
        invalid["prohibited_claims"]["a_long_alpha_found"] = True
        invalid["prohibited_claims"]["production_ready"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_self_test_checker_origin_is_required(self) -> None:
        invalid = copy.deepcopy(self._build_valid_report())
        del invalid["required_runner_self_tests"][0]["checker_origin"]

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
