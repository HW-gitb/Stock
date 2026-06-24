# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 per-profile multi-week aggregation (engine/us_short_paper_multiweek_scorecard.py).

Covers: the two DISTINCT calibers — the cumulative full-caliber position tally over ALL weeks (summed
filled/win/loss/flat/unfilled/open/selected_total + cost + overall bad_pick_rate) AND the embedded realized-basket
nav_drawdown (open weeks coverage-counted, NOT on the curve — §12.1 不虚高); the frozen paper-only boundary
(mirrors the scorecard's + nav_drawdown's); the de-identified per-week ``period_source`` + SOURCE-TRACEABILITY (a
self-consistent forged cumulative — e.g. all-zeros — and a source-divergent nav are both refused because the
validator RE-DERIVES from period_source); STRICT-int count fields (n_weeks=2.0 / n_weeks=False / a float cumulative
count refused); empty / no-filled edge cases; adversarial input propagated from build_nav_drawdown; and the rest of
the CLOSED-WORLD validator. Feeds REAL build_paper_scorecard outputs (drift guard). Pure/offline; no provider/live;
no A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_scorecard as sc  # noqa: E402
import engine.us_short_paper_nav_drawdown as nd  # noqa: E402
import engine.us_short_paper_multiweek_scorecard as mw  # noqa: E402


def _nr_closed(net, cost=0.0):
    return {"outcome": "filled_tp_exit", "realized": True, "gross_return": net + cost, "cost_fraction": cost,
            "net_return": net, "unfilled_cash": False}


def _nr_cash():
    return {"outcome": "cash_unfilled", "realized": True, "gross_return": 0.0, "cost_fraction": 0.0,
            "net_return": 0.0, "unfilled_cash": True}


def _nr_open():
    return {"outcome": "open_unrealized", "realized": False, "gross_return": None, "cost_fraction": None,
            "net_return": None, "unfilled_cash": False}


def _sc(*nrs):
    mapping = {("t%d" % i): e for i, e in enumerate(nrs)}
    return sc.build_paper_scorecard(mapping, selected_tickers=list(mapping))


def _period(as_of, scorecard):
    return {"as_of": as_of, "scorecard": scorecard}


# week 1: 1 win(+0.10) / 1 loss(-0.05) / 1 cash ; week 2: 2 win(+0.05) / 1 cash
W1 = _sc(_nr_closed(0.10), _nr_closed(-0.05), _nr_cash())
W2 = _sc(_nr_closed(0.05), _nr_closed(0.05), _nr_cash())


def _two_week():
    return mw.build_multiweek_scorecard([_period("20260105", W1), _period("20260112", W2)])


class Build(unittest.TestCase):
    def test_structure_and_boundary(self):
        r = _two_week()
        self.assertEqual(set(r), {"n_weeks", "period_source", "cumulative", "nav_drawdown", "boundary"})
        self.assertEqual(r["n_weeks"], 2)
        self.assertEqual(r["boundary"], {"evidence_level": "paper", "full_size_ship_gate_allowed": False,
                                         "ship_gate_evidence_level": "paper_not_live_normalized"})

    def test_boundary_mirrors_scorecard_and_nav(self):
        self.assertEqual(mw._BOUNDARY, sc._BOUNDARY)
        self.assertEqual(mw._BOUNDARY, nd._BOUNDARY)

    def test_cumulative_tally(self):
        c = _two_week()["cumulative"]
        self.assertEqual(c["cum_selected_total"], 6)     # 3 + 3
        self.assertEqual(c["cum_filled"], 4)             # 2 + 2
        self.assertEqual(c["cum_win"], 3)                # 1 + 2
        self.assertEqual(c["cum_loss"], 1)               # 1 + 0
        self.assertEqual(c["cum_flat"], 0)
        self.assertEqual(c["cum_unfilled_cash"], 2)      # 1 + 1
        self.assertEqual(c["cum_open_unrealized"], 0)
        self.assertAlmostEqual(c["overall_bad_pick_rate"], 1 / 4, places=12)  # cum_loss / cum_filled over weeks

    def test_cost_summed(self):
        wc = _sc(_nr_closed(0.10, cost=0.002), _nr_closed(-0.05, cost=0.003))
        r = mw.build_multiweek_scorecard([_period("20260105", wc)])
        self.assertAlmostEqual(r["cumulative"]["cum_total_cost_fraction"], 0.005, places=12)

    def test_nav_drawdown_embedded(self):
        # net_baskets: W1 = 0.05/3, W2 = 0.10/3 (both positive) → monotonic, max_drawdown 0.0
        r = _two_week()
        self.assertEqual(r["nav_drawdown"]["n_realized"], 2)
        self.assertEqual(r["nav_drawdown"]["max_drawdown"], 0.0)

    def test_open_week_counted_in_cumulative_not_curve(self):
        # week 2 has an open position → its filled/win count in cumulative, but the WEEK is unrealized for the curve
        wopen = _sc(_nr_closed(0.10), _nr_open())
        r = mw.build_multiweek_scorecard([_period("20260105", W1), _period("20260112", wopen)])
        self.assertEqual(r["cumulative"]["cum_open_unrealized"], 1)        # the open position is tallied
        self.assertEqual(r["cumulative"]["cum_filled"], 3)                 # W1 2 + wopen 1
        self.assertEqual(r["nav_drawdown"]["n_realized"], 1)              # only W1 is a realized basket
        self.assertEqual(r["nav_drawdown"]["n_unrealized"], 1)            # wopen week not on the curve (不虚高)

    def test_period_source_is_deidentified(self):
        r = _two_week()
        self.assertEqual(len(r["period_source"]), 2)
        for item in r["period_source"]:
            self.assertEqual(set(item), {"as_of", "scorecard"})
            sc.validate_paper_scorecard(item["scorecard"])   # de-identified closed-world scorecard (no tickers / $)

    def test_empty_sequence(self):
        r = mw.build_multiweek_scorecard([])
        self.assertEqual(r["n_weeks"], 0)
        self.assertEqual(r["period_source"], [])
        self.assertEqual(r["cumulative"]["cum_filled"], 0)
        self.assertIsNone(r["cumulative"]["overall_bad_pick_rate"])
        self.assertIsNone(r["nav_drawdown"]["max_drawdown"])

    def test_no_filled_bad_pick_none(self):
        wcash = _sc(_nr_cash(), _nr_cash())
        r = mw.build_multiweek_scorecard([_period("20260105", wcash)])
        self.assertEqual(r["cumulative"]["cum_filled"], 0)
        self.assertIsNone(r["cumulative"]["overall_bad_pick_rate"])


