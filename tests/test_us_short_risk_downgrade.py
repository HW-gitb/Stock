# -*- coding: utf-8 -*-
"""Tests for US-short risk_downgrade (engine/us_short_risk_downgrade.py) — §4.2 / §5.2.

Adversarial focus (fewer FAIL->修复 rounds): the load-bearing gates are the SPY/QQQ relative exemption
(a systematic market fall is NOT a stock-specific bad reaction), the two-field separation (the current
event must not feed the slow history score), and soft-only (this never produces a hard veto).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_risk_downgrade as rd  # noqa: E402


class CurrentEventTests(unittest.TestCase):
    def test_good_data_bad_reaction_underperforming_market_is_event(self):
        out = rd.current_good_data_bad_reaction_event(True, -0.05, -0.01)   # stock −5%, market −1%
        self.assertTrue(out["is_event"])
        self.assertFalse(out["exempt"])
        self.assertEqual(out["soft_penalty"], rd.SOFT_EVENT_PENALTY)

    def test_relative_exemption_systematic_fall_is_not_a_downgrade(self):
        # REVERSE-FAILURE control: stock fell LESS than the market → systematic, must NOT downgrade
        out = rd.current_good_data_bad_reaction_event(True, -0.01, -0.05)   # stock −1%, market −5%
        self.assertFalse(out["is_event"])
        self.assertTrue(out["exempt"])

    def test_stock_rose_is_not_a_bad_reaction(self):
        self.assertFalse(rd.current_good_data_bad_reaction_event(True, 0.01, -0.05)["is_event"])

    def test_no_good_data_no_event(self):
        self.assertFalse(rd.current_good_data_bad_reaction_event(False, -0.05, 0.0)["is_event"])

    def test_exemption_boundary_is_strict(self):
        # s == market − X is NOT exempt (downgrade); just above it IS exempt
        self.assertTrue(rd.current_good_data_bad_reaction_event(True, -0.02, 0.0)["is_event"])
        self.assertTrue(rd.current_good_data_bad_reaction_event(True, -0.019, 0.0)["exempt"])

    def test_missing_returns_no_event(self):
        self.assertFalse(rd.current_good_data_bad_reaction_event(True, None, -0.01)["is_event"])
        self.assertFalse(rd.current_good_data_bad_reaction_event(True, -0.05, None)["is_event"])


class HistoryScoreTests(unittest.TestCase):
    def test_scales_with_quarters_and_caps(self):
        self.assertEqual(rd.earnings_reaction_history_score(3), 15.0)
        self.assertEqual(rd.earnings_reaction_history_score(5), rd.HISTORY_MAX_QUARTERS * rd.HISTORY_PER_QUARTER)

    def test_zero_negative_bool_nonint_is_zero(self):
        for bad in (0, -1, True, False, "3", None, 2.0):
            self.assertEqual(rd.earnings_reaction_history_score(bad), 0.0, repr(bad))


class RiskDowngradeTests(unittest.TestCase):
    def test_sum_of_components(self):
        ev = rd.current_good_data_bad_reaction_event(True, -0.05, 0.0)
        out = rd.risk_downgrade(history_score=15.0, current_event=ev, analyst_collective_downgrade=True)
        self.assertEqual(out["points"], 15.0 + rd.SOFT_EVENT_PENALTY + rd.ANALYST_DOWNGRADE_PENALTY)

    def test_never_a_hard_veto(self):
        # REVERSE-FAILURE control: even the worst combination is soft, never a hard veto
        ev = rd.current_good_data_bad_reaction_event(True, -0.20, 0.0)
        out = rd.risk_downgrade(history_score=999.0, current_event=ev, analyst_collective_downgrade=True)
        self.assertFalse(out["hard_veto"])

    def test_current_event_does_not_feed_history(self):
        # two-field separation: the current event lands only in its own component, never inflating history
        ev = rd.current_good_data_bad_reaction_event(True, -0.05, 0.0)
        out = rd.risk_downgrade(history_score=rd.earnings_reaction_history_score(2), current_event=ev)
        self.assertEqual(out["components"]["history"], 10.0)          # 2 quarters × 5, untouched by the event
        self.assertEqual(out["components"]["current_event"], rd.SOFT_EVENT_PENALTY)
        self.assertEqual(out["points"], 20.0)

    def test_exempt_event_adds_nothing(self):
        ev = rd.current_good_data_bad_reaction_event(True, -0.01, -0.05)  # exempt
        out = rd.risk_downgrade(history_score=10.0, current_event=ev)
        self.assertEqual(out["components"]["current_event"], 0.0)
        self.assertEqual(out["points"], 10.0)

    def test_no_signals_is_zero(self):
        out = rd.risk_downgrade()
        self.assertEqual(out["points"], 0.0)
        self.assertFalse(out["hard_veto"])


class BadShapeInputTests(unittest.TestCase):
    """REVERSE-FAILURE class: malformed public-API inputs must fail closed (no fabricated penalty, no
    score boost, no NaN/Inf, no crash) — only an exact-True bool / a real finite non-negative number counts."""

    def test_truthy_nonbool_earnings_beat_is_not_a_beat(self):
        for beat in ("False", "unknown", 1, "True"):
            self.assertFalse(rd.current_good_data_bad_reaction_event(beat, -0.05, -0.01)["is_event"], repr(beat))

    def test_legit_bool_true_beat_still_fires(self):                 # positive control
        self.assertTrue(rd.current_good_data_bad_reaction_event(True, -0.05, -0.01)["is_event"])

    def test_truthy_nonbool_analyst_flag_adds_nothing(self):
        for flag in ("False", 1, "yes"):
            self.assertEqual(rd.risk_downgrade(analyst_collective_downgrade=flag)["components"]["analyst"], 0.0, repr(flag))
        self.assertEqual(rd.risk_downgrade(analyst_collective_downgrade=True)["components"]["analyst"],
                         rd.ANALYST_DOWNGRADE_PENALTY)                # positive control

    def test_truthy_string_is_event_does_not_count(self):
        out = rd.risk_downgrade(current_event={"is_event": "False", "soft_penalty": 10})
        self.assertEqual(out["components"]["current_event"], 0.0)
        self.assertEqual(out["points"], 0.0)

    def test_malformed_soft_penalty_fails_closed_to_zero(self):
        for bad in ("10", None, -100.0, float("nan"), float("inf"), True):
            out = rd.risk_downgrade(current_event={"is_event": True, "soft_penalty": bad})
            self.assertEqual(out["components"]["current_event"], 0.0, repr(bad))   # no penalty / no boost
            self.assertEqual(out["points"], 0.0, repr(bad))
            self.assertFalse(out["hard_veto"])

    def test_non_dict_event_is_ignored(self):
        for bad in ("event", 5, ["is_event"], None):
            self.assertEqual(rd.risk_downgrade(current_event=bad)["points"], 0.0, repr(bad))

    def test_bad_history_score_fails_closed(self):
        for bad in ("15", float("nan"), float("inf"), -50.0, None, True):
            self.assertEqual(rd.risk_downgrade(history_score=bad)["components"]["history"], 0.0, repr(bad))

    def test_bad_exempt_margin_fails_closed_to_default(self):
        # numeric-string / bool / bad / negative / non-finite margins must NOT become live overrides — they
        # fall back to the default so they can't flip, suppress, or invert the relative-exemption gate.
        # (`0` is a legitimate margin, NOT bad, so it is deliberately excluded here.)
        bad_margins = ("bad", None, "0.0", "999", True, False, -1.0, float("nan"), float("inf"))
        # an exempt-by-default case stays exempt (a "0.0" / False override would otherwise flip it to an event)
        self.assertTrue(rd.current_good_data_bad_reaction_event(True, -0.051, -0.05)["exempt"])
        for bad in bad_margins:
            self.assertTrue(
                rd.current_good_data_bad_reaction_event(True, -0.051, -0.05, exempt_margin=bad)["exempt"], repr(bad))
        # an event-by-default case stays an event (a "999" / True override would otherwise suppress it)
        self.assertTrue(rd.current_good_data_bad_reaction_event(True, -0.05, -0.01)["is_event"])
        for bad in bad_margins:
            self.assertTrue(
                rd.current_good_data_bad_reaction_event(True, -0.05, -0.01, exempt_margin=bad)["is_event"], repr(bad))

    def test_legitimate_numeric_margin_still_applies(self):
        # positive control: a real wider margin (0.05) makes a default-event case exempt — genuine numeric
        # overrides still work, only malformed-typed ones fail closed.
        self.assertTrue(rd.current_good_data_bad_reaction_event(True, -0.04, -0.005)["is_event"])          # default 0.02
        self.assertTrue(rd.current_good_data_bad_reaction_event(True, -0.04, -0.005, exempt_margin=0.05)["exempt"])

    def test_bool_or_string_returns_fail_closed(self):
        # REVERSE-FAILURE control: a bool / numeric-string stock or market return must NOT be parsed into a
        # number that fabricates (or suppresses) an event — it fails closed to "no event".
        for bad in (True, False, "-0.05", "0.05", "bad"):
            self.assertFalse(rd.current_good_data_bad_reaction_event(True, bad, -0.01)["is_event"], "stock=%r" % (bad,))
            self.assertFalse(rd.current_good_data_bad_reaction_event(True, -0.05, bad)["is_event"], "market=%r" % (bad,))
        self.assertTrue(rd.current_good_data_bad_reaction_event(True, -0.05, -0.01)["is_event"])   # float positive control


if __name__ == "__main__":
    unittest.main()
