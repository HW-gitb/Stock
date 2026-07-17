from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from runners.a_short_rule6_yfinance_probe import RAW_ROOT, run_probe


class _FakeTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol

    def history(self, **_kwargs):
        return pd.DataFrame({"Close": [1.0], "Volume": [2.0]})

    @property
    def recommendations(self):
        return pd.DataFrame({"To Grade": ["Buy"]})

    @property
    def news(self):
        return [{"title": "raw-payload-only", "url": "https://example.invalid/private"}]

    @property
    def institutional_holders(self):
        return pd.DataFrame({"Holder": ["sample"]})


class _FakeYfinance:
    Ticker = _FakeTicker


class Rule6YfinanceProbeTests(unittest.TestCase):
    def test_probe_records_shapes_only_and_cannot_authorize_rule6_wiring(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_root = Path(tmp) / "provider_samples/a_short_rule6_yfinance_probe_20260714"
            summary = run_probe(_FakeYfinance, raw_root)
            tracked = json.dumps(summary, ensure_ascii=False)

            self.assertEqual(summary["storage"]["raw_payload_root"], RAW_ROOT.as_posix())
            self.assertNotIn("raw-payload-only", tracked)
            self.assertNotIn("example.invalid", tracked)
            self.assertTrue((raw_root / "600519_SS.json").exists())
            self.assertFalse(summary["scope"]["yfinance_is_wired_into_rule6"])
            self.assertFalse(summary["decision"]["downstream_rule6_wiring_authorized"])
            self.assertTrue(summary["decision"]["rule6_d_tier_status_remains_not_applicable"])
            for result in summary["d_tier_disposition"].values():
                self.assertFalse(result["usable_as_rule6_hard_veto_source"])


if __name__ == "__main__":
    unittest.main()
