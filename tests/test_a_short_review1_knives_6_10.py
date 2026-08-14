from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import copy
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.data.analysis_input_contract import (
    AnalysisInputContractError,
    build_a_short_run_identity,
    validate_analysis_input_contract,
)
from runners import a_short_weekly_pipeline as weekly_pipeline
from runners import forward_tracker
from runners import backtest_rank, backtest_execution
from runners.a_short_m67_render import render_weekly_markdown
from tests.support.analysis_input_payload import cloned_minimal_analysis_input_payload

EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_review1_knives_6_10", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class HardVetoSourceAndCalendarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.em = _load_egs_module()

    def test_trade_calendar_source_failure_never_fabricates_weekdays(self) -> None:
        em = self.em
        em.pro = SimpleNamespace(trade_cal=lambda **kwargs: None)
        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "safe_api", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "trade calendar"):
                em.get_trade_dates(5)

    def test_trade_calendar_rejects_malformed_provider_payload(self) -> None:
        em = self.em
        em.pro = SimpleNamespace(trade_cal=lambda **kwargs: None)
        malformed = pd.DataFrame({"wrong": ["20260102"]})
        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "safe_api", return_value=malformed):
            with self.assertRaisesRegex(RuntimeError, "cal_date"):
                em.get_trade_dates(5)

    def test_daily_basic_fallback_records_actual_quote_source_date(self) -> None:
        em = self.em
        em.pro = SimpleNamespace(daily_basic=lambda **kwargs: None)
        calls = []

        def fake_safe_api(_fn, *args, **kwargs):
            calls.append(kwargs["trade_date"])
            if kwargs["trade_date"] == "20260105":
                return pd.DataFrame()
            return pd.DataFrame([{
                "ts_code": "600000.SH", "close": 10.0, "pe": 8.0,
                "pe_ttm": 9.0, "pb": 1.0, "roe": 10.0,
                "turnover_rate": 1.0, "total_mv": 1000.0, "circ_mv": 800.0,
            }])

        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "save_cache"), \
             patch.object(em, "safe_api", side_effect=fake_safe_api):
            frame = em.get_daily_basic("20260105", ["20260105", "20251231"])

        self.assertEqual(calls, ["20260105", "20251231"])
        self.assertEqual(set(frame["source_trade_date"]), {"20251231"})

    def test_daily_basic_allows_same_date_confirmed_suspension_gap(self) -> None:
        em = self.em
        universe = pd.DataFrame({"ts_code": ["600000.SH", "000001.SZ"]})
        daily_basic = pd.DataFrame([{
            "ts_code": "600000.SH", "close": 10.0, "pe": 8.0,
            "pe_ttm": 9.0, "pb": 1.0, "roe": 10.0,
            "turnover_rate": 1.0, "total_mv": 1000.0, "circ_mv": 800.0,
        }])
        em.pro = SimpleNamespace(
            stock_basic=lambda **kwargs: None,
            daily_basic=lambda **kwargs: None,
        )
        with patch.object(em, "get_stock_list", return_value=universe), \
             patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "save_cache") as save_cache, \
             patch.object(em, "safe_api", return_value=daily_basic):
            frame = em.get_daily_basic(
                "20260105", ["20260105"],
                suspended_codes={"000001.SZ"},
                suspended_observed_at="20260105",
            )

        self.assertEqual(set(frame["ts_code"]), {"600000.SH"})
        self.assertEqual(set(frame["source_trade_date"]), {"20260105"})
        self.assertNotIn("000001.SZ", set(frame["ts_code"]))
        save_cache.assert_called_once()

    def test_daily_basic_keeps_unexplained_missing_fail_closed(self) -> None:
        em = self.em
        universe = pd.DataFrame({"ts_code": ["600000.SH", "000001.SZ", "000002.SZ"]})
        daily_basic = pd.DataFrame([{
            "ts_code": "600000.SH", "close": 10.0, "pe": 8.0,
            "pe_ttm": 9.0, "pb": 1.0, "roe": 10.0,
            "turnover_rate": 1.0, "total_mv": 1000.0, "circ_mv": 800.0,
        }])
        em.pro = SimpleNamespace(
            stock_basic=lambda **kwargs: None,
            daily_basic=lambda **kwargs: None,
        )
        with patch.object(em, "get_stock_list", return_value=universe), \
             patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "save_cache") as save_cache, \
             patch.object(em, "safe_api", return_value=daily_basic):
            with self.assertRaisesRegex(RuntimeError, "target coverage incomplete.*000002.SZ"):
                em.get_daily_basic(
                    "20260105", ["20260105"],
                    suspended_codes={"000001.SZ"},
                    suspended_observed_at="20260105",
                )

        save_cache.assert_not_called()

    def test_daily_basic_rejects_cross_date_suspension_explanation(self) -> None:
        em = self.em
        universe = pd.DataFrame({"ts_code": ["600000.SH", "000001.SZ"]})
        daily_basic = pd.DataFrame([{
            "ts_code": "600000.SH", "close": 10.0, "pe": 8.0,
            "pe_ttm": 9.0, "pb": 1.0, "roe": 10.0,
            "turnover_rate": 1.0, "total_mv": 1000.0, "circ_mv": 800.0,
        }])
        em.pro = SimpleNamespace(
            stock_basic=lambda **kwargs: None,
            daily_basic=lambda **kwargs: None,
        )
        with patch.object(em, "get_stock_list", return_value=universe), \
             patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "save_cache") as save_cache, \
             patch.object(em, "safe_api", return_value=daily_basic):
            with self.assertRaisesRegex(RuntimeError, "target coverage incomplete.*000001.SZ"):
                em.get_daily_basic(
                    "20260105", ["20260105"],
                    suspended_codes={"000001.SZ"},
                    suspended_observed_at="20260104",
                )

        save_cache.assert_not_called()

    def test_daily_basic_cache_uses_same_date_suspension_rule(self) -> None:
        em = self.em
        universe = pd.DataFrame({"ts_code": ["600000.SH", "000001.SZ"]})
        cached = pd.DataFrame([{
            "ts_code": "600000.SH", "close": 10.0, "pe": 8.0,
            "pe_ttm": 9.0, "pb": 1.0, "roe": 10.0,
            "turnover_rate": 1.0, "total_mv": 1000.0, "circ_mv": 800.0,
            "source_trade_date": "20260105",
        }])
        refreshed = cached.copy()
        refreshed.loc[len(refreshed)] = {
            "ts_code": "000001.SZ", "close": 11.0, "pe": 9.0,
            "pe_ttm": 10.0, "pb": 1.1, "roe": 11.0,
            "turnover_rate": 1.1, "total_mv": 1100.0, "circ_mv": 900.0,
            "source_trade_date": "20260105",
        }
        em.pro = SimpleNamespace(
            stock_basic=lambda **kwargs: None,
            daily_basic=lambda **kwargs: None,
        )

        with self.subTest("same-date cache is reusable"):
            with patch.object(em, "get_stock_list", return_value=universe), \
                 patch.object(em, "load_cache", return_value=cached), \
                 patch.object(em, "safe_api") as safe_api:
                frame = em.get_daily_basic(
                    "20260105", ["20260105"],
                    suspended_codes={"000001.SZ"},
                    suspended_observed_at="20260105",
                )
            self.assertEqual(set(frame["ts_code"]), {"600000.SH"})
            safe_api.assert_not_called()

        with self.subTest("cross-date cache must refresh"):
            with patch.object(em, "get_stock_list", return_value=universe), \
                 patch.object(em, "load_cache", return_value=cached), \
                 patch.object(em, "save_cache") as save_cache, \
                 patch.object(em, "safe_api", return_value=refreshed) as safe_api:
                frame = em.get_daily_basic(
                    "20260105", ["20260105"],
                    suspended_codes={"000001.SZ"},
                    suspended_observed_at="20260104",
                )
            self.assertEqual(set(frame["ts_code"]), {"600000.SH", "000001.SZ"})
            safe_api.assert_called_once()
            save_cache.assert_called_once()

    def test_missing_suspend_source_blocks_run(self) -> None:
        em = self.em
        em.pro = SimpleNamespace(daily=lambda **kwargs: None)
        stocks = pd.DataFrame({"ts_code": ["600000.SH", "000001.SZ"]})
        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "save_cache"), \
             patch.object(em, "get_stock_list", return_value=stocks), \
             patch.object(em, "safe_api", return_value=pd.DataFrame()):
            with self.assertRaisesRegex(RuntimeError, "suspend source unavailable"):
                em.get_suspend_info(["20260105", "20251231"])

    def test_unlock_uses_real_circulating_share_denominator_only(self) -> None:
        em = self.em
        old_today, old_dt = em.TODAY, em.TODAY_DT
        em.TODAY, em.TODAY_DT = "20260105", datetime(2026, 1, 5)
        em.pro = SimpleNamespace(share_float=lambda **kwargs: None)
        daily = pd.DataFrame([
            {"ts_code": "600000.SH", "close": 10.0, "circ_mv": 1000.0, "source_trade_date": "20251231"},
            {"ts_code": "000001.SZ", "close": None, "circ_mv": None, "source_trade_date": "20251231"},
            {"ts_code": "300001.SZ", "close": 10.0, "circ_mv": 1000.0, "source_trade_date": "20251231"},
            {"ts_code": "400001.SZ", "close": 10.0, "circ_mv": 1000.0, "source_trade_date": "20251231"},
        ])
        source = pd.DataFrame([
            {"ts_code": "600000.SH", "ann_date": "20260104", "float_date": "20260120", "float_share": 20.0, "float_ratio": 99.0},
            {"ts_code": "000001.SZ", "ann_date": "20260104", "float_date": "20260120", "float_share": 20.0, "float_ratio": 99.0},
            {"ts_code": "300001.SZ", "ann_date": "20260104", "float_date": "20260120", "float_share": 1.0, "float_ratio": 1.0},
            {"ts_code": "400001.SZ", "ann_date": "20260104", "float_date": "20260120", "float_share": "invalid", "float_ratio": 99.0},
        ])
        try:
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache") as save_cache, \
                 patch.object(em, "safe_api", return_value=source):
                blocked = em.get_unlock_future(pd.DataFrame(), daily)
        finally:
            em.TODAY, em.TODAY_DT = old_today, old_dt

        # 600000: 20 / (1000/10) = 20%, a real denominator hit.
        # 000001: denominator missing => blocked/unknown; float_ratio must not rescue it.
        self.assertEqual(blocked, {"600000.SH", "000001.SZ", "400001.SZ"})
        health = em._LAST_HARD_VETO_SOURCE_HEALTH["unlock"]
        self.assertEqual(health["status"], "known_hit")
        self.assertEqual(health["hit_count"], 3)
        self.assertEqual(health["large_unlock_count"], 1)
        self.assertEqual(health["unlock_uncomputable_count"], 2)
        self.assertEqual(health["float_share_invalid_count"], 1)
        self.assertEqual(health["circ_share_unavailable_count"], 1)
        self.assertEqual(em._LAST_UNLOCK_DETAILS["000001.SZ"]["status"], "unknown")
        self.assertEqual(
            em._LAST_UNLOCK_DETAILS["000001.SZ"]["unknown_reason"],
            "circ_share_unavailable",
        )
        self.assertEqual(
            em._LAST_UNLOCK_DETAILS["400001.SZ"]["unknown_reason"],
            "float_share_invalid",
        )
        self.assertEqual(em._LAST_UNLOCK_DETAILS["300001.SZ"]["status"], "known_clear")
        save_cache.assert_not_called()
        self.assertNotIn("0.6", Path(EGS_SCRIPT).read_text(encoding="utf-8")[
            Path(EGS_SCRIPT).read_text(encoding="utf-8").index("def get_unlock_future"):
            Path(EGS_SCRIPT).read_text(encoding="utf-8").index("def get_holder_reductions")
        ])

    def test_unlock_source_exception_remains_unknown(self) -> None:
        em = self.em
        old_today, old_dt = em.TODAY, em.TODAY_DT
        em.TODAY, em.TODAY_DT = "20260105", datetime(2026, 1, 5)
        em.pro = SimpleNamespace(share_float=lambda **kwargs: None)
        daily = pd.DataFrame([{"ts_code": "600000.SH", "close": 10.0, "circ_mv": 1000.0}])

        def failed_safe_api(_fn, *args, **kwargs):
            kwargs["errors"].append(RuntimeError("provider failure"))
            return None

        try:
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache") as save_cache, \
                 patch.object(em, "safe_api", side_effect=failed_safe_api):
                with self.assertRaisesRegex(RuntimeError, "unlock source exception"):
                    em.get_unlock_future(pd.DataFrame(), daily)
        finally:
            em.TODAY, em.TODAY_DT = old_today, old_dt

        health = em._LAST_HARD_VETO_SOURCE_HEALTH["unlock"]
        self.assertEqual(health["status"], "unknown")
        self.assertEqual(health["failure_class"], "exception")
        self.assertEqual(health["exception_type"], "RuntimeError")
        save_cache.assert_not_called()

    def test_unlock_only_local_gap_is_known_hit_and_not_cached(self) -> None:
        em = self.em
        old_today, old_dt = em.TODAY, em.TODAY_DT
        em.TODAY, em.TODAY_DT = "20260105", datetime(2026, 1, 5)
        em.pro = SimpleNamespace(share_float=lambda **kwargs: None)
        daily = pd.DataFrame([
            {"ts_code": "600000.SH", "close": 10.0, "circ_mv": 1000.0},
            {"ts_code": "000001.SZ", "close": None, "circ_mv": None},
        ])
        source = pd.DataFrame([
            {"ts_code": "600000.SH", "ann_date": "20260104", "float_date": "20260120", "float_share": 1.0},
            {"ts_code": "000001.SZ", "ann_date": "20260104", "float_date": "20260120", "float_share": 20.0},
        ])

        try:
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache") as save_cache, \
                 patch.object(em, "safe_api", return_value=source):
                blocked = em.get_unlock_future(pd.DataFrame(), daily)
        finally:
            em.TODAY, em.TODAY_DT = old_today, old_dt

        self.assertEqual(blocked, {"000001.SZ"})
        health = em._LAST_HARD_VETO_SOURCE_HEALTH["unlock"]
        self.assertEqual(health["status"], "known_hit")
        self.assertEqual(health["hit_count"], 1)
        self.assertEqual(health["large_unlock_count"], 0)
        self.assertEqual(health["unlock_uncomputable_count"], 1)
        payload = cloned_minimal_analysis_input_payload()
        payload["source"]["hard_veto_source_health"] = {
            "suspension": {"status": "known_clear", "observed_at": "20260105"},
            "unlock": health,
            "holder_reduction": {"status": "known_clear", "observed_at": "20260105"},
        }
        validate_analysis_input_contract(payload)
        save_cache.assert_not_called()

    def test_unlock_unconfirmed_empty_remains_unknown(self) -> None:
        em = self.em
        old_today, old_dt = em.TODAY, em.TODAY_DT
        em.TODAY, em.TODAY_DT = "20260105", datetime(2026, 1, 5)
        em.pro = SimpleNamespace(share_float=lambda **kwargs: None)
        daily = pd.DataFrame([{"ts_code": "600000.SH", "close": 10.0, "circ_mv": 1000.0}])

        try:
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache") as save_cache, \
                 patch.object(em, "safe_api", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "unconfirmed empty"):
                    em.get_unlock_future(pd.DataFrame(), daily)
        finally:
            em.TODAY, em.TODAY_DT = old_today, old_dt

        health = em._LAST_HARD_VETO_SOURCE_HEALTH["unlock"]
        self.assertEqual(health["status"], "unknown")
        self.assertEqual(health["failure_class"], "unconfirmed_empty")
        save_cache.assert_not_called()

    def test_unlock_rejects_future_observation(self) -> None:
        em = self.em
        old_today, old_dt = em.TODAY, em.TODAY_DT
        em.TODAY, em.TODAY_DT = "20260105", datetime(2026, 1, 5)
        em.pro = SimpleNamespace(share_float=lambda **kwargs: None)
        daily = pd.DataFrame([{"ts_code": "600000.SH", "close": 10.0, "circ_mv": 1000.0}])
        future = pd.DataFrame([{
            "ts_code": "600000.SH", "ann_date": "20260106", "float_date": "20260120",
            "float_share": 20.0, "float_ratio": 20.0,
        }])
        try:
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache"), \
                 patch.object(em, "safe_api", return_value=future):
                with self.assertRaisesRegex(RuntimeError, "unlock.*PIT"):
                    em.get_unlock_future(pd.DataFrame(), daily)
        finally:
            em.TODAY, em.TODAY_DT = old_today, old_dt

    def test_missing_holder_reduction_source_blocks_run(self) -> None:
        em = self.em
        em.pro = SimpleNamespace(stk_holdertrade=lambda **kwargs: None)
        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "safe_api", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "holder-reduction source returned unconfirmed empty"):
                em.get_holder_reductions()

    def test_holder_reduction_isolates_only_uncomputable_after_ratio(self) -> None:
        em = self.em
        old_today, old_dt = em.TODAY, em.TODAY_DT
        em.TODAY, em.TODAY_DT = "20260105", datetime(2026, 1, 5)
        em.pro = SimpleNamespace(stk_holdertrade=lambda **kwargs: None)
        source = pd.DataFrame([
            {"ts_code": "600000.SH", "ann_date": "20260104", "in_de": "DE", "after_ratio": 4.99},
            {"ts_code": "000001.SZ", "ann_date": "20260104", "in_de": "DE", "after_ratio": None},
            {"ts_code": "000002.SZ", "ann_date": "20260104", "in_de": "DE", "after_ratio": "6.0"},
        ])
        try:
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache") as save_cache, \
                 patch.object(em, "safe_api", return_value=source):
                result = em.get_holder_reductions()
        finally:
            em.TODAY, em.TODAY_DT = old_today, old_dt

        self.assertEqual(result["veto_10d"], {"600000.SH", "000001.SZ", "000002.SZ"})
        self.assertEqual(result["deduct_30d"], set())
        self.assertEqual(result["unknown_codes"], {"000001.SZ"})
        self.assertEqual(
            {event["ts_code"] for event in result["rule6_holder_events"]},
            {"600000.SH", "000002.SZ"},
        )
        health = em._LAST_HARD_VETO_SOURCE_HEALTH["holder_reduction"]
        self.assertEqual(health["status"], "known_hit")
        self.assertEqual(health["hit_count"], 3)
        self.assertEqual(health["holder_reduction_event_count"], 3)
        self.assertEqual(health["holder_reduction_uncomputable_count"], 1)
        save_cache.assert_not_called()

    def test_holder_reduction_unknown_codes_are_removed_before_l0(self) -> None:
        em = self.em
        stocks = pd.DataFrame([
            {"ts_code": "600000.SH", "name": "A", "list_status": "L", "delist_date": ""},
            {"ts_code": "000001.SZ", "name": "B", "list_status": "L", "delist_date": ""},
            {"ts_code": "000002.SZ", "name": "C", "list_status": "L", "delist_date": ""},
        ])
        result = em.filter_l0(
            stocks,
            pd.DataFrame(),
            set(),
            {"veto_10d": set(), "deduct_30d": set(), "unknown_codes": {"000001.SZ"}},
            set(),
            set(),
        )
        self.assertEqual(set(result["ts_code"]), {"600000.SH", "000002.SZ"})

    def test_holder_reduction_unconfirmed_empty_remains_unknown(self) -> None:
        em = self.em
        em.pro = SimpleNamespace(stk_holdertrade=lambda **kwargs: None)
        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "save_cache") as save_cache, \
             patch.object(em, "safe_api", return_value=pd.DataFrame()):
            with self.assertRaisesRegex(RuntimeError, "unconfirmed empty"):
                em.get_holder_reductions()
        health = em._LAST_HARD_VETO_SOURCE_HEALTH["holder_reduction"]
        self.assertEqual(health["status"], "unknown")
        self.assertEqual(health["failure_class"], "unconfirmed_empty")
        save_cache.assert_not_called()

    def test_holder_reduction_exception_remains_unknown(self) -> None:
        em = self.em
        em.pro = SimpleNamespace(stk_holdertrade=lambda **kwargs: None)

        def failed_safe_api(_fn, *args, **kwargs):
            kwargs["errors"].append(RuntimeError("provider failure"))
            return None

        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "save_cache") as save_cache, \
             patch.object(em, "safe_api", side_effect=failed_safe_api):
            with self.assertRaisesRegex(RuntimeError, "holder-reduction source exception"):
                em.get_holder_reductions()
        health = em._LAST_HARD_VETO_SOURCE_HEALTH["holder_reduction"]
        self.assertEqual(health["status"], "unknown")
        self.assertEqual(health["failure_class"], "exception")
        self.assertEqual(health["exception_type"], "RuntimeError")
        save_cache.assert_not_called()

    def test_holder_reduction_missing_field_and_future_pit_remain_unknown(self) -> None:
        em = self.em
        old_today, old_dt = em.TODAY, em.TODAY_DT
        em.TODAY, em.TODAY_DT = "20260105", datetime(2026, 1, 5)
        em.pro = SimpleNamespace(stk_holdertrade=lambda **kwargs: None)
        cases = [
            (
                pd.DataFrame([{"ts_code": "600000.SH", "ann_date": "20260104", "in_de": "DE"}]),
                "missing required fields",
            ),
            (
                pd.DataFrame([{
                    "ts_code": "600000.SH", "ann_date": "20260106", "in_de": "DE", "after_ratio": 6.0,
                }]),
                "holder-reduction PIT",
            ),
        ]
        try:
            for source, message in cases:
                with self.subTest(message=message):
                    with patch.object(em, "load_cache", return_value=None), \
                         patch.object(em, "save_cache") as save_cache, \
                         patch.object(em, "safe_api", return_value=source):
                        with self.assertRaisesRegex(RuntimeError, message):
                            em.get_holder_reductions()
                    self.assertEqual(
                        em._LAST_HARD_VETO_SOURCE_HEALTH["holder_reduction"]["status"],
                        "unknown",
                    )
                    save_cache.assert_not_called()
        finally:
            em.TODAY, em.TODAY_DT = old_today, old_dt

    def test_holder_reduction_complete_non_hit_is_known_clear_and_cached(self) -> None:
        em = self.em
        em.pro = SimpleNamespace(stk_holdertrade=lambda **kwargs: None)
        source = pd.DataFrame([{
            "ts_code": "600000.SH", "ann_date": "20260104", "in_de": "IN", "after_ratio": 6.0,
        }])
        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "save_cache") as save_cache, \
             patch.object(em, "safe_api", return_value=source):
            result = em.get_holder_reductions()
        self.assertEqual(result["veto_10d"], set())
        self.assertEqual(result["deduct_30d"], set())
        self.assertEqual(result["unknown_codes"], set())
        self.assertEqual(result["rule6_holder_events"], [])
        health = em._LAST_HARD_VETO_SOURCE_HEALTH["holder_reduction"]
        self.assertEqual(health["status"], "known_clear")
        save_cache.assert_called_once()


