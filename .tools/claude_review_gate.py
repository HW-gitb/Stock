from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".claude" / "review_gate"
ACTIVE_REVIEW = "active_review.json"
SESSION_LOG = ROOT / "docs" / "SESSION_LOG.md"
ADOPTION_MARKER = "REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER"


def is_review_prompt(prompt: str) -> bool:
    text = " ".join((prompt or "").strip().split())
    lowered = text.lower()
    if not text:
        return False
    if "/stock-review" in lowered:
        return True
    # Discussion about the review system itself must not arm the Stop hook.
    discussion_markers = (
        "审查 workflow",
        "审查workflow",
        "修改 claude code 的审查",
        "修改claude code的审查",
        "讨论审查",
    )
    if any(marker in lowered for marker in discussion_markers):
        return False
    command_markers = (
        "审查当前",
        "审查这次",
        "重新审查",
        "复审",
        "re-review",
    )
    if any(marker in lowered for marker in command_markers):
        return True
    command_phrase_markers = (
        "请审查",
        "请复审",
        "麻烦审查",
        "麻烦复审",
        "帮我审查",
        "帮我复审",
        "有的话审查",
        "顺便审查",
        "顺便复审",
        "可以审查",
        "可以复审",
        "可否审查",
        "可否复审",
        "继续审查",
        "继续复审",
        "再审查",
        "再复审",
    )
    if any(marker in text for marker in command_phrase_markers):
        return True
    return bool(re.match(r"^[`\"'“”\s]*(审查|review)\b", text, re.IGNORECASE))


def _clip(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[clipped {len(text) - limit} chars]"


def _run(args: list[str], *, root: Path) -> dict:
    try:
        result = subprocess.run(
            args,
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        output = result.stdout
        rc = result.returncode
    except Exception as exc:  # pragma: no cover - defensive for hook runtime only
        output = f"{type(exc).__name__}: {exc}"
        rc = 127
    return {
        "cmd": " ".join(args),
        "returncode": rc,
        "output": _clip(output.strip() or "<no output>"),
    }


def collect_review_snapshot(*, prompt: str, root: Path = ROOT) -> dict:
    commands = [
        ["git", "-c", "core.excludesFile=", "status", "--short", "--untracked-files=all"],
        ["git", "-c", "core.excludesFile=", "diff", "--name-only", "HEAD"],
        ["git", "-c", "core.excludesFile=", "diff", "--stat", "HEAD"],
        ["git", "-c", "core.excludesFile=", "diff", "--numstat", "HEAD"],
        ["git", "-c", "core.excludesFile=", "log", "-5", "--oneline"],
    ]
    results = [_run(cmd, root=root) for cmd in commands]
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest_input = json.dumps(
        {"prompt": prompt, "results": results, "now": now},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(digest_input).hexdigest()[:12]
    return {
        "review_id": f"{now}-{digest}",
        "evidence_token": f"review-evidence:{digest}",
        "created_at_utc": now,
        "prompt_sha256": hashlib.sha256((prompt or "").encode("utf-8")).hexdigest(),
        "commands": results,
    }


def _format_snapshot_context(snapshot: dict) -> str:
    lines = [
        "[stock-review-gate] REVIEW EVIDENCE SNAPSHOT",
        f"review_id: {snapshot['review_id']}",
        f"required SESSION_LOG Verify token: {snapshot['evidence_token']}",
        "",
        "Anti-fabrication protocol:",
        "- A command result is valid only if it appears in this injected snapshot, a real tool result, or a user-run ! command output.",
        "- Do not write simulated Bash / Read / Agent output, fake agent IDs, fake diffs, fake line numbers, or fake test results.",
        "- If evidence is missing or tool output provenance is uncertain, write NOT_VERIFIED and do not use it as PASS evidence.",
        "- The review-cycle SESSION_LOG entry's Verify line must include the exact review-evidence token above.",
        "- Do not create REVIEW_PACKET.md; material findings still live only in docs/system_risk_register.md, with a minimal SESSION_LOG entry.",
        "",
        "Ground-truth command outputs captured before the model response:",
    ]
    for item in snapshot["commands"]:
        lines.append("")
        lines.append(f"$ {item['cmd']}  # exit {item['returncode']}")
        lines.append("```text")
        lines.append(item["output"])
        lines.append("```")
    return "\n".join(lines)


def _fix_context() -> str:
    return (
        "[codex-fix-gate 自动触发] 本轮输入含「修复」。动任何代码前，先按 "
        ".claude/skills/codex-fix-gate/SKILL.md 走完 6 步硬门，尤其："
        "§1 从该 finding 在 docs/system_risk_register.md 的 Required repair + Closure tests 全文"
        "枚举出整个缺陷类成 checklist（别只修 Codex 探针演示的那一条腿）；"
        "§3 复现 reviewer 的确切探针、证明 fail-closed/零残留；"
        "§4 SESSION_LOG 评审循环条目每 bullet ≤450 字、一次过 doc-governance guard。"
        "DONE gate 未满足前不得宣称 fixed pending Codex。"
    )


def _review_context() -> str:
    return (
        "[审查-standard 自动触发] 本轮进入审查门。侦察可以高效，但 PASS 证据必须来自真实工具结果、"
        "用户 ! 输出或上方 REVIEW EVIDENCE SNAPSHOT。若需要命令而没有真实输出，写 NOT_VERIFIED。"
        "仍按 AGENTS 的分级：高危子集 PASS 前必须独立对抗 agent + reviewer 自己整读和探针；"
        "轻量 slice 仍至少整读改动 + 1 个反向探针。"
    )


def handle_prompt_hook(raw: str, *, root: Path = ROOT, state_dir: Path = STATE_DIR) -> str:
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return ""
    prompt = data.get("prompt", "") or ""
    parts: list[str] = []
    if "修复" in prompt:
        parts.append(_fix_context())
    if is_review_prompt(prompt):
        snapshot = collect_review_snapshot(prompt=prompt, root=root)
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / ACTIVE_REVIEW).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        parts.append(_format_snapshot_context(snapshot))
        parts.append(_review_context())
    if not parts:
        return ""
    out = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n\n".join(parts),
        }
    }
    return json.dumps(out, ensure_ascii=False)


