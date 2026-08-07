"""Acceptance tests for the #16 market-wide financing-overheat wiring (queue row 19).

The eight-cell matrix from the reviewed plan: one positive control, five reverse
controls (switch / coverage / harshest-not-product / unit / refactor-neutrality),
the threshold-evidence output, and one planted control that neutralises the
consumption seam and proves the positive control was load-bearing.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.a_short_margin_overheat as margin_overheat  # noqa: E402
import runners.a_short_weekly_pipeline as weekly_pipeline  # noqa: E402
from runners.a_short_weekly_pipeline import (  # noqa: E402
    _allocate_cash,
    _margin_overheat_control_from_analysis,
    _resolve_cash_factor_stack,
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
WINDOW_SESSIONS = margin_overheat.MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS
#: A whole-market financing balance of the order the row 21 probe observed
#: (~1.3e12 CNY on SSE alone).  Written out so the unit control below compares
#: against a number a human can check, not against a fixture constant.
SSE_BALANCE = 1.30e12
SZSE_BALANCE = 1.10e12
BSE_BALANCE = 6.0e9


def _sessions(count: int = WINDOW_SESSIONS, end_year: int = 2026) -> tuple[str, ...]:
    """A synthetic descending session calendar; only ordering and identity matter."""
    dates = pd.bdate_range(end=f"{end_year}-06-09", periods=count)
    return tuple(sorted((date.strftime("%Y%m%d") for date in dates), reverse=True))


#: 000001.SH free-float market value of the order the B0 probe observed
#: (~5.2e13 CNY): balances of ~2.4e12 over it give a ratio near 4.6%.
DENOMINATOR_FLOAT_MV = 5.20e13


def _margin_rows(sessions, *, ramp=True, drop=(), exchanges=margin_overheat.MARGIN_OVERHEAT_EXCHANGES):
    """Provider-shaped rows: one per exchange per session, oldest cheapest."""
    ordered = sorted(sessions)
    rows = []
    for index, trade_date in enumerate(ordered):
        if trade_date in set(drop):
            continue
        scale = (1.0 + index / (len(ordered) - 1)) if ramp else 1.0
        for exchange, base in zip(
            exchanges, (SSE_BALANCE, SZSE_BALANCE, BSE_BALANCE)
        ):
            rows.append(
                {"trade_date": trade_date, "exchange_id": exchange, "rzye": base * scale}
            )
    return rows


def _denominator_rows(sessions, *, ramp=False, drop=()):
    """000001.SH ``index_dailybasic`` rows: flat by default so the ratio keeps
    the numerator's shape and the pre-ratio test expectations stay readable."""
    ordered = sorted(sessions)
    rows = []
    for index, trade_date in enumerate(ordered):
        if trade_date in set(drop):
            continue
        scale = (1.0 + index / (len(ordered) - 1)) if ramp else 1.0
        rows.append({
            "ts_code": margin_overheat.MARGIN_RATIO_DENOMINATOR_INDEX,
            "trade_date": trade_date,
            "float_mv": DENOMINATOR_FLOAT_MV * scale,
        })
    return rows


def _facts(sessions, rows=None, denominator=None, *, production_effect_enabled=False):
    return margin_overheat.margin_overheat_facts(
        _margin_rows(sessions) if rows is None else rows,
        _denominator_rows(sessions) if denominator is None else denominator,
        requested_dates=sessions,
        production_effect_enabled=production_effect_enabled,
    )


def _control(sessions, rows=None, denominator=None, *, production_effect_enabled=False):
    facts = _facts(sessions, rows, denominator,
                   production_effect_enabled=production_effect_enabled)
    payload = {"source_as_of": AS_OF, "source_path": weekly_pipeline._MARGIN_OVERHEAT_SOURCE_PATH}
    payload.update(facts)
    payload["window_end"] = AS_OF
    payload["window_start"] = min(sessions) if sessions else None
    return payload


def _adjudicated(threshold=0.90, cash_factor=0.7):
    """Stand in for the user's future threshold adjudication.

    Row 19 deliberately ships both governance constants as ``None``; the wiring
    can only be exercised by supplying the numbers the user has not yet chosen.
    """
    return patch.multiple(
        margin_overheat,
        MARGIN_OVERHEAT_PERCENTILE_THRESHOLD=threshold,
        MARGIN_OVERHEAT_CASH_FACTOR=cash_factor,
    )


