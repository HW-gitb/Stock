# Review-gate task-notification repair handoff — 2026-08-03

## Scope and owner

- **Finding**: `R-REVIEWGATE-OUTSTANDING-AGENT-CHECK-CANNOT-SEE-REAL-TASK-NOTIFICATIONS` (P1).
- **Current owner**: Codex executor/fixer. The repair is in the working tree; Claude Code independent review and commit are not done.
- **Truth sources**: full mechanism and closure criteria are in `docs/system_risk_register.md`; this handoff is the next-actor pointer, not a duplicate risk record.

## Files changed

- `.tools/claude_review_gate.py`: real transcript-row notification parsing, structured async-result detection, pending closeout validation, and Stop-hook `transcript_path` plumbing.
- `tests/test_claude_review_gate.py`: exact `queue-operation` and `attachment` notification fixtures, structured async signal, planted removal failure, Stop-hook block/clear, forwarding, and reverse controls.
- `AGENTS.md`: evidence-completeness rule now describes the implemented real-row behavior and the explicit `agent-aborted:` exception.

## Mechanism now under review

1. A launch is an `Agent`/`Task` `tool_use` block in `message.content`.
2. A result is async when top-level `toolUseResult.isAsync` is true or its status is `async_launched`; the observed prose marker remains fallback. A synchronous inline result is not pending.
3. A completed report is recognized by serializing the whole decoded JSONL row and extracting its `<tool-use-id>` only when `<task-notification>` is present. This covers top-level `content` and top-level `attachment`, instead of assuming `message.content`.
4. A launch after the review arm with no later report blocks closeout. A pre-arm launch is excluded; a missing launch timestamp is not an exemption. `agent-aborted:<reason>` is the only explicit abandonment escape.

## Evidence and limits

- Fixed interpreter: `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`, `Python 3.13.8`.
- `py_compile` passed for the changed Python files.
- `tests.test_claude_review_gate`: `Ran 12 tests ... OK`.
- Direct replay against a repository-resident real Claude transcript is `NOT_VERIFIED`: none is present in this current worktree. The tests use the exact observed top-level notification wrappers from the finding.
- No independent agent was launched during this repair. No provider/network/live-data action, A-short run, commit, push, or merge was performed. Existing untracked A-short artifacts are unrelated and must be preserved.

## Next actor

Claude Code: independently review the current diff and risk-register Required/closure matrix; if its runtime exposes a real transcript, replay the parser against it and record the result. Do not treat the focused green as a real-transcript PASS, and do not commit until the review gate itself passes.