class FinancialL0CoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.em = _load_egs_module()

    @staticmethod
    def _financial_frame(codes):
        return pd.DataFrame({"ts_code": list(codes)})

    def _patch_run_inputs(self, stack, stocks, l0, financial, build_master):
        em = self.em
        sw_map = {
            code: {"l1_name": "行业A", "l2_name": "行业B"}
            for code in stocks["ts_code"]
        }
        stack.enter_context(patch.object(em, "_load_iv_feed_projection", return_value={}))
        stack.enter_context(patch.object(
            em,
            "get_trade_dates",
            return_value=["20260105", "20260102", "20260101", "20251231", "20251230"],
        ))
        stack.enter_context(patch.object(em, "a_share_market_date", return_value="20260105"))
        stack.enter_context(patch.object(em, "get_trade_calendar_context", return_value={}))
        stack.enter_context(patch.object(em, "_require_nonempty_stock_universe", return_value=stocks))
        stack.enter_context(patch.object(em, "get_sw_industry_map", return_value=sw_map))
        stack.enter_context(patch.object(em, "get_csi300_return", return_value=0.0))
        stack.enter_context(patch.object(em, "get_daily_all", return_value=pd.DataFrame()))
        stack.enter_context(patch.object(em, "get_suspend_info", return_value=set()))
        stack.enter_context(patch.object(em, "get_daily_basic", return_value=pd.DataFrame()))
        stack.enter_context(patch.object(em, "get_relisted_stocks", return_value=set()))
        stack.enter_context(patch.object(em, "get_unlock_future", return_value=set()))
        stack.enter_context(patch.object(
            em,
            "get_holder_reductions",
            return_value={"veto_10d": set(), "deduct_30d": set(),
                          "unknown_codes": set(), "rule6_holder_events": []},
        ))
        stack.enter_context(patch.object(em, "precompute_stock_stats", return_value=pd.DataFrame()))
        stack.enter_context(patch.object(em, "filter_l0", return_value=l0.copy()))
        stack.enter_context(patch.object(em, "get_financial_data", return_value=financial))
        stack.enter_context(patch.object(em, "get_moneyflow", return_value=None))
        stack.enter_context(patch.object(
            em,
            "get_margin",
            return_value=SimpleNamespace(frame=pd.DataFrame()),
        ))
        stack.enter_context(patch.object(em, "build_master", side_effect=build_master))

    def test_95_percent_full_coverage_isolates_only_missing_l0_code(self) -> None:
        codes = [f"{600000 + i:06d}.SH" for i in range(20)]
        stocks = pd.DataFrame({"ts_code": codes})
        captured = {}

        class BuildReached(RuntimeError):
            pass

        def stop_after_build(df_l0, *args, **kwargs):
            captured["df_l0"] = df_l0.copy()
            raise BuildReached()

        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            with ExitStack() as stack:
                self._patch_run_inputs(
                    stack,
                    stocks,
                    stocks,
                    self._financial_frame(codes[:-1]),
                    stop_after_build,
                )
                with self.assertRaises(BuildReached):
                    self.em.run_egs(backtest_mode=True, output_root=tmp)

        self.assertEqual(set(captured["df_l0"]["ts_code"]), set(codes[:-1]))

    def test_financial_full_universe_below_floor_aborts_before_build_master(self) -> None:
        codes = [f"{600000 + i:06d}.SH" for i in range(20)]
        stocks = pd.DataFrame({"ts_code": codes})
        reached = []

        def stop_after_build(*args, **kwargs):
            reached.append(True)
            raise RuntimeError("build_master reached")

        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            with ExitStack() as stack:
                self._patch_run_inputs(
                    stack,
                    stocks,
                    stocks,
                    self._financial_frame(codes[:-2]),
                    stop_after_build,
                )
                with self.assertRaisesRegex(RuntimeError, "financial full-universe coverage"):
                    self.em.run_egs(backtest_mode=True, output_root=tmp)
        self.assertEqual(reached, [])

    def test_financial_response_code_contract_fails_closed(self) -> None:
        codes = [f"{600000 + i:06d}.SH" for i in range(20)]
        stocks = pd.DataFrame({"ts_code": codes})
        for label, financial in (
            ("empty", pd.DataFrame()),
            ("missing_ts_code", pd.DataFrame({"wrong": [1]})),
            ("foreign_code", self._financial_frame(codes[:-1] + ["999999.SH"])),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
                reached = []

                def stop_after_build(*args, **kwargs):
                    reached.append(True)
                    raise RuntimeError("build_master reached")

                with ExitStack() as stack:
                    self._patch_run_inputs(stack, stocks, stocks, financial, stop_after_build)
                    with self.assertRaisesRegex(RuntimeError, "financial full-universe"):
                        self.em.run_egs(backtest_mode=True, output_root=tmp)
                self.assertEqual(reached, [])


class RunIdentityAndPublishTest(unittest.TestCase):
    def test_analysis_input_run_identity_binds_exact_candidate_set(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["source"]["run_identity"] = build_a_short_run_identity(
            payload["trade_date"], payload["candidates"]
        )
        validate_analysis_input_contract(payload)
        payload["candidates"][0]["name"] = "changed-after-digest"
        with self.assertRaisesRegex(AnalysisInputContractError, "candidate_digest"):
            validate_analysis_input_contract(payload)

    def test_multi_file_publish_failure_restores_every_old_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / "weekly_m67.json", root / "weekly_m67.md", root / "ratchet.json"]
            for path in paths:
                path.write_bytes(("old:" + path.name).encode("utf-8"))
            payloads = {str(path): ("new:" + path.name).encode("utf-8") for path in paths}
            real_replace = os.replace
            calls = {"count": 0}

            def fail_second(src, dst):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("injected publish failure")
                return real_replace(src, dst)

            with patch.object(weekly_pipeline.os, "replace", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "injected"):
                    weekly_pipeline._replace_many_with_rollback(payloads)

            for path in paths:
                self.assertEqual(path.read_bytes(), ("old:" + path.name).encode("utf-8"))

    def test_egs_official_transaction_restores_every_old_surface_on_failure(self) -> None:
        em = HardVetoSourceAndCalendarTest.em
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in (
                "analysis_input.json", "candidates.csv", "data_health.json", "official_publish.json"
            )]
            for path in paths:
                path.write_text("old:" + path.name, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "injected publish failure"):
                with em.official_output_transaction(paths):
                    for path in paths:
                        path.write_text("new:" + path.name, encoding="utf-8")
                    raise RuntimeError("injected publish failure")
            for path in paths:
                self.assertEqual(path.read_text(encoding="utf-8"), "old:" + path.name)

    def test_p4_sidecar_and_old_marker_bytes_restore_when_later_publish_fails(self) -> None:
        em = HardVetoSourceAndCalendarTest.em
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / "stage3_overlay_score.json", Path(tmp) / "official_publish.json"]
            for path in paths:
                path.write_bytes(("old:" + path.name).encode("utf-8"))
            with self.assertRaisesRegex(RuntimeError, "later formal publish failure"):
                with em.official_output_transaction(paths):
                    paths[0].write_bytes(b"new-p4-sidecar-bytes")
                    raise RuntimeError("later formal publish failure")
            self.assertEqual(paths[0].read_bytes(), b"old:stage3_overlay_score.json")
            self.assertEqual(paths[1].read_bytes(), b"old:official_publish.json")

    def test_weekly_consumer_rejects_analysis_bytes_not_bound_by_marker(self) -> None:
        identity = {"run_id": "a-short-20260105-" + "a" * 16, "candidate_digest": "a" * 64}
        with tempfile.TemporaryDirectory() as tmp:
            analysis = Path(tmp) / "analysis_input.json"
            analysis.write_text("{}", encoding="utf-8")
            marker = {
                **identity,
                "stage_status": "complete",
                "files": {"analysis_input": {
                    "path": analysis.name,
                    "sha256": hashlib.sha256(analysis.read_bytes()).hexdigest(),
                }},
            }
            weekly_pipeline._validate_official_publish_marker(analysis, marker, identity)
            analysis.write_text('{"tampered": true}', encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "does not bind"):
                weekly_pipeline._validate_official_publish_marker(analysis, marker, identity)
            analysis.write_text('{"candidate":', encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "official publish marker/analysis_input") as exc:
                weekly_pipeline._validate_official_publish_marker(analysis, marker, identity)
            self.assertNotIn("candidate", str(exc.exception))

    def test_weekly_consumer_rejects_truncated_marker_without_payload_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "official_publish.json"
            marker.write_text('{"candidate_code": "600000.SH",', encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "official publish marker/analysis_input") as exc:
                weekly_pipeline._load_official_publish_marker(marker)
        self.assertNotIn("600000.SH", str(exc.exception))

    def test_markdown_exposes_same_run_digest_and_complete_status(self) -> None:
        digest = "a" * 64
        weekly = {
            "as_of": "20260105", "reports": [],
            "run_lineage": {
                "run_id": "a-short-20260105-" + digest[:16],
                "candidate_digest": digest,
                "stage_status": "complete",
                "account_status": "absent",
                "sizing_mode": "observation_only_no_account",
            },
        }
        rendered = render_weekly_markdown(weekly)
        self.assertIn("a-short-20260105-" + digest[:16], rendered)
        self.assertIn(digest, rendered)
        self.assertIn("stage=complete", rendered)

    def test_wrapper_m67_failure_paths_exit_nonzero(self) -> None:
        text = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        for reason in (
            "analysis_input_missing",
            "account_path_missing",
            "weekly_pipeline_failed",
            "weekly_operation_bundle_invalid",
        ):
            self.assertIn(f"Set-M67Failure -Reason '{reason}'", text)
        self.assertIn("$script:FinalExitCode = $ExitCode", text)
        self.assertIn("exit $FinalExitCode", text)
        self.assertNotIn("exit $M67ExitCode", text)
        self.assertIn("stage_status = 'failed'", text)