def _top_review_entry(text: str) -> str | None:
    zone = text.split(ADOPTION_MARKER, 1)[0] if ADOPTION_MARKER in text else text
    matches = list(re.finditer(r"(?m)^## \d{4}-\d{2}-\d{2}\b.*$", zone))
    if not matches:
        return None
    start = matches[0].start()
    end = matches[1].start() if len(matches) > 1 else len(zone)
    return zone[start:end]


def validate_session_log_text(text: str, evidence_token: str) -> list[str]:
    errors: list[str] = []
    entry = _top_review_entry(text)
    if not entry:
        return ["no dated SESSION_LOG entry found above review marker"]
    header = entry.splitlines()[0]
    if "审查" not in header and "review" not in header.lower():
        errors.append("top SESSION_LOG entry is not a review entry")
    verify_lines = [
        line for line in entry.splitlines()
        if re.match(r"^\s*-\s+\*\*Verify\*\*\s*[:：]", line)
    ]
    if not verify_lines:
        errors.append("top review entry has no Verify line")
    elif not any(evidence_token in line for line in verify_lines):
        errors.append("top review entry Verify line is missing the review evidence token")
    return errors


def handle_stop_hook(*, root: Path = ROOT, state_dir: Path = STATE_DIR) -> int:
    state_path = state_dir / ACTIVE_REVIEW
    if not state_path.exists():
        return 0
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        print("stock-review-gate: active_review.json is unreadable; re-arm or remove the corrupt state file", file=sys.stderr)
        return 2
    if state.get("completed_at_utc"):
        try:
            state_path.unlink()
        except OSError:
            pass
        return 0
    token = state.get("evidence_token")
    if not token:
        print("stock-review-gate: active_review.json is missing evidence_token; re-arm the review gate", file=sys.stderr)
        return 2
    log_path = root / "docs" / "SESSION_LOG.md"
    if not log_path.exists():
        print("stock-review-gate: docs/SESSION_LOG.md not found", file=sys.stderr)
        return 2
    errors = validate_session_log_text(log_path.read_text(encoding="utf-8"), token)
    if errors:
        print("stock-review-gate blocked final response:", file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        print(f"- required token: {token}", file=sys.stderr)
        print("Put the token in the review-cycle SESSION_LOG Verify line, or mark NOT_VERIFIED if evidence is unavailable.", file=sys.stderr)
        return 2
    state_path.unlink()
    return 0


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "prompt-hook"
    if mode == "prompt-hook":
        out = handle_prompt_hook(sys.stdin.read())
        if out:
            sys.stdout.write(out)
        return 0
    if mode == "stop-hook":
        sys.stdin.read()
        return handle_stop_hook()
    if mode == "collect-context":
        prompt = " ".join(argv[2:])
        sys.stdout.write(_format_snapshot_context(collect_review_snapshot(prompt=prompt)))
        return 0
    if mode == "validate-session-log":
        if len(argv) != 3:
            print("usage: claude_review_gate.py validate-session-log review-evidence:<id>", file=sys.stderr)
            return 2
        errors = validate_session_log_text(SESSION_LOG.read_text(encoding="utf-8"), argv[2])
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 2
        return 0
    print(f"unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
