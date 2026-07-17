from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runners.a_short_rule6_report_rc_coverage_audit import run_audit
from tests.test_a_short_rule6_report_rc_coverage_audit import _FakePro, _analysis_input


class Rule6ReportRcCoverageAuditSummarySchemaTests(unittest.TestCase):
    def test_schema_accepts_only_the_nonwired_audit_summary(self):
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(Path("schemas/a_short_rule6_report_rc_coverage_audit_summary.schema.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_audit(_FakePro(), _analysis_input(), Path(tmp) / "provider_samples/a_short_rule6_report_rc_coverage_audit_20260714")
        summary["candidate_pool"]["analysis_input_reference"] = "result/a_short/20260714/analysis_input.json"
        summary["candidate_pool"]["analysis_input_sha256"] = "a" * 64
        self.assertEqual(list(Draft7Validator(schema).iter_errors(summary)), [])
        summary["decision"]["downstream_rule6_wiring_authorized"] = True
        self.assertNotEqual(list(Draft7Validator(schema).iter_errors(summary)), [])


if __name__ == "__main__":
    unittest.main()
