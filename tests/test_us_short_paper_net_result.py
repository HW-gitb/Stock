# -*- coding: utf-8 -*-
"""Tests for US-short §12.1 paper net result (engine/us_short_paper_net_result.py).

Covers: per-status net (not_filled → 0 cash; same-day close → gross - round-trip cost; held → unrealized
None); the §13 #18 cost prior as round-trip return-drag (commission + spread + slippage_bps/10000);
reproducibility; whole malformed-input class (fill_result / cost_prior shape, unknown status, bad / missing /
negative / non-finite cost, bad close prices); and an integration drift-guard feeding REAL simulate_fill outputs
through. Pure/offline; no provider/live; no A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_net_result as nr  # noqa: E402
import engine.us_short_paper_fill as pf  # noqa: E402

COST = {"commission_fee": 0.001, "slippage_bps": 10.0, "spread_cost": 0.0005}  # total = 0.0025
ZERO_COST = {"commission_fee": 0.0, "slippage_bps": 0.0, "spread_cost": 0.0}


_EXIT_REASON = {"filled_stopped": "same_day_stop", "filled_tp_exit": "same_day_tp_exit"}


def _fill(status, fill_price=None, exit_price=None):
    return {"status": status, "fill_price": fill_price, "exit_price": exit_price,
            "exit_reason": _EXIT_REASON.get(status), "reason": None}


class PerStatus(unittest.TestCase):
    def test_not_filled_is_zero_cash(self):
        r = nr.paper_net_result(_fill("not_filled"), cost_prior=COST)
        self.assertEqual(r["net_return"], 0.0)
        self.assertEqual(r["cost_fraction"], 0.0)  # no trade → no cost
        self.assertTrue(r["unfilled_cash"])
        self.assertTrue(r["realized"])

    def test_stopped_realizes_loss_net_of_cost(self):
        r = nr.paper_net_result(_fill("filled_stopped", fill_price=100.0, exit_price=95.0), cost_prior=COST)
        self.assertAlmostEqual(r["gross_return"], -0.05)
        self.assertAlmostEqual(r["net_return"], -0.05 - 0.0025)
        self.assertTrue(r["realized"])
        self.assertFalse(r["unfilled_cash"])

    def test_tp_exit_realizes_gain_net_of_cost(self):
        r = nr.paper_net_result(_fill("filled_tp_exit", fill_price=100.0, exit_price=110.0), cost_prior=COST)
        self.assertAlmostEqual(r["gross_return"], 0.10)
        self.assertAlmostEqual(r["net_return"], 0.10 - 0.0025)

    def test_held_is_unrealized_none(self):
        r = nr.paper_net_result(_fill("filled_held", fill_price=100.0), cost_prior=COST)
        self.assertEqual(r["outcome"], "open_unrealized")
        self.assertFalse(r["realized"])
        self.assertIsNone(r["net_return"])  # an open position is NOT booked as net (§12.1 不虚高)


class CostModel(unittest.TestCase):
    def test_total_cost_is_commission_plus_spread_plus_bps(self):
        r = nr.paper_net_result(_fill("filled_tp_exit", fill_price=100.0, exit_price=100.0), cost_prior=COST)
        self.assertAlmostEqual(r["cost_fraction"], 0.0025)  # 0.001 + 0.0005 + 10/10000

    def test_zero_cost_net_equals_gross(self):
        r = nr.paper_net_result(_fill("filled_tp_exit", fill_price=100.0, exit_price=110.0), cost_prior=ZERO_COST)
        self.assertAlmostEqual(r["net_return"], r["gross_return"])


class Reproducible(unittest.TestCase):
    def test_same_inputs_same_result(self):
        f = _fill("filled_stopped", fill_price=100.0, exit_price=95.0)
        self.assertEqual(nr.paper_net_result(f, cost_prior=COST), nr.paper_net_result(f, cost_prior=COST))


class MalformedFailsClosed(unittest.TestCase):
    def test_bad_fill_result_refused(self):
        for bad in (None, "x", 5, []):
            with self.assertRaises(nr.PaperNetResultError, msg=repr(bad)):
                nr.paper_net_result(bad, cost_prior=COST)

    def test_unknown_status_refused(self):
        with self.assertRaises(nr.PaperNetResultError):
            nr.paper_net_result(_fill("filled_partial"), cost_prior=COST)

    def test_bad_cost_prior_refused(self):
        for bad in (None, "x", {"commission_fee": 0.001}, dict(COST, extra=1),
                    dict(COST, commission_fee=-0.001), dict(COST, slippage_bps="10"),
                    dict(COST, spread_cost=True), dict(COST, commission_fee=float("inf"))):
            with self.assertRaises(nr.PaperNetResultError, msg=repr(bad)):
                nr.paper_net_result(_fill("not_filled"), cost_prior=bad)

    def test_bad_close_prices_refused(self):
        for f in (_fill("filled_stopped", fill_price=None, exit_price=95.0),
                  _fill("filled_stopped", fill_price=0, exit_price=95.0),
                  _fill("filled_stopped", fill_price=100.0, exit_price=-95.0),
                  _fill("filled_tp_exit", fill_price=100.0, exit_price=None),
                  _fill("filled_tp_exit", fill_price="100", exit_price=110.0)):
            with self.assertRaises(nr.PaperNetResultError, msg=repr(f)):
                nr.paper_net_result(f, cost_prior=COST)


class IntegrationWithSimulateFill(unittest.TestCase):
    """Drift guard: feed REAL simulate_fill outputs through paper_net_result for every status it emits, so a new
    fill status can't silently slip past this consumer."""

    def _order(self):
        return {"order_type": "pullback_limit", "order_expiry": "first_regular_session_only",
                "valid_entry_low": 95.0, "valid_entry_high": 105.0, "limit_order_price": 98.0,
                "stop_clear_price": 92.0, "take_profit_exit_price": 115.0}

    def test_each_real_fill_status_handled(self):
        bars = {
            "not_filled": {"open": 100.0, "high": 103.0, "low": 99.0, "close": 101.0},   # low > limit
            "filled_held": {"open": 100.0, "high": 103.0, "low": 97.0, "close": 101.0},  # filled, no same-day exit
            "filled_stopped": {"open": 100.0, "high": 103.0, "low": 90.0, "close": 93.0},
            "filled_tp_exit": {"open": 100.0, "high": 116.0, "low": 97.0, "close": 114.0},
        }
        for expected_status, bar in bars.items():
            fill = pf.simulate_fill(self._order(), bar)
            self.assertEqual(fill["status"], expected_status)
            r = nr.paper_net_result(fill, cost_prior=COST)  # must not raise for any real status
            if expected_status == "not_filled":
                self.assertEqual(r["net_return"], 0.0)
            elif expected_status == "filled_held":
                self.assertIsNone(r["net_return"])
            else:
                self.assertTrue(r["realized"])
                self.assertIsNotNone(r["net_return"])


