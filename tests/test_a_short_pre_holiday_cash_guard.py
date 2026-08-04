from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_weekly_pipeline import (  # noqa: E402
    _allocate_cash,
    _pre_holiday_control_from_analysis,
    validate_weekly_report,
)
from tests.test_a_short_weekly_pipeline import (  # noqa: E402
    AS_OF,
    GEN,
    build_weekly_report,
    _feed,
    _normalized,
    _sized_lineage,
)
from runners.a_short_phase5_engine import MIN_AMOUNT  # noqa: E402


EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_pre_holiday_guard", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _calendar_frame(start: str, end: str, open_dates: set[str]) -> pd.DataFrame:
    begin = datetime.strptime(start, "%Y%m%d")
    finish = datetime.strptime(end, "%Y%m%d")
    rows = []
    current = begin
    while current <= finish:
        date = current.strftime("%Y%m%d")
        rows.append({"cal_date": date, "is_open": int(date in open_dates)})
        current += timedelta(days=1)
    return pd.DataFrame(rows)


class PreHolidayCalendarProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs_module()

    def test_last_weekly_run_before_long_closure_is_source_bound(self):
        frame = _calendar_frame(
            "20260928", "20261008",
            {"20260928", "20260929", "20260930", "20261008"},
        )
        with patch.object(self.egs, "load_cache", return_value=None), \
             patch.object(self.egs, "save_cache"), \
             patch.object(self.egs, "safe_api", return_value=frame) as fetch:
            context = self.egs.get_trade_calendar_context("20260928")
        self.assertEqual(fetch.call_args.kwargs["fields"], "cal_date,is_open")
        self.assertEqual(context["decision_as_of"], "20260928")
        self.assertEqual(context["next_trade_date"], "20260929")
        self.assertTrue(context["is_pre_holiday_window"])
        self.assertEqual(context["holiday_days_ahead"], 7)

    def test_two_weeks_before_same_holiday_does_not_trigger(self):
        frame = _calendar_frame(
            "20260921", "20261008",
            {"20260921", "20260922", "20260923", "20260924", "20260925",
             "20260928", "20260929", "20260930", "20261008"},
        )
        with patch.object(self.egs, "load_cache", return_value=None), \
             patch.object(self.egs, "save_cache"), \
             patch.object(self.egs, "safe_api", return_value=frame):
            context = self.egs.get_trade_calendar_context("20260921")
        self.assertFalse(context["is_pre_holiday_window"])
        self.assertEqual(context["holiday_days_ahead"], 0)

    def test_four_closed_days_does_not_trigger(self):
        frame = _calendar_frame(
            "20260928", "20261005",
            {"20260928", "20260929", "20260930", "20261005"},
        )
        with patch.object(self.egs, "load_cache", return_value=None), \
             patch.object(self.egs, "save_cache"), \
             patch.object(self.egs, "safe_api", return_value=frame):
            context = self.egs.get_trade_calendar_context("20260928")
        self.assertFalse(context["is_pre_holiday_window"])
        self.assertEqual(context["holiday_days_ahead"], 0)

    def test_missing_is_open_column_fails_closed(self):
        malformed = pd.DataFrame({"cal_date": ["20260928"]})
        with patch.object(self.egs, "load_cache", return_value=None), \
             patch.object(self.egs, "safe_api", return_value=malformed):
            with self.assertRaisesRegex(RuntimeError, "cal_date,is_open"):
                self.egs.get_trade_calendar_context("20260928")


