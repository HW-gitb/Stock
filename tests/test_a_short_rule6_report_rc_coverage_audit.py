from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from engine.data.analysis_input_contract import candidate_digest
from runners.a_short_rule6_report_rc_coverage_audit import RAW_ROOT, run_audit


def _analysis_input() -> dict:
    candidates = [{"ts_code": "600519.SH"}, {"ts_code": "000001.SZ"}]
    return {"trade_date": "20260714", "candidates": candidates, "source": {"run_identity": {"candidate_digest": candidate_digest(candidates)}}}


class _FakePro:
    def __init__(self):
        self.calls: list[dict[str, str]] = []

    def report_rc(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["ts_code"] == "000001.SZ":
            raise Exception("抱歉，您没有权限访问该接口")
        return pd.DataFrame(
            {
                "ts_code": [kwargs["ts_code"], kwargs["ts_code"], kwargs["ts_code"]],
                "report_date": ["20260701", "20260701", "20260715"],
                "org_name": ["Firm A", "Firm A", "Firm B"],
                "author_name": ["A", "A", "B"],
                "report_title": ["raw-row-only", "raw-row-only", "future-row"],
                "quarter": ["2026Q2", "2026Q2", "2026Q2"],
            }
        )


class Rule6ReportRcCoverageAuditTests(unittest.TestCase):
    def test_audit_is_aggregate_only_and_cannot_authorize_rule6_wiring(self):
        pro = _FakePro()
        sleeps: list[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            raw_root = Path(tmp) / "provider_samples/a_short_rule6_report_rc_coverage_audit_20260714"
            summary = run_audit(pro, _analysis_input(), raw_root, min_interval_seconds=5, sleep_fn=sleeps.append)
            tracked = json.dumps(summary, ensure_ascii=False)

            self.assertEqual(summary["execution"], {"status": "completed_with_errors", "planned_report_rc_reads": 2, "completed_report_rc_reads": 1, "error_report_rc_reads": 1, "min_interval_seconds": 5, "error_category_counts": {"permission_or_entitlement": 1}})
            self.assertEqual(summary["coverage"]["total_response_rows"], 3)
            self.assertEqual(summary["coverage"]["total_as_of_rows"], 2)
            self.assertEqual(summary["coverage"]["total_future_dated_rows"], 1)
            self.assertEqual(summary["coverage"]["total_duplicate_identity_rows"], 1)
            self.assertNotIn("raw-row-only", tracked)
            self.assertNotIn("600519.SH", tracked)
            self.assertTrue((raw_root / "600519_SH.json").exists())
            self.assertEqual(summary["storage"]["raw_payload_root"], RAW_ROOT.as_posix())
            self.assertFalse(summary["decision"]["downstream_rule6_wiring_authorized"])
            self.assertTrue(summary["decision"]["rule6_d_tier_status_remains_not_applicable"])
            self.assertEqual(len(pro.calls), 2)
            self.assertEqual(sleeps, [5])
            self.assertEqual(pro.calls[0]["end_date"], "20260714")


if __name__ == "__main__":
    unittest.main()
