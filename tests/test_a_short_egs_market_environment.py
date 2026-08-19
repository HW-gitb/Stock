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
        self.assertTrue(facts["northbound"]["production_effect_enabled"])
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
                "production_effect_enabled": True,
            },
        )
        self.assertEqual(payload["market_context"]["breadth"]["csi300_pct_change_window"], -12.0)
        self.assertEqual(
            payload["market_context"]["breadth"]["csi300_window"]["length_unit"],
            "calendar_days",
        )


class EgsMarketBreadthWiringTest(unittest.TestCase):
    TRADE_DATES = [f"202608{day:02d}" for day in range(11, 0, -1)]

    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def _limit_panel(self):
        return pd.DataFrame([
            {
                "ts_code": code,
                "trade_date": trade_date,
                "up_limit": 11.0,
                "down_limit": 9.0,
            }
            for trade_date in self.TRADE_DATES
            for code in ("600000.SH", "000001.SZ")
        ])

    def test_stk_limit_window_requests_exactly_eleven_sessions_and_caches_complete_panel(self):
        calls = []
        endpoint = object()

        def fake_safe_api(actual_endpoint, **kwargs):
            calls.append((actual_endpoint, kwargs))
            trade_date = kwargs["trade_date"]
            return self._limit_panel()[self._limit_panel()["trade_date"] == trade_date]

        with patch.object(self.egs_main.pro, "stk_limit", endpoint), \
                patch.object(self.egs_main, "safe_api", side_effect=fake_safe_api), \
                patch.object(self.egs_main, "load_cache", return_value=None), \
                patch.object(self.egs_main, "save_cache") as save_cache:
            # The production helper only requires a callable endpoint; the mock
            # safe_api receives and records it without invoking it.
            self.egs_main.pro.stk_limit = lambda **_kwargs: None
            result = self.egs_main.get_full_market_stk_limit_window(self.TRADE_DATES)

        self.assertEqual(len(calls), 11)
        self.assertEqual(set(call[1]["trade_date"] for call in calls), set(self.TRADE_DATES))
        self.assertTrue(all(
            call[1]["fields"] == "ts_code,trade_date,up_limit,down_limit"
            for call in calls
        ))
        self.assertEqual(len(result), 22)
        save_cache.assert_called_once()

    def test_stk_limit_cache_hit_skips_provider_and_bad_cache_refetches(self):
        panel = self._limit_panel()
        with patch.object(self.egs_main, "load_cache", return_value=panel), \
                patch.object(self.egs_main, "safe_api", side_effect=AssertionError("provider called")):
            cached = self.egs_main.get_full_market_stk_limit_window(self.TRADE_DATES)
        self.assertEqual(len(cached), len(panel))

        bad = panel.copy()
        bad["trade_date"] = "20991231"
        calls = []

        def fake_safe_api(_endpoint, **kwargs):
            calls.append(kwargs["trade_date"])
            return panel[panel["trade_date"] == kwargs["trade_date"]]

        with patch.object(self.egs_main, "load_cache", return_value=bad), \
                patch.object(self.egs_main, "safe_api", side_effect=fake_safe_api), \
                patch.object(self.egs_main, "save_cache"):
            self.egs_main.pro.stk_limit = lambda **_kwargs: None
            self.egs_main.get_full_market_stk_limit_window(self.TRADE_DATES)
        self.assertEqual(len(calls), 11)

    def test_stk_limit_validation_scopes_to_a_shares_before_limit_checks(self):
        panel = pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": "20260811",
             "up_limit": 11.0, "down_limit": 9.0},
            {"ts_code": "900901.SH", "trade_date": "20260811",
             "up_limit": 0.0, "down_limit": 0.0},
            {"ts_code": "510300.SH", "trade_date": "20260811",
             "up_limit": None, "down_limit": None},
        ])

        result = self.egs_main._validate_stk_limit_frame(
            panel, ["20260811"], "stk_limit"
        )

        self.assertEqual(result["ts_code"].tolist(), ["600000.SH"])

        bad_a_share = panel.iloc[[0]].copy()
        bad_a_share.loc[:, "up_limit"] = float("nan")
        with self.assertRaisesRegex(RuntimeError, "non-finite or non-positive limits"):
            self.egs_main._validate_stk_limit_frame(
                bad_a_share, ["20260811"], "stk_limit"
            )

    def _breadth(self, *, down=None, height=None, status="complete"):
        return {
            "full_market_limit_up_count": 0,
            "full_market_limit_down_count": down,
            "full_market_consecutive_limit_up_height": height,
            "coverage": {"status": status},
        }

    def test_v14_2_regime_legs_are_independent_and_boundaries_stay_unknown(self):
        iv_unknown = {"iv_feed_status": "not_requested"}
        defense = self.egs_main.derive_v14_2_market_regime(
            self._breadth(down=101, height=4),
            self._breadth(down=0, height=5),
            iv_unknown,
        )
        self.assertEqual(defense["status"], "defense")
        self.assertEqual(defense["position_cap_total_pct"], 50.0)
        self.assertEqual(defense["min_reward_risk"], 2.0)
        self.assertIn(
            {"id": "limit_up_index_defense_leg", "status": "unknown",
             "value": None, "threshold": "drop>3%"},
            defense["triggers"],
        )

        iv_ready = {
            "iv_feed_status": "ready",
            "source_status": "complete",
            "freshness_status": "aligned",
            "iv_percentile_252d": 90.0001,
        }
        iv_only = self.egs_main.derive_v14_2_market_regime(
            self._breadth(down=None, height=None, status="unavailable"),
            self._breadth(down=None, height=None, status="unavailable"),
            iv_ready,
        )
        self.assertEqual(iv_only["status"], "defense")

        contraction = self.egs_main.derive_v14_2_market_regime(
            self._breadth(down=0, height=3),
            self._breadth(down=0, height=5),
            iv_unknown,
        )
        self.assertEqual(contraction["status"], "contraction")
        self.assertEqual(contraction["position_cap_single_pct"], 0.0)
        self.assertEqual(contraction["position_cap_total_pct"], None)

        boundary = self.egs_main.derive_v14_2_market_regime(
            self._breadth(down=100, height=4),
            self._breadth(down=0, height=4),
            {
                "iv_feed_status": "ready",
                "source_status": "complete",
                "freshness_status": "aligned",
                "iv_percentile_252d": 90.0,
            },
        )
        self.assertEqual(boundary["status"], "unknown")
        self.assertIsNone(boundary["position_cap_single_pct"])

    def test_contraction_precedes_defense_when_both_legs_pass(self):
        regime = self.egs_main.derive_v14_2_market_regime(
            self._breadth(down=101, height=3),
            self._breadth(down=0, height=5),
            {"iv_feed_status": "not_requested"},
        )
        self.assertEqual(regime["status"], "contraction")

    def test_iv_and_height_both_pass_still_choose_contraction(self):
        regime = self.egs_main.derive_v14_2_market_regime(
            self._breadth(down=0, height=3),
            self._breadth(down=0, height=5),
            {
                "iv_feed_status": "ready",
                "source_status": "complete",
                "freshness_status": "aligned",
                "iv_percentile_252d": 90.01,
            },
        )
        self.assertEqual(regime["status"], "contraction")

    def test_single_defense_or_contraction_leg_keeps_its_status(self):
        defense = self.egs_main.derive_v14_2_market_regime(
            self._breadth(down=101, height=4),
            self._breadth(down=0, height=4),
            {"iv_feed_status": "not_requested"},
        )
        contraction = self.egs_main.derive_v14_2_market_regime(
            self._breadth(down=0, height=3),
            self._breadth(down=0, height=5),
            {"iv_feed_status": "not_requested"},
        )
        self.assertEqual(defense["status"], "defense")
        self.assertEqual(contraction["status"], "contraction")

    def _real_breadth_inputs(self, *, missing_contender=False,
                             non_contender_missing_date=None):
        dates = self.TRADE_DATES
        codes = ("600000.SH", "600001.SH", "600002.SH")
        stock_basic = pd.DataFrame([
            {"ts_code": code, "market": "主板", "list_date": "20100101",
             "delist_date": "", "list_status": "L"}
            for code in codes
        ])
        daily_rows = []
        limit_rows = []
        prior_up_dates = {f"202608{day:02d}" for day in range(6, 11)}
        current_up_dates = {"20260809", "20260810", "20260811"}
        for trade_date in dates:
            for code in codes:
                if (
                    code == "600002.SH"
                    and trade_date == (
                        dates[0]
                        if non_contender_missing_date is None
                        else non_contender_missing_date
                    )
                ):
                    continue
                if missing_contender and code == "600001.SH" and trade_date == "20260809":
                    continue
                at_limit = (
                    code == "600000.SH" and trade_date in prior_up_dates
                ) or (
                    code == "600001.SH" and trade_date in current_up_dates
                )
                close = 11.0 if at_limit else 10.0
                daily_rows.append({
                    "ts_code": code, "trade_date": trade_date,
                    "close": close, "high": close,
                })
                limit_rows.append({
                    "ts_code": code, "trade_date": trade_date,
                    "up_limit": 11.0, "down_limit": 9.0,
                })
        return (
            pd.DataFrame(daily_rows),
            stock_basic,
            pd.DataFrame(limit_rows),
        )

    def test_real_breadth_builder_allows_non_contender_halt_for_contraction(self):
        all_daily, stock_basic, limit_panel = self._real_breadth_inputs()
        with patch.object(
            self.egs_main, "get_full_market_stk_limit_window", return_value=limit_panel
        ):
            current, previous = self.egs_main._build_full_market_breadth_observation(
                self.TRADE_DATES,
                all_daily=all_daily,
                df_stocks=stock_basic,
                suspended_set={"600002.SH"},
            )
        self.assertEqual(current["coverage"]["status"], "partial")
        self.assertTrue(current["coverage"]["_current_height_usable"])
        self.assertTrue(previous["coverage"]["_previous_height_usable"])
        regime = self.egs_main.derive_v14_2_market_regime(
            current, previous, {"iv_feed_status": "not_requested"}
        )
        self.assertEqual(regime["status"], "contraction")

    def test_real_breadth_builder_blocks_contraction_on_missing_contender_bar(self):
        all_daily, stock_basic, limit_panel = self._real_breadth_inputs(
            missing_contender=True
        )
        with patch.object(
            self.egs_main, "get_full_market_stk_limit_window", return_value=limit_panel
        ):
            current, previous = self.egs_main._build_full_market_breadth_observation(
                self.TRADE_DATES,
                all_daily=all_daily,
                df_stocks=stock_basic,
                suspended_set={"600002.SH"},
            )
        self.assertIn(
            "contender_bar_missing_in_window",
            current["coverage"]["unavailable_reason"],
        )
        self.assertFalse(current["coverage"]["_current_height_usable"])
        self.assertFalse(previous["coverage"]["_previous_height_usable"])
        regime = self.egs_main.derive_v14_2_market_regime(
            current, previous, {"iv_feed_status": "not_requested"}
        )
        self.assertNotEqual(regime["status"], "contraction")

    def test_real_breadth_builder_allows_previous_partial_height_for_contraction(self):
        all_daily, stock_basic, limit_panel = self._real_breadth_inputs(
            non_contender_missing_date=self.TRADE_DATES[1]
        )
        with patch.object(
            self.egs_main, "get_full_market_stk_limit_window", return_value=limit_panel
        ):
            current, previous = self.egs_main._build_full_market_breadth_observation(
                self.TRADE_DATES,
                all_daily=all_daily,
                df_stocks=stock_basic,
                suspended_set=set(),
            )
        self.assertEqual(current["coverage"]["status"], "complete")
        self.assertEqual(previous["coverage"]["status"], "partial")
        self.assertTrue(current["coverage"]["_current_height_usable"])
        self.assertTrue(previous["coverage"]["_previous_height_usable"])
        regime = self.egs_main.derive_v14_2_market_regime(
            current, previous, {"iv_feed_status": "not_requested"}
        )
        self.assertEqual(regime["status"], "contraction")

    def test_breadth_height_usable_rejects_history_reasons_even_with_height(self):
        for reason in (
            "incomplete_history_window",
            "contender_bar_missing_in_window",
        ):
            with self.subTest(reason=reason):
                self.assertFalse(
                    self.egs_main._breadth_height_usable(
                        {
                            "full_market_consecutive_limit_up_height": 5,
                            "coverage": {
                                "status": "partial",
                                "unavailable_reason": reason,
                            },
                        }
                    )
                )

    def test_run_egs_passes_all_breadth_inputs_to_market_environment(self):
        source = (ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8")
        for text in (
            "all_daily=all_daily",
            "df_stocks=df_stocks",
            "suspended_set=suspended_set",
            "iv_projection=iv_projection",
        ):
            self.assertIn(text, source)


if __name__ == "__main__":
    unittest.main()
