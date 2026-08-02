from __future__ import annotations

import importlib.util
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

    def _transcript(self, rows: list[dict]) -> str:
        return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"

    def _agent_launch_row(self, use_id: str, *, stamp: str, description: str = "adversarial probe") -> dict:
        return {
            "type": "assistant", "timestamp": stamp,
            "message": {"content": [{
                "type": "tool_use", "name": "Agent", "id": use_id,
                "input": {"description": description, "prompt": "attack it"},
            }]},
        }

    def _tool_result_row(self, use_id: str, *, stamp: str, body: str) -> dict:
        return {
            "type": "user", "timestamp": stamp,
            "message": {"content": [{
                "type": "tool_result", "tool_use_id": use_id, "content": body,
            }]},
        }

    def _notification_row(self, use_id: str, *, stamp: str) -> dict:
        return {
            "type": "user", "timestamp": stamp,
            "message": {"content": (
                f"<task-notification>\n<task-id>ad20</task-id>\n"
                f"<tool-use-id>{use_id}</tool-use-id>\n<status>completed</status>\n</task-notification>"
            )},
        }

    def test_pending_async_agents_matches_the_real_transcript_shape(self):
        gate = _load_gate()
        launch = self._agent_launch_row("toolu_LIVE", stamp="2026-08-02T14:10:00.000Z")
        launched = self._tool_result_row(
            "toolu_LIVE", stamp="2026-08-02T14:10:01.000Z",
            body="Async agent launched successfully. agentId: ad2047ce4fd21b026",
        )
        note = self._notification_row("toolu_LIVE", stamp="2026-08-02T14:30:00.000Z")

        outstanding = gate.pending_async_agents(self._transcript([launch, launched]))
        self.assertEqual(len(outstanding), 1)
        self.assertIn("adversarial probe", outstanding[0])
        # positive control: once the notification lands, nothing is outstanding
        self.assertEqual(gate.pending_async_agents(self._transcript([launch, launched, note])), [])
        # a launch whose result is still missing is outstanding too
        self.assertEqual(len(gate.pending_async_agents(self._transcript([launch]))), 1)
        # a synchronous agent returned its report inline and is never pending
        inline = self._tool_result_row(
            "toolu_LIVE", stamp="2026-08-02T14:10:01.000Z", body="CONFIRMED FINDINGS\n1. ...",
        )
        self.assertEqual(gate.pending_async_agents(self._transcript([launch, inline])), [])
        # an agent launched before this review armed is not this review's obligation
        self.assertEqual(
            gate.pending_async_agents(
                self._transcript([launch, launched]), armed_after_epoch=1798000000.0,
            ),
            [],
        )

    def test_outstanding_agent_blocks_the_closeout_until_waited_for_or_declared(self):
        gate = _load_gate()
        token = "review-evidence:abc123"
        log = (
            "# log\n\n"
            "## 2026-08-02 — Claude 审查 FAIL (slice)\n"
            "- **Verdict/Action**: FAIL\n"
            "- **Required**: R-X\n"
            f"- **Verify**: full pack OK; {token}\n"
            "- **Next**: Codex：修复\n\n"
            "REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER\n"
        )
        pending = ["adversarial probe (u_LIVE)"]

        self.assertEqual(gate.validate_session_log_text(log, token), [])
        blocked = gate.validate_session_log_text(log, token, pending_agents=pending)
        self.assertTrue(any("have not reported yet" in err for err in blocked), blocked)
        declared = log.replace(
            f"; {token}", f"; {token}; {gate.AGENT_PENDING_OVERRIDE_MARKER}配额挂了",
        )
        self.assertEqual(
            gate.validate_session_log_text(declared, token, pending_agents=pending), [],
        )

    def test_stop_hook_blocks_while_a_launched_agent_is_outstanding(self):
        gate = _load_gate()
        token = "review-evidence:abc123"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs" / "SESSION_LOG.md").write_text(
                "# log\n\n"
                "## 2026-08-02 — Claude 审查 FAIL (slice)\n"
                "- **Verdict/Action**: FAIL\n"
                "- **Required**: R-X\n"
                f"- **Verify**: full pack OK; {token}\n"
                "- **Next**: Codex：修复\n",
                encoding="utf-8",
            )
            state_dir = root / ".claude" / "review_gate"
            state_dir.mkdir(parents=True)
            state_path = state_dir / "active_review.json"
            state_path.write_text(json.dumps({"evidence_token": token}), encoding="utf-8")
            transcript = root / "transcript.jsonl"
            launch = self._agent_launch_row("toolu_LIVE", stamp="2026-08-02T14:10:00.000Z")
            launched = self._tool_result_row(
                "toolu_LIVE", stamp="2026-08-02T14:10:01.000Z",
                body="Async agent launched successfully. agentId: ad20",
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
                    launch, launched,
                    self._notification_row("toolu_LIVE", stamp="2026-08-02T14:30:00.000Z"),
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

    def test_agents_pins_review_anti_fabrication_gate(self):
        text = AGENTS.read_text(encoding="utf-8")
        for anchor in (
            "Claude review anti-fabrication gate",
            "review-evidence:",
            "simulated Bash / Read / Agent output",
            ".tools/claude_review_gate.py",
            "NOT_VERIFIED",
            "agent-aborted:",
        ):
            self.assertIn(anchor, text)
        gate = _load_gate()
        self.assertIn(gate.AGENT_PENDING_OVERRIDE_MARKER, text)


if __name__ == "__main__":
    unittest.main()
