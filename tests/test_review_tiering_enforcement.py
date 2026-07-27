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
        # ⑤ scope tests to changed symbols, not changed files (no whole-module tax)
        self.assertIn("全模块税", text)
        self.assertIn("改动的函数", text)

    def test_review_context_carries_rule7_execution_schedule(self):
        """Rule 7 (2026-07-27) must ride on every review prompt, not on memory."""
        text = _load_review_gate()._review_context()
        self.assertIn("rule 7", text)
        self.assertIn("run_in_background", text)   # (a) slow superset pack starts FIRST
        self.assertIn("超集", text)                 # (b) superset only
        self.assertIn("禁跑其子集", text)
        self.assertIn("mtime", text)               # (d) residue before code when a test is red
        self.assertIn("10-15", text)               # wall-clock target

    def test_agents_md_carries_rule7(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("审查执行调度", agents)
        self.assertIn("只跑超集，禁跑其子集", agents)

    def test_review_prompt_detection_unchanged(self):
        gate = _load_review_gate()
        self.assertTrue(gate.is_review_prompt("审查当前 diff"))
        self.assertFalse(gate.is_review_prompt("讨论审查 workflow"))

    def test_review_prompt_arms_after_a_context_clause(self):
        """The 2026-07-27 miss: `背景是…，审查4a的再次修复。` never armed the gate."""
        gate = _load_review_gate()
        self.assertTrue(gate.is_review_prompt("背景是桌面文件 x.md，审查4a的再次修复。不起全量测试。"))
        self.assertTrue(gate.is_review_prompt("先看 SESSION_LOG，复审 K4a"))
        # Meta-discussion about the review process itself must still stay disarmed.
        self.assertFalse(gate.is_review_prompt("你更新相关的审查规则，确保未来严格执行"))
        self.assertFalse(gate.is_review_prompt("为什么审查流程这么慢"))
        self.assertFalse(gate.is_review_prompt("我们系统里已经有作为审查者审查时需要遵守的规定"))


class WallClockBudgetTests(unittest.TestCase):
    """Rule 7 teeth: the gate MEASURES the review wall clock; it never trusts a self-report."""

    ENTRY = (
        "## 2026-07-27 — Claude Code 审查 PASS (x)\n\n"
        "- **Verdict/Action**: PASS\n"
        "- **Verify**: review-evidence:abc123 亲跑 1 OK\n"
    )

    def test_overrun_without_a_reason_is_blocked(self):
        gate = _load_review_gate()
        errors = gate.validate_session_log_text(
            self.ENTRY, "review-evidence:abc123", elapsed_seconds=3000, budget_seconds=1800)
        self.assertTrue(any("wall clock" in err for err in errors), errors)

    def test_overrun_with_a_recorded_reason_passes(self):
        gate = _load_review_gate()
        entry = self.ENTRY.replace("亲跑 1 OK", "亲跑 1 OK。超时原因:等一个 8 分钟的超集包")
        self.assertEqual(
            gate.validate_session_log_text(
                entry, "review-evidence:abc123", elapsed_seconds=3000, budget_seconds=1800),
            [],
        )

    def test_within_budget_needs_no_reason(self):
        gate = _load_review_gate()
        self.assertEqual(
            gate.validate_session_log_text(
                self.ENTRY, "review-evidence:abc123", elapsed_seconds=600, budget_seconds=1800),
            [],
        )

    def test_stop_hook_blocks_an_over_budget_review_without_a_reason(self):
        """End-to-end teeth: the Stop hook must refuse to close the response."""
        import json
        import tempfile
        from datetime import datetime, timezone
        gate = _load_review_gate()
        entry = (
            "# Session Log\n\n## 2026-07-27 — Claude Code 审查 PASS (t)\n\n"
            "- **Verdict/Action**: PASS\n- **Verify**: review-evidence:deadbeef 1 OK\n\n"
            "REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER\n"
        )
        for elapsed_min, expected in ((12, 0), (47, 2)):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root / "docs").mkdir()
                (root / "docs" / "SESSION_LOG.md").write_text(entry, encoding="utf-8")
                state_dir = root / ".claude" / "review_gate"
                state_dir.mkdir(parents=True)
                (state_dir / "active_review.json").write_text(json.dumps({
                    "evidence_token": "review-evidence:deadbeef",
                    "armed_at_epoch": datetime.now(timezone.utc).timestamp() - elapsed_min * 60,
                    "wall_clock_budget_seconds": 1800,
                }), encoding="utf-8")
                self.assertEqual(
                    gate.handle_stop_hook(root=root, state_dir=state_dir), expected,
                    f"elapsed={elapsed_min}min",
                )

    def test_gate_follows_the_worktree_the_review_runs_in(self):
        """A gate pinned to the main tree silently no-ops in a review worktree."""
        gate = _load_review_gate()
        self.assertEqual(gate.resolve_repo_root(str(ROOT)), ROOT)
        self.assertEqual(gate.resolve_repo_root("Z:/does-not-exist"), gate.ROOT)
        self.assertEqual(gate.resolve_repo_root(None), gate.ROOT)

    def test_snapshot_records_the_measured_start_and_budget(self):
        gate = _load_review_gate()
        snapshot = gate.collect_review_snapshot(prompt="审查当前 diff", root=ROOT)
        self.assertIsInstance(snapshot["armed_at_epoch"], float)
        self.assertEqual(snapshot["wall_clock_budget_seconds"], gate.WALL_CLOCK_BUDGET_SECONDS)


class PromptHookInjectionTests(unittest.TestCase):
    def test_review_prompt_injects_tiering_end_to_end(self):
        # Full path: git snapshot collection (git output carries non-ASCII commit text that a locale
        # gbk decode would choke on — `_run` must decode UTF-8/replace) THEN the tiering STEP-0.
        import json
        import tempfile
        gate = _load_review_gate()
        with tempfile.TemporaryDirectory() as td:
            out = gate.handle_prompt_hook(
                json.dumps({"prompt": "审查当前 diff"}), root=ROOT, state_dir=Path(td))
        self.assertIn("REVIEW EVIDENCE SNAPSHOT", out)   # snapshot injected (no encoding crash)
        self.assertIn("full_pack_ledger.py check", out)  # tiering STEP-0 injected


class StdinEncodingTests(unittest.TestCase):
    def test_stdin_read_decodes_utf8_regardless_of_locale(self):
        # A locale (gbk) stdin would mangle a Chinese 审查 prompt so the hook never fires; the reader
        # must decode UTF-8 from the raw byte buffer.
        import io
        import sys as _sys
        gate = _load_review_gate()

        class _FakeStdin:
            buffer = io.BytesIO('{"prompt":"审查当前 diff"}'.encode("utf-8"))

        orig = _sys.stdin
        _sys.stdin = _FakeStdin()
        try:
            raw = gate._read_stdin_utf8()
        finally:
            _sys.stdin = orig
        self.assertIn("审查当前", raw)


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

    def test_hook_uses_only_the_pinned_stock_python(self):
        self.assertIn(
            'PINNED_STOCK_PY="/c/Users/cnhea/AppData/Local/Programs/Python/Python313/python.exe"',
            self.hook,
        )
        self.assertIn('PY="$PINNED_STOCK_PY"', self.hook)
        self.assertNotIn("find_python", self.hook)
        self.assertNotIn("command -v", self.hook)
        self.assertNotIn("codex-runtimes", self.hook)


if __name__ == "__main__":
    unittest.main()