class AdversarialPropagation(unittest.TestCase):
    def test_not_a_list(self):
        with self.assertRaises(nd.PaperNavDrawdownError):
            mw.build_multiweek_scorecard({"as_of": "20260105", "scorecard": W1})

    def test_non_increasing_as_of(self):
        with self.assertRaises(nd.PaperNavDrawdownError):
            mw.build_multiweek_scorecard([_period("20260112", W1), _period("20260105", W2)])

    def test_invalid_embedded_scorecard(self):
        bad = _sc(_nr_closed(0.1))
        bad["filled_count"] = 99
        with self.assertRaises(sc.PaperScorecardError):
            mw.build_multiweek_scorecard([_period("20260105", bad)])

    def test_net_le_minus_one(self):
        with self.assertRaises(nd.PaperNavDrawdownError):
            mw.build_multiweek_scorecard([_period("20260105", _sc(_nr_closed(-1.5)))])


class Validator(unittest.TestCase):
    def test_extra_or_missing_key(self):
        g = _two_week(); g["x"] = 1
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)
        g2 = _two_week(); del g2["period_source"]
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g2)

    def test_cumulative_wrong_keys(self):
        g = _two_week(); g["cumulative"]["extra"] = 1
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_boundary_tamper(self):
        g = _two_week(); g["boundary"] = dict(g["boundary"], full_size_ship_gate_allowed=True)
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_forged_self_consistent_cumulative_rejected(self):
        # the Codex probe: an INTERNALLY-consistent but source-DIVERGENT cumulative (all zeros) with valid
        # nav_drawdown / n_weeks / boundary / period_source — the re-derivation from period_source must reject it
        g = _two_week()
        g["cumulative"] = {"cum_selected_total": 0, "cum_filled": 0, "cum_unfilled_cash": 0, "cum_open_unrealized": 0,
                           "cum_win": 0, "cum_loss": 0, "cum_flat": 0, "cum_total_cost_fraction": 0.0,
                           "overall_bad_pick_rate": None}
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_doctored_count_rejected(self):
        g = _two_week(); g["cumulative"]["cum_win"] = 99   # source-divergent (re-derive catches)
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_cumulative_count_float_rejected(self):
        # a float that compares numerically equal (4.0 == 4) must be refused by the STRICT-int check
        g = _two_week(); g["cumulative"]["cum_filled"] = 4.0
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_bad_pick_tamper(self):
        g = _two_week(); g["cumulative"]["overall_bad_pick_rate"] = 0.99
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_negative_cost(self):
        g = _two_week(); g["cumulative"]["cum_total_cost_fraction"] = -0.01
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_cost_bool_rejected(self):
        # False == 0.0 must NOT slip past the value == re-derivation — the strict numeric-type gate refuses it
        g = _two_week(); g["cumulative"]["cum_total_cost_fraction"] = False
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_cost_nonfinite_rejected(self):
        g = _two_week(); g["cumulative"]["cum_total_cost_fraction"] = float("inf")
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_bad_pick_bool_rejected(self):
        # False == 0.0 / True == 1.0 must NOT slip past the value == — the strict numeric-type gate refuses a bool
        for v in (False, True):
            g = _two_week(); g["cumulative"]["overall_bad_pick_rate"] = v
            with self.assertRaises(mw.PaperMultiweekScorecardError):
                mw.validate_multiweek_scorecard(g)

    def test_bad_pick_nonfinite_rejected(self):
        g = _two_week(); g["cumulative"]["overall_bad_pick_rate"] = float("nan")
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_n_weeks_mismatch(self):
        g = _two_week(); g["n_weeks"] = 5
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_n_weeks_float_rejected(self):
        g = _two_week(); g["n_weeks"] = 2.0   # numerically == 2 but not a strict int
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_n_weeks_bool_rejected(self):
        g = _two_week(); g["n_weeks"] = False  # bool is not an acceptable count
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)

    def test_invalid_embedded_nav(self):
        g = _two_week(); g["nav_drawdown"]["max_drawdown"] = 0.5   # positive drawdown → nav validator rejects
        with self.assertRaises(nd.PaperNavDrawdownError):
            mw.validate_multiweek_scorecard(g)

    def test_source_divergent_nav(self):
        # a VALID nav_drawdown that was NOT built from this artifact's period_source must be refused
        g = _two_week()
        g["nav_drawdown"] = nd.build_nav_drawdown([_period("20260105", W1)])  # a 1-week nav, valid but wrong source
        with self.assertRaises(mw.PaperMultiweekScorecardError):
            mw.validate_multiweek_scorecard(g)


if __name__ == "__main__":
    unittest.main()