class FillShapeLocked(unittest.TestCase):
    """R-USSHORT-BATCH3-PAPER-NET-FILL-SHAPE-GAP: the FULL per-status fill_result shape is locked — an
    inconsistent status ⇔ price/reason record is refused before any accounting (the consumer never trusts the
    producer)."""

    def _held(self, **over):
        d = {"status": "filled_held", "fill_price": 100.0, "exit_price": None, "exit_reason": None, "reason": None}
        d.update(over)
        return d

    def test_held_bad_fill_price_refused(self):
        for bad in (None, 0, -100.0, "100", True, float("inf")):
            with self.assertRaises(nr.PaperNetResultError, msg=repr(bad)):
                nr.paper_net_result(self._held(fill_price=bad), cost_prior=ZERO_COST)

    def test_held_with_exit_refused(self):  # held is OPEN — no exit_price / closed exit_reason
        with self.assertRaises(nr.PaperNetResultError):
            nr.paper_net_result(self._held(exit_price=110.0), cost_prior=ZERO_COST)
        with self.assertRaises(nr.PaperNetResultError):
            nr.paper_net_result(self._held(exit_reason="same_day_stop"), cost_prior=ZERO_COST)

    def test_not_filled_with_prices_or_reason_refused(self):
        for over in ({"fill_price": 100.0}, {"exit_price": 95.0}, {"exit_reason": "same_day_stop"}):
            d = {"status": "not_filled", "fill_price": None, "exit_price": None, "exit_reason": None, "reason": "x"}
            d.update(over)
            with self.assertRaises(nr.PaperNetResultError, msg=repr(over)):
                nr.paper_net_result(d, cost_prior=ZERO_COST)

    def test_closed_wrong_or_missing_exit_reason_refused(self):
        for status, bad in [("filled_stopped", "same_day_tp_exit"), ("filled_stopped", None),
                            ("filled_tp_exit", "same_day_stop"), ("filled_tp_exit", "wrong")]:
            with self.assertRaises(nr.PaperNetResultError, msg="%s/%s" % (status, bad)):
                nr.paper_net_result({"status": status, "fill_price": 100.0, "exit_price": 105.0,
                                     "exit_reason": bad, "reason": None}, cost_prior=ZERO_COST)

    def test_correct_closed_reasons_pass(self):  # positive controls: the simulator's exact status⇔reason pairs
        nr.paper_net_result({"status": "filled_stopped", "fill_price": 100.0, "exit_price": 95.0,
                             "exit_reason": "same_day_stop", "reason": None}, cost_prior=ZERO_COST)
        nr.paper_net_result({"status": "filled_tp_exit", "fill_price": 100.0, "exit_price": 110.0,
                             "exit_reason": "same_day_tp_exit", "reason": None}, cost_prior=ZERO_COST)


if __name__ == "__main__":
    unittest.main()
