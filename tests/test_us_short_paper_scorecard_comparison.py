# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 two-way scorecard comparison (engine/us_short_paper_scorecard_comparison.py).

Covers: balanced-vs-shadow build (embeds the 4 full-caliber scorecards, per-shadow deltas vs balanced over the
§12.2 honest metrics, the #24 theme_weight_marginal_net, the frozen ship-gate-isolation/paper-only boundary);
None delta when a basket is unrealized (open); profile coverage (missing / extra profile refused); the fixed-TopN
denominator invariant (§12.2 固定 TopN — mismatched selected_total across profiles: small / large shadow basket /
theme_off mismatch refused on build AND validate; all-empty shared OK); bad as_of; an invalid embedded scorecard
refused; and the CLOSED-WORLD validator (extra key / boundary tamper / doctored delta / theme-marginal tamper /
primary tamper refused). Pure/offline; no provider/live; no A-share crossing.
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_scorecard as sc  # noqa: E402
import engine.us_short_paper_scorecard_comparison as cmp  # noqa: E402

AS_OF = "20260112"


def _nr(outcome, net=None, cost=0.0):
    if outcome == "cash_unfilled":
        return {"outcome": "cash_unfilled", "realized": True, "gross_return": 0.0, "cost_fraction": 0.0,
                "net_return": 0.0, "unfilled_cash": True}
    if outcome == "open_unrealized":
        return {"outcome": "open_unrealized", "realized": False, "gross_return": None, "cost_fraction": None,
                "net_return": None, "unfilled_cash": False}
    return {"outcome": outcome, "realized": True, "gross_return": net + cost, "cost_fraction": cost,
            "net_return": net, "unfilled_cash": False}


def _scorecard(*nrs):
    mapping = {("t%d" % i): e for i, e in enumerate(nrs)}
    return sc.build_paper_scorecard(mapping, selected_tickers=list(mapping))


# balanced: 1 win(+0.10) / 1 loss(-0.05) / 1 cash → net_basket 0.05/3, bad_pick 0.5
BAL = _scorecard(_nr("filled_tp_exit", net=0.10), _nr("filled_stopped", net=-0.05), _nr("cash_unfilled"))
# theme_off: 2 win(+0.05 each) / 1 cash → net_basket 0.10/3, bad_pick 0.0
TOFF = _scorecard(_nr("filled_tp_exit", net=0.05), _nr("filled_tp_exit", net=0.05), _nr("cash_unfilled"))
# theme_plus: 2 loss(-0.10) / 1 win(+0.05) → net_basket -0.15/3, bad_pick 2/3
TPLUS = _scorecard(_nr("filled_stopped", net=-0.10), _nr("filled_stopped", net=-0.10), _nr("filled_tp_exit", net=0.05))
# theme_aggressive: 1 win(+0.20) / 2 cash → net_basket 0.20/3, bad_pick 0.0
TAGG = _scorecard(_nr("filled_tp_exit", net=0.20), _nr("cash_unfilled"), _nr("cash_unfilled"))


def _four(balanced=BAL, theme_plus=TPLUS, theme_aggressive=TAGG, theme_off=TOFF):
    return {"balanced": balanced, "theme_plus": theme_plus, "theme_aggressive": theme_aggressive, "theme_off": theme_off}


class Build(unittest.TestCase):
    def test_structure(self):
        c = cmp.build_scorecard_comparison(_four(), as_of=AS_OF)
        self.assertEqual(c["as_of"], AS_OF)
        self.assertEqual(c["primary_profile"], "balanced")
        self.assertEqual(set(c["profiles"]), {"balanced", "theme_plus", "theme_aggressive", "theme_off"})
        self.assertEqual(set(c["vs_balanced"]), {"theme_plus", "theme_aggressive", "theme_off"})
        self.assertEqual(c["boundary"], {"track": "comparison_non_production", "evidence_level": "paper",
                                         "shadow_counts_ship_gate": False, "full_size_ship_gate_allowed": False})

    def test_full_caliber_scorecards_embedded(self):
        c = cmp.build_scorecard_comparison(_four(), as_of=AS_OF)
        self.assertEqual(c["profiles"]["theme_plus"]["loss_count"], 2)        # the shadow's extra losers are visible
        self.assertEqual(c["profiles"]["balanced"]["loss_count"], 1)

    def test_deltas(self):
        c = cmp.build_scorecard_comparison(_four(), as_of=AS_OF)
        d = c["vs_balanced"]["theme_plus"]
        self.assertEqual(d["loss_count_delta"], 1)                            # theme_plus 2 - balanced 1
        self.assertEqual(d["unfilled_cash_count_delta"], -1)                  # 0 - 1
        self.assertAlmostEqual(d["net_basket_delta"], (-0.15 / 3) - (0.05 / 3))
        self.assertAlmostEqual(d["bad_pick_rate_delta"], (2 / 3) - 0.5)

    def test_theme_weight_marginal_net(self):
        # #24 NAV-level: balanced.net - theme_off.net (here theme_off did better → marginal is negative)
        c = cmp.build_scorecard_comparison(_four(), as_of=AS_OF)
        self.assertAlmostEqual(c["theme_weight_marginal_net"], (0.05 / 3) - (0.10 / 3))

    def test_open_basket_yields_none_net_delta(self):
        tplus_open = _scorecard(_nr("filled_stopped", net=-0.10), _nr("open_unrealized"), _nr("filled_tp_exit", net=0.05))
        c = cmp.build_scorecard_comparison(_four(theme_plus=tplus_open), as_of=AS_OF)
        self.assertIsNone(c["vs_balanced"]["theme_plus"]["net_basket_delta"])  # unrealized → not compared (§12.1 不虚高)
        self.assertIsNotNone(c["vs_balanced"]["theme_plus"]["loss_count_delta"])  # count deltas still computed

    def test_theme_off_open_yields_none_marginal(self):
        toff_open = _scorecard(_nr("filled_tp_exit", net=0.05), _nr("open_unrealized"), _nr("cash_unfilled"))
        c = cmp.build_scorecard_comparison(_four(theme_off=toff_open), as_of=AS_OF)
        self.assertIsNone(c["theme_weight_marginal_net"])


class FixedTopNDenominator(unittest.TestCase):
    """§12.2 固定 TopN: every profile's basket must share the same selected_total (no mixed basket sizes)."""

    def test_small_shadow_basket_refused(self):
        small = _scorecard(_nr("filled_tp_exit", net=0.1))  # selected_total=1 vs balanced 3
        with self.assertRaises(cmp.ScorecardComparisonError):
            cmp.build_scorecard_comparison(_four(theme_plus=small), as_of=AS_OF)

    def test_large_shadow_basket_refused(self):
        large = _scorecard(_nr("cash_unfilled"), _nr("cash_unfilled"), _nr("cash_unfilled"), _nr("cash_unfilled"))  # 4
        with self.assertRaises(cmp.ScorecardComparisonError):
            cmp.build_scorecard_comparison(_four(theme_aggressive=large), as_of=AS_OF)

    def test_theme_off_mismatch_refused(self):
        small_toff = _scorecard(_nr("filled_tp_exit", net=0.05), _nr("cash_unfilled"))  # 2 vs balanced 3 (affects #24)
        with self.assertRaises(cmp.ScorecardComparisonError):
            cmp.build_scorecard_comparison(_four(theme_off=small_toff), as_of=AS_OF)

    def test_validator_rejects_mismatched_denominator(self):
        good = cmp.build_scorecard_comparison(_four(), as_of=AS_OF)
        bad = copy.deepcopy(good)
        bad["profiles"]["theme_plus"] = _scorecard(_nr("filled_tp_exit", net=0.1))  # valid scorecard but selected_total=1
        with self.assertRaises(cmp.ScorecardComparisonError):
            cmp.validate_scorecard_comparison(bad)

    def test_all_empty_baskets_share_denominator(self):
        empty = sc.build_paper_scorecard({}, selected_tickers=[])  # selected_total=0 for all → shared
        c = cmp.build_scorecard_comparison({"balanced": empty, "theme_plus": empty,
                                            "theme_aggressive": empty, "theme_off": empty}, as_of=AS_OF)
        self.assertEqual(c["profiles"]["balanced"]["selected_total"], 0)
        self.assertIsNone(c["theme_weight_marginal_net"])


class BadInput(unittest.TestCase):
    def test_missing_profile_refused(self):
        four = _four(); four.pop("theme_off")
        with self.assertRaises(cmp.ScorecardComparisonError):
            cmp.build_scorecard_comparison(four, as_of=AS_OF)

    def test_extra_profile_refused(self):
        four = _four(); four["theme_weird"] = BAL
        with self.assertRaises(cmp.ScorecardComparisonError):
            cmp.build_scorecard_comparison(four, as_of=AS_OF)

    def test_bad_as_of_refused(self):
        with self.assertRaises(cmp.ScorecardComparisonError):
            cmp.build_scorecard_comparison(_four(), as_of="20260231")

    def test_not_dict_refused(self):
        with self.assertRaises(cmp.ScorecardComparisonError):
            cmp.build_scorecard_comparison([BAL], as_of=AS_OF)

    def test_invalid_embedded_scorecard_refused(self):
        bad = copy.deepcopy(BAL); bad["boundary"]["full_size_ship_gate_allowed"] = True  # not a valid paper scorecard
        with self.assertRaises(sc.PaperScorecardError):
            cmp.build_scorecard_comparison(_four(balanced=bad), as_of=AS_OF)


class Validator(unittest.TestCase):
    def setUp(self):
        self.good = cmp.build_scorecard_comparison(_four(), as_of=AS_OF)

    def _rejects(self, mutate):
        bad = copy.deepcopy(self.good)
        mutate(bad)
        with self.assertRaises(cmp.ScorecardComparisonError):
            cmp.validate_scorecard_comparison(bad)

    def test_good_passes(self):
        cmp.validate_scorecard_comparison(self.good)

    def test_extra_key_refused(self):
        self._rejects(lambda b: b.__setitem__("note", "x"))

    def test_boundary_ship_gate_flip_refused(self):
        self._rejects(lambda b: b["boundary"].__setitem__("shadow_counts_ship_gate", True))

    def test_doctored_delta_refused(self):
        self._rejects(lambda b: b["vs_balanced"]["theme_plus"].__setitem__("loss_count_delta", 0))

    def test_theme_marginal_tamper_refused(self):
        self._rejects(lambda b: b.__setitem__("theme_weight_marginal_net", 9.9))

    def test_primary_tamper_refused(self):
        self._rejects(lambda b: b.__setitem__("primary_profile", "theme_plus"))

    def test_missing_shadow_in_vs_balanced_refused(self):
        self._rejects(lambda b: b["vs_balanced"].pop("theme_off"))


if __name__ == "__main__":
    unittest.main()
