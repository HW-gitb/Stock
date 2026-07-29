"""Knife-8D0 governance guards for registry-driven P3b external evidence."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from engine.a_short_experiment_admission_registry import p3b_external_comparison_tracks


class P3bGovernanceTests(unittest.TestCase):
    def test_p5_is_registered_with_a_terminal_verdict_contract(self):
        rows = {row["track_id"]: row for row in p3b_external_comparison_tracks()}
        self.assertIn("p5_industry_weight", rows)
        contract = rows["p5_industry_weight"]["public_verdict_contract"]
        self.assertTrue(rows["p5_industry_weight"]["implementation"]["value"])
        self.assertEqual(contract["terminal_stage_field"], "adjudication_stage")
        self.assertIn("do_not_promote", contract["terminal_verdicts"])
        from runners import a_short_final_action_validation_runner as runner
        self.assertEqual(runner._valid_external_public_verdicts(), 0)

    def test_flipping_implemented_track_false_removes_its_vote(self):
        from runners import a_short_final_action_validation_runner as runner
        tracks = ({"track_id": "p2", "public_summary_path": "missing.json", "implementation": {"value": False},
                   "public_verdict_contract": {"terminal_verdicts": ("edge_positive",)}},)
        with patch.object(runner, "p3b_external_comparison_tracks", return_value=tracks), \
                patch.object(runner, "_is_current_external_public_summary", side_effect=AssertionError("must not read")):
            self.assertEqual(runner._valid_external_public_verdicts(), 0)

    def test_unimplemented_extra_track_cannot_change_count(self):
        from runners import a_short_final_action_validation_runner as runner
        implemented = {"track_id": "p2", "public_summary_path": "missing.json", "implementation": {"value": True},
                       "public_verdict_contract": {"terminal_verdicts": ("edge_positive",)}}
        extra = {"track_id": "future", "public_summary_path": "also-missing.json", "implementation": {"value": False},
                 "public_verdict_contract": {"terminal_verdicts": ("future_terminal",)}}
        with patch.object(runner, "p3b_external_comparison_tracks", return_value=(implemented,)):
            baseline = runner._valid_external_public_verdicts()
        with patch.object(runner, "p3b_external_comparison_tracks", return_value=(implemented, extra)):
            self.assertEqual(runner._valid_external_public_verdicts(), baseline)

    def test_implemented_track_without_a_closed_terminal_contract_has_no_vote(self):
        from runners import a_short_final_action_validation_runner as runner
        track = {"track_id": "future", "public_summary_path": "missing.json", "implementation": {"value": True}}
        with patch.object(runner, "p3b_external_comparison_tracks", return_value=(track,)), \
                patch.object(runner, "_is_current_external_public_summary", side_effect=AssertionError("must not read")):
            self.assertEqual(runner._valid_external_public_verdicts(), 0)

    def test_p5_counts_only_after_its_terminal_stage_and_closed_verdict(self):
        import json
        import tempfile
        from pathlib import Path
        from engine.a_short_industry_weight_comparison import build_public_progress, write_public_progress
        from runners import a_short_final_action_validation_runner as runner
        track = next(row for row in p3b_external_comparison_tracks() if row["track_id"] == "p5_industry_weight")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research" / "results" / "a_short" / "industry_weight_comparison_summary.json"
            summary = build_public_progress(root=None, as_of="20260727")
            write_public_progress(summary, json_path=path, markdown_path=path.with_suffix(".md"))
            with patch.object(runner, "ROOT", Path(tmp)), patch.object(runner, "p3b_external_comparison_tracks", return_value=(track,)):
                self.assertEqual(runner._valid_external_public_verdicts(), 0)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["status"] = "review_due"
                payload["verdict"] = "do_not_promote"
                payload["adjudication_stage"] = "terminal"
                for question in payload["questions"]:
                    question["verdict"] = "do_not_promote"
                    question["checkpoint_stage"] = "terminal"
                write_public_progress(payload, json_path=path, markdown_path=path.with_suffix(".md"))
                self.assertEqual(runner._valid_external_public_verdicts(), 1)

    def test_two_implemented_valid_tracks_make_p3b_condition_reachable(self):
        from runners.a_short_final_action_validation_runner import _p3b_ready
        self.assertTrue(_p3b_ready("edge_positive", 2))
        self.assertFalse(_p3b_ready("not_adjudicated", 2))
