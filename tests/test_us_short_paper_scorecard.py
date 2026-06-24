# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 paper scorecard (engine/us_short_paper_scorecard.py).

Covers: the basket-LINEAGE contract (§12.2 禁止挑样本/全量 — the map must cover EXACTLY the frozen selection: a
winner-only subset / omitted loser / extra stale ticker / missing selected ticker / duplicate-or-blank identity is
refused); per-basket full-caliber aggregation (counts, win/loss/flat + bad_pick_rate, total cost, equal-weight
net_basket booked only when fully resolved — open blocks it, cash = 0 现金拖累, empty/all-cash edges); the FROZEN
paper-only boundary + the validator's CLOSED-WORLD key set + count-consistency self-check (boundary flip / doctored
count / net_basket presence tamper / smuggled ticker / per-name field / top-level ship-gate-or-track-or-evidence
drift / arbitrary extra or missing key refused); the SOURCE-TRACEABLE magnitude re-derivation from the
de-identified per-position realized_legs (forged net_basket / total_cost VALUE / win-loss split / leg shape
refused); the whole malformed-net_result class; and an integration drift-guard feeding REAL paper_net_result
outputs. Pure/offline; no provider/live; no A-share crossing.
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_scorecard as sc  # noqa: E402
import engine.us_short_paper_net_result as nr  # noqa: E402

COST = {"commission_fee": 0.001, "slippage_bps": 10.0, "spread_cost": 0.0005}  # total 0.0025
_EXIT_REASON = {"filled_stopped": "same_day_stop", "filled_tp_exit": "same_day_tp_exit"}
_BOUNDARY = {"evidence_level": "paper", "full_size_ship_gate_allowed": False,
             "ship_gate_evidence_level": "paper_not_live_normalized"}


def _nr(outcome, net=None, cost=None):
    if outcome == "cash_unfilled":
        return {"outcome": "cash_unfilled", "realized": True, "gross_return": 0.0, "cost_fraction": 0.0,
                "net_return": 0.0, "unfilled_cash": True}
    if outcome == "open_unrealized":
        return {"outcome": "open_unrealized", "realized": False, "gross_return": None, "cost_fraction": None,
                "net_return": None, "unfilled_cash": False}
    return {"outcome": outcome, "realized": True, "gross_return": net + cost, "cost_fraction": cost,
            "net_return": net, "unfilled_cash": False}


def _fill(status, fill_price=None, exit_price=None):
    return {"status": status, "fill_price": fill_price, "exit_price": exit_price,
            "exit_reason": _EXIT_REASON.get(status), "reason": None}


def _basket(mapping):
    """A complete basket: selected_tickers = the map's keys (full coverage)."""
    return sc.build_paper_scorecard(mapping, selected_tickers=list(mapping))


class Aggregation(unittest.TestCase):
    def test_fully_resolved_basket(self):
        s = _basket({"AAA": _nr("filled_tp_exit", net=0.0975, cost=0.0025),
                     "BBB": _nr("filled_stopped", net=-0.0525, cost=0.0025),
                     "CCC": _nr("cash_unfilled")})
        self.assertEqual((s["selected_total"], s["filled_count"], s["unfilled_cash_count"], s["open_unrealized_count"]), (3, 2, 1, 0))
        self.assertEqual((s["win_count"], s["loss_count"], s["flat_count"]), (1, 1, 0))
        self.assertEqual(s["bad_pick_rate"], 0.5)
        self.assertAlmostEqual(s["total_cost_fraction"], 0.005)
        self.assertTrue(s["fully_resolved"])
        self.assertAlmostEqual(s["net_basket"], 0.045 / 3)
        self.assertEqual(s["boundary"], _BOUNDARY)

    def test_open_position_blocks_net_basket(self):
        s = _basket({"AAA": _nr("filled_tp_exit", net=0.10, cost=0.0), "BBB": _nr("open_unrealized")})
        self.assertEqual(s["open_unrealized_count"], 1)
        self.assertFalse(s["fully_resolved"])
        self.assertIsNone(s["net_basket"])

    def test_empty_basket(self):
        s = sc.build_paper_scorecard({}, selected_tickers=[])
        self.assertEqual(s["selected_total"], 0)
        self.assertTrue(s["fully_resolved"])
        self.assertIsNone(s["net_basket"])
        self.assertIsNone(s["bad_pick_rate"])

    def test_all_cash_is_zero_basket_with_full_drag(self):
        s = _basket({"AAA": _nr("cash_unfilled"), "BBB": _nr("cash_unfilled")})
        self.assertEqual((s["unfilled_cash_count"], s["filled_count"]), (2, 0))
        self.assertIsNone(s["bad_pick_rate"])
        self.assertEqual(s["net_basket"], 0.0)

    def test_flat_closed_counts_as_flat(self):
        s = _basket({"AAA": _nr("filled_stopped", net=0.0, cost=0.0025)})
        self.assertEqual((s["flat_count"], s["win_count"], s["loss_count"]), (1, 0, 0))
        self.assertEqual(s["bad_pick_rate"], 0.0)

    def test_bad_pick_rate_fraction(self):
        s = _basket({"AAA": _nr("filled_tp_exit", net=0.1, cost=0.0), "BBB": _nr("filled_stopped", net=-0.1, cost=0.0),
                     "CCC": _nr("filled_stopped", net=-0.2, cost=0.0)})
        self.assertEqual(s["loss_count"], 2)
        self.assertAlmostEqual(s["bad_pick_rate"], 2 / 3)


