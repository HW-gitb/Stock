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
        if north_money_wan is None or isinstance(north_money_wan, pd.DataFrame):
            payload = north_money_wan
        else:
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

    def test_outflow_below_threshold_does_not_trigger_defensive_signal(self) -> None:
        text = self._render([-400000.0])

        self.assertIn("北向资金近一周净流入: -40.00 亿", text)
        self.assertNotIn("北向资金大幅流出，防御信号", text)

    def test_outflow_at_threshold_does_not_trigger_strict_less_than_guard(self) -> None:
        text = self._render([-500000.0])

        self.assertIn("北向资金近一周净流入: -50.00 亿", text)
        self.assertNotIn("北向资金大幅流出，防御信号", text)

    def test_invalid_northbound_payload_fails_closed(self) -> None:
        payloads = {
            "all_nan": pd.DataFrame({"north_money": [float("nan")]}),
            "empty": pd.DataFrame({"north_money": []}),
            "missing_column": pd.DataFrame({"other": [1.0]}),
            "non_finite": pd.DataFrame({"north_money": [float("inf")]}),
            "provider_none": None,
        }

        for label, payload in payloads.items():
            with self.subTest(payload=label):
                text = self._render(payload)

                self.assertIn("北向资金数据不可用", text)
                self.assertNotIn("北向资金大幅流出，防御信号", text)


if __name__ == "__main__":
    unittest.main()
