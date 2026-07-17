from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from runners.a_short_rule6_tushare_d_tier_probe import PROBE_SPECS, RAW_ROOT, _error_category, run_probe


class _FakePro:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, str]]] = []

    def hk_hold(self, **kwargs):
        self.calls.append(("hk_hold", kwargs))
        return pd.DataFrame({"ts_code": [kwargs["ts_code"]], "trade_date": ["20260714"], "vol": [10]})

    def report_rc(self, **kwargs):
        self.calls.append(("report_rc", kwargs))
        return pd.DataFrame({"ts_code": [kwargs["ts_code"]], "org_name": ["raw-payload-only"]})

    def anns_d(self, **kwargs):
        self.calls.append(("anns_d", kwargs))
        return pd.DataFrame({"ts_code": [kwargs["ts_code"]], "ann_date": ["20260714"], "title": ["raw-payload-only"]})


class Rule6PaidTushareProbeTests(unittest.TestCase):
    def test_error_category_does_not_retain_provider_text(self):
        self.assertEqual(_error_category(Exception("抱歉，您没有权限访问该接口")), "permission_or_entitlement")
        self.assertEqual(_error_category(Exception("unexpected gateway response")), "provider_or_undetermined")

    def test_probe_is_shape_only_and_cannot_authorize_rule6_wiring(self):
        pro = _FakePro()
        with tempfile.TemporaryDirectory() as tmp:
            raw_root = Path(tmp) / "provider_samples/a_short_rule6_tushare_d_tier_probe_20260714"
            summary = run_probe(pro, raw_root)
            tracked = json.dumps(summary, ensure_ascii=False)

            self.assertEqual(summary["storage"]["raw_payload_root"], RAW_ROOT.as_posix())
            self.assertEqual(summary["execution"]["planned_endpoint_reads"], 6)
            self.assertEqual(summary["execution"]["completed_endpoint_reads"], 6)
            self.assertNotIn("raw-payload-only", tracked)
            self.assertTrue((raw_root / "600519_SH.json").exists())
            self.assertFalse(summary["scope"]["tushare_is_wired_into_rule6"])
            self.assertFalse(summary["decision"]["downstream_rule6_wiring_authorized"])
            self.assertTrue(summary["decision"]["rule6_d_tier_status_remains_not_applicable"])
            self.assertEqual([name for name, _ in pro.calls], ["hk_hold", "hk_hold", "report_rc", "report_rc", "anns_d", "anns_d"])
            self.assertEqual(pro.calls[0][1], {"ts_code": "600519.SH", **PROBE_SPECS[0]["parameters"]})
            for result in summary["d_tier_disposition"].values():
                self.assertFalse(result["usable_as_rule6_hard_veto_source"])


if __name__ == "__main__":
    unittest.main()
