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
# AGENTS §Verification tiering rule 7 (user-directed 2026-07-27): a knife review targets
# 10-15 minutes; past this hard cap the Stop hook blocks until the Verify line states why.
WALL_CLOCK_BUDGET_SECONDS = 1800
OVERRUN_REASON_MARKER = "超时原因"


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
    if re.match(r"^[`\"'“”\s]*(审查|review)\b", text, re.IGNORECASE):
        return True
    # `审查4a的再次修复` / `复审 K4a` arrive AFTER a context clause, so the
    # start-anchored match above missed them and the gate never armed (found
    # 2026-07-27).  Arm when the verb carries a concrete object; a meta word
    # (`审查规则` / `审查流程` / `审查者`) stays a discussion and must not arm.
    return _carries_review_object(text)


REVIEW_META_TAILS = (
    "规则", "规定", "流程", "方式", "方法", "标准", "机制", "时间", "耗时", "系统", "工作流",
    "workflow", "者", "员", "习惯", "经验", "教训", "方案", "模板", "清单", "指南", "要求",
    "原则", "轮数", "窗口", "质量", "成本", "策略", "文档", "的", "得", "了", "过", "很", "太",
)
# Object shapes an actual review command uses.  `审查工作树017a的k4b修复` armed nothing
# because `工作树` was missing here, so that round had no token and no wall clock at all.
REVIEW_OBJECT_HEADS = (
    "刀", "当前", "这", "本", "上", "该", "下", "新", "第", "所有", "一下", "完",
    "工作树", "树", "分支", "提交", "改动", "变更", "补丁", "切片",
)


def _carries_review_object(text: str) -> bool:
    for match in re.finditer(r"(审查|复审)", text):
        tail = text[match.end():match.end() + 8].lstrip(" :：`\"'“”")
        if not tail:
            continue
        if any(tail.startswith(meta) for meta in REVIEW_META_TAILS):
            continue
        if re.match(r"^[0-9A-Za-z]", tail):
            return True
        if any(tail.startswith(head) for head in REVIEW_OBJECT_HEADS):
            return True
    return False


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
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        output = result.stdout or ""
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
        # AGENTS §Verification tiering rule 7: the wall clock is a hard metric, so the
        # gate MEASURES it instead of trusting a self-reported number.
        "armed_at_epoch": datetime.now(timezone.utc).timestamp(),
        "wall_clock_budget_seconds": WALL_CLOCK_BUDGET_SECONDS,
        # The two hooks must judge the SAME repository.  They used to resolve it
        # independently, so a cwd change between arming and closing pointed the
        # SESSION_LOG check at a different tree than the snapshot came from.
        "repo_root": str(Path(root).resolve()),
        "prompt_sha256": hashlib.sha256((prompt or "").encode("utf-8")).hexdigest(),
        "commands": results,
    }


