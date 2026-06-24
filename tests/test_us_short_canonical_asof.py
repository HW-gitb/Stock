# -*- coding: utf-8 -*-
"""Tests for the US-short canonical decision-day resolver (engine/us_short_canonical_asof.py) — batch4 slice 4a.

Design authority: docs/us_short_system_design.md §2.1 / §3.5 / §18.2 batch4 row.

Adversarial focus (fewer FAIL->修复 rounds): the load-bearing behaviour is the US-specific
intraday DEAD ZONE (fail-closed OutOfWindowError) and its boundaries (open inclusive / close
exclusive), which A-share's single-cutoff resolver lacks. We pair every dead-zone assertion
with a positive control (weekend / premarket must NOT raise) and prove window-internal
convergence (Fri-close / weekend / Mon-premarket all -> the same Monday decision_date), plus
adversarial malformed-session inputs against the resolver's own strict validators.
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_canonical_asof as ca  # noqa: E402

# Mnemonic injected trading-session dates (the resolver is calendar-agnostic; holidays are
# simulated by OMITTING a session, half-days by a "close" override).
FRI = "20260612"
SAT = "20260613"  # not a trading session (weekend)
SUN = "20260614"  # not a trading session (weekend)
MON = "20260615"
TUE = "20260616"
WED = "20260617"


def _sess(date, open_=None, close=None):
    d = {"date": date}
    if open_ is not None:
        d["open"] = open_
    if close is not None:
        d["close"] = close
    return d


def _dt(date, hh, mm, ss=0):
    return datetime(int(date[:4]), int(date[4:6]), int(date[6:]), hh, mm, ss)


_FULL_WEEK = [_sess(FRI), _sess(MON), _sess(TUE)]


class LegalWindowTests(unittest.TestCase):
    """Outside any session's [open, close) -> resolve to the next upcoming session."""

    def test_friday_after_close_to_monday(self):
        r = ca.resolve_canonical_asof(_dt(FRI, 16, 30), _FULL_WEEK)
        self.assertEqual(r["decision_date"], MON)
        self.assertEqual(r["price_basis_date"], FRI)
        self.assertEqual(r["window_state"], "live")
        self.assertEqual(r["session_scope"], "RTH")
        self.assertEqual(r["run_date"], FRI)

    def test_saturday_to_monday(self):
        r = ca.resolve_canonical_asof(_dt(SAT, 10, 0), _FULL_WEEK)
        self.assertEqual(r["decision_date"], MON)
        self.assertEqual(r["price_basis_date"], FRI)

    def test_sunday_to_monday(self):
        r = ca.resolve_canonical_asof(_dt(SUN, 18, 0), _FULL_WEEK)
        self.assertEqual(r["decision_date"], MON)
        self.assertEqual(r["price_basis_date"], FRI)

    def test_monday_premarket_to_monday(self):
        # Monday 08:00 ET, before 09:30 open -> still deciding FOR Monday (NOT a dead zone).
        r = ca.resolve_canonical_asof(_dt(MON, 8, 0), _FULL_WEEK)
        self.assertEqual(r["decision_date"], MON)
        self.assertEqual(r["price_basis_date"], FRI)

    def test_monday_close_exact_rolls_to_tuesday(self):
        # 16:00:00 exactly -> settled ("收盘后才 roll") -> next session.
        r = ca.resolve_canonical_asof(_dt(MON, 16, 0, 0), _FULL_WEEK)
        self.assertEqual(r["decision_date"], TUE)
        self.assertEqual(r["price_basis_date"], MON)

    def test_monday_after_close_rolls_to_tuesday(self):
        r = ca.resolve_canonical_asof(_dt(MON, 16, 30), _FULL_WEEK)
        self.assertEqual(r["decision_date"], TUE)
        self.assertEqual(r["price_basis_date"], MON)

    def test_session_scope_always_rth(self):
        # session_scope is hardcoded RTH (no caller param) so it can never disagree with price_clock.
        r = ca.resolve_canonical_asof(_dt(SAT, 10, 0), _FULL_WEEK)
        self.assertEqual(r["session_scope"], "RTH")


