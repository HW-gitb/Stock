"""Tests for the A-short per-run bundle path convention (engine/a_short_run_paths.py).

Pins the consolidated run-folder rule (bundle = <EGS output_root>/<as_of>/) and:
- comparison-diff CO-LOCATES with analysis_input in the same bundle for ANY output_root (the fix
  for the previous split where selection and comparison landed in different trees);
- the analysis flow (output_root=research/results/a_short) is guard-safe (does NOT trip the weekly
  pipeline's _reject_production_output_path);
- the default/production bundle equals forward_tracker's read root (result/a_short/<as_of>), so the
  convention is consistent with the production reader.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_run_paths import (  # noqa: E402
    ANALYSIS_OUTPUT_ROOT, LANES, lane_output_root, run_bundle_dir, analysis_input_path,
    weight_comparison_path, weekly_m67_path, account_path,
)
from runners.a_short_weekly_pipeline import _reject_production_output_path  # noqa: E402
from runners.forward_tracker import LIVE_RESULT_ROOT  # noqa: E402

AS_OF = "20260609"


def _n(p):
    return str(p).replace("\\", "/")


class LaneOutputRootTests(unittest.TestCase):
    def test_lane_roots(self):
        self.assertEqual(set(LANES), {"a_short", "a_long", "us_short", "us_long"})
        for lane in LANES:
            p = _n(lane_output_root(lane))
            self.assertTrue(p.endswith(f"research/results/{lane}"), p)
            self.assertNotIn("/result/a_short/", p + "/")          # never the production root
        # a_short lane root == the analysis output root used by the bundle convention
        self.assertTrue(_n(lane_output_root("a_short")).endswith(_n(ANALYSIS_OUTPUT_ROOT)))

    def test_unknown_lane_rejected(self):
        with self.assertRaises(ValueError):
            lane_output_root("a_share")


class RunPathTests(unittest.TestCase):
    def test_comparison_colocates_with_analysis_input_any_output_root(self):
        # the core fix: comparison-diff is in the SAME bundle as analysis_input, for any output_root.
        for orr in (None, ANALYSIS_OUTPUT_ROOT, "result/a_short", "/abs/custom"):
            bundle = _n(run_bundle_dir(AS_OF, output_root=orr))
            self.assertTrue(_n(analysis_input_path(AS_OF, output_root=orr)).startswith(bundle), orr)
            self.assertTrue(_n(weight_comparison_path(AS_OF, output_root=orr)).startswith(bundle), orr)
            self.assertTrue(_n(weekly_m67_path(AS_OF, output_root=orr)).startswith(bundle), orr)
            self.assertTrue(_n(account_path(AS_OF, output_root=orr)).startswith(bundle), orr)
            self.assertTrue(bundle.endswith(f"/{AS_OF}"))

    def test_analysis_flow_bundle_is_guard_safe(self):
        # analysis flow (research/results/a_short) must NOT trip the production-path guard.
        for p in (run_bundle_dir, analysis_input_path, weight_comparison_path, weekly_m67_path, account_path):
            _reject_production_output_path(p(AS_OF, output_root=ANALYSIS_OUTPUT_ROOT))  # no raise
        self.assertNotIn("/result/a_short/", _n(run_bundle_dir(AS_OF, output_root=ANALYSIS_OUTPUT_ROOT)) + "/")

    def test_production_bundle_matches_forward_tracker_read_root(self):
        # default (production) bundle == forward_tracker's LIVE_RESULT_ROOT/<as_of> (the reader's path).
        self.assertEqual(_n(run_bundle_dir(AS_OF)), _n(LIVE_RESULT_ROOT / AS_OF))

    def test_production_path_correctly_tripped_by_guard(self):
        # sanity: the production bundle IS a result/a_short path (so pipeline rightly refuses it;
        # that's why production flow does not put pipeline M6.7 there).
        with self.assertRaises(ValueError):
            _reject_production_output_path(weekly_m67_path(AS_OF))  # default output_root → result/a_short


if __name__ == "__main__":
    unittest.main()
