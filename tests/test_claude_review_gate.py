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

    def test_agents_pins_review_anti_fabrication_gate(self):
        text = AGENTS.read_text(encoding="utf-8")
        for anchor in (
            "Claude review anti-fabrication gate",
            "review-evidence:",
            "simulated Bash / Read / Agent output",
            ".tools/claude_review_gate.py",
            "NOT_VERIFIED",
        ):
            self.assertIn(anchor, text)


if __name__ == "__main__":
    unittest.main()
