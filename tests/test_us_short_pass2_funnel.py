from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_pass2_funnel import Pass2FunnelError, select_pass2_targets  # noqa: E402


class SelectPass2TargetsTest(unittest.TestCase):
    def test_narrows_to_top_k_by_score_desc(self):
        scores = {"AAA": 10.0, "BBB": 90.0, "CCC": 50.0, "DDD": 70.0}
        eligible = {"AAA", "BBB", "CCC", "DDD"}
        target = select_pass2_targets(
            momentum_scores=scores, theme_scores={}, eligible=eligible, catalyst_recall=set(), forced_holdings=set(), top_k=2
        )
        # top-2 by score = BBB(90), DDD(70); returned sorted
        self.assertEqual(target, ["BBB", "DDD"])

    def test_tie_break_is_canonical_ticker_ascending(self):
        # Three tickers tied at 50; K=2 -> keep the two lexicographically smallest tickers.
        scores = {"CCC": 50.0, "AAA": 50.0, "BBB": 50.0}
        target = select_pass2_targets(
            momentum_scores=scores, theme_scores={}, eligible={"AAA", "BBB", "CCC"}, catalyst_recall=set(), forced_holdings=set(), top_k=2
        )
        self.assertEqual(target, ["AAA", "BBB"])

    def test_forced_holdings_always_included_even_if_not_top_k(self):
        scores = {"AAA": 90.0, "BBB": 80.0, "HOLD": 1.0}
        target = select_pass2_targets(
            momentum_scores=scores,
            theme_scores={},
            eligible={"AAA", "BBB", "HOLD"},
            catalyst_recall=set(),
            forced_holdings={"HOLD"},
            top_k=2,
        )
        # top-2 by score = AAA, BBB; HOLD (score 1, not top-2) is force-added.
        self.assertEqual(target, ["AAA", "BBB", "HOLD"])

    def test_forced_holding_not_momentum_scored_is_still_included(self):
        scores = {"AAA": 90.0, "BBB": 80.0}
        target = select_pass2_targets(
            momentum_scores=scores,
            theme_scores={},
            eligible={"AAA", "BBB", "HOLD"},
            catalyst_recall=set(),
            forced_holdings={"HOLD"},
            top_k=2,
        )
        self.assertEqual(target, ["AAA", "BBB", "HOLD"])

    def test_scored_but_not_eligible_is_excluded(self):
        scores = {"AAA": 90.0, "STALE": 95.0}
        target = select_pass2_targets(
            momentum_scores=scores, theme_scores={}, eligible={"AAA"}, catalyst_recall=set(), forced_holdings=set(), top_k=5
        )
        self.assertEqual(target, ["AAA"])

    def test_k_larger_than_scored_returns_all_scored_eligible(self):
        scores = {"AAA": 10.0, "BBB": 20.0}
        target = select_pass2_targets(
            momentum_scores=scores, theme_scores={}, eligible={"AAA", "BBB"}, catalyst_recall=set(), forced_holdings=set(), top_k=200
        )
        self.assertEqual(target, ["AAA", "BBB"])

    def test_large_universe_narrows_to_exactly_top_k(self):
        scores = {f"T{i:04d}": float(i) for i in range(1000)}
        eligible = set(scores)
        target = select_pass2_targets(
            momentum_scores=scores, theme_scores={}, eligible=eligible, catalyst_recall=set(), forced_holdings=set(), top_k=200
        )
        self.assertEqual(len(target), 200)
        # highest scores are the largest i; top-200 = T0800..T0999
        self.assertEqual(target[0], "T0800")
        self.assertEqual(target[-1], "T0999")

    def test_empty_scored_with_holdings_returns_holdings(self):
        target = select_pass2_targets(
            momentum_scores={}, theme_scores={}, eligible={"HOLD"}, catalyst_recall=set(), forced_holdings={"HOLD"}, top_k=200
        )
        self.assertEqual(target, ["HOLD"])

    def test_forced_holding_outside_eligible_is_still_included(self):
        target = select_pass2_targets(
            momentum_scores={"AAA": 10.0}, theme_scores={}, eligible={"AAA"}, catalyst_recall=set(),
            forced_holdings={"HOLD"}, top_k=5,
        )
        self.assertEqual(target, ["AAA", "HOLD"])

    def test_theme_leader_can_enter_top_k_even_with_low_momentum(self):
        target = select_pass2_targets(
            momentum_scores={"MOMO": 90.0, "THEME": 1.0},
            theme_scores={"MOMO": 0.0, "THEME": 100.0},
            eligible={"MOMO", "THEME"}, catalyst_recall=set(), forced_holdings=set(), top_k=1,
        )
        self.assertEqual(target, ["THEME"])

    def test_catalyst_recall_is_bounded_to_eligible_and_union_selected(self):
        target = select_pass2_targets(
            momentum_scores={"AAA": 90.0, "CAT": 1.0}, theme_scores={}, eligible={"AAA", "CAT"},
            catalyst_recall={"CAT"}, forced_holdings=set(), top_k=1,
        )
        self.assertEqual(target, ["AAA", "CAT"])
        with self.assertRaises(Pass2FunnelError):
            select_pass2_targets(
                momentum_scores={"AAA": 90.0}, theme_scores={}, eligible={"AAA"}, catalyst_recall={"STALE"},
                forced_holdings=set(), top_k=1,
            )

    def test_bad_top_k_raises(self):
        for bad in (0, -1, 2.0, True, "5"):
            with self.subTest(bad=bad):
                with self.assertRaises(Pass2FunnelError):
                    select_pass2_targets(
                        momentum_scores={"AAA": 10.0}, theme_scores={}, eligible={"AAA"}, catalyst_recall=set(), forced_holdings=set(), top_k=bad
                    )

    def test_bad_momentum_scores_shape_raises(self):
        for bad in ([("AAA", 1.0)], None, "AAA"):
            with self.subTest(bad=bad):
                with self.assertRaises(Pass2FunnelError):
                    select_pass2_targets(
                        momentum_scores=bad, theme_scores={}, eligible={"AAA"}, catalyst_recall=set(), forced_holdings=set(), top_k=5
                    )

    def test_non_str_key_or_non_finite_or_bool_score_raises(self):
        for scores in (
            {1: 10.0},
            {"AAA": float("nan")},
            {"AAA": float("inf")},
            {"AAA": True},
            {"AAA": "10"},
            {"AAA": None},
        ):
            with self.subTest(scores=scores):
                with self.assertRaises(Pass2FunnelError):
                    select_pass2_targets(
                        momentum_scores=scores, theme_scores={}, eligible={"AAA"}, catalyst_recall=set(), forced_holdings=set(), top_k=5
                    )

    def test_non_str_ticker_in_eligible_or_holdings_raises(self):
        with self.assertRaises(Pass2FunnelError):
            select_pass2_targets(
                momentum_scores={"AAA": 1.0}, theme_scores={}, eligible={"AAA", 2}, catalyst_recall=set(), forced_holdings=set(), top_k=5
            )
        with self.assertRaises(Pass2FunnelError):
            select_pass2_targets(
                momentum_scores={"AAA": 1.0}, theme_scores={}, eligible={"AAA"}, catalyst_recall=set(), forced_holdings=[2], top_k=5
            )


if __name__ == "__main__":
    unittest.main()
