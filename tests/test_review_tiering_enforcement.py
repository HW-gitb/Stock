"""Guards for the verification-tiering enforcement layers (AGENTS.md §Verification tiering).

Two mechanical layers must not silently regress:
1. The review-gate prompt hook (`_review_context`) injects the tiering STEP-0 (bounded focused /
   one-command full run / FAIL-early / independent-agent gate) on a review prompt.
2. The pre-commit verification-tiering reminder is scoped to the a-short production surface and is
   WARN-ONLY — it can never block a commit.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_verification_receipt import build_docs_only_merge  # noqa: E402


def _load_review_gate():
    spec = importlib.util.spec_from_file_location(
        "claude_review_gate", ROOT / ".tools" / "claude_review_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewContextTieringTests(unittest.TestCase):
    def test_review_context_carries_tiering_step0(self):
        text = _load_review_gate()._review_context()
        # ① focused work is bounded and process folklore is not evidence.
        self.assertIn("bounded_unittest", text)
        self.assertIn("默认最多 300 秒", text)
        self.assertIn("最高 1300 秒", text)
        self.assertIn("PID/CPU", text)
        # ② the full path is one bounded ledger command.
        self.assertIn("full_pack_ledger `run`", text)
        self.assertIn("860", text)
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

    def test_review_prompt_arms_on_a_worktree_or_diff_object(self):
        """`审查工作树017a的k4b修复` armed nothing, so that round had no token and no clock."""
        gate = _load_review_gate()
        for prompt in (
            "审查工作树017a的k4b修复",
            "复审017a",
            "审查该分支的改动",
            "先读 register，审查提交 7da0b220",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(gate.is_review_prompt(prompt))
        # `工作流` must not be dragged in by `工作树`: the meta list is checked first.
        for prompt in ("审查工作流要不要改", "讨论一下审查方式", "审查耗时为什么这么长"):
            with self.subTest(prompt=prompt):
                self.assertFalse(gate.is_review_prompt(prompt))


class RecordedRepoRootTests(unittest.TestCase):
    """Both hooks must judge the tree the snapshot came from, not the tree they resolve now."""

    ENTRY = (
        "# Session Log\n\n## 2026-07-27 审查 PASS (t)\n\n"
        "- **Verdict/Action**: PASS\n- **Verify**: review-evidence:deadbeef 1 OK\n\n"
        "REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER\n"
    )

    def _tree(self, base: Path, name: str, entry: str) -> Path:
        root = base / name
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "SESSION_LOG.md").write_text(entry, encoding="utf-8")
        return root

    def test_stop_hook_uses_the_recorded_root_not_its_own(self):
        import json
        import tempfile
        from datetime import datetime, timezone
        gate = _load_review_gate()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reviewed = self._tree(base, "reviewed", self.ENTRY)
            elsewhere = self._tree(base, "elsewhere", self.ENTRY.replace("review-evidence:deadbeef", "no token"))
            state_dir = base / "state"
            state_dir.mkdir()
            for recorded, expected in ((reviewed, 0), (elsewhere, 2)):
                with self.subTest(recorded=recorded.name):
                    (state_dir / "active_review.json").write_text(json.dumps({
                        "evidence_token": "review-evidence:deadbeef",
                        "armed_at_epoch": datetime.now(timezone.utc).timestamp(),
                        "wall_clock_budget_seconds": 1800,
                        "repo_root": str(recorded),
                    }), encoding="utf-8")
                    # `root=elsewhere` is deliberately the WRONG tree; the record must win.
                    self.assertEqual(
                        gate.handle_stop_hook(root=elsewhere, state_dir=state_dir), expected,
                    )

    def test_snapshot_records_the_reviewed_root_and_state_lives_in_one_place(self):
        import json
        import tempfile
        gate = _load_review_gate()
        snapshot = gate.collect_review_snapshot(prompt="审查当前 diff", root=ROOT)
        self.assertEqual(Path(snapshot["repo_root"]), ROOT.resolve())
        with tempfile.TemporaryDirectory() as tmp:
            out = gate.handle_prompt_hook(
                json.dumps({"prompt": "审查当前 diff", "cwd": str(ROOT)}), state_dir=Path(tmp))
            self.assertIn("REVIEW EVIDENCE SNAPSHOT", out)
            written = json.loads((Path(tmp) / "active_review.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(written["repo_root"]), ROOT.resolve())
        self.assertEqual(gate.STATE_DIR, gate.ROOT / ".claude" / "review_gate")


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
        self.assertIn("full_pack_ledger `run`", out)  # tiering STEP-0 injected


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
        # The marker is that branch's own header, so anything a later edit inserts beneath it is
        # claimed by "NEVER blocks" — which is how a blocking receipt gate once landed inside here.
        marker = "Verification-tiering reminder"
        self.assertEqual(self.hook.count(marker), 1)
        block = self.hook[self.hook.index(marker):]
        self.assertNotIn("exit 1", block)

    def test_the_receipt_gate_ahead_of_the_reminder_really_blocks(self):
        # Reverse control for the test above. On its own, "warn only" is satisfiable by moving the
        # marker below every gate, which would pass while proving nothing; the hard gate has to be
        # asserted hard somewhere, and it lives ahead of the marker.
        marker = "Verification-tiering reminder"
        ahead = self.hook[: self.hook.index(marker)]
        blocked = "pre-commit BLOCKED: no current bounded focused acceptance receipt"
        self.assertIn(blocked, ahead)
        self.assertIn("exit 1", ahead[ahead.index(blocked):])

    def _receipt_gate_condition(self):
        """Lift the gate's real decision lines out of the hook, so this runs what ships."""
        lines = self.hook.splitlines()
        picked = {}
        for line in lines:
            for key, prefix in (("merging", "merging="), ("changed", "code_changed="),
                                ("branch", 'if [ -n "$code_changed" ]')):
                if line.strip().startswith(prefix) and key not in picked:
                    picked[key] = line.strip()
        self.assertEqual(sorted(picked), ["branch", "changed", "merging"])
        self.assertIn("MERGE_HEAD", picked["merging"])
        return "; ".join([picked["merging"], picked["changed"], picked["branch"]]) + \
            " echo FIRED; else echo SKIPPED; fi"

    def _decide(self, repo, snippet):
        """Run the hook's own condition under the shell git runs hooks with.

        Taking `sh` off PATH reads simpler and is wrong here: the mandated
        launcher resets PATH to a fixed allowlist that carries git but not the
        directory holding `sh.exe`, so the test would skip in exactly the
        environment the project requires -- and a control that skips is a
        control that proves nothing.  A `!` alias runs under git's own shell,
        which is the shell that will execute this hook for real, and it needs
        no hard-coded install path to find.
        """
        done = subprocess.run(
            ["git", "-C", str(repo), "-c", "alias.gateprobe=!" + snippet, "gateprobe"],
            capture_output=True, text=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        decision = done.stdout.strip().splitlines()[-1]
        # Fail loudly rather than skip if the shell never reached the branch.
        self.assertIn(decision, {"FIRED", "SKIPPED"}, done.stdout)
        return decision

    def test_a_documents_only_merge_still_demands_a_receipt(self):
        # The reviewer's case: a merge carrying the other side's code in, with a staged diff that
        # holds no code at all. The old condition looked only at the staged diff and walked past.
        script = self._receipt_gate_condition()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            build_docs_only_merge(repo)
            staged = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--name-only"],
                                    capture_output=True, text=True).stdout.split()
            self.assertTrue(staged and all(name.endswith(".md") for name in staged), staged)
            self.assertEqual(self._decide(repo, script), "FIRED")
            # Reverse leg: the same documents-only change with no merge under way must NOT be
            # gated, or this would have become a blanket widening rather than a merge rule.
            subprocess.run(["git", "-C", str(repo), "merge", "--abort"], check=True)
            (repo / "docs" / "note.md").write_text("plain docs edit\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            self.assertEqual(self._decide(repo, script), "SKIPPED")

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
