"""Knife-8D0 governance guards for registry-driven P3b external evidence."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from engine.a_short_experiment_admission_registry import p3b_external_comparison_tracks


class P3bGovernanceTests(unittest.TestCase):
    def test_p5_is_registered_but_unimplemented_track_has_no_vote(self):
        rows = {row["track_id"]: row for row in p3b_external_comparison_tracks()}
        self.assertIn("p5_industry_weight", rows)
        self.assertFalse(rows["p5_industry_weight"]["implementation"]["value"])

    def test_flipping_implemented_track_false_removes_its_vote(self):
        from runners import a_short_final_action_validation_runner as runner
        tracks = ({"track_id": "p2", "public_summary_path": "missing.json", "implementation": {"value": False}},)
        with patch.object(runner, "p3b_external_comparison_tracks", return_value=tracks), \
                patch.object(runner, "_is_current_external_public_summary", side_effect=AssertionError("must not read")):
            self.assertEqual(runner._valid_external_public_verdicts(), 0)

    def test_unimplemented_extra_track_cannot_change_count(self):
        from runners import a_short_final_action_validation_runner as runner
        implemented = {"track_id": "p2", "public_summary_path": "missing.json", "implementation": {"value": True}}
        extra = {"track_id": "future", "public_summary_path": "also-missing.json", "implementation": {"value": False}}
        with patch.object(runner, "p3b_external_comparison_tracks", return_value=(implemented,)):
            baseline = runner._valid_external_public_verdicts()
        with patch.object(runner, "p3b_external_comparison_tracks", return_value=(implemented, extra)):
            self.assertEqual(runner._valid_external_public_verdicts(), baseline)

    def test_two_implemented_valid_tracks_make_p3b_condition_reachable(self):
        from runners.a_short_final_action_validation_runner import _p3b_ready
        self.assertTrue(_p3b_ready("edge_positive", 2))
        self.assertFalse(_p3b_ready("not_adjudicated", 2))