def _format_snapshot_context(snapshot: dict) -> str:
    lines = [
        "[stock-review-gate] REVIEW EVIDENCE SNAPSHOT",
        f"review_id: {snapshot['review_id']}",
        f"required SESSION_LOG Verify token: {snapshot['evidence_token']}",
        f"wall-clock budget (AGENTS rule 7): 目标 10-15 分钟，硬上限 "
        f"{snapshot.get('wall_clock_budget_seconds', WALL_CLOCK_BUDGET_SECONDS) // 60} 分钟 —— "
        f"超时后 Stop hook 会拦住最终回复，直到 Verify 行写出 `{OVERRUN_REASON_MARKER}:<一句话>`。"
        "计时从本快照开始，由 hook 实测，不采信自报。",
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
        "[审查-standard 自动触发] 本轮进入审查门。**先执行 AGENTS §Verification tiering rule 7（墙钟硬指标，"
        "目标 10-15 分钟；超 30 分钟=流程缺陷，须在 Verify 写原因）**："
        "(a) 第一条命令 `git status/diff` 出改动清单 → **第二条命令**就把本轮唯一最慢的那个**超集**测试命令"
        "交给 bounded runner 后 `run_in_background`，再去整读函数体/写探针——禁止读完、探针跑完才起;"
        "(b) **只跑超集、禁跑其子集**:单测→测试类→整模块只跑最大的那个，超集绿=其内全绿，"
        "不得为「再确认」回头补跑子集或重跑同一个包;"
        "(c) 同一时刻只跑一个重包(并发重包会互拖、甚至无 traceback 崩溃 exit 127)，其余结论用探针/静态证据;"
        "(d) 测试红了先看 gitignored 残留目录及 mtime 再怀疑代码，禁止用重复慢跑去二分残留导致的红;"
        "(e) 一件事只确认一次，重跑同一命令不产新信息即浪费。"
        "**不可删的三样**:整读被消费的函数体 + 自写反向/植入探针 + 放松类改动的强制腿反向控制。"
        " PASS 证据只能来自真实工具结果、用户 ! 输出或上方 REVIEW EVIDENCE SNAPSHOT，拿不到就写 NOT_VERIFIED。"
        " 分级门(rule 3/4/5/8)："
        "①focused 只用 bounded_unittest 单入口，默认最多 300 秒；已实测慢 focused 包可显式申请，最高 1300 秒；"
        "PID/CPU/父子进程切换不等于测试进度或 PASS;"
        "②按 rule 3 触发的全量只用 full_pack_ledger `run` 单命令，最多 800 秒，自动查缓存并成功记账;"
        "③FAIL 一旦被真实探针坐实就先出结论、不必等全量包;"
        "④独立对抗 agent 只在真钱/选股/安全/PIT-进选股/大而绕 diff 才起、且只起一个，"
        "小低危改动别起 agent 也别跑全量(rule 8，过度审查=缺陷);"
        "⑤测试范围跟「改动的函数/符号」走、不跟「改动的文件」走:先说清本刀改了哪几个函数,"
        "已选/已跑的 targeted 测试若已直接调用该改动函数即为覆盖、别再加跑该文件的整测试模块"
        "(其余用例与本刀无关=全模块税);也别在第一个测试包结果回来前投机并起第二个全模块包。"
        "⑥TIMEOUT/无退出码/无 `Ran N tests` 一律 UNKNOWN，终止本命令拥有的进程树后缩窄或诊断一次，不得重复等待。"
    )


def resolve_repo_root(cwd: str | None) -> Path:
    """Reviews run in git worktrees; a gate pinned to the main tree silently no-ops there.

    Resolve the repository the reviewer is actually working in, so the snapshot and the
    SESSION_LOG the Stop hook validates come from the same tree (found 2026-07-27).
    """
    if not cwd:
        return ROOT
    candidate = Path(cwd)
    if not candidate.is_dir():
        return ROOT
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=str(candidate), text=True,
            encoding="utf-8", errors="replace", stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=10,
        )
    except Exception:
        return ROOT
    top = (result.stdout or "").strip()
    if result.returncode != 0 or not top:
        return ROOT
    resolved = Path(top)
    return resolved if (resolved / "docs" / "SESSION_LOG.md").exists() else ROOT


def handle_prompt_hook(raw: str, *, root: Path | None = None, state_dir: Path | None = None) -> str:
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return ""
    if root is None:
        root = resolve_repo_root(data.get("cwd"))
    if state_dir is None:
        # ONE canonical state location next to the canonical script.  Deriving it from the
        # reviewed tree meant the Stop hook could resolve a different tree, fail to find the
        # state file at all, and silently enforce nothing.
        state_dir = STATE_DIR
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


def validate_session_log_text(
    text: str, evidence_token: str, *, elapsed_seconds: float | None = None,
    budget_seconds: int = WALL_CLOCK_BUDGET_SECONDS,
) -> list[str]:
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
    # Rule 7 teeth: a review that blew the wall-clock budget may still close, but it must
    # say why in the same Verify line, so the overrun is recorded instead of forgotten.
    if (
        elapsed_seconds is not None
        and elapsed_seconds > budget_seconds
        and not any(OVERRUN_REASON_MARKER in line for line in verify_lines)
    ):
        errors.append(
            f"review wall clock {int(elapsed_seconds // 60)} min exceeded the rule-7 budget "
            f"({budget_seconds // 60} min) and the Verify line has no `{OVERRUN_REASON_MARKER}:` note"
        )
    return errors


