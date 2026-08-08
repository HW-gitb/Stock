"""Full-market breadth: every board counts, every caliber is the stock's own."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_market_breadth import (  # noqa: E402
    LIMIT_TOL,
    MarketBreadthError,
    compute_full_market_breadth,
    full_market_universe,
    max_limit_streak,
)

SESSIONS = ["20260720", "20260721", "20260722", "20260723", "20260724"]

#: One name per board plus the two shapes that must NOT be counted.
BASIC = pd.DataFrame([
    {"ts_code": "600000.SH", "market": "主板", "list_date": "20100101",
     "delist_date": "", "list_status": "L"},
    {"ts_code": "300001.SZ", "market": "创业板", "list_date": "20100101",
     "delist_date": "", "list_status": "L"},
    {"ts_code": "688001.SH", "market": "科创板", "list_date": "20100101",
     "delist_date": "", "list_status": "L"},
    {"ts_code": "830001.BJ", "market": "北交所", "list_date": "20100101",
     "delist_date": "", "list_status": "L"},
    {"ts_code": "900001.SH", "market": "B股", "list_date": "20100101",
     "delist_date": "", "list_status": "L"},
    {"ts_code": "999999.XX", "market": "未知", "list_date": "20100101",
     "delist_date": "", "list_status": "L"},
])


def _rows(date, spec):
    """spec: {code: (close, high, up_limit, down_limit)}; None drops the limit row."""
    daily, limits = [], []
    for code, values in spec.items():
        close, high, up, down = values
        daily.append({"ts_code": code, "trade_date": date, "close": close, "high": high})
        if up is not None:
            limits.append({"ts_code": code, "trade_date": date,
                           "up_limit": up, "down_limit": down})
    return daily, limits


def _panel(per_date):
    daily, limits = [], []
    for date, spec in per_date.items():
        d, l = _rows(date, spec)
        daily.extend(d)
        limits.extend(l)
    return pd.DataFrame(daily), pd.DataFrame(limits)


#: Quiet day for one name: nowhere near either limit.
def _quiet(code_up):
    return (10.0, 10.0, code_up, 8.0)


def _at_limit(up=11.0):
    return (up, up, up, 9.0)


class FullMarketUniverseTests(unittest.TestCase):
    def test_every_a_share_board_is_in_and_b_shares_and_unknown_codes_are_out(self):
        universe = full_market_universe(BASIC, "20260724")
        self.assertEqual(universe, {"600000.SH", "300001.SZ", "688001.SH", "830001.BJ"})

    def test_listing_and_delisting_are_point_in_time(self):
        basic = pd.concat([BASIC, pd.DataFrame([
            {"ts_code": "601111.SH", "market": "主板", "list_date": "20260725",
             "delist_date": "", "list_status": "L"},
            {"ts_code": "601222.SH", "market": "主板", "list_date": "20100101",
             "delist_date": "20260101", "list_status": "D"},
        ])], ignore_index=True)
        universe = full_market_universe(basic, "20260724")
        self.assertNotIn("601111.SH", universe, "a name that had not listed yet")
        self.assertNotIn("601222.SH", universe, "a name already delisted")

    def test_a_missing_stock_basic_fails_closed(self):
        with self.assertRaises(MarketBreadthError):
            full_market_universe(None, "20260724")


class FullMarketBreadthTests(unittest.TestCase):
    def _compute(self, per_date, **kwargs):
        daily, limits = _panel(per_date)
        return compute_full_market_breadth(
            as_of="20260724", daily=daily, stk_limit=limits, stock_basic=BASIC,
            trading_days=SESSIONS, **kwargs)

    def _quiet_day(self, extra=None):
        day = {"600000.SH": _quiet(11.0), "300001.SZ": _quiet(12.0),
               "688001.SH": _quiet(13.0), "830001.BJ": _quiet(14.0),
               "900001.SH": _quiet(15.0), "999999.XX": _quiet(16.0)}
        day.update(extra or {})
        return day

    def test_one_limit_up_on_each_board_is_counted_once_each(self):
        day = self._quiet_day({
            "600000.SH": _at_limit(11.0), "300001.SZ": _at_limit(12.0),
            "688001.SH": _at_limit(13.0), "830001.BJ": _at_limit(14.0)})
        result = self._compute({d: self._quiet_day() for d in SESSIONS[:-1]} | {"20260724": day})
        self.assertEqual(result["full_market_limit_up_count"], 4)
        self.assertEqual(result["coverage"]["universe_name"], "a_share_full_market")

    def test_a_b_share_or_unknown_code_at_its_limit_is_not_counted(self):
        day = self._quiet_day({"900001.SH": _at_limit(15.0), "999999.XX": _at_limit(16.0)})
        result = self._compute({d: self._quiet_day() for d in SESSIONS[:-1]} | {"20260724": day})
        self.assertEqual(result["full_market_limit_up_count"], 0)

    def test_each_stock_is_judged_against_its_own_band_not_a_hard_coded_percent(self):
        """A 20cm name at +11% is NOT a limit-up; a 5% ST name at +5% is."""
        day = self._quiet_day({
            # 20cm board: yesterday 10 -> up_limit 12; closing at 11.1 is +11%, not a limit
            "300001.SZ": (11.1, 11.1, 12.0, 8.0),
            # ST-style 5% band: up_limit 10.5 and it closed there
            "600000.SH": (10.5, 10.5, 10.5, 9.5),
        })
        result = self._compute({d: self._quiet_day() for d in SESSIONS[:-1]} | {"20260724": day})
        self.assertEqual(result["full_market_limit_up_count"], 1,
                         "only the name that reached ITS OWN up_limit counts")

    def test_limit_downs_use_each_stock_s_own_down_limit(self):
        day = self._quiet_day({"600000.SH": (8.0, 8.0, 11.0, 8.0)})
        result = self._compute({d: self._quiet_day() for d in SESSIONS[:-1]} | {"20260724": day})
        self.assertEqual(result["full_market_limit_down_count"], 1)
        self.assertEqual(result["full_market_limit_up_count"], 0)

    def test_one_traded_name_without_a_limit_row_makes_the_day_unavailable(self):
        day = self._quiet_day({"600000.SH": (10.0, 10.0, None, None)})
        result = self._compute({d: self._quiet_day() for d in SESSIONS[:-1]} | {"20260724": day})
        for field in ("full_market_limit_up_count", "full_market_limit_down_count",
                      "full_market_consecutive_limit_up_height"):
            self.assertIsNone(result[field], f"{field} must not be 0 when data is missing")
        self.assertEqual(result["coverage"]["status"], "unavailable")
        self.assertEqual(result["coverage"]["unavailable_reason"],
                         "incomplete_usable_rows_for_as_of")

    def test_a_run_that_breaks_on_the_last_day_resets_the_height(self):
        per_date = {}
        for date in SESSIONS[:-1]:
            per_date[date] = self._quiet_day({"600000.SH": _at_limit(11.0)})
        per_date["20260724"] = self._quiet_day()          # the run breaks today
        result = self._compute(per_date)
        self.assertEqual(result["full_market_consecutive_limit_up_height"], 0)

    def test_a_run_ending_today_is_measured_to_its_true_length(self):
        per_date = {SESSIONS[0]: self._quiet_day()}
        for date in SESSIONS[1:]:
            per_date[date] = self._quiet_day({"600000.SH": _at_limit(11.0)})
        result = self._compute(per_date)
        self.assertEqual(result["full_market_consecutive_limit_up_height"], 4)

    def test_a_missing_session_does_not_get_bridged_into_a_longer_run(self):
        per_date = {d: self._quiet_day({"600000.SH": _at_limit(11.0)}) for d in SESSIONS}
        del per_date["20260722"]                          # a hole in the middle
        result = self._compute(per_date)
        self.assertIsNone(result["full_market_consecutive_limit_up_height"],
                          "an incomplete window may not report a best-effort height")
        self.assertEqual(result["coverage"]["status"], "partial")
        self.assertEqual(result["coverage"]["unavailable_reason"], "incomplete_history_window")
        # the same-day counts are still knowable and still reported
        self.assertEqual(result["full_market_limit_up_count"], 1)

    def test_duplicate_and_non_canonical_rows_fail_closed(self):
        daily, limits = _panel({d: self._quiet_day() for d in SESSIONS})
        with self.assertRaises(MarketBreadthError):
            compute_full_market_breadth(
                as_of="20260724", daily=pd.concat([daily, daily.tail(1)]), stk_limit=limits,
                stock_basic=BASIC, trading_days=SESSIONS)
        bad = daily.copy()
        bad.loc[bad.index[0], "trade_date"] = "2026-07-20"
        with self.assertRaises(MarketBreadthError):
            compute_full_market_breadth(as_of="20260724", daily=bad, stk_limit=limits,
                                        stock_basic=BASIC, trading_days=SESSIONS)

    def test_a_session_list_that_does_not_end_at_as_of_fails_closed(self):
        daily, limits = _panel({d: self._quiet_day() for d in SESSIONS})
        with self.assertRaises(MarketBreadthError):
            compute_full_market_breadth(as_of="20260724", daily=daily, stk_limit=limits,
                                        stock_basic=BASIC, trading_days=SESSIONS[:-1])

    def test_the_tolerance_is_applied_rather_than_exact_equality(self):
        """Providers round the limit to 2dp; an exact test would drop real limit-ups."""
        day = self._quiet_day({"600000.SH": (11.0 * LIMIT_TOL, 11.0, 11.0, 9.0)})
        result = self._compute({d: self._quiet_day() for d in SESSIONS[:-1]} | {"20260724": day})
        self.assertEqual(result["full_market_limit_up_count"], 1)


class AbsentIsNotInvisibleTests(unittest.TestCase):
    """Completeness must be measured against what exists, not against what arrived.

    Every case here is a reviewer probe that used to come back `complete`. They share
    one root: `eligible` counted rows that turned up, so a stock that never arrived
    was invisible to the fail-closed check -- and a truncated page produced a smaller
    limit-up count AND a shorter run, both pointing the same way.
    """

    def _compute(self, per_date, basic=BASIC, sessions=SESSIONS):
        daily, limits = _panel(per_date)
        return compute_full_market_breadth(
            as_of=sessions[-1], daily=daily, stk_limit=limits, stock_basic=basic,
            trading_days=sessions)

    def _day(self, codes, at_limit=()):
        prices = {"600000.SH": 11.0, "300001.SZ": 12.0, "688001.SH": 13.0, "830001.BJ": 14.0}
        out = {}
        for code in codes:
            up = prices[code]
            out[code] = (up, up, up, 9.0) if code in at_limit else (10.0, 10.0, up, 8.0)
        return out

    ALL = ("600000.SH", "300001.SZ", "688001.SH", "830001.BJ")

    def test_a_short_panel_is_reported_and_may_not_be_called_complete(self):
        """Reviewer probe 1: universe of 4, only 2 names delivered."""
        arrived = self.ALL[:2]
        result = self._compute({d: self._day(arrived, at_limit=arrived[:1]) for d in SESSIONS})
        coverage = result["coverage"]
        self.assertEqual(coverage["universe_size"], 4)
        self.assertEqual(coverage["eligible_stock_count"], 2)
        self.assertEqual(coverage["absent_stock_count"], 2, "the gap must be visible at all")
        self.assertNotEqual(coverage["status"], "complete")
        self.assertIn("universe_rows_absent", coverage["unavailable_reason"])

    def test_a_contender_missing_one_mid_window_bar_makes_the_height_unavailable(self):
        """Reviewer probe 2: height read 2 when the truth was 5."""
        per_date = {d: self._day(self.ALL, at_limit=("600000.SH",)) for d in SESSIONS}
        held = per_date["20260722"].pop("600000.SH")           # one bar, one stock
        self.assertIsNotNone(held)
        result = self._compute(per_date)
        self.assertIsNone(result["full_market_consecutive_limit_up_height"],
                          "a hole under the run's own leader may not be counted through")
        self.assertIn("contender_bar_missing_in_window", result["coverage"]["unavailable_reason"])
        self.assertEqual(result["full_market_limit_up_count"], 1,
                         "today's counts are still knowable and still reported")

    def test_b_shares_are_out_even_when_the_provider_labels_them_main_board(self):
        """Reviewer probe 3: `market` alone is one mislabelled row wide."""
        basic = pd.DataFrame([
            {"ts_code": "600000.SH", "market": "主板", "list_date": "20100101",
             "delist_date": "", "list_status": "L"},
            {"ts_code": "900001.SH", "market": "主板", "list_date": "20100101",
             "delist_date": "", "list_status": "L"},
            {"ts_code": "200002.SZ", "market": "主板", "list_date": "20100101",
             "delist_date": "", "list_status": "L"},
        ])
        self.assertEqual(full_market_universe(basic, "20260724"), {"600000.SH"})

    def test_a_delisted_status_removes_a_name_even_with_no_delist_date(self):
        """Reviewer probe 4: `list_status` was required and never read."""
        basic = pd.DataFrame([
            {"ts_code": "600000.SH", "market": "主板", "list_date": "20100101",
             "delist_date": "", "list_status": "D"},
            {"ts_code": "600001.SH", "market": "主板", "list_date": "20100101",
             "delist_date": "", "list_status": "L"},
        ])
        self.assertEqual(full_market_universe(basic, "20260724"), {"600001.SH"})

    def test_a_halted_name_stays_in_the_universe_and_shows_up_as_a_gap(self):
        """`P` is paused, not gone: it belongs in the denominator, reported absent."""
        basic = pd.DataFrame([
            {"ts_code": "600000.SH", "market": "主板", "list_date": "20100101",
             "delist_date": "", "list_status": "P"},
        ])
        self.assertEqual(full_market_universe(basic, "20260724"), {"600000.SH"})

    def test_a_complete_panel_is_unchanged_by_all_of_the_above(self):
        """Closure 5: the repairs may not condemn a good day."""
        result = self._compute({d: self._day(self.ALL, at_limit=("600000.SH",)) for d in SESSIONS})
        self.assertEqual(result["coverage"]["status"], "complete")
        self.assertIsNone(result["coverage"]["unavailable_reason"])
        self.assertEqual(result["coverage"]["absent_stock_count"], 0)
        self.assertEqual(result["coverage"]["universe_size"], 4)
        self.assertEqual(result["full_market_limit_up_count"], 1)
        self.assertEqual(result["full_market_consecutive_limit_up_height"], 5)

    def test_a_run_that_fills_the_window_is_flagged_as_a_floor_not_a_defect(self):
        """Saturation is a property of the height, not a coverage problem.

        Folding it into `status` would make "I cannot see far enough back" and
        "the panel was short" the same word, and a reader would learn nothing
        from either.
        """
        saturated = self._compute({d: self._day(self.ALL, at_limit=("600000.SH",))
                                   for d in SESSIONS})["coverage"]
        self.assertTrue(saturated["height_window_saturated"])
        self.assertEqual(saturated["status"], "complete", "a floor is not a defect")
        self.assertIsNone(saturated["unavailable_reason"])

        per_date = {SESSIONS[0]: self._day(self.ALL)}
        for date in SESSIONS[1:]:
            per_date[date] = self._day(self.ALL, at_limit=("600000.SH",))
        short = self._compute(per_date)["coverage"]
        self.assertFalse(short["height_window_saturated"], "a 4-of-5 run is fully seen")


class LimitStreakTests(unittest.TestCase):
    def test_a_session_the_stock_missed_ends_its_run(self):
        ups = {"d1": {"A"}, "d2": set(), "d3": {"A"}}
        self.assertEqual(max_limit_streak(ups, ["d1", "d2", "d3"]), 1,
                         "the run restarts at d3; d1 is on the far side of a break")

    def test_this_function_trusts_the_session_list_it_is_given(self):
        """Where the anti-bridging guarantee actually lives.

        Handed `["d1", "d3"]` this counts 2 -- it takes the caller's list as THE
        consecutive sessions. That is deliberate and is why
        `compute_full_market_breadth` refuses to report a height at all when a
        window session is missing from the panel, rather than passing a shortened
        list down here (see `test_a_missing_session_does_not_get_bridged_...`).
        """
        ups = {"d1": {"A"}, "d2": {"A"}, "d3": {"A"}}
        self.assertEqual(max_limit_streak(ups, ["d1", "d2", "d3"]), 3)
        self.assertEqual(max_limit_streak(ups, ["d1", "d3"]), 2)

    def test_the_height_is_the_max_over_stocks_not_the_sum(self):
        ups = {"d1": {"A"}, "d2": {"A", "B"}, "d3": {"A", "B"}}
        self.assertEqual(max_limit_streak(ups, ["d1", "d2", "d3"]), 3)


if __name__ == "__main__":
    unittest.main()