class BasketCoverage(unittest.TestCase):
    """§12.2 禁止挑样本/全量: the map must cover EXACTLY the frozen selection."""

    def test_winner_only_subset_refused(self):
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": _nr("filled_tp_exit", net=0.1, cost=0.0)},
                                     selected_tickers=["AAA", "BBB", "CCC"])

    def test_omitted_loser_refused(self):
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": _nr("filled_tp_exit", net=0.1, cost=0.0), "CCC": _nr("cash_unfilled")},
                                     selected_tickers=["AAA", "BBB", "CCC"])

    def test_extra_stale_ticker_refused(self):
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": _nr("filled_tp_exit", net=0.1, cost=0.0),
                                      "BBB": _nr("filled_stopped", net=-0.1, cost=0.0),
                                      "STALE": _nr("filled_tp_exit", net=0.1, cost=0.0)},
                                     selected_tickers=["AAA", "BBB"])

    def test_duplicate_identity_in_selection_refused(self):
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": _nr("cash_unfilled")}, selected_tickers=["AAA", "AAA"])

    def test_blank_or_nonstring_identity_refused(self):
        for bad in ([""], ["  "], [123], ["AAA", None]):
            with self.assertRaises(sc.PaperScorecardError):
                sc.build_paper_scorecard({}, selected_tickers=bad)

    def test_map_not_dict_refused(self):
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard([_nr("cash_unfilled")], selected_tickers=["AAA"])

    def test_selected_tickers_not_list_refused(self):
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": _nr("cash_unfilled")}, selected_tickers="AAA")


class Malformed(unittest.TestCase):
    def test_bad_entry_shape(self):
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": {"outcome": "cash_unfilled"}}, selected_tickers=["AAA"])

    def test_unknown_outcome(self):
        e = _nr("filled_tp_exit", net=0.1, cost=0.0); e["outcome"] = "weird"
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": e}, selected_tickers=["AAA"])

    def test_inconsistent_net(self):
        e = _nr("filled_tp_exit", net=0.1, cost=0.0); e["net_return"] = 0.5
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": e}, selected_tickers=["AAA"])

    def test_cash_with_nonzero_net(self):
        e = _nr("cash_unfilled"); e["net_return"] = 0.1
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": e}, selected_tickers=["AAA"])

    def test_open_with_a_number(self):
        e = _nr("open_unrealized"); e["net_return"] = 0.1
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": e}, selected_tickers=["AAA"])

    def test_closed_with_negative_cost(self):
        with self.assertRaises(sc.PaperScorecardError):
            sc.build_paper_scorecard({"AAA": _nr("filled_stopped", net=-0.05, cost=-0.001)}, selected_tickers=["AAA"])


class ScorecardValidator(unittest.TestCase):
    def setUp(self):
        self.good = _basket({"AAA": _nr("filled_tp_exit", net=0.0975, cost=0.0025),
                             "BBB": _nr("filled_stopped", net=-0.0525, cost=0.0025),
                             "CCC": _nr("cash_unfilled")})

    def _rejects(self, mutate):
        bad = copy.deepcopy(self.good)
        mutate(bad)
        with self.assertRaises(sc.PaperScorecardError):
            sc.validate_paper_scorecard(bad)

    def test_good_passes(self):
        sc.validate_paper_scorecard(self.good)

    def test_ship_gate_flip_refused(self):
        self._rejects(lambda b: b["boundary"].__setitem__("full_size_ship_gate_allowed", True))

    def test_evidence_level_tamper_refused(self):
        self._rejects(lambda b: b["boundary"].__setitem__("evidence_level", "live_normalized"))

    def test_doctored_count_refused(self):
        self._rejects(lambda b: b.__setitem__("loss_count", 0))  # filled != win+loss+flat

    def test_selected_total_mismatch_refused(self):
        self._rejects(lambda b: b.__setitem__("selected_total", 9))

    def test_net_basket_missing_on_resolved_refused(self):
        self._rejects(lambda b: b.__setitem__("net_basket", None))

    # closed-world: no ticker / ship-gate / live field may be smuggled onto the de-identified paper scorecard
    def test_smuggled_tickers_field_refused(self):
        self._rejects(lambda b: b.__setitem__("tickers", ["AAA", "BBB", "CCC"]))

    def test_per_name_performance_field_refused(self):
        self._rejects(lambda b: b.__setitem__("performance_by_ticker", {"AAA": 0.1}))

    def test_top_level_ship_gate_flag_refused(self):
        self._rejects(lambda b: b.__setitem__("full_size_ship_gate_allowed", True))

    def test_top_level_track_drift_refused(self):
        self._rejects(lambda b: b.__setitem__("track", "live_normalized"))

    def test_top_level_evidence_level_drift_refused(self):
        self._rejects(lambda b: b.__setitem__("evidence_level", "live_normalized"))

    def test_arbitrary_extra_key_refused(self):
        self._rejects(lambda b: b.__setitem__("note", "anything"))

    def test_missing_key_refused(self):
        self._rejects(lambda b: b.pop("net_basket"))


