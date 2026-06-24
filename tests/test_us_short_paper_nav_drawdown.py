# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 NAV-path / drawdown primitive (engine/us_short_paper_nav_drawdown.py).

Covers: the weekly realized basket-net equity curve (coverage counts, realized net sequence, final cumulative net,
NON-POSITIVE max_drawdown mirroring the a_long convention); a known peak-to-trough drawdown; monotonic / single /
first-week-loss curves; §12.1 不虚高 (open / empty weeks counted as coverage, NOT imputed; all-unrealized & empty →
None metrics); the frozen paper-only boundary (mirrors the scorecard's); and the adversarial fail-closed surface —
non-list / bad item shape / bad as_of (incl. the isascii trap) / non-increasing-or-duplicate as_of / an invalid
embedded scorecard refused / a net <= -1 (NAV <= 0) refused; and the CLOSED-WORLD validator (extra-or-missing key /
boundary tamper / doctored cumulative or POSITIVE drawdown / count or length mismatch / None-coupling refused).
Feeds REAL build_paper_scorecard outputs (drift guard). Pure/offline; no provider/live; no A-share crossing.
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_scorecard as sc  # noqa: E402
import engine.us_short_paper_nav_drawdown as nd  # noqa: E402


def _nr_closed(net, cost=0.0):
    return {"outcome": "filled_tp_exit", "realized": True, "gross_return": net + cost, "cost_fraction": cost,
            "net_return": net, "unfilled_cash": False}


def _nr_open():
    return {"outcome": "open_unrealized", "realized": False, "gross_return": None, "cost_fraction": None,
            "net_return": None, "unfilled_cash": False}


def _sc_net(net):
    """A 1-position basket whose realized net_basket == net (selected_total 1)."""
    return sc.build_paper_scorecard({"t0": _nr_closed(net)}, selected_tickers=["t0"])


def _sc_open():
    """A 1-position basket that is OPEN → net_basket None (not fully resolved)."""
    return sc.build_paper_scorecard({"t0": _nr_open()}, selected_tickers=["t0"])


def _sc_empty():
    """An empty basket → net_basket None."""
    return sc.build_paper_scorecard({}, selected_tickers=[])


def _period(as_of, scorecard):
    return {"as_of": as_of, "scorecard": scorecard}


def _seq(*pairs):
    """pairs = (as_of, scorecard) → ordered period_scorecards list."""
    return [_period(a, s) for a, s in pairs]


class Build(unittest.TestCase):
    def test_structure_and_boundary(self):
        r = nd.build_nav_drawdown(_seq(("20260105", _sc_net(0.10)), ("20260112", _sc_net(-0.05))))
        self.assertEqual(r["n_total"], 2)
        self.assertEqual(r["n_realized"], 2)
        self.assertEqual(r["n_unrealized"], 0)
        self.assertEqual(r["realized_period_nets"], [0.10, -0.05])
        self.assertEqual(r["boundary"], {"evidence_level": "paper", "full_size_ship_gate_allowed": False,
                                         "ship_gate_evidence_level": "paper_not_live_normalized"})

    def test_boundary_mirrors_scorecard(self):
        # the docstring claims the boundary mirrors engine.us_short_paper_scorecard._BOUNDARY — lock it
        self.assertEqual(nd._BOUNDARY, sc._BOUNDARY)

    def test_known_drawdown(self):
        # nets +0.10 / -0.20 / +0.05 → NAV 1.10 / 0.88 / 0.924; peak 1.10, trough 0.88 → max_dd -0.20
        r = nd.build_nav_drawdown(_seq(("20260105", _sc_net(0.10)), ("20260112", _sc_net(-0.20)), ("20260119", _sc_net(0.05))))
        self.assertAlmostEqual(r["max_drawdown"], -0.20, places=12)
        self.assertAlmostEqual(r["final_cumulative_net"], 1.10 * 0.80 * 1.05 - 1.0, places=12)

    def test_monotonic_zero_drawdown(self):
        r = nd.build_nav_drawdown(_seq(("20260105", _sc_net(0.05)), ("20260112", _sc_net(0.05))))
        self.assertEqual(r["max_drawdown"], 0.0)
        self.assertAlmostEqual(r["final_cumulative_net"], 1.05 * 1.05 - 1.0, places=12)

    def test_single_realized_week(self):
        r = nd.build_nav_drawdown(_seq(("20260105", _sc_net(0.07))))
        self.assertEqual(r["max_drawdown"], 0.0)          # single point — no peak-to-trough
        self.assertAlmostEqual(r["final_cumulative_net"], 0.07, places=12)

    def test_first_week_loss_is_drawdown_from_starting_capital(self):
        # NAV starts at 1.0 (deployed capital); a first-week loss IS a drawdown from that starting peak
        r = nd.build_nav_drawdown(_seq(("20260105", _sc_net(-0.05))))
        self.assertAlmostEqual(r["max_drawdown"], -0.05, places=12)

    def test_unrealized_counted_not_imputed(self):
        # week 2 open → counted as coverage but NOT a step; curve = [+0.10, +0.05] (不虚高)
        r = nd.build_nav_drawdown(_seq(("20260105", _sc_net(0.10)), ("20260112", _sc_open()), ("20260119", _sc_net(0.05))))
        self.assertEqual(r["n_total"], 3)
        self.assertEqual(r["n_realized"], 2)
        self.assertEqual(r["n_unrealized"], 1)
        self.assertEqual(r["realized_period_nets"], [0.10, 0.05])

    def test_empty_basket_week_is_unrealized(self):
        r = nd.build_nav_drawdown(_seq(("20260105", _sc_empty()), ("20260112", _sc_net(0.03))))
        self.assertEqual(r["n_realized"], 1)
        self.assertEqual(r["n_unrealized"], 1)

    def test_empty_sequence(self):
        r = nd.build_nav_drawdown([])
        self.assertEqual((r["n_total"], r["n_realized"], r["n_unrealized"]), (0, 0, 0))
        self.assertIsNone(r["final_cumulative_net"])
        self.assertIsNone(r["max_drawdown"])

    def test_all_unrealized(self):
        r = nd.build_nav_drawdown(_seq(("20260105", _sc_open()), ("20260112", _sc_open())))
        self.assertEqual(r["n_realized"], 0)
        self.assertIsNone(r["final_cumulative_net"])      # no realized week → no path, 不虚高
        self.assertIsNone(r["max_drawdown"])


class Adversarial(unittest.TestCase):
    def test_not_a_list(self):
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.build_nav_drawdown({"as_of": "20260105", "scorecard": _sc_net(0.1)})

    def test_item_not_dict(self):
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.build_nav_drawdown([("20260105", _sc_net(0.1))])

    def test_item_wrong_keys(self):
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.build_nav_drawdown([{"as_of": "20260105", "scorecard": _sc_net(0.1), "x": 1}])
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.build_nav_drawdown([{"as_of": "20260105"}])

    def test_bad_as_of(self):
        for bad in ("2026-01-05", "20261305", "abcd0105", "2026010", 20260105, "２０２６0105"):
            with self.assertRaises(nd.PaperNavDrawdownError):
                nd.build_nav_drawdown([_period(bad, _sc_net(0.1))])

    def test_as_of_not_strictly_increasing(self):
        for a, b in (("20260112", "20260105"), ("20260105", "20260105")):  # decreasing / duplicate
            with self.assertRaises(nd.PaperNavDrawdownError):
                nd.build_nav_drawdown(_seq((a, _sc_net(0.1)), (b, _sc_net(0.1))))

    def test_invalid_embedded_scorecard_refused(self):
        bad = _sc_net(0.1)
        bad["filled_count"] = 99  # break the count invariant → validate_paper_scorecard rejects
        with self.assertRaises(sc.PaperScorecardError):
            nd.build_nav_drawdown([_period("20260105", bad)])

    def test_net_le_minus_one_refused(self):
        # a (corrupt) scorecard whose net_basket <= -1 would drive NAV <= 0 — impossible for a stop-bounded long basket
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.build_nav_drawdown([_period("20260105", _sc_net(-1.5))])


class Validator(unittest.TestCase):
    def _good(self):
        return nd.build_nav_drawdown(_seq(("20260105", _sc_net(0.10)), ("20260112", _sc_net(-0.20))))

    def test_extra_or_missing_key(self):
        g = self._good()
        g["x"] = 1
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.validate_nav_drawdown(g)
        g2 = self._good()
        del g2["max_drawdown"]
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.validate_nav_drawdown(g2)

    def test_boundary_tamper(self):
        g = self._good()
        g["boundary"] = dict(g["boundary"], full_size_ship_gate_allowed=True)
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.validate_nav_drawdown(g)

    def test_positive_drawdown_refused(self):
        g = self._good()
        g["max_drawdown"] = 0.05  # drawdown must be non-positive
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.validate_nav_drawdown(g)

    def test_doctored_cumulative(self):
        g = self._good()
        g["final_cumulative_net"] = g["final_cumulative_net"] + 0.5
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.validate_nav_drawdown(g)

    def test_count_mismatch(self):
        g = self._good()
        g["n_unrealized"] = 1  # n_total(2) != n_realized(2) + n_unrealized(1)
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.validate_nav_drawdown(g)

    def test_realized_nets_length_mismatch(self):
        g = self._good()
        g["realized_period_nets"] = g["realized_period_nets"] + [0.01]  # len 3 != n_realized 2
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.validate_nav_drawdown(g)

    def test_embedded_net_le_minus_one(self):
        g = self._good()
        g["realized_period_nets"] = [-1.5, 0.10]
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.validate_nav_drawdown(g)

    def test_none_coupling(self):
        g = nd.build_nav_drawdown([])  # no realized week → both None
        g["max_drawdown"] = 0.0        # break the coupling (cum None but dd set)
        with self.assertRaises(nd.PaperNavDrawdownError):
            nd.validate_nav_drawdown(g)


if __name__ == "__main__":
    unittest.main()
