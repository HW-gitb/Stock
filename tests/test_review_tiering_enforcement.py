"""Guards for the verification-tiering enforcement layers (AGENTS.md §Verification tiering).

Two mechanical layers must not silently regress:
1. The review-gate prompt hook (`_review_context`) injects the tiering STEP-0 (ledger check /
   defer the full pack to PASS-merge / FAIL-early / independent-agent gate) on a review prompt.
2. The pre-commit verification-tiering reminder is scoped to the a-short production surface and is
   WARN-ONLY — it can never block a commit.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_review_gate():
    spec = importlib.util.spec_from_file_location(
        "claude_review_gate", ROOT / ".tools" / "claude_review_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewContextTieringTests(unittest.TestCase):
    def test_review_context_carries_tiering_step0(self):
        text = _load_review_gate()._review_context()
        # ① ledger-first + cite-green (do not re-run the full pack)
        self.assertIn("full_pack_ledger.py check", text)
        # ② defer the full pack to the PASS/merge gate
        self.assertIn("全量", text)
        # ④ the independent agent is gated, not a default
        self.assertIn("agent", text)

    def test_review_prompt_detection_unchanged(self):
        gate = _load_review_gate()
        self.assertTrue(gate.is_review_prompt("审查当前 diff"))
        self.assertFalse(gate.is_review_prompt("讨论审查 workflow"))


class PreCommitReminderTests(unittest.TestCase):
    def setUp(self):
        self.hook = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")

    def test_reminder_exists_and_scoped_to_a_short_production(self):
        self.assertIn("Verification-tiering reminder", self.hook)
        self.assertIn("full_pack_ledger.py check a_short", self.hook)
        self.assertIn("runners/a_short_", self.hook)

    def test_reminder_block_is_warn_only(self):
        # From the reminder marker to EOF must contain no `exit 1`: the reminder can never block.
        marker = "Verification-tiering reminder"
        self.assertEqual(self.hook.count(marker), 1)
        block = self.hook[self.hook.index(marker):]
        self.assertNotIn("exit 1", block)


if __name__ == "__main__":
    unittest.main()
