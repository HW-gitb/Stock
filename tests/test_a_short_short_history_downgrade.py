"""Queue row 18: short-history candidates are downgraded, never excluded.

2026-08-04 user ruling: names with fewer usable closes than the indicator
requirement stay in the scoring pool but may not reach Tier1 or the final
recommendation.  These tests pin the bar itself, its boundary, its degenerate
inputs, and that both watch-pool selector call sites actually go through it.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_short_history_probe", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _frame(pairs):
    return pd.DataFrame(
        [{"ts_code": code, "price_observation_count": count} for code, count in pairs]
    )


class ShortHistoryDowngradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs()
        cls.required = cls.egs.DAILY_STATS_REQUIRED_CLOSES

    def test_threshold_is_the_shared_indicator_requirement(self):
        # The bar must not invent its own number; 60-session lookback + 1 close.
        self.assertEqual(self.required, max(self.egs.DAILY_STATS_LOOKBACKS.values()) + 1)

    def test_short_history_row_is_barred_but_stays_in_the_scoring_pool(self):
        scored = _frame([("600000.SH", 40), ("600519.SH", 65)])
        eligible = self.egs.watch_pool_eligible_frame(scored)
        self.assertEqual(list(eligible["ts_code"]), ["600519.SH"])
        # The scoring pool itself is untouched -- downgrade, not exclusion.
        self.assertEqual(len(scored), 2)
        self.assertIn("600000.SH", set(scored["ts_code"]))

    def test_full_history_rows_pass_through_field_for_field(self):
        scored = _frame([("600000.SH", 65), ("600519.SH", 64), ("601318.SH", 200)])
        eligible = self.egs.watch_pool_eligible_frame(scored)
        pd.testing.assert_frame_equal(
            eligible.reset_index(drop=True), scored.reset_index(drop=True)
        )

    def test_exact_threshold_is_admitted_and_one_below_is_barred(self):
        scored = _frame([("600000.SH", self.required), ("600519.SH", self.required - 1)])
        eligible = self.egs.watch_pool_eligible_frame(scored)
        self.assertEqual(list(eligible["ts_code"]), ["600000.SH"])

    def test_degenerate_observation_counts_fail_closed_without_crashing(self):
        # Zero sits in the gap the published counter's between(1, N-1) leaves
        # open; it is strictly worse than short history and must be barred too.
        scored = pd.DataFrame([
            {"ts_code": "600000.SH", "price_observation_count": 0},
            {"ts_code": "600519.SH", "price_observation_count": None},
            {"ts_code": "601318.SH", "price_observation_count": "not-a-number"},
            {"ts_code": "600036.SH", "price_observation_count": 90},
        ])
        eligible = self.egs.watch_pool_eligible_frame(scored)
        self.assertEqual(list(eligible["ts_code"]), ["600036.SH"])

    def test_missing_column_and_empty_frame_do_not_crash(self):
        no_column = pd.DataFrame([{"ts_code": "600000.SH"}])
        self.assertEqual(len(self.egs.watch_pool_eligible_frame(no_column)), 1)
        empty = pd.DataFrame(columns=["ts_code", "price_observation_count"])
        self.assertEqual(len(self.egs.watch_pool_eligible_frame(empty)), 0)

    def test_planted_removal_of_the_bar_makes_the_positive_control_red(self):
        scored = _frame([("600000.SH", 40), ("600519.SH", 65)])
        original = self.egs.watch_pool_eligible_frame
        try:
            self.egs.watch_pool_eligible_frame = lambda df: df
            neutralised = self.egs.watch_pool_eligible_frame(scored)
        finally:
            self.egs.watch_pool_eligible_frame = original
        # With the bar neutralised the short-history name survives, so the
        # positive control above is genuinely load-bearing.
        self.assertIn("600000.SH", set(neutralised["ts_code"]))
        self.assertNotIn(
            "600000.SH", set(self.egs.watch_pool_eligible_frame(scored)["ts_code"])
        )

    def test_every_watch_pool_selector_call_site_goes_through_the_bar(self):
        """Regression guard: an unfiltered frame must never reach the selector."""
        tree = ast.parse(EGS_SCRIPT.read_text(encoding="utf-8"))
        unguarded = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "select_profile_watch_pool" or not node.args:
                continue
            first = node.args[0]
            guarded = (
                isinstance(first, ast.Call)
                and getattr(first.func, "id", getattr(first.func, "attr", None))
                == "watch_pool_eligible_frame"
            )
            if not guarded:
                unguarded.append(ast.dump(first)[:60])
        self.assertEqual(unguarded, [], f"unguarded selector call sites: {unguarded}")


if __name__ == "__main__":
    unittest.main()
