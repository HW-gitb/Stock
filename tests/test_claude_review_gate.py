from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = ROOT / ".tools" / "claude_review_gate.py"
AGENTS = ROOT / "AGENTS.md"


def _load_gate():
    spec = importlib.util.spec_from_file_location("claude_review_gate", GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ClaudeReviewGateTests(unittest.TestCase):
    def _transcript(self, rows: list[dict]) -> str:
        return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"

    def _agent_launch_row(
        self, use_id: str, *, stamp: str | None, description: str = "adversarial probe",
    ) -> dict:
        row = {
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use",
                "name": "Agent",
                "id": use_id,
                "input": {"description": description, "prompt": "attack it"},
            }]},
        }
        if stamp is not None:
            row["timestamp"] = stamp
        return row

    def _tool_result_row(
        self, use_id: str, *, stamp: str, body: str, async_result: bool = False,
    ) -> dict:
        row = {
            "type": "user",
            "timestamp": stamp,
            "message": {"content": [{
                "type": "tool_result",
                "tool_use_id": use_id,
                "content": body,
            }]},
        }
        if async_result:
            row["toolUseResult"] = {
                "isAsync": True,
                "status": "async_launched",
                "agentId": "agent-real-shape",
            }
        return row

    def _notification_row(self, use_id: str, *, stamp: str, shape: str) -> dict:
        notification = (
            "<task-notification>\n"
            "<task-id>task-real-shape</task-id>\n"
            f"<tool-use-id>{use_id}</tool-use-id>\n"
            "<status>completed</status>\n"
            "</task-notification>"
        )
        if shape == "queue-operation":
            return {"type": shape, "timestamp": stamp, "content": notification}
        if shape == "attachment":
            return {
                "type": shape,
                "timestamp": stamp,
                "attachment": {"content": notification},
            }
        raise AssertionError(f"unknown notification shape: {shape}")

    def test_pending_async_agents_reads_real_notification_row_shapes(self):
        gate = _load_gate()
        use_id = "toolu_REAL_NOTIFICATION"
        launch = self._agent_launch_row(use_id, stamp="2026-08-02T14:10:00.000Z")
        launched = self._tool_result_row(
            use_id,
            stamp="2026-08-02T14:10:01.000Z",
            body="launch wording changed; structured result is authoritative",
            async_result=True,
        )

        outstanding = gate.pending_async_agents(self._transcript([launch, launched]))
        self.assertEqual(len(outstanding), 1)
        self.assertIn("adversarial probe", outstanding[0])

        for shape in ("queue-operation", "attachment"):
            notification = self._notification_row(
                use_id, stamp="2026-08-02T14:30:00.000Z", shape=shape,
            )
            self.assertEqual(
                gate.pending_async_agents(self._transcript([launch, launched, notification])),
                [],
                shape,
            )

        # Removing the notification must turn the same fixture red again.
        self.assertEqual(
            len(gate.pending_async_agents(self._transcript([launch, launched]))), 1,
        )

    def test_pending_async_agents_keeps_reverse_controls(self):
        gate = _load_gate()
        use_id = "toolu_REVERSE"
        launch = self._agent_launch_row(use_id, stamp="2026-08-02T14:10:00.000Z")

        # No tool result at all is still outstanding.
        self.assertEqual(len(gate.pending_async_agents(self._transcript([launch]))), 1)

        # A synchronous inline report does not need a task notification.
        inline = self._tool_result_row(
            use_id, stamp="2026-08-02T14:10:01.000Z", body="synchronous report",
        )
        self.assertEqual(gate.pending_async_agents(self._transcript([launch, inline])), [])

        # An agent launched before arming is not this review's obligation.
        armed_after = gate._epoch("2026-08-02T14:20:00.000Z")
        self.assertIsNotNone(armed_after)
        self.assertEqual(
            gate.pending_async_agents(self._transcript([launch]), armed_after_epoch=armed_after),
            [],
        )

        # Missing launch timestamps do not exempt an otherwise outstanding agent.
        no_stamp = self._agent_launch_row("toolu_NO_TIMESTAMP", stamp=None)
        self.assertEqual(len(gate.pending_async_agents(self._transcript([no_stamp]))), 1)

    def test_outstanding_agent_blocks_closeout_until_reported_or_declared(self):
        gate = _load_gate()
        token = "review-evidence:abc123"
        log = (
            "# log\n\n"
            "## 2026-08-02 — Claude review FAIL (slice)\n"
            "- **Verdict/Action**: FAIL\n"
            "- **Required**: R-X\n"
            f"- **Verify**: full pack OK; {token}\n"
            "- **Next**: Codex: fix\n\n"
            "REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER\n"
        )
        pending = ["adversarial probe (n_NOTIFICATION)"]

        self.assertEqual(gate.validate_session_log_text(log, token), [])
        blocked = gate.validate_session_log_text(log, token, pending_agents=pending)
        self.assertTrue(any("have not reported yet" in err for err in blocked), blocked)
        declared = log.replace(
            f"; {token}",
            f"; {token}; {gate.AGENT_PENDING_OVERRIDE_MARKER}agent process died",
        )
        self.assertEqual(
            gate.validate_session_log_text(declared, token, pending_agents=pending), [],
        )

    def test_stop_hook_blocks_then_clears_after_real_notification(self):
        gate = _load_gate()
        token = "review-evidence:abc123"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs" / "SESSION_LOG.md").write_text(
                "# log\n\n"
                "## 2026-08-02 — Claude review FAIL (slice)\n"
                "- **Verdict/Action**: FAIL\n"
                "- **Required**: R-X\n"
                f"- **Verify**: full pack OK; {token}\n"
                "- **Next**: Codex: fix\n",
                encoding="utf-8",
            )
            state_dir = root / ".claude" / "review_gate"
            state_dir.mkdir(parents=True)
            state_path = state_dir / "active_review.json"
            state_path.write_text(json.dumps({"evidence_token": token}), encoding="utf-8")
            transcript = root / "transcript.jsonl"
            launch = self._agent_launch_row(
                "toolu_STOP", stamp="2026-08-02T14:10:00.000Z",
            )
            launched = self._tool_result_row(
                "toolu_STOP",
                stamp="2026-08-02T14:10:01.000Z",
                body="structured async launch",
                async_result=True,
            )
            transcript.write_text(self._transcript([launch, launched]), encoding="utf-8")

            self.assertEqual(
                gate.handle_stop_hook(
                    root=root, state_dir=state_dir, transcript_path=str(transcript),
                ),
                2,
            )
            self.assertTrue(state_path.exists())

            transcript.write_text(
                self._transcript([
                    launch,
                    launched,
                    self._notification_row(
                        "toolu_STOP", stamp="2026-08-02T14:30:00.000Z",
                        shape="attachment",
                    ),
                ]),
                encoding="utf-8",
            )
            self.assertEqual(
                gate.handle_stop_hook(
                    root=root, state_dir=state_dir, transcript_path=str(transcript),
                ),
                0,
            )
            self.assertFalse(state_path.exists())

    def test_review_intent_detector_is_command_scoped(self):
        gate = _load_gate()
        self.assertTrue(gate.is_review_prompt("审查当前 diff"))
        self.assertTrue(gate.is_review_prompt("请复审这次修改"))
        self.assertTrue(gate.is_review_prompt("有的话审查"))
        self.assertTrue(gate.is_review_prompt("/stock-review standard"))
        self.assertFalse(gate.is_review_prompt("帮我修改 claude code 的审查 workflow"))
        self.assertFalse(gate.is_review_prompt("讨论审查制度，不进入实际 review"))

    def test_prompt_hook_context_injects_real_snapshot_and_token(self):
        gate = _load_gate()
        with tempfile.TemporaryDirectory() as td:
            result = gate.handle_prompt_hook(
                json.dumps({"prompt": "审查当前 diff"}),
                root=ROOT,
                state_dir=Path(td),
            )
            payload = json.loads(result)

            ctx = payload["hookSpecificOutput"]["additionalContext"]
            state = json.loads((Path(td) / "active_review.json").read_text(encoding="utf-8"))

        self.assertIn("REVIEW EVIDENCE SNAPSHOT", ctx)
        self.assertIn("git -c core.excludesFile= status --short --untracked-files=all", ctx)
        self.assertIn("git -c core.excludesFile= diff --name-only HEAD", ctx)
        self.assertIn("Anti-fabrication protocol", ctx)
        self.assertIn(state["evidence_token"], ctx)
        self.assertTrue(state["evidence_token"].startswith("review-evidence:"))

    def test_stop_validation_requires_token_on_verify_line(self):
        gate = _load_gate()
        token = "review-evidence:abc123"
        compliant_log = (
            "# log\n\n---\n\n"
            "## 2026-07-04 — Claude 审查 PASS (slice)\n"
            "- **Verdict/Action**: PASS\n"
            "- **Required**: 无\n"
            f"- **Verify**: full pack OK; {token}\n"
            "- **Next**: 无\n\n"
            "REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER\n"
        )
        missing = compliant_log.replace(f"; {token}", "")
        wrong_line = compliant_log.replace(
            f"- **Verify**: full pack OK; {token}",
            "- **Verify**: full pack OK\n- **Required**: 无; review-evidence:abc123",
        )

        self.assertEqual(gate.validate_session_log_text(compliant_log, token), [])
        self.assertIn("Verify", "\n".join(gate.validate_session_log_text(missing, token)))
        self.assertIn("Verify", "\n".join(gate.validate_session_log_text(wrong_line, token)))

    def test_stop_hook_blocks_corrupt_active_review_state(self):
        gate = _load_gate()
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir()
            state_path = state_dir / "active_review.json"
            state_path.write_text("{bad json", encoding="utf-8")

            self.assertEqual(gate.handle_stop_hook(root=Path(td), state_dir=state_dir), 2)
            self.assertTrue(state_path.exists())

    def test_stop_hook_clears_active_review_state_after_success(self):
        gate = _load_gate()
        token = "review-evidence:abc123"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            docs = root / "docs"
            docs.mkdir()
            (docs / "SESSION_LOG.md").write_text(
                "# log\n\n---\n\n"
                "## 2026-07-04 - Claude review PASS (slice)\n"
                "- **Verdict/Action**: PASS\n"
                "- **Required**: none\n"
                f"- **Verify**: full pack OK; {token}\n"
                "- **Next**: none\n",
                encoding="utf-8",
            )
            state_dir = root / ".claude" / "review_gate"
            state_dir.mkdir(parents=True)
            state_path = state_dir / "active_review.json"
            state_path.write_text(
                json.dumps({"evidence_token": token}, ensure_ascii=False),
                encoding="utf-8",
            )

            self.assertEqual(gate.handle_stop_hook(root=root, state_dir=state_dir), 0)
            self.assertFalse(state_path.exists())

    def test_stop_hook_cli_forwards_transcript_path(self):
        gate = _load_gate()
        seen = {}

        def fake_handle(*, root=None, state_dir=None, transcript_path=None):
            seen["transcript_path"] = transcript_path
            return 0

        original_handle, original_stdin = gate.handle_stop_hook, gate._read_stdin_utf8
        gate.handle_stop_hook = fake_handle
        gate._read_stdin_utf8 = lambda: json.dumps({
            "cwd": str(ROOT),
            "transcript_path": "C:/tmp/session.jsonl",
            "hook_event_name": "Stop",
        })
        try:
            self.assertEqual(gate.main(["gate", "stop-hook"]), 0)
            self.assertEqual(seen["transcript_path"], "C:/tmp/session.jsonl")
            gate._read_stdin_utf8 = lambda: json.dumps({"cwd": str(ROOT)})
            self.assertEqual(gate.main(["gate", "stop-hook"]), 0)
            self.assertIsNone(seen["transcript_path"])
        finally:
            gate.handle_stop_hook, gate._read_stdin_utf8 = original_handle, original_stdin

    def test_missing_transcript_is_announced_not_silently_skipped(self):
        gate = _load_gate()
        token = "review-evidence:abc123"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs" / "SESSION_LOG.md").write_text(
                "# log\n\n## 2026-08-02 — Claude review PASS (slice)\n"
                "- **Verdict/Action**: PASS\n- **Required**: none\n"
                f"- **Verify**: ok; {token}\n- **Next**: none\n",
                encoding="utf-8",
            )
            state_dir = root / "state"
            state_dir.mkdir()
            (state_dir / "active_review.json").write_text(
                json.dumps({"evidence_token": token}), encoding="utf-8",
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = gate.handle_stop_hook(
                    root=root, state_dir=state_dir, transcript_path=None,
                )
        self.assertEqual(code, 0)
        self.assertIn("outstanding-agent check did not run", stderr.getvalue())

    def test_agents_pins_review_anti_fabrication_gate(self):
        text = AGENTS.read_text(encoding="utf-8")
        for anchor in (
            "Claude review anti-fabrication gate",
            "review-evidence:",
            "simulated Bash / Read / Agent output",
            ".tools/claude_review_gate.py",
            "NOT_VERIFIED",
            "Evidence-completeness leg",
            "agent-aborted:",
        ):
            self.assertIn(anchor, text)
        gate = _load_gate()
        self.assertIn(gate.AGENT_PENDING_OVERRIDE_MARKER, text)


if __name__ == "__main__":
    unittest.main()
