# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 multi-week two-way comparison (engine/us_short_paper_multiweek_comparison.py).

Covers: balanced-vs-shadow build (embeds the 4 full-caliber multiweek aggregates, per-shadow deltas over
final_cumulative_net / max_drawdown / overall_bad_pick_rate / cum_total_cost_fraction / cum_loss / cum_unfilled_cash
/ cum_win, the #24 theme_weight_marginal_net, the frozen ship-gate-isolation/paper-only boundary); None delta when a
profile is unrealized; the §12.2 aligned-window + fixed-TopN invariant (a mis-dated / mixed-TopN profile refused on
build AND validate); profile coverage (missing / extra refused); an invalid embedded aggregate refused; and the
CLOSED-WORLD validator (extra key / boundary tamper / doctored delta / **bool delta (False==0.0) refused by the
strict type gate** / theme-marginal tamper / primary tamper refused). Pure/offline; no provider/live; no A-share.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_scorecard as sc  # noqa: E402
import engine.us_short_paper_multiweek_scorecard as mws  # noqa: E402
import engine.us_short_paper_multiweek_comparison as cmp  # noqa: E402


def _closed(net):
    return {"outcome": "filled_tp_exit", "realized": True, "gross_return": net, "cost_fraction": 0.0,
            "net_return": net, "unfilled_cash": False}


def _cash():
    return {"outcome": "cash_unfilled", "realized": True, "gross_return": 0.0, "cost_fraction": 0.0,
            "net_return": 0.0, "unfilled_cash": True}


def _open():
    return {"outcome": "open_unrealized", "realized": False, "gross_return": None, "cost_fraction": None,
            "net_return": None, "unfilled_cash": False}


def _sc(*nrs):
    mapping = {("t%d" % i): e for i, e in enumerate(nrs)}
    return sc.build_paper_scorecard(mapping, selected_tickers=list(mapping))


def _mw(*weeks):
    """weeks = ((as_of, (nr, ...)), ...) → a per-profile multiweek aggregate."""
    return mws.build_multiweek_scorecard([{"as_of": a, "scorecard": _sc(*nrs)} for a, nrs in weeks])


A0, A1 = "20260105", "20260112"
# all 4 profiles over the SAME weeks with the SAME fixed-TopN (3 positions) per week → aligned
BAL = _mw((A0, (_closed(0.10), _closed(-0.05), _cash())), (A1, (_closed(0.05), _closed(0.05), _cash())))
TOFF = _mw((A0, (_closed(0.05), _closed(0.05), _cash())), (A1, (_closed(0.05), _closed(0.05), _cash())))
TPLUS = _mw((A0, (_closed(-0.10), _closed(-0.10), _closed(0.05))), (A1, (_closed(-0.10), _closed(0.05), _cash())))
TAGG = _mw((A0, (_closed(0.20), _cash(), _cash())), (A1, (_closed(0.10), _cash(), _cash())))


def _four(balanced=BAL, theme_plus=TPLUS, theme_aggressive=TAGG, theme_off=TOFF):
    return {"balanced": balanced, "theme_plus": theme_plus, "theme_aggressive": theme_aggressive, "theme_off": theme_off}


class Build(unittest.TestCase):
    def test_structure_and_boundary(self):
        c = cmp.build_multiweek_comparison(_four())
        self.assertEqual(set(c), {"primary_profile", "profiles", "vs_balanced", "theme_weight_marginal_net", "boundary"})
        self.assertEqual(c["primary_profile"], "balanced")
        self.assertEqual(set(c["profiles"]), {"balanced", "theme_plus", "theme_aggressive", "theme_off"})
        self.assertEqual(set(c["vs_balanced"]), {"theme_plus", "theme_aggressive", "theme_off"})
        self.assertEqual(c["boundary"], {"track": "comparison_non_production", "evidence_level": "paper",
                                         "shadow_counts_ship_gate": False, "full_size_ship_gate_allowed": False})

    def test_full_caliber_embedded(self):
        c = cmp.build_multiweek_comparison(_four())
        self.assertEqual(c["profiles"]["theme_plus"]["cumulative"]["cum_loss"], 3)   # the shadow's extra losers visible
        self.assertEqual(c["profiles"]["balanced"]["cumulative"]["cum_loss"], 1)

    def test_deltas(self):
        c = cmp.build_multiweek_comparison(_four())
        d = c["vs_balanced"]["theme_plus"]
        self.assertEqual(d["cum_loss_delta"], 3 - 1)        # theme_plus 3 − balanced 1
        self.assertEqual(set(d), {m + "_delta" for m in ("final_cumulative_net", "max_drawdown", "overall_bad_pick_rate",
                                                         "cum_total_cost_fraction", "cum_loss", "cum_unfilled_cash", "cum_win")})

    def test_theme_marginal(self):
        c = cmp.build_multiweek_comparison(_four())
        expected = BAL["nav_drawdown"]["final_cumulative_net"] - TOFF["nav_drawdown"]["final_cumulative_net"]
        self.assertAlmostEqual(c["theme_weight_marginal_net"], expected, places=12)

    def test_none_delta_when_unrealized(self):
        # a theme_aggressive whose both weeks are OPEN → final_cumulative_net None → its delta None (不虚高)
        tagg_open = _mw((A0, (_open(), _open(), _open())), (A1, (_open(), _open(), _open())))
        c = cmp.build_multiweek_comparison(_four(theme_aggressive=tagg_open))
        self.assertIsNone(c["vs_balanced"]["theme_aggressive"]["final_cumulative_net_delta"])
        self.assertIsNone(c["vs_balanced"]["theme_aggressive"]["max_drawdown_delta"])


class Alignment(unittest.TestCase):
    def test_mismatched_topn_refused(self):
        # theme_plus week 0 has a DIFFERENT fixed-TopN (2 vs 3) → mis-aligned window
        bad = _mw((A0, (_closed(0.1), _cash())), (A1, (_closed(0.05), _closed(0.05), _cash())))
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.build_multiweek_comparison(_four(theme_plus=bad))

    def test_mismatched_weeks_refused(self):
        # theme_aggressive over a DIFFERENT week date → mis-aligned window
        bad = _mw((A0, (_closed(0.2), _cash(), _cash())), ("20260119", (_closed(0.1), _cash(), _cash())))
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.build_multiweek_comparison(_four(theme_aggressive=bad))

    def test_validate_side_misalignment(self):
        c = cmp.build_multiweek_comparison(_four())
        c["profiles"]["theme_off"] = _mw((A0, (_closed(0.05), _closed(0.05), _cash())))  # 1-week → window len differs
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.validate_multiweek_comparison(c)


class Coverage(unittest.TestCase):
    def test_missing_profile(self):
        f = _four(); del f["theme_off"]
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.build_multiweek_comparison(f)

    def test_extra_profile(self):
        f = _four(); f["extra"] = BAL
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.build_multiweek_comparison(f)

    def test_not_a_dict(self):
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.build_multiweek_comparison([BAL, TPLUS, TAGG, TOFF])

    def test_invalid_embedded_aggregate(self):
        bad = _four()
        broken = dict(BAL); broken["n_weeks"] = 99   # n_weeks != len(period_source) → multiweek validator rejects
        bad["theme_plus"] = broken
        with self.assertRaises(mws.PaperMultiweekScorecardError):
            cmp.build_multiweek_comparison(bad)


class Validator(unittest.TestCase):
    def _good(self):
        return cmp.build_multiweek_comparison(_four())

    def test_extra_key(self):
        c = self._good(); c["x"] = 1
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.validate_multiweek_comparison(c)

    def test_boundary_tamper(self):
        c = self._good(); c["boundary"] = dict(c["boundary"], full_size_ship_gate_allowed=True)
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.validate_multiweek_comparison(c)

    def test_doctored_delta(self):
        c = self._good(); c["vs_balanced"]["theme_plus"]["cum_loss_delta"] = 99
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.validate_multiweek_comparison(c)

    def test_bool_delta_rejected(self):
        # a delta whose REAL value is 0 (a profile identical to balanced) forged to False (False==0) must be refused
        # by the strict type gate — proving the gate, NOT just the == re-derivation, closes the bool slip
        c = cmp.build_multiweek_comparison(_four(theme_aggressive=BAL))   # theme_aggressive == balanced → deltas all 0
        self.assertEqual(c["vs_balanced"]["theme_aggressive"]["cum_loss_delta"], 0)
        c["vs_balanced"]["theme_aggressive"]["cum_loss_delta"] = False    # False == 0 would slip past the == alone
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.validate_multiweek_comparison(c)

    def test_theme_marginal_tamper(self):
        c = self._good(); c["theme_weight_marginal_net"] = 0.123
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.validate_multiweek_comparison(c)

    def test_theme_marginal_bool_rejected(self):
        c = self._good(); c["theme_weight_marginal_net"] = False
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.validate_multiweek_comparison(c)

    def test_primary_tamper(self):
        c = self._good(); c["primary_profile"] = "theme_plus"
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.validate_multiweek_comparison(c)

    def test_missing_delta_key(self):
        c = self._good(); del c["vs_balanced"]["theme_plus"]["cum_win_delta"]
        with self.assertRaises(cmp.MultiweekComparisonError):
            cmp.validate_multiweek_comparison(c)


if __name__ == "__main__":
    unittest.main()