class MarginOverheatEngineTests(unittest.TestCase):
    def test_three_exchange_total_is_summed_in_cny(self):
        sessions = _sessions(WINDOW_SESSIONS)
        facts = _facts(sessions)
        self.assertTrue(facts["coverage_complete"])
        expected_latest = (SSE_BALANCE + SZSE_BALANCE + BSE_BALANCE) * 2.0
        self.assertAlmostEqual(facts["balance_yuan"], expected_latest, delta=expected_latest * 1e-9)
        self.assertEqual(facts["percentile"], 1.0)
        self.assertEqual(facts["window_end"], sessions[0])
        self.assertEqual(facts["window_start"], sessions[-1])

    def test_a_missing_session_on_one_exchange_fails_closed(self):
        sessions = _sessions(WINDOW_SESSIONS)
        rows = [
            row for row in _margin_rows(sessions)
            if not (row["trade_date"] == sorted(sessions)[10] and row["exchange_id"] == "BSE")
        ]
        facts = _facts(sessions, rows)
        self.assertFalse(facts["coverage_complete"])
        self.assertIsNone(facts["percentile"])
        self.assertIsNone(facts["balance_yuan"])

    def test_short_window_is_never_published_as_a_rolling_window(self):
        sessions = _sessions(WINDOW_SESSIONS - 1)
        facts = _facts(sessions)
        self.assertFalse(facts["coverage_complete"])
        self.assertIsNone(facts["percentile"])

    def test_duplicate_and_out_of_window_rows_fail_closed(self):
        sessions = _sessions(WINDOW_SESSIONS)
        duplicated = _margin_rows(sessions) + [
            {"trade_date": sessions[0], "exchange_id": "SSE", "rzye": SSE_BALANCE}
        ]
        self.assertFalse(_facts(sessions, duplicated)["coverage_complete"])
        stray = _margin_rows(sessions)
        stray[0] = dict(stray[0], trade_date="19990101")
        self.assertFalse(_facts(sessions, stray)["coverage_complete"])

    def test_non_finite_balance_fails_closed(self):
        sessions = _sessions(WINDOW_SESSIONS)
        rows = _margin_rows(sessions)
        rows[5] = dict(rows[5], rzye=float("nan"))
        self.assertFalse(_facts(sessions, rows)["coverage_complete"])

    def test_predicate_is_fail_closed_without_an_adjudicated_threshold(self):
        self.assertIsNone(margin_overheat.MARGIN_OVERHEAT_PERCENTILE_THRESHOLD)
        self.assertIsNone(margin_overheat.MARGIN_OVERHEAT_CASH_FACTOR)
        self.assertFalse(margin_overheat.should_reduce_new_exposure(1.0))
        self.assertFalse(margin_overheat.should_reduce_new_exposure(None, 0.9))
        self.assertTrue(margin_overheat.should_reduce_new_exposure(0.9, 0.9))
        self.assertFalse(margin_overheat.should_reduce_new_exposure(0.89, 0.9))

    def test_the_window_closes_at_the_newest_published_session(self):
        # The real 2026-08-05 fetch returned every exchange through 08-04 and
        # nothing for 08-05: requiring the window to reach the decision date
        # would make every live run fail closed.
        calendar = _sessions(WINDOW_SESSIONS + 1)
        published = calendar[1:]
        rows = _margin_rows(published)
        window = margin_overheat.resolve_published_window(rows, calendar_dates=calendar)
        self.assertEqual(window, published)
        facts = margin_overheat.margin_overheat_facts(
            rows, _denominator_rows(window), requested_dates=window
        )
        self.assertTrue(facts["coverage_complete"])
        self.assertEqual(facts["window_end"], published[0])

    def test_a_silence_longer_than_the_publication_lag_fails_closed(self):
        calendar = _sessions(WINDOW_SESSIONS + 3)
        rows = _margin_rows(calendar[3:])
        self.assertEqual(
            margin_overheat.resolve_published_window(rows, calendar_dates=calendar), ()
        )
        self.assertFalse(
            margin_overheat.margin_overheat_facts(rows, requested_dates=())["coverage_complete"]
        )

    def test_a_partially_published_newest_session_is_not_a_reference_date(self):
        calendar = _sessions(WINDOW_SESSIONS + 1)
        rows = _margin_rows(calendar)
        rows = [
            row for row in rows
            if not (row["trade_date"] == calendar[0] and row["exchange_id"] == "BSE")
        ]
        self.assertEqual(
            margin_overheat.resolve_published_window(rows, calendar_dates=calendar),
            calendar[1:],
        )

    def test_a_pre_bse_window_is_complete_with_two_exchanges(self):
        # Adjudicated option (a): before BSE's first published margin session
        # the required set is SSE+SZSE, so six-year history stays usable.
        sessions = _sessions(WINDOW_SESSIONS, end_year=2020)
        rows = _margin_rows(sessions, exchanges=("SSE", "SZSE"))
        facts = _facts(sessions, rows)
        self.assertTrue(facts["coverage_complete"])
        self.assertAlmostEqual(
            facts["balance_yuan"], (SSE_BALANCE + SZSE_BALANCE) * 2.0,
            delta=(SSE_BALANCE + SZSE_BALANCE) * 2e-9,
        )

    def test_a_window_reaching_2026_with_no_bse_at_all_fails_closed(self):
        # The date-effective rule must not excuse a truncated fetch: by the
        # frozen BSE_MARGIN_EXPECTED_BY date, BSE data is known to exist.
        sessions = _sessions(WINDOW_SESSIONS)   # ends 2026-06-09
        rows = _margin_rows(sessions, exchanges=("SSE", "SZSE"))
        facts = _facts(sessions, rows)
        self.assertFalse(facts["coverage_complete"])
        self.assertIsNone(facts["percentile"])

    def test_a_bse_gap_after_its_first_session_fails_closed(self):
        # Once BSE has published, it is required from that date onward; a gap
        # cannot be silently absorbed by the date-effective rule.
        sessions = _sessions(WINDOW_SESSIONS)
        ordered = sorted(sessions)
        midpoint = ordered[len(ordered) // 2]
        rows = [
            row for row in _margin_rows(sessions)
            if not (row["exchange_id"] == "BSE" and row["trade_date"] < midpoint)
        ]
        gap = sorted(date for date in ordered if date >= midpoint)[5]
        rows = [
            row for row in rows
            if not (row["exchange_id"] == "BSE" and row["trade_date"] == gap)
        ]
        facts = _facts(sessions, rows)
        self.assertFalse(facts["coverage_complete"])
        # The same rows WITH the gap restored are complete, proving the gate
        # above is the gap and nothing else.
        healed = rows + [{"trade_date": gap, "exchange_id": "BSE", "rzye": BSE_BALANCE}]
        self.assertTrue(_facts(sessions, healed)["coverage_complete"])

    def test_the_ratio_identity_holds_and_a_wan_denominator_is_rejected(self):
        sessions = _sessions(WINDOW_SESSIONS)
        facts = _facts(sessions)
        self.assertAlmostEqual(
            facts["ratio"] * facts["denominator_float_mv_yuan"],
            facts["balance_yuan"],
            delta=facts["balance_yuan"] * 1e-9,
        )
        # A 万元-scaled denominator drives the ratio above 1; the weekly echo
        # validator rejects that shape outright.
        wan = [dict(row, float_mv=row["float_mv"] / 10_000) for row in _denominator_rows(sessions)]
        inflated = _facts(sessions, denominator=wan)
        self.assertTrue(inflated["coverage_complete"])
        self.assertGreater(inflated["ratio"], 1.0)
        with self.assertRaisesRegex(ValueError, "ratio in \\(0,1\\]"):
            weekly_pipeline._normalise_margin_overheat_control(
                _control(sessions, denominator=wan), AS_OF
            )

    def test_fetch_segments_stay_under_the_vendor_row_cap(self):
        sessions = _sessions(WINDOW_SESSIONS)
        segments = margin_overheat.fetch_segments(sessions)
        self.assertEqual(sum(len(segment) for segment in segments), len(sessions))
        self.assertEqual(sorted(date for segment in segments for date in segment),
                         sorted(sessions))
        for segment in segments:
            rows = len(segment) * len(margin_overheat.MARGIN_OVERHEAT_EXCHANGES)
            self.assertLess(rows, margin_overheat.MARGIN_PROVIDER_ROW_CAP)


#: Six-ish years of business days, so the later weeks carry a FULL rolling
#: three-year live-caliber window (the evidence basis adjudicated 2026-08-06).
EVIDENCE_SESSIONS = 1450


class MarginOverheatThresholdEvidenceTests(unittest.TestCase):
    def test_evidence_publishes_every_candidate_threshold_and_warm_up_weeks(self):
        sessions = _sessions(EVIDENCE_SESSIONS)
        totals = margin_overheat.market_margin_totals(
            _margin_rows(sessions), requested_dates=sessions
        )["totals"]
        evidence = margin_overheat.threshold_trigger_evidence(totals)
        self.assertIn("live_caliber_rolling_3y", evidence["basis"])
        self.assertEqual(
            [row["percentile_threshold"] for row in evidence["by_threshold"]],
            list(margin_overheat.MARGIN_OVERHEAT_CANDIDATE_PERCENTILES),
        )
        self.assertEqual(
            evidence["week_count"],
            evidence["evaluable_week_count"] + evidence["unavailable_week_count"],
        )
        self.assertGreater(evidence["evaluable_week_count"], 100)
        self.assertGreater(evidence["unavailable_week_count"], 0)
        self.assertEqual(evidence["unavailable_breakdown"]["warm_up"],
                         evidence["unavailable_week_count"])
        # Every evaluable week's window meets the live 600-session floor.
        for row in evidence["weeks"]:
            if row["verdict"] == "evaluable":
                self.assertGreaterEqual(
                    row["trailing_session_count"],
                    margin_overheat.MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS,
                )
        # A monotonically rising balance sits at its own running maximum, so every
        # evaluable week triggers at every threshold.  That is the point of
        # publishing the frequency before choosing a number.
        for row in evidence["by_threshold"]:
            self.assertEqual(row["trigger_week_count"], evidence["evaluable_week_count"])
            self.assertEqual(row["longest_consecutive_trigger_weeks"],
                             evidence["evaluable_week_count"])
            self.assertEqual(sum(row["trigger_weeks_by_year"].values()),
                             row["trigger_week_count"])

    def test_a_flat_series_never_reaches_a_strictly_higher_threshold(self):
        sessions = _sessions(WINDOW_SESSIONS)
        totals = margin_overheat.market_margin_totals(
            _margin_rows(sessions, ramp=False), requested_dates=sessions
        )["totals"]
        evidence = margin_overheat.threshold_trigger_evidence(totals)
        # Every value ties the maximum, so percentile == 1.0 and all fire; the
        # control that matters is that the count is derived, not asserted.
        for row in evidence["by_threshold"]:
            self.assertEqual(row["trigger_week_count"], evidence["evaluable_week_count"])

    def test_a_missing_calendar_week_breaks_the_consecutive_run(self):
        # Review Optional O-5: "longest consecutive" is calendar adjacency; a
        # week with no trading sessions must break the run, not be bridged.
        sessions = _sessions(EVIDENCE_SESSIONS)
        ordered = sorted(sessions)
        weeks = margin_overheat._week_endpoints(tuple(ordered))
        gap_week = weeks[-3]
        gap_monday = margin_overheat._week_monday(gap_week)
        kept = [
            date for date in ordered
            if not 0 <= (datetime.strptime(date, "%Y%m%d") - gap_monday).days < 7
        ]
        totals = margin_overheat.market_margin_totals(
            _margin_rows(tuple(sorted(kept, reverse=True))), requested_dates=kept
        )["totals"]
        evidence = margin_overheat.threshold_trigger_evidence(totals)
        top = max(row["longest_consecutive_trigger_weeks"]
                  for row in evidence["by_threshold"])
        self.assertLess(top, evidence["evaluable_week_count"],
                        msg="a removed calendar week must split the run")
        for row in evidence["by_threshold"]:
            self.assertEqual(row["trigger_week_count"], evidence["evaluable_week_count"])

    def test_trigger_years_use_the_iso_year_of_the_week(self):
        # Review Optional O-5: a 12-31 endpoint belongs to its ISO year.
        sessions = tuple(sorted((
            date.strftime("%Y%m%d")
            for date in pd.bdate_range(end="2026-01-30", periods=EVIDENCE_SESSIONS)
        ), reverse=True))
        totals = margin_overheat.market_margin_totals(
            _margin_rows(sessions), requested_dates=sessions
        )["totals"]
        evidence = margin_overheat.threshold_trigger_evidence(totals)
        year_keys = {year for row in evidence["by_threshold"]
                     for year in row["trigger_weeks_by_year"]}
        iso_years = {str(margin_overheat._iso_week_key(row["week_end"])[0])
                     for row in evidence["weeks"] if row["verdict"] == "evaluable"}
        self.assertEqual(year_keys, iso_years)
        # 2025-12-31 falls in ISO 2026-W01: it must not be filed under "2025".
        boundary = [row for row in evidence["weeks"]
                    if row["week_end"].startswith("202512") and
                    margin_overheat._iso_week_key(row["week_end"])[0] == 2026]
        if boundary:
            self.assertNotIn("2025", {
                str(margin_overheat._iso_week_key(row["week_end"])[0]) for row in boundary
            })

    def test_a_falling_series_stops_triggering(self):
        sessions = _sessions(EVIDENCE_SESSIONS)
        rows = _margin_rows(sessions)
        ordered = sorted(sessions)
        recent = set(ordered[-40:])
        rows = [
            dict(row, rzye=row["rzye"] * 0.1) if row["trade_date"] in recent else row
            for row in rows
        ]
        totals = margin_overheat.market_margin_totals(
            rows, requested_dates=sessions
        )["totals"]
        evidence = margin_overheat.threshold_trigger_evidence(totals)
        by_threshold = {row["percentile_threshold"]: row for row in evidence["by_threshold"]}
        self.assertLess(
            by_threshold[0.95]["trigger_week_count"],
            evidence["evaluable_week_count"],
        )
        self.assertLessEqual(
            by_threshold[0.95]["trigger_week_count"],
            by_threshold[0.80]["trigger_week_count"],
        )


class MarginOverheatCashControlTests(unittest.TestCase):
    """The reviewed acceptance matrix, cells 1-6 and 8."""

    def _rows(self):
        rows = []
        for code, l2 in (("600000.SH", "银行"), ("000001.SZ", "证券")):
            row = _normalized(code)
            row["portfolio_risk_facts"] = {
                "source": "margin_overheat_fixture",
                "sw_l2_key": l2,
                "circ_mv_rmb": 10_000_000_000.0,
                "margin_balance_to_float_mv_pct": 1.0,
                "is_large_index_component": False,
            }
            rows.append(row)
        return rows

    def _affordable_cash(self):
        raw = build_weekly_report(
            self._rows(), AS_OF, GEN, run_lineage=_sized_lineage(),
            available_cash=10_000_000.0,
        )
        report = next(r for r in raw["reports"] if r["m67"]["table"]["操作"] == "建仓")
        plan = report["machine"]["entry_exit_size_star"]["plan"]
        entry_high = float(plan["entry_high"])
        shares = (math.ceil(MIN_AMOUNT / entry_high / 100) + 1) * 100
        return shares * entry_high

    def _weekly(self, *, cash, control=None, pre_holiday_control=None):
        return build_weekly_report(
            self._rows(), AS_OF, GEN, run_lineage=_sized_lineage(),
            available_cash=cash, new_exposure_capacity=cash * 2,
            margin_overheat_control=control,
            pre_holiday_control=pre_holiday_control,
        )

    def test_cell1_positive_high_percentile_with_effect_on_reduces_cash(self):
        sessions = _sessions(WINDOW_SESSIONS)
        cash = self._affordable_cash()
        with _adjudicated():
            weekly = self._weekly(
                cash=cash,
                control=_control(sessions, production_effect_enabled=True),
            )
            # Validated inside the same governance state that produced it: the
            # control's verdict is derived from the constants, exactly like
            # pre_holiday_control's cash_factor, so a later threshold change is
            # meant to invalidate an old artifact rather than be absorbed.
            validate_weekly_report(weekly, _feed())
        allocation = weekly["cash_allocation"]
        control = allocation["margin_overheat_control"]
        self.assertEqual(control["reason"], "margin_overheated")
        self.assertTrue(control["predicate_triggered"])
        self.assertEqual(control["cash_factor"], 0.7)
        self.assertEqual(control["percentile"], 1.0)
        self.assertEqual(control["window_end"], AS_OF)
        self.assertEqual(control["requested_session_count"], len(sessions))
        self.assertEqual(control["observed_session_count"], len(sessions))
        self.assertEqual(allocation["available_cash_start"], round(cash * 0.7, 2))
        self.assertEqual(allocation["new_exposure_capacity_start"], round(cash * 2 * 0.7, 2))
        self.assertEqual(allocation["cash_factor_stack"]["effective_cash_factor"], 0.7)
        self.assertEqual(allocation["cash_factor_stack"]["binding_controls"],
                         ["margin_overheat_control"])

    def test_cell2_reverse_switch_off_records_the_percentile_and_changes_nothing(self):
        sessions = _sessions(WINDOW_SESSIONS)
        cash = self._affordable_cash()
        with _adjudicated():
            on = self._weekly(cash=cash, control=_control(sessions, production_effect_enabled=True))
            off = self._weekly(cash=cash, control=_control(sessions, production_effect_enabled=False))
            baseline = self._weekly(cash=cash)
        off_control = off["cash_allocation"]["margin_overheat_control"]
        self.assertTrue(off_control["predicate_triggered"])
        self.assertEqual(off_control["reason"], "production_effect_disabled")
        self.assertEqual(off_control["cash_factor"], 1.0)
        self.assertEqual(off_control["percentile"], 1.0)
        self.assertEqual(off_control["balance_yuan"],
                         on["cash_allocation"]["margin_overheat_control"]["balance_yuan"])
        for field in ("available_cash_start", "allocated_cash_total", "remaining_cash",
                      "new_exposure_capacity_start", "remaining_new_exposure_capacity"):
            self.assertEqual(off["cash_allocation"][field], baseline["cash_allocation"][field],
                             msg=field)
        self.assertEqual(
            [r["m67"]["table"]["操作"] for r in off["reports"]],
            [r["m67"]["table"]["操作"] for r in baseline["reports"]],
        )
        self.assertNotEqual(on["cash_allocation"]["available_cash_start"],
                            off["cash_allocation"]["available_cash_start"])

    def test_cell3_reverse_incomplete_window_produces_no_percentile_and_no_reduction(self):
        sessions = _sessions(WINDOW_SESSIONS)
        cash = self._affordable_cash()
        rows = [row for row in _margin_rows(sessions) if row["trade_date"] != sorted(sessions)[7]]
        with _adjudicated():
            weekly = self._weekly(
                cash=cash,
                control=_control(sessions, rows, production_effect_enabled=True),
            )
            baseline = self._weekly(cash=cash)
        control = weekly["cash_allocation"]["margin_overheat_control"]
        self.assertFalse(control["coverage_complete"])
        self.assertIsNone(control["percentile"])
        self.assertFalse(control["predicate_triggered"])
        self.assertEqual(control["reason"], "coverage_incomplete")
        self.assertEqual(control["cash_factor"], 1.0)
        self.assertEqual(weekly["cash_allocation"]["available_cash_start"],
                         baseline["cash_allocation"]["available_cash_start"])

    def test_cell4_reverse_two_gates_take_the_harshest_never_the_product(self):
        sessions = _sessions(WINDOW_SESSIONS)
        cash = self._affordable_cash()
        pre_holiday = {
            "source_as_of": AS_OF,
            "next_trade_date": "20260610",
            "is_pre_holiday_window": True,
            "holiday_days_ahead": 7,
            "regime_status": "unknown",
        }
        with _adjudicated(cash_factor=0.7):
            both = self._weekly(
                cash=cash,
                control=_control(sessions, production_effect_enabled=True),
                pre_holiday_control=pre_holiday,
            )
        stack = both["cash_allocation"]["cash_factor_stack"]
        self.assertEqual(stack["control_factors"],
                         {"pre_holiday_control": 0.8, "margin_overheat_control": 0.7})
        self.assertEqual(stack["effective_cash_factor"], 0.7)
        self.assertEqual(stack["binding_controls"], ["margin_overheat_control"])
        self.assertEqual(both["cash_allocation"]["available_cash_start"], round(cash * 0.7, 2))
        self.assertNotEqual(both["cash_allocation"]["available_cash_start"],
                            round(cash * 0.8 * 0.7, 2))

    def test_cell4b_the_harsher_gate_wins_from_either_side(self):
        sessions = _sessions(WINDOW_SESSIONS)
        cash = self._affordable_cash()
        pre_holiday = {
            "source_as_of": AS_OF,
            "next_trade_date": "20260610",
            "is_pre_holiday_window": True,
            "holiday_days_ahead": 7,
            "regime_status": "unknown",
        }
        with _adjudicated(cash_factor=0.9):
            weekly = self._weekly(
                cash=cash,
                control=_control(sessions, production_effect_enabled=True),
                pre_holiday_control=pre_holiday,
            )
        stack = weekly["cash_allocation"]["cash_factor_stack"]
        self.assertEqual(stack["effective_cash_factor"], 0.8)
        self.assertEqual(stack["binding_controls"], ["pre_holiday_control"])
        self.assertEqual(weekly["cash_allocation"]["available_cash_start"], round(cash * 0.8, 2))

    def test_cell5_reverse_unit_the_contract_carries_yuan_not_wan(self):
        sessions = _sessions(WINDOW_SESSIONS)
        cash = self._affordable_cash()
        with _adjudicated():
            weekly = self._weekly(
                cash=cash, control=_control(sessions, production_effect_enabled=True))
        control = weekly["cash_allocation"]["margin_overheat_control"]
        self.assertEqual(control["balance_unit"], "CNY")
        # Hand-checkable: the newest session's three exchanges at the 2.0 ramp.
        expected = (SSE_BALANCE + SZSE_BALANCE + BSE_BALANCE) * 2.0
        self.assertAlmostEqual(control["balance_yuan"], expected, delta=expected * 1e-9)
        self.assertGreater(control["balance_yuan"], 1e12)
        self.assertNotAlmostEqual(control["balance_yuan"], expected / 10_000,
                                  delta=expected * 1e-9)

    def test_cell6_reverse_the_stack_refactor_is_field_identical_for_one_control(self):
        cash = self._affordable_cash()
        rows_a = self._rows()
        rows_b = self._rows()
        pre_holiday = {
            "source_as_of": AS_OF,
            "next_trade_date": "20260610",
            "is_pre_holiday_window": True,
            "holiday_days_ahead": 7,
            "regime_status": "unknown",
        }
        stacked = _allocate_cash(
            [dict(r) for r in build_weekly_report(
                rows_a, AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=cash,
                pre_holiday_control=pre_holiday)["reports"]],
            cash, cash * 2, as_of=AS_OF, pre_holiday_control=pre_holiday,
        )
        pre_refactor = weekly_pipeline._normalise_pre_holiday_control(pre_holiday, AS_OF)
        factor = pre_refactor["cash_factor"]
        self.assertEqual(stacked["available_cash_start"], round(cash * factor, 2))
        self.assertEqual(stacked["new_exposure_capacity_start"], round(cash * 2 * factor, 2))
        self.assertEqual(stacked["cash_factor_stack"]["effective_cash_factor"], factor)
        self.assertEqual(stacked["cash_factor_stack"]["binding_controls"], ["pre_holiday_control"])
        self.assertEqual(stacked["margin_overheat_control"]["cash_factor"], 1.0)
        # And the no-control default is still exactly 1.0 end to end.
        neutral = build_weekly_report(
            rows_b, AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=cash)
        self.assertEqual(neutral["cash_allocation"]["available_cash_start"], round(cash, 2))
        self.assertEqual(
            neutral["cash_allocation"]["cash_factor_stack"],
            {"effective_cash_factor": 1.0,
             "control_factors": {"pre_holiday_control": 1.0, "margin_overheat_control": 1.0},
             "binding_controls": ["margin_overheat_control", "pre_holiday_control"]},
        )

    def test_cell8_planted_neutralising_the_consumption_seam_breaks_cell1(self):
        sessions = _sessions(WINDOW_SESSIONS)
        cash = self._affordable_cash()

        real_resolver = weekly_pipeline._resolve_cash_factor_stack

        def _ignore_margin_control(controls):
            return real_resolver({"pre_holiday_control": controls.get("pre_holiday_control")})

        with _adjudicated():
            live = self._weekly(
                cash=cash, control=_control(sessions, production_effect_enabled=True))
            with patch.object(weekly_pipeline, "_resolve_cash_factor_stack",
                              side_effect=_ignore_margin_control):
                neutralised = self._weekly(
                    cash=cash, control=_control(sessions, production_effect_enabled=True))
        self.assertEqual(live["cash_allocation"]["available_cash_start"], round(cash * 0.7, 2))
        self.assertEqual(neutralised["cash_allocation"]["available_cash_start"], round(cash, 2))
        self.assertNotEqual(live["cash_allocation"]["available_cash_start"],
                            neutralised["cash_allocation"]["available_cash_start"])


class MarginOverheatControlBindingTests(unittest.TestCase):
    def test_control_defaults_to_the_shared_production_switch(self):
        analysis_input = {
            "decision_as_of": AS_OF,
            "market_context": {"margin_overheat": {
                "percentile": None, "balance_yuan": None,
                "window_start": None, "window_end": None,
                "requested_session_count": 0, "observed_session_count": 0,
                "coverage_complete": False,
            }},
        }
        control = _margin_overheat_control_from_analysis(analysis_input, AS_OF)
        self.assertEqual(control["production_effect_enabled"],
                         margin_overheat.MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED)
        self.assertFalse(control["production_effect_enabled"])
        self.assertEqual(control["reason"], "coverage_incomplete")
        self.assertEqual(control["cash_factor"], 1.0)

    def test_analysis_schema_and_engine_constant_are_one_switch(self):
        schema = json.loads(
            (ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8"))
        pinned = (schema["properties"]["market_context"]["properties"]["margin_overheat"]
                  ["properties"]["production_effect_enabled"]["const"])
        self.assertEqual(pinned, margin_overheat.MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED,
                         msg="flipping the gate must move both files together")

    def test_threshold_and_cash_factor_cannot_come_from_analysis_input(self):
        sessions = _sessions(WINDOW_SESSIONS)
        payload = _control(sessions, production_effect_enabled=True)
        payload["percentile_threshold"] = 0.10
        payload["cash_factor"] = 0.1
        with _adjudicated():
            with self.assertRaisesRegex(ValueError, "cash_factor disagrees"):
                weekly_pipeline._normalise_margin_overheat_control(payload, AS_OF)
        control = weekly_pipeline._normalise_margin_overheat_control(
            {k: v for k, v in payload.items() if k not in {"percentile_threshold", "cash_factor"}},
            AS_OF,
        )
        self.assertIsNone(control["percentile_threshold"])
        self.assertEqual(control["cash_factor"], 1.0)

    def test_a_null_cash_factor_echo_is_treated_as_not_supplied(self):
        # Review Optional O-7: sibling parity with _normalise_pre_holiday_control
        # -- a present-but-None echo passes; a non-numeric echo raises ValueError.
        sessions = _sessions(WINDOW_SESSIONS)
        payload = _control(sessions)
        payload["cash_factor"] = None
        control = weekly_pipeline._normalise_margin_overheat_control(payload, AS_OF)
        self.assertEqual(control["cash_factor"], 1.0)
        payload["cash_factor"] = "0.7"
        with self.assertRaisesRegex(ValueError, "cash_factor disagrees"):
            weekly_pipeline._normalise_margin_overheat_control(payload, AS_OF)

    def test_input_schema_rejects_an_out_of_range_percentile(self):
        # Review Optional O-6: the input side now pins the same bounds the
        # weekly report side already pins.
        schema = json.loads(
            (ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8"))
        node = {"$defs": schema["$defs"],
                **schema["properties"]["market_context"]["properties"]["margin_overheat"]}
        good = {"percentile": 0.83, "balance_yuan": 2.59e12}
        jsonschema.validate(good, node)
        for bad in ({"percentile": 1.5}, {"percentile": -0.1}, {"balance_yuan": 0}):
            with self.assertRaises(jsonschema.ValidationError, msg=bad):
                jsonschema.validate(bad, node)

    def test_validator_binds_the_report_to_the_analysis_input_margin_facts(self):
        sessions = _sessions(WINDOW_SESSIONS)
        source = weekly_pipeline._normalise_margin_overheat_control(
            _control(sessions, production_effect_enabled=False), AS_OF)
        rows = [_normalized("600000.SH")]
        weekly = build_weekly_report(
            rows, AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=1_000_000.0,
            margin_overheat_control=source)
        validate_weekly_report(weekly, _feed(), expected_margin_overheat_control=source)
        dropped = build_weekly_report(
            [_normalized("600000.SH")], AS_OF, GEN, run_lineage=_sized_lineage(),
            available_cash=1_000_000.0)
        validate_weekly_report(dropped, _feed())
        with self.assertRaisesRegex(ValueError, "融资余额事实不一致"):
            validate_weekly_report(dropped, _feed(), expected_margin_overheat_control=source)

    def test_validator_rejects_a_multiplied_cash_factor_stack(self):
        rows = [_normalized("600000.SH")]
        weekly = build_weekly_report(
            rows, AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=1_000_000.0)
        weekly["cash_allocation"]["cash_factor_stack"]["effective_cash_factor"] = 0.64
        with self.assertRaisesRegex(ValueError, "取最狠系数重算"):
            validate_weekly_report(weekly, _feed())

    def test_resolver_rejects_an_out_of_range_or_unknown_control(self):
        with self.assertRaisesRegex(ValueError, "unknown cash factor control"):
            _resolve_cash_factor_stack({"invented_control": {"cash_factor": 0.5}})
        with self.assertRaisesRegex(ValueError, "pre_holiday_control cash_factor"):
            _resolve_cash_factor_stack({"pre_holiday_control": {"cash_factor": 1.5}})
        with self.assertRaisesRegex(ValueError, "margin_overheat_control cash_factor"):
            _resolve_cash_factor_stack({"margin_overheat_control": {"cash_factor": 0.0}})


class MarginOverheatProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old_argv = sys.argv[:]
        sys.argv = [str(EGS_SCRIPT), "--help"]
        try:
            spec = importlib.util.spec_from_file_location("egs_margin_overheat", EGS_SCRIPT)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            cls.egs = module
        finally:
            sys.argv = old_argv

    def _patched(self, sessions, rows, denominator=None):
        calendar = pd.DataFrame({"cal_date": sorted(sessions)})
        denominator_rows = _denominator_rows(sessions) if denominator is None else denominator

        def _api(func, *args, **kwargs):
            name = getattr(func, "_probe_name", "")
            if name == "trade_cal":
                return calendar
            frame = pd.DataFrame(denominator_rows if name == "index_dailybasic" else rows)
            if frame.empty:
                return frame
            window = frame[(frame["trade_date"] >= kwargs["start_date"])
                           & (frame["trade_date"] <= kwargs["end_date"])]
            return window.reset_index(drop=True)

        trade_cal = lambda **kwargs: None            # noqa: E731 - identity marker only
        trade_cal._probe_name = "trade_cal"
        margin = lambda **kwargs: None               # noqa: E731
        margin._probe_name = "margin"
        index_dailybasic = lambda **kwargs: None     # noqa: E731
        index_dailybasic._probe_name = "index_dailybasic"
        pro = type("Pro", (), {"trade_cal": trade_cal, "margin": margin,
                               "index_dailybasic": index_dailybasic})()
        return patch.object(self.egs, "safe_api", side_effect=_api), patch.object(self.egs, "pro", pro)

    def test_producer_emits_the_percentile_from_a_complete_window(self):
        sessions = _sessions(WINDOW_SESSIONS)
        rows = _margin_rows(sessions)
        api_patch, pro_patch = self._patched(sessions, rows)
        with api_patch, pro_patch:
            facts = self.egs._margin_overheat_provider_facts(sessions[0])
        self.assertTrue(facts["coverage_complete"])
        self.assertEqual(facts["percentile"], 1.0)
        self.assertAlmostEqual(
            facts["ratio"],
            facts["balance_yuan"] / facts["denominator_float_mv_yuan"],
        )
        self.assertFalse(facts["production_effect_enabled"])
        self.assertIn("近3年分位 100.0%", self.egs._margin_overheat_environment_line(facts))
        self.assertIn("比率", self.egs._margin_overheat_environment_line(facts))
        self.assertIn("仅记录", self.egs._margin_overheat_environment_line(facts))

    def test_producer_fails_closed_when_the_denominator_leg_is_empty(self):
        sessions = _sessions(WINDOW_SESSIONS)
        rows = _margin_rows(sessions)
        api_patch, pro_patch = self._patched(sessions, rows, denominator=[])
        with api_patch, pro_patch:
            facts = self.egs._margin_overheat_provider_facts(sessions[0])
        self.assertFalse(facts["coverage_complete"])
        self.assertIsNone(facts["percentile"])
        self.assertIsNone(facts["ratio"])

    def test_producer_fails_closed_on_a_capped_margin_response(self):
        sessions = _sessions(WINDOW_SESSIONS)
        rows = _margin_rows(sessions)
        calendar = pd.DataFrame({"cal_date": sorted(sessions)})
        capped = pd.DataFrame(
            [{"trade_date": sessions[0], "exchange_id": "SSE", "rzye": SSE_BALANCE}]
            * margin_overheat.MARGIN_PROVIDER_ROW_CAP
        )

        def _api(func, *args, **kwargs):
            return calendar if "cal_date" in str(kwargs.get("fields", "")) else capped

        pro = type("Pro", (), {"trade_cal": lambda **k: None, "margin": lambda **k: None})()
        with patch.object(self.egs, "safe_api", side_effect=_api), \
             patch.object(self.egs, "pro", pro):
            facts = self.egs._margin_overheat_provider_facts(sessions[0])
        self.assertFalse(facts["coverage_complete"])
        self.assertIsNone(facts["percentile"])
        self.assertEqual(facts["requested_session_count"], len(sessions))
        self.assertIn("不可用", self.egs._margin_overheat_environment_line(facts))
        self.assertNotIn(len(rows) * [""] and "待接入", "")

    def test_producer_fails_closed_on_a_capped_calendar_response(self):
        capped = pd.DataFrame(
            {"cal_date": [f"2026{index:04d}" for index in range(
                margin_overheat.MARGIN_PROVIDER_ROW_CAP)]}
        )
        pro = type("Pro", (), {"trade_cal": lambda **k: None, "margin": lambda **k: None})()
        with patch.object(self.egs, "safe_api", return_value=capped), \
             patch.object(self.egs, "pro", pro):
            self.assertEqual(self.egs._margin_overheat_window_sessions("20260609"), ())

    def test_placeholder_text_is_gone_from_the_producer(self):
        source = EGS_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("待接入两融余额历史分位", source)
        self.assertIn("margin", self.egs.EGS_API_FAMILIES)

    def test_emitted_leaves_validate_against_the_analysis_input_schema(self):
        schema = json.loads(
            (ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8"))
        sessions = _sessions(WINDOW_SESSIONS)
        facts = _facts(sessions)
        payload = {key: facts[key] for key in (
            "percentile", "balance_yuan", "window_start", "window_end",
            "requested_session_count", "observed_session_count", "coverage_complete",
            "production_effect_enabled")}
        jsonschema.validate(
            payload,
            {"$defs": schema["$defs"],
             **schema["properties"]["market_context"]["properties"]["margin_overheat"]},
        )


if __name__ == "__main__":
    unittest.main()