class HolidayRollTests(unittest.TestCase):
    """Holidays are simulated by omitting the session -> roll forward, basis = last real close."""

    def test_monday_holiday_rolls_to_tuesday(self):
        sessions = [_sess(FRI), _sess(TUE)]  # Monday is a holiday (omitted)
        r = ca.resolve_canonical_asof(_dt(SAT, 10, 0), sessions)
        self.assertEqual(r["decision_date"], TUE)
        self.assertEqual(r["price_basis_date"], FRI)

    def test_double_holiday_rolls_to_wednesday(self):
        sessions = [_sess(FRI), _sess(WED)]  # Mon + Tue holidays
        r = ca.resolve_canonical_asof(_dt(SUN, 12, 0), sessions)
        self.assertEqual(r["decision_date"], WED)
        self.assertEqual(r["price_basis_date"], FRI)


class DeadZoneTests(unittest.TestCase):
    """Intraday [open, close) -> fail-closed OutOfWindowError (the US-specific divergence)."""

    def test_monday_midday_raises(self):
        with self.assertRaises(ca.OutOfWindowError):
            ca.resolve_canonical_asof(_dt(MON, 11, 0), _FULL_WEEK)

    def test_monday_open_exact_raises(self):
        # 09:30:00 exactly is NOT "before open" -> dead zone (must decide strictly before open).
        with self.assertRaises(ca.OutOfWindowError):
            ca.resolve_canonical_asof(_dt(MON, 9, 30, 0), _FULL_WEEK)

    def test_monday_one_second_before_close_raises(self):
        with self.assertRaises(ca.OutOfWindowError):
            ca.resolve_canonical_asof(_dt(MON, 15, 59, 59), _FULL_WEEK)

    def test_dead_zone_takes_precedence_over_complete_window(self):
        # Even with a full upcoming+settled window, an intraday now still fails closed.
        with self.assertRaises(ca.OutOfWindowError):
            ca.resolve_canonical_asof(_dt(MON, 12, 0), [_sess(FRI), _sess(MON), _sess(TUE)])

    def test_half_day_intraday_raises(self):
        sessions = [_sess(FRI), _sess(MON, close="13:00"), _sess(TUE)]
        with self.assertRaises(ca.OutOfWindowError):
            ca.resolve_canonical_asof(_dt(MON, 11, 0), sessions)  # 11:00 in [09:30, 13:00)

    def test_half_day_after_early_close_rolls(self):
        sessions = [_sess(FRI), _sess(MON, close="13:00"), _sess(TUE)]
        r = ca.resolve_canonical_asof(_dt(MON, 14, 0), sessions)  # 14:00 >= 13:00 close -> settled
        self.assertEqual(r["decision_date"], TUE)
        self.assertEqual(r["price_basis_date"], MON)

    def test_half_day_premarket_not_dead_zone(self):
        # Positive control: premarket on a half-day still resolves to that day (not a dead zone).
        sessions = [_sess(FRI), _sess(MON, close="13:00"), _sess(TUE)]
        r = ca.resolve_canonical_asof(_dt(MON, 8, 0), sessions)
        self.assertEqual(r["decision_date"], MON)
        self.assertEqual(r["price_basis_date"], FRI)

    def test_normal_close_time_after_1pm_not_dead_zone_on_regular_day(self):
        # Positive control: a REGULAR day (close 16:00) at 14:00 IS a dead zone (sanity vs half-day).
        with self.assertRaises(ca.OutOfWindowError):
            ca.resolve_canonical_asof(_dt(MON, 14, 0), _FULL_WEEK)