class ForwardCohortReplacementTest(unittest.TestCase):
    @staticmethod
    def _payload(codes: list[str]) -> dict:
        payload = cloned_minimal_analysis_input_payload()
        template = payload["candidates"][0]
        candidates = []
        for index, code in enumerate(codes):
            row = copy.deepcopy(template)
            row["ts_code"] = code
            row["name"] = f"candidate-{index}"
            row["exchange"] = "SH" if code.endswith(".SH") else "SZ"
            candidates.append(row)
        payload["candidates"] = candidates
        payload["source"]["run_identity"] = build_a_short_run_identity(
            payload["trade_date"], candidates
        )
        return payload

    def test_same_day_rerun_replaces_cohort_instead_of_union(self) -> None:
        as_of = cloned_minimal_analysis_input_payload()["trade_date"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "result"
            bucket = root / as_of
            bucket.mkdir(parents=True)
            tracker = Path(tmp) / "forward_tracker.csv"
            input_path = bucket / "analysis_input.json"
            input_path.write_text(json.dumps(self._payload(["600000.SH", "000001.SZ"]), ensure_ascii=False), encoding="utf-8")
            with patch.object(forward_tracker, "LIVE_RESULT_ROOT", root), \
                 patch.object(forward_tracker, "TRACKER_CSV", tracker):
                self.assertEqual(forward_tracker.capture(as_of), 0)
                input_path.write_text(json.dumps(self._payload(["000001.SZ", "600001.SH"]), ensure_ascii=False), encoding="utf-8")
                self.assertEqual(forward_tracker.capture(as_of), 0)

            written = pd.read_csv(tracker, dtype={"as_of": str, "ts_code": str})
            self.assertEqual(set(written[written["as_of"] == as_of]["ts_code"]), {"000001.SZ", "600001.SH"})
            self.assertNotIn("600000.SH", set(written["ts_code"]))
            self.assertEqual(written["run_id"].nunique(), 1)
            self.assertEqual(written["candidate_digest"].nunique(), 1)

    def test_incomplete_same_run_capture_is_replaced_not_treated_as_noop(self) -> None:
        payload = self._payload(["600000.SH", "000001.SZ"])
        as_of = payload["trade_date"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "result"
            bucket = root / as_of
            bucket.mkdir(parents=True)
            tracker = Path(tmp) / "forward_tracker.csv"
            input_path = bucket / "analysis_input.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            identity = payload["source"]["run_identity"]
            partial = forward_tracker._candidate_row(
                as_of, "2026-01-01T00:00:00+08:00", identity["run_id"],
                identity["candidate_digest"], payload["candidates"][0],
            )
            pd.DataFrame([partial], columns=forward_tracker.SCHEMA_COLUMNS).to_csv(tracker, index=False)
            with patch.object(forward_tracker, "LIVE_RESULT_ROOT", root), \
                 patch.object(forward_tracker, "TRACKER_CSV", tracker):
                self.assertEqual(forward_tracker.capture(as_of), 0)
            written = pd.read_csv(tracker, dtype={"as_of": str, "ts_code": str})
            self.assertEqual(set(written["ts_code"]), {"600000.SH", "000001.SZ"})


class BacktestInputAndEvidenceBoundaryTest(unittest.TestCase):
    def test_unknown_momentum_flags_fail_closed_in_variant_masks(self) -> None:
        sample = pd.DataFrame([{
            "rank": 1,
            "tier": "Tier1",
            "entry_flag": "正常",
            "l4_flag": "",
            "q0_dt_yoy": 10,
            "q1_dt_yoy": 10,
            "esp_raw": 10,
            "l2_name": "银行",
            "final_score": 90,
            "completeness_score": 100,
            "chasing_high": pd.NA,
            "overheat_flag": pd.NA,
        }])

        self.assertFalse(backtest_rank._variant_mask(sample, "no_chase").iloc[0])
        self.assertFalse(backtest_rank._variant_mask(sample, "no_overheat").iloc[0])
        self.assertFalse(backtest_rank._variant_mask(sample, "combined_p0").iloc[0])
        grouped = backtest_rank.build_group_columns(sample)
        self.assertIn("momentum_history_unknown", grouped.loc[0, "risk_reasons"])

    def test_invalid_pit_input_fails_before_rank_or_execution_output(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["candidates"][0]["fundamental"]["expectation"]["earnings_report_date"] = "20990101"
        as_of = payload["trade_date"]
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "generated"
            bucket = source_root / as_of
            bucket.mkdir(parents=True)
            path = bucket / "analysis_input.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            out = Path(tmp) / "outputs"
            with patch.object(backtest_rank, "BACKTEST_DIR", out):
                with self.assertRaisesRegex(ValueError, "invalid rank backtest input"):
                    backtest_rank.load_analysis_inputs(source_root, [as_of])
            self.assertFalse(out.exists())
            with self.assertRaisesRegex(AnalysisInputContractError, "earnings_report_date"):
                backtest_execution.load_analysis_input(path)

    def test_rank_schema_pins_engineering_replay_boundary(self) -> None:
        schema = json.loads((ROOT / "schemas" / "rank_backtest_report.schema.json").read_text(encoding="utf-8"))
        props = schema["properties"]
        self.assertEqual(props["evidence_role"]["const"], "engineering_rank_replay")
        self.assertTrue(props["includes_backtest_only_tier2_filler"]["const"])
        self.assertFalse(props["includes_full_m67_operation_chain"]["const"])
        self.assertFalse(props["production_or_live_historical_replay"]["const"])
        self.assertFalse(props["full_size_allowed"]["const"])

    def test_execution_backtest_never_grants_full_size(self) -> None:
        capital_context = {
            "manual_execution_only": True,
            "ship_gate": {
                "policy_logic": "and",
                "monthly_alpha_t_stat_min": 2.0,
                "sharpe_min": 1.0,
                "max_drawdown_max": 0.15,
                "forward_live_months_min": 12,
                "failure_mode": "paper_or_minimal_size_or_risk_filter_only",
            },
        }
        evaluation = backtest_execution.build_ship_gate_evaluation(
            {"trade_count": 100, "max_drawdown": 0.01}, capital_context
        )
        self.assertFalse(evaluation["full_size_allowed"])


if __name__ == "__main__":
    unittest.main()
