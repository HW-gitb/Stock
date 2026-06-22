# -*- coding: utf-8 -*-
"""Tests for US-short theme_opportunity_state determination (engine/us_short_theme_opportunity.py) — §7/§4.5.

Adversarial focus: the 4-state mapping + thresholds, only MARKET-CONFIRMED themes earning strong/extreme,
strict `market_confirmed`, and fail-closed (malformed theme ignored, non-list/empty/all-weak → no_strong_theme).
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_theme_opportunity as to  # noqa: E402

_GOV = ROOT / "presets" / "us_short_theme_probe_governance_20260622.json"


def _theme(score, confirmed=False):
    return {"theme_score": score, "market_confirmed": confirmed}


class ClassifyTests(unittest.TestCase):
    def test_extreme_needs_confirmed_at_or_above_threshold(self):
        self.assertEqual(to.classify_theme_opportunity_state([_theme(to.EXTREME_SCORE, confirmed=True)]), "extreme")
        self.assertEqual(to.classify_theme_opportunity_state([_theme(95, confirmed=True), _theme(40, confirmed=True)]), "extreme")

    def test_strong_is_any_confirmed_below_extreme(self):
        self.assertEqual(to.classify_theme_opportunity_state([_theme(to.EXTREME_SCORE - 0.1, confirmed=True)]), "strong")
        self.assertEqual(to.classify_theme_opportunity_state([_theme(30, confirmed=True), _theme(90, confirmed=False)]), "strong")

    def test_confirmed_low_or_zero_score_is_intentionally_strong(self):
        # DESIGN DECISION pinned (user-approved 2026-06-22; cc_review_v2 §4.3 / Codex review_v2 §4.3):
        # `market_confirmed` is the AUTHORITATIVE boolean gate (the theme passed the §4.3 ≥3/7 confirmation);
        # `theme_score` only sets the EXTREME bar. So a market-confirmed theme below EXTREME_SCORE is `strong`
        # REGARDLESS of how low the score is — INCLUDING score=0. This is pinned INTENTIONAL (not a missing
        # score-floor): §8 back-gates (30% / 同主题周≤2 / 最小仓 / hard_veto) still bound the actual sizing. A
        # score floor would change the approved semantics, so it is deliberately NOT added.
        for score in (0.0, 0.1, 5.0, 19.9, to.EXTREME_SCORE - 0.1):
            self.assertEqual(to.classify_theme_opportunity_state([_theme(score, confirmed=True)]), "strong",
                             f"confirmed+score={score} must stay strong (market_confirmed is the authoritative gate)")

    def test_normal_is_activity_without_confirmation(self):
        self.assertEqual(to.classify_theme_opportunity_state([_theme(to.ACTIVITY_FLOOR)]), "normal")
        self.assertEqual(to.classify_theme_opportunity_state([_theme(60), _theme(10)]), "normal")   # unconfirmed only

    def test_no_strong_theme_when_no_activity(self):
        self.assertEqual(to.classify_theme_opportunity_state([_theme(to.ACTIVITY_FLOOR - 0.1)]), "no_strong_theme")
        self.assertEqual(to.classify_theme_opportunity_state([]), "no_strong_theme")

    def test_only_confirmed_themes_earn_strong_or_extreme(self):
        # a very strong UNCONFIRMED theme does not make the week strong/extreme — it falls to normal
        self.assertEqual(to.classify_theme_opportunity_state([_theme(99, confirmed=False)]), "normal")


class StrictAndFailClosedTests(unittest.TestCase):
    def test_market_confirmed_strict_true(self):
        # a truthy-non-True market_confirmed must NOT count as confirmed → the high score falls to normal
        for truthy in (1, "yes", [1]):
            out = to.classify_theme_opportunity_state([{"theme_score": 95, "market_confirmed": truthy}])
            self.assertEqual(out, "normal", repr(truthy))

    def test_malformed_theme_or_score_ignored(self):
        # a confirmed theme with a valid score still classifies; malformed siblings are ignored, not fatal
        themes = ["notadict", {"market_confirmed": True}, {"theme_score": "x", "market_confirmed": True},
                  {"theme_score": float("nan"), "market_confirmed": True}, _theme(85, confirmed=True)]
        self.assertEqual(to.classify_theme_opportunity_state(themes), "extreme")

    def test_all_malformed_or_non_list_is_no_strong(self):
        self.assertEqual(to.classify_theme_opportunity_state(["x", {"market_confirmed": True}]), "no_strong_theme")
        for bad in (None, "themes", 5, {"theme_score": 90}):
            self.assertEqual(to.classify_theme_opportunity_state(bad), "no_strong_theme", repr(bad))

    def test_out_of_range_finite_score_ignored_not_upgraded(self):
        # a finite score outside [0,100] is a scale bug — ignored, NEVER upgrading the state
        for bad in (1000, 100.1, -1, -0.1):
            self.assertEqual(to.classify_theme_opportunity_state([{"theme_score": bad, "market_confirmed": True}]),
                             "no_strong_theme", repr(bad))                       # sole out-of-range theme → ignored
            self.assertEqual(to.classify_theme_opportunity_state([{"theme_score": bad, "market_confirmed": False}]),
                             "no_strong_theme", repr(bad))
        # an out-of-range theme alongside a valid one does not contaminate
        self.assertEqual(to.classify_theme_opportunity_state([_theme(1000, confirmed=True), _theme(30)]), "normal")


class ContractTests(unittest.TestCase):
    def test_vocab_matches_preset(self):
        gov = json.loads(_GOV.read_text(encoding="utf-8"))
        self.assertEqual(to.THEME_OPPORTUNITY_STATES, tuple(gov["theme_opportunity_state_vocab"]))

    def test_every_output_is_in_the_vocab(self):
        for themes in ([], [_theme(10)], [_theme(50)], [_theme(50, True)], [_theme(90, True)]):
            self.assertIn(to.classify_theme_opportunity_state(themes), to.THEME_OPPORTUNITY_STATES)

    def test_thresholds_pinned_to_v1_priors(self):
        # pin the §13.1 #29 v1 thresholds exactly — an accidental change must break the test, not pass silently
        self.assertEqual(to.ACTIVITY_FLOOR, 20.0)
        self.assertEqual(to.EXTREME_SCORE, 80.0)
        self.assertTrue(0.0 <= to.ACTIVITY_FLOOR < to.EXTREME_SCORE <= 100.0)


if __name__ == "__main__":
    unittest.main()