def handle_stop_hook(*, root: Path | None = None, state_dir: Path | None = None) -> int:
    if root is None:
        root = ROOT
    if state_dir is None:
        state_dir = STATE_DIR
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
    # Judge the tree the snapshot was taken in, not whatever tree this hook happens
    # to resolve now.  Only an unreadable/missing record falls back to `root`.
    recorded_root = state.get("repo_root")
    if isinstance(recorded_root, str) and recorded_root:
        candidate = Path(recorded_root)
        if (candidate / "docs" / "SESSION_LOG.md").exists():
            root = candidate
        else:
            print(
                f"stock-review-gate: recorded repo_root is no longer readable ({recorded_root}); "
                f"falling back to {root}",
                file=sys.stderr,
            )
    log_path = root / "docs" / "SESSION_LOG.md"
    if not log_path.exists():
        print("stock-review-gate: docs/SESSION_LOG.md not found", file=sys.stderr)
        return 2
    armed_at = state.get("armed_at_epoch")
    elapsed = None
    if isinstance(armed_at, (int, float)):
        elapsed = max(0.0, datetime.now(timezone.utc).timestamp() - float(armed_at))
    errors = validate_session_log_text(
        log_path.read_text(encoding="utf-8"), token, elapsed_seconds=elapsed,
        budget_seconds=int(state.get("wall_clock_budget_seconds", WALL_CLOCK_BUDGET_SECONDS)),
    )
    if errors:
        print("stock-review-gate blocked final response:", file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        print(f"- required token: {token}", file=sys.stderr)
        print("Put the token in the review-cycle SESSION_LOG Verify line, or mark NOT_VERIFIED if evidence is unavailable.", file=sys.stderr)
        print(
            f"If the run overran the rule-7 budget, add `{OVERRUN_REASON_MARKER}:<一句话>` to that same Verify line; "
            "a non-review discussion turn is disarmed with `claude_review_gate.py disarm`.",
            file=sys.stderr,
        )
        return 2
    state_path.unlink()
    return 0


def _read_stdin_utf8() -> str:
    # Claude Code pipes UTF-8 JSON; a locale (gbk) stdin would mangle a Chinese 审查 prompt so the
    # hook silently never fires. Read raw bytes and decode UTF-8 to stay locale-independent.
    data = sys.stdin.buffer.read()
    return data.decode("utf-8", errors="replace") if data else ""


def _write_stdout_utf8(text: str) -> None:
    # The injected context carries Chinese; write UTF-8 bytes so a gbk stdout cannot corrupt/crash it.
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "prompt-hook"
    if mode == "prompt-hook":
        out = handle_prompt_hook(_read_stdin_utf8())
        if out:
            _write_stdout_utf8(out)
        return 0
    if mode == "stop-hook":
        raw = _read_stdin_utf8()
        try:
            cwd = (json.loads(raw) if raw.strip() else {}).get("cwd")
        except Exception:
            cwd = None
        return handle_stop_hook(root=resolve_repo_root(cwd))
    if mode == "disarm":
        # Escape hatch for a prompt that mentioned a review but produced no review cycle
        # (discussion, planning, rule edits).  Leaves the reason in the state directory.
        disarm_state = STATE_DIR
        state_path = disarm_state / ACTIVE_REVIEW
        if not state_path.exists():
            return 0
        reason = " ".join(argv[2:]).strip() or "non-review turn"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
        state["disarmed_reason"] = reason
        state["disarmed_at_utc"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (disarm_state / "last_disarm.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        state_path.unlink()
        print(f"stock-review-gate disarmed: {reason}")
        return 0
    if mode == "collect-context":
        prompt = " ".join(argv[2:])
        _write_stdout_utf8(_format_snapshot_context(collect_review_snapshot(prompt=prompt)))
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