class ConvergenceDeterminismTests(unittest.TestCase):
    def test_window_internal_runs_converge_to_same_decision(self):
        nows = [_dt(FRI, 16, 1), _dt(SAT, 0, 0), _dt(SAT, 23, 59), _dt(SUN, 9, 0), _dt(MON, 9, 29)]
        decisions = {ca.resolve_canonical_asof(n, _FULL_WEEK)["decision_date"] for n in nows}
        bases = {ca.resolve_canonical_asof(n, _FULL_WEEK)["price_basis_date"] for n in nows}
        self.assertEqual(decisions, {MON})  # all converge to the same Monday
        self.assertEqual(bases, {FRI})

    def test_deterministic(self):
        a = ca.resolve_canonical_asof(_dt(SAT, 10, 0), _FULL_WEEK)
        b = ca.resolve_canonical_asof(_dt(SAT, 10, 0), _FULL_WEEK)
        self.assertEqual(a, b)

    def test_sessions_order_free(self):
        # Unsorted (but unique) input -> same result as the clean week (sorted internally).
        messy = [_sess(TUE), _sess(MON), _sess(FRI)]
        r = ca.resolve_canonical_asof(_dt(SAT, 10, 0), messy)
        self.assertEqual(r["decision_date"], MON)
        self.assertEqual(r["price_basis_date"], FRI)


class WindowCoverageErrorTests(unittest.TestCase):
    def test_no_upcoming_session_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess(FRI)])  # only a past session

    def test_no_settled_session_raises_valueerror(self):
        # now before any session (FRI is not a session here; all sessions are future).
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(FRI, 8, 0), [_sess(MON), _sess(TUE)])

    def test_empty_sessions_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [])


class MalformedInputTests(unittest.TestCase):
    """Adversarial bad inputs against the resolver's own strict validators (fail-closed, not silent)."""

    def test_now_not_datetime_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof("20260613", _FULL_WEEK)

    def test_session_not_dict_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [FRI, MON])  # bare strings, not dicts

    def test_bad_date_dashes_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess("2026-06-15"), _sess(TUE)])

    def test_bad_date_short_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess("2026"), _sess(TUE)])

    def test_non_ascii_date_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess("２０２６０６１５"), _sess(TUE)])

    def test_bad_time_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess(MON, close="25:00"), _sess(TUE)])

    def test_bad_time_not_zero_padded_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess(MON, open_="9:30"), _sess(TUE)])

    def test_open_not_before_close_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess(MON, open_="16:00", close="13:00")])

    def test_open_equals_close_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess(MON, open_="13:00", close="13:00")])


class CalendarValidityTests(unittest.TestCase):
    """Shape-valid but impossible calendar dates must fail closed (not laundered into output)."""

    def test_impossible_upcoming_date_raises(self):
        # 20260631 = June 31 (does not exist); would otherwise become decision_date.
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess(FRI), _sess("20260631")])

    def test_impossible_settled_date_raises(self):
        # 20260631 as the would-be price_basis_date must also be rejected.
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess("20260631"), _sess(MON)])

    def test_feb_29_non_leap_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess(FRI), _sess("20260229")])

    def test_month_zero_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess(FRI), _sess("20260015")])

    def test_day_zero_raises(self):
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), [_sess(FRI), _sess("20260600")])


class DuplicateSessionTests(unittest.TestCase):
    """Duplicate session dates must be rejected (no order-dependent last-wins)."""

    def test_duplicate_conflicting_regular_then_halfday_raises(self):
        sessions = [_sess(FRI), _sess(MON), _sess(MON, close="13:00"), _sess(TUE)]
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(MON, 14, 0), sessions)

    def test_duplicate_conflicting_halfday_then_regular_raises(self):
        # Same data, reversed order — must ALSO raise (was order-dependent before the fix).
        sessions = [_sess(FRI), _sess(MON, close="13:00"), _sess(MON), _sess(TUE)]
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(MON, 14, 0), sessions)

    def test_duplicate_identical_raises(self):
        sessions = [_sess(FRI), _sess(MON), _sess(MON), _sess(TUE)]
        with self.assertRaises(ValueError):
            ca.resolve_canonical_asof(_dt(SAT, 10, 0), sessions)


if __name__ == "__main__":
    unittest.main()
