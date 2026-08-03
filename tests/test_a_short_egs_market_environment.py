"""Offline regression tests for EGS market-environment unit boundaries."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location(
            "egs_main_market_environment_under_test", EGS_SCRIPT
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class EgsMarketEnvironmentNorthboundUnitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def _render(self, north_money_wan, *, csi300_ret=0.0) -> str:
        payload = pd.DataFrame({"north_money": north_money_wan})
        with patch.object(self.egs_main, "safe_api", return_value=payload), \
                patch.object(self.egs_main, "get_csi300_return", return_value=csi300_ret):
            return self.egs_main.market_environment(
                ["20260803", "20260802", "20260801", "20260731", "20260730"],
                None,
            )

    def test_tushare_wan_values_are_normalized_before_display(self) -> None:
        text = self._render([281077.72, 341408.12, 363460.14, 354101.65])

        self.assertIn("北向资金近一周净流入: 134.00 亿", text)
        self.assertNotIn("0.01 亿", text)

    def test_normalized_flow_reaches_both_defensive_consumers(self) -> None:
        text = self._render([-600000.0], csi300_ret=-11.0)

        self.assertIn("北向资金近一周净流入: -60.00 亿", text)
        self.assertIn("北向资金大幅流出，防御信号", text)
        self.assertIn("[静默] 市场进入防御/收缩期", text)


if __name__ == "__main__":
    unittest.main()
