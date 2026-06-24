# -*- coding: utf-8 -*-
"""Tests for the US-short market calendar session-builder (engine/us_short_market_calendar.py) — batch4 slice 4b.

Design authority: docs/us_short_system_design.md §2.1 / §3.5 / §18.2 batch4 (D2).

The builder LOGIC is verified against tiny INJECTED fixture calendars (not the production
preset's date accuracy, which is gated on authoritative cross-check): weekday filter, holiday
skip, early-close time, inclusive window, out-of-range fail-closed, and end-to-end into
resolve_canonical_asof (a Friday-holiday + weekend rolls the decision to Monday and the price
basis to the prior Thursday). Adversarial: malformed calendars fail closed via
validate_market_calendar (holiday==early-close, out-of-range, dup, bad date/time).
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_market_calendar as mc  # noqa: E402
import engine.us_short_canonical_asof as ca  # noqa: E402


def _cal(holidays=("20260619",), half_days=None, start="20260601", end="20260630"):
    return {
        "calendar": "NYSE_NASDAQ",
        "timezone": "America/New_York",
        "start_date": start,
        "end_date": end,
        "regular_open": "09:30",
        "regular_close": "16:00",
        "holidays": list(holidays),
        "half_days": dict(half_days or {}),
        "data_provenance": {
            "source": "test fixture",
            "verification_status": "pending_authoritative_cross_check",
            "note": "test",
        },
    }


class BuildSessionsTests(unittest.TestCase):
    def test_weekday_filter_and_holiday_skip(self):
        # 2026-06: Mon15 Tue16 Wed17 Thu18 [Fri19 HOLIDAY] [Sat20 Sun21] Mon22
        sessions = mc.build_sessions("20260615", "20260622", calendar=_cal())
        self.assertEqual([s["date"] for s in sessions], ["20260615", "20260616", "20260617", "20260618", "20260622"])
        self.assertTrue(all(s["open"] == "09:30" and s["close"] == "16:00" for s in sessions))

    def test_early_close_applied(self):
        sessions = mc.build_sessions("20260622", "20260626", calendar=_cal(half_days={"20260626": "13:00"}))
        by_date = {s["date"]: s["close"] for s in sessions}
        self.assertEqual(by_date["20260626"], "13:00")
        self.assertEqual(by_date["20260625"], "16:00")

    def test_window_out_of_calendar_range_raises(self):
        with self.assertRaises(ValueError):
            mc.build_sessions("20251201", "20260105", calendar=_cal())  # starts before frozen range

    def test_window_start_after_end_raises(self):
        with self.assertRaises(ValueError):
            mc.build_sessions("20260622", "20260615", calendar=_cal())

    def test_sessions_for_window_clamps_to_range(self):
        # center near the calendar's start edge -> low end clamps to start_date, no out-of-range raise.
        sessions = mc.sessions_for_window("20260605", calendar=_cal(), back_days=30, fwd_days=5)
        self.assertTrue(sessions and sessions[0]["date"] >= "20260601")


class ResolverIntegrationTests(unittest.TestCase):
    def test_friday_holiday_weekend_rolls_to_monday_basis_thursday(self):
        # now = Sat 2026-06-20 10:00 ET; Fri 19 is a holiday -> decision Mon 22, price basis Thu 18.
        sessions = mc.build_sessions("20260601", "20260630", calendar=_cal())
        r = ca.resolve_canonical_asof(datetime(2026, 6, 20, 10, 0), sessions)
        self.assertEqual(r["decision_date"], "20260622")
        self.assertEqual(r["price_basis_date"], "20260618")
        self.assertEqual(r["session_scope"], "RTH")

    def test_half_day_after_early_close_rolls(self):
        # Fri 26 closes 13:00; now 14:00 -> settled -> decision Mon 29, basis Fri 26.
        sessions = mc.build_sessions("20260601", "20260630", calendar=_cal(half_days={"20260626": "13:00"}))
        r = ca.resolve_canonical_asof(datetime(2026, 6, 26, 14, 0), sessions)
        self.assertEqual(r["decision_date"], "20260629")
        self.assertEqual(r["price_basis_date"], "20260626")

    def test_half_day_intraday_is_dead_zone(self):
        sessions = mc.build_sessions("20260601", "20260630", calendar=_cal(half_days={"20260626": "13:00"}))
        with self.assertRaises(ca.OutOfWindowError):
            ca.resolve_canonical_asof(datetime(2026, 6, 26, 11, 0), sessions)  # 11:00 in [09:30,13:00)


class ValidateMarketCalendarTests(unittest.TestCase):
    def test_clean_fixture_passes(self):
        self.assertIsInstance(mc.validate_market_calendar(_cal()), dict)

    def test_missing_key_raises(self):
        bad = _cal()
        del bad["holidays"]
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(bad)

    def test_unknown_top_level_key_raises(self):
        bad = _cal()
        bad["unknown_field"] = "ignored"  # builder no-op; closed-world must reject
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(bad)

    def test_holiday_out_of_range_raises(self):
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(_cal(holidays=("20250101",)))  # before start

    def test_impossible_holiday_date_raises(self):
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(_cal(holidays=("20260631",)))  # June 31

    def test_duplicate_holiday_raises(self):
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(_cal(holidays=("20260619", "20260619")))

    def test_date_both_holiday_and_half_day_raises(self):
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(_cal(holidays=("20260626",), half_days={"20260626": "13:00"}))

    def test_non_1300_early_close_raises(self):
        # §3.5 contract: NYSE/NASDAQ early-close is pinned to EXACTLY 13:00 (09:30 = open==close degenerate).
        for bad in ("16:30", "09:30", "14:00", "15:59"):
            with self.assertRaises(mc.MarketCalendarError):
                mc.validate_market_calendar(_cal(half_days={"20260626": bad}))

    def test_valid_1300_early_close_passes(self):
        self.assertIsInstance(mc.validate_market_calendar(_cal(half_days={"20260626": "13:00"})), dict)

    def test_weekend_holiday_raises(self):
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(_cal(holidays=("20260620",)))  # Saturday — builder no-op

    def test_actual_saturday_independence_day_raises(self):
        # Jul 4 2026 is a Saturday (actual); the artifact must encode the OBSERVED Fri 20260703 instead,
        # else the builder ignores 20260704 AND leaves 20260703 open — the closure is not encoded.
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(_cal(holidays=("20260704",)))

    def test_weekend_half_day_raises(self):
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(_cal(half_days={"20260620": "13:00"}))  # Saturday — builder no-op

    def test_early_close_out_of_range_raises(self):
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(_cal(half_days={"20270101": "13:00"}))  # after end


class ProvenanceValidationTests(unittest.TestCase):
    """data_provenance is the honesty gate (pending_authoritative_cross_check) — runtime-validated, not schema-only."""

    def test_bad_verification_status_raises(self):
        bad = _cal()
        bad["data_provenance"]["verification_status"] = "trust_me"
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(bad)

    def test_missing_source_raises(self):
        bad = _cal()
        del bad["data_provenance"]["source"]
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(bad)

    def test_non_object_provenance_raises(self):
        bad = _cal()
        bad["data_provenance"] = "pending_authoritative_cross_check"
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(bad)

    def test_extra_provenance_key_raises(self):
        bad = _cal()
        bad["data_provenance"]["extra"] = "x"
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(bad)

    def test_empty_note_raises(self):
        bad = _cal()
        bad["data_provenance"]["note"] = "   "
        with self.assertRaises(mc.MarketCalendarError):
            mc.validate_market_calendar(bad)

    def test_authoritative_verified_status_passes(self):
        ok = _cal()
        ok["data_provenance"]["verification_status"] = "authoritative_verified"
        self.assertIsInstance(mc.validate_market_calendar(ok), dict)


class ProductionCalendarSmokeTests(unittest.TestCase):
    def test_production_calendar_loads_and_validates(self):
        path = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"
        cal = mc.load_market_calendar(path)
        self.assertEqual(cal["calendar"], "NYSE_NASDAQ")
        # provenance must declare the verification gate honestly.
        self.assertEqual(cal["data_provenance"]["verification_status"], "pending_authoritative_cross_check")
        # builder runs end-to-end over the full frozen range without raising.
        sessions = mc.build_sessions(cal["start_date"], cal["end_date"], calendar=cal)
        self.assertTrue(len(sessions) > 400)  # ~250 trading days/yr * 2yr, minus holidays

    def test_known_2026_holidays_are_not_sessions(self):
        path = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"
        cal = mc.load_market_calendar(path)
        sessions = {s["date"] for s in mc.build_sessions("20260101", "20261231", calendar=cal)}
        for holiday in ("20260101", "20260703", "20261126", "20261225"):
            self.assertNotIn(holiday, sessions)
        # a known early-close is still a session, with the 13:00 close.
        nov27 = [s for s in mc.build_sessions("20261127", "20261127", calendar=cal)]
        self.assertEqual(nov27, [{"date": "20261127", "open": "09:30", "close": "13:00"}])


if __name__ == "__main__":
    unittest.main()