class MagnitudeSourceTraceable(unittest.TestCase):
    """R-USSHORT-BATCH3-SCORECARD-MAGNITUDE-TRACEBACK-GAP: net_basket / total_cost_fraction / win-loss-flat are
    RE-DERIVED from the de-identified per-position ``realized_legs`` (mirrors nav_drawdown / multiweek source-
    traceability), so a lazily-tampered aggregate that diverges from its own legs fails closed — VALUE tamper, not
    just presence. (A fully self-consistent re-forge of legs + aggregate is the accepted system limit.)"""

    def setUp(self):
        self.good = _basket({"AAA": _nr("filled_tp_exit", net=0.05, cost=0.001),
                             "BBB": _nr("filled_stopped", net=-0.03, cost=0.001),
                             "CCC": _nr("cash_unfilled")})

    def _rejects(self, mutate):
        bad = copy.deepcopy(self.good)
        mutate(bad)
        with self.assertRaises(sc.PaperScorecardError):
            sc.validate_paper_scorecard(bad)

    def test_realized_legs_de_identified_and_sorted(self):
        legs = self.good["realized_legs"]
        self.assertEqual(len(legs), 2)                                             # one per CLOSED position
        self.assertEqual(legs, sorted(legs, key=lambda d: (d["net"], d["cost"])))  # sorted (breaks ticker correlation)
        self.assertEqual(set(legs[0]), {"net", "cost"})                            # no tickers / $

    def test_forged_net_basket_value_refused(self):     # the headline gap: a doctored VALUE (not presence) is caught
        self._rejects(lambda b: b.__setitem__("net_basket", 5.0))

    def test_forged_total_cost_value_refused(self):
        self._rejects(lambda b: b.__setitem__("total_cost_fraction", 999.0))

    def test_bool_total_cost_refused(self):             # numerically-equal bool can't slip past the value re-derivation
        empty = sc.build_paper_scorecard({}, selected_tickers=[])                  # total_cost_fraction == 0.0
        bad = copy.deepcopy(empty); bad["total_cost_fraction"] = False             # False == 0.0
        with self.assertRaises(sc.PaperScorecardError):
            sc.validate_paper_scorecard(bad)

    def test_forged_win_loss_split_refused(self):       # win=2/loss=0 still sums to filled=2 but diverges from the legs
        self._rejects(lambda b: (b.__setitem__("win_count", 2), b.__setitem__("loss_count", 0)))

    def test_legs_diverge_from_filled_count_refused(self):
        self._rejects(lambda b: b["realized_legs"].pop())                          # len(legs) != filled_count

    def test_bad_leg_shape_refused(self):
        for mutate in (lambda b: b["realized_legs"].__setitem__(0, {"net": 0.05}),            # missing cost
                       lambda b: b["realized_legs"].__setitem__(0, {"net": True, "cost": 0.0}),  # bool net
                       lambda b: b["realized_legs"].__setitem__(0, {"net": 0.05, "cost": -0.1}),  # negative cost
                       lambda b: b.__setitem__("realized_legs", "nope")):                     # not a list
            self._rejects(mutate)


class IntegrationDriftGuard(unittest.TestCase):
    def test_real_net_results_feed_through(self):
        fills = {"AAA": _fill("filled_tp_exit", 100.0, 110.0), "BBB": _fill("filled_stopped", 100.0, 95.0),
                 "CCC": _fill("not_filled"), "DDD": _fill("filled_held", 100.0)}
        mapping = {t: nr.paper_net_result(f, cost_prior=COST) for t, f in fills.items()}
        s = sc.build_paper_scorecard(mapping, selected_tickers=list(mapping))
        self.assertEqual((s["filled_count"], s["unfilled_cash_count"], s["open_unrealized_count"]), (2, 1, 1))
        self.assertEqual((s["win_count"], s["loss_count"]), (1, 1))
        self.assertFalse(s["fully_resolved"])
        self.assertIsNone(s["net_basket"])
        self.assertEqual(s["boundary"], _BOUNDARY)


if __name__ == "__main__":
    unittest.main()
