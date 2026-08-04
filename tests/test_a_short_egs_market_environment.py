"""Offline regression tests for EGS market-environment unit boundaries."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
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
    TRADE_DATES = ["20260803", "20260802", "20260801", "20260731", "20260730"]

    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def _render(self, north_money_wan, *, csi300_ret=0.0, structured=False, trade_dates=None):
        if north_money_wan is None or isinstance(north_money_wan, pd.DataFrame):
            payload = north_money_wan
        else:
            values = list(north_money_wan)
            dates = list(trade_dates) if trade_dates is not None else self.TRADE_DATES
            if trade_dates is None and len(values) < len(dates):
                values.extend([0.0] * (len(dates) - len(values)))
            payload = pd.DataFrame({"north_money": values, "trade_date": dates})
        with patch.object(self.egs_main, "safe_api", return_value=payload), \
                patch.object(self.egs_main, "get_csi300_return", return_value=csi300_ret):
            return self.egs_main.market_environment(
                self.TRADE_DATES,
                None,
                return_facts=structured,
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

    def test_partial_duplicate_and_out_of_window_sessions_fail_closed(self) -> None:
        payloads = {
            "one_session": pd.DataFrame({
                "trade_date": ["20260803"], "north_money": [-600000.0],
            }),
            "three_sessions": pd.DataFrame({
                "trade_date": ["20260803", "20260802", "20260801"],
                "north_money": [-600000.0, 0.0, 0.0],
            }),
            "window_outside": pd.DataFrame({
                "trade_date": ["20260803", "20260802", "20260801", "20260731", "20260729"],
                "north_money": [-600000.0, 0.0, 0.0, 0.0, 0.0],
            }),
            "duplicate": pd.DataFrame({
                "trade_date": ["20260803", "20260803", "20260801", "20260731", "20260730"],
                "north_money": [-600000.0, 0.0, 0.0, 0.0, 0.0],
            }),
        }
        for label, payload in payloads.items():
            with self.subTest(payload=label):
                _text, facts = self._render(payload, csi300_ret=-12.0, structured=True)
                self.assertEqual(facts["northbound"]["status"], "unknown")
                self.assertIsNone(facts["northbound"]["net_flow_5d"])
                self.assertFalse(facts["northbound"]["coverage_complete"])
                self.assertNotEqual(facts["northbound"]["observed_session_count"], 5)

    def test_structured_facts_preserve_cny_unit_status_and_csi_window(self) -> None:
        _text, facts = self._render([-123.0], csi300_ret=-12.0, structured=True)

        self.assertEqual(facts["northbound"]["net_flow_5d"], -1230000.0)
        self.assertEqual(facts["northbound"]["status"], "outflow")
        self.assertEqual(facts["northbound"]["requested_session_count"], 5)
        self.assertEqual(facts["northbound"]["observed_session_count"], 5)
        self.assertTrue(facts["northbound"]["coverage_complete"])
        self.assertFalse(facts["northbound"]["production_effect_enabled"])
        self.assertEqual(facts["csi300_pct_change_window"], -12.0)
        self.assertEqual(facts["csi300_window"]["length_unit"], "calendar_days")


class EgsAnalysisInputNorthboundWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def test_export_writes_structured_market_context_facts(self) -> None:
        row = {
            "ts_code": "600000.SH",
            "name": "Probe",
            "close": 10.0,
            "high_20d": 11.0,
            "low_20d": 9.0,
            "avg_amount_5d": 2e8,
            "avg_amount_20d": 2e8,
            "turnover_rate": 1.0,
            "final_score": 80.0,
            "egs_base": 70.0,
            "esp_score": 50.0,
            "cat_score": 60.0,
            "l4_score": 100.0,
            "industry_heat_score": 1.0,
            "l1_name": "金融",
            "l2_name": "银行",
            "pct_5d_n": 1.0,
            "pct_20d_n": 2.0,
            "pct_60d": 3.0,
            "drawdown_20d": 0.1,
            "q0_dt_yoy": 1.0,
            "q1_dt_yoy": 1.0,
            "pe_ttm": 10.0,
            "pb": 1.0,
            "roe": 10.0,
            "total_mv": 1e9,
            "big_ratio": 0.1,
            "tier": "Tier1",
            "entry_flag": "可直接观察",
        }
        frame = pd.DataFrame([row])
        calendar = {
            "decision_as_of": "20260522",
            "next_trade_date": None,
            "is_pre_holiday_window": False,
            "holiday_days_ahead": 0,
            "calendar_source": "tushare.trade_cal",
        }
        for name in ("suspension", "unlock", "holder_reduction"):
            self.egs_main._LAST_HARD_VETO_SOURCE_HEALTH[name] = {
                "status": "known_clear",
                "observed_at": "20260522",
            }
        self.egs_main.CONF.update({
            "l3_mode": "pit",
            "l3_provider": "legacy_tushare_snapshot",
            "l3_snapshot_date": "20260522",
            "l3_pit_strict": True,
            "l3_coverage": None,
        })
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            _full, _watch, _tier1, payload = self.egs_main.export_analysis_input(
                frame, frame, frame, "20260522", ["20260522"], set(), set(), set(), {},
                ROOT / "tier1.csv", ROOT / "full.csv", output_root=tmp,
                price_data_through="20260522", run_date="20260522",
                trade_calendar_context=calendar,
                market_context_facts={
                    "northbound": {
                        "net_flow_5d": -1230000.0,
                        "status": "outflow",
                        "requested_session_count": 5,
                        "observed_session_count": 5,
                        "coverage_complete": True,
                    },
                    "csi300_pct_change_window": -12.0,
                },
            )

        self.assertEqual(
            payload["market_context"]["northbound"],
            {
                "net_flow_5d": -1230000.0,
                "status": "outflow",
                "requested_session_count": 5,
                "observed_session_count": 5,
                "coverage_complete": True,
                "production_effect_enabled": False,
            },
        )
        self.assertEqual(payload["market_context"]["breadth"]["csi300_pct_change_window"], -12.0)
        self.assertEqual(
            payload["market_context"]["breadth"]["csi300_window"]["length_unit"],
            "calendar_days",
        )


if __name__ == "__main__":
    unittest.main()