class PreHolidayCashConsumerTests(unittest.TestCase):
    def _row(self):
        row = _normalized("600000.SH")
        row["portfolio_risk_facts"] = {
            "source": "pre_holiday_fixture",
            "sw_l2_key": "bank",
            "circ_mv_rmb": 10_000_000_000.0,
            "margin_balance_to_float_mv_pct": 1.0,
            "is_large_index_component": False,
        }
        return row

    def _rows(self):
        rows = []
        for code, l2 in (("600000.SH", "bank"), ("600519.SH", "consumer"),
                         ("601318.SH", "health")):
            row = _normalized(code)
            row["portfolio_risk_facts"] = {
                "source": "pre_holiday_fixture",
                "sw_l2_key": l2,
                "circ_mv_rmb": 10_000_000_000.0,
                "margin_balance_to_float_mv_pct": 1.0,
                "is_large_index_component": False,
            }
            rows.append(row)
        return rows

    def test_unknown_regime_reduces_only_new_entry_cash_and_emits_audit(self):
        rows = self._rows()
        raw = build_weekly_report(
            rows, AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=10_000_000.0
        )
        report = next(r for r in raw["reports"] if r["m67"]["table"]["操作"] == "建仓")
        plan = report["machine"]["entry_exit_size_star"]["plan"]
        entry_high = float(plan["entry_high"])
        normal_shares = (math.ceil(MIN_AMOUNT / entry_high / 100) + 1) * 100
        available_cash = normal_shares * entry_high
        normal = build_weekly_report(
            self._rows(), AS_OF, GEN, run_lineage=_sized_lineage(),
            available_cash=available_cash,
            new_exposure_capacity=available_cash * 2,
        )
        holiday = build_weekly_report(
            self._rows(), AS_OF, GEN, run_lineage=_sized_lineage(),
            available_cash=available_cash,
            new_exposure_capacity=available_cash * 2,
            pre_holiday_control={
                "source_as_of": AS_OF,
                "next_trade_date": "20260610",
                "is_pre_holiday_window": True,
                "holiday_days_ahead": 7,
                "regime_status": "unknown",
            },
        )
        self.assertEqual(normal["reports"][0]["m67"]["table"]["操作"], "建仓")
        self.assertEqual(holiday["reports"][0]["m67"]["table"]["操作"], "观察")
        control = holiday["cash_allocation"]["pre_holiday_control"]
        self.assertEqual(control["cash_factor"], 0.8)
        self.assertEqual(holiday["cash_allocation"]["available_cash_start"],
                         round(available_cash * 0.8, 2))
        self.assertEqual(holiday["cash_allocation"]["new_exposure_capacity_start"],
                         round(available_cash * 2 * 0.8, 2))
        validate_weekly_report(holiday, _feed())

    def test_attack_regime_is_the_only_pre_holiday_exemption(self):
        rows = self._rows()
        raw = build_weekly_report(
            rows, AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=10_000_000.0
        )
        report = next(r for r in raw["reports"] if r["m67"]["table"]["操作"] == "建仓")
        plan = report["machine"]["entry_exit_size_star"]["plan"]
        available_cash = float(plan["raw_shares"]) * float(plan["entry_high"]) * 1.05
        holiday_attack = build_weekly_report(
            self._rows(), AS_OF, GEN, run_lineage=_sized_lineage(),
            available_cash=available_cash,
            pre_holiday_control={
                "source_as_of": AS_OF,
                "next_trade_date": "20260610",
                "is_pre_holiday_window": True,
                "holiday_days_ahead": 7,
                "regime_status": "attack",
            },
        )
        self.assertEqual(holiday_attack["cash_allocation"]["pre_holiday_control"]["cash_factor"], 1.0)
        self.assertEqual(holiday_attack["reports"][0]["m67"]["table"]["操作"], "建仓")

    def test_bad_or_unbound_calendar_control_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "qualifying source-bound closure"):
            build_weekly_report(
                self._rows(), AS_OF, GEN, run_lineage=_sized_lineage(),
                available_cash=100_000.0,
                pre_holiday_control={
                    "source_as_of": AS_OF,
                    "next_trade_date": "20260610",
                    "is_pre_holiday_window": True,
                    "holiday_days_ahead": 4,
                    "regime_status": "unknown",
                },
            )
        with self.assertRaisesRegex(ValueError, "not bound"):
            _pre_holiday_control_from_analysis({
                "decision_as_of": "20260608",
                "market_context": {
                    "trade_calendar": {"is_pre_holiday_window": False},
                    "market_regime": {"status": "unknown"},
                },
            }, AS_OF)
        with self.assertRaisesRegex(ValueError, "requires weekly as_of"):
            _allocate_cash(
                [], 100_000.0,
                pre_holiday_control={
                    "source_as_of": AS_OF,
                    "next_trade_date": "20260610",
                    "is_pre_holiday_window": True,
                    "holiday_days_ahead": 7,
                    "regime_status": "unknown",
                    "cash_factor": 0.8,
                },
            )


if __name__ == "__main__":
    unittest.main()
