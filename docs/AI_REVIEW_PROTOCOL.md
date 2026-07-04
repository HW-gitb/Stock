# AI Review Protocol

> Status: Active compatibility pointer
> Scope: Multi-LLM review workflow only
> Priority: `AGENTS.md` is the single source of truth for roles, short-command binding, adversarial review standards, closeout gates, and commit/execute boundaries. If this file conflicts with `AGENTS.md`, `AGENTS.md` wins.

## Source Of Truth

Do not maintain a detailed second protocol in this file.

Current binding lives in `AGENTS.md`; this short compatibility map only prevents stale role startup:

- Codex = executor + fixer.
- Claude Code = independent reviewer + post-PASS committer.
- User = final approver.
- `审查` addressed to Claude Code = independent adversarial review, with no business-code edits.
- `修复` addressed to Codex = implementation / repair work after judging the reviewed finding.
- `提交` after a Claude Code `审查` PASS is owned by Claude Code automatically; it is not handed to Codex.
- `执行` remains subject to the specific user command and the project approval gates in `AGENTS.md`.
- `批准` / `批准修改` is NOT required between a Claude Code `审查` and a Codex `修复`: the user's `修复` directly authorizes repairing the reviewed Required findings, and Codex records that user-directed authorization in `docs/SESSION_LOG.md`. `批准` remains only for a standalone strategic / spend approval the user explicitly chooses to record.

## Required Reading

Every reviewer or implementer still follows the startup routing in `AGENTS.md`:

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/CURRENT.md`
4. `docs/system_risk_register.md`
5. `docs/SESSION_LOG.md` top 1-3 entries
6. this file
7. the current route-specific owner files named by `docs/README.md` / `docs/CURRENT.md`

## Review Recording

Reviewer verdicts must be prepended to `docs/SESSION_LOG.md` before replying to the user, using the minimal review-cycle template (see Single-source recording below).

Claude Code review evidence is also subject to the anti-fabrication gate in `AGENTS.md §Claude review anti-fabrication gate`. In short: only actual tool results, user-run `!` outputs, or the local `.tools/claude_review_gate.py` `REVIEW EVIDENCE SNAPSHOT` count as command/file/test evidence; simulated Bash / Read / Agent output is never evidence; uncertain provenance must be marked `NOT_VERIFIED`.

Review depth is governed by `AGENTS.md §Codex adversarial review standard` (historical standard name; current reviewer = Claude Code), especially the first-review slice-complete rule and the one-pass defect-class matrix rule. A review must not be delta-only on the first pass, and must not stop at the first obvious issue when same-class variants remain unreviewed.

A review must CAPTURE the following — but split by destination, never duplicated:

- **In `docs/system_risk_register.md` (full detail, single source):** scope manifest (tracked/staged/unstaged/untracked files reviewed), each Required finding with materiality + PIT/scope labels + Required repair + boundary, Optional findings, register outcome (fixed / registered / non-material / covered by existing id), and closure evidence.
- **In the `docs/SESSION_LOG.md` minimal entry:** verdict (Pass / Fail / Pass-with-Required), the Required ID(s) pointing to the register, the verification run (tests / schema / recompute / guard-mutation + any gaps) in one line, and next step.

This is repository logging, not a chat-output section: final user-facing replies follow `AGENTS.md` and 不再另起 `验证结果` / `已验证` / `Verify` / `验证` section.

A clean Pass still needs a minimal PASS-only `docs/SESSION_LOG.md` entry so the next actor can find the verdict from repository state.

**Single-source recording (2026-06-13):** a material finding's FULL detail (scope manifest, Required text, materiality/risk, repair conditions/boundary, closure evidence) lives in `docs/system_risk_register.md` ONLY. **EVERY review-cycle `docs/SESSION_LOG.md` entry — including the first `审查` FAIL that introduces a Required ID, every `修复`, and PASS — uses the minimal template** in `AGENTS.md §Session log discipline → 评审循环 entry 极简模板` (verdict / Required-ID pointer / verify command / next; `修复` adds the one-line Pre-Codex Proof-of-use, which is NOT optional) and must NOT re-narrate the register's full analysis. There is **no first-review exemption**: the first FAIL records full findings in the register and only the minimal entry in SESSION_LOG, so the duplicate mutable fact never exists. A session-level handoff that genuinely needs broader context is a SEPARATE entry and still must not duplicate register findings. Double-writing + the minimal template are guarded by `tests/test_doc_governance_guard.py` (marker-gated compliant zone). `AGENTS.md` remains authoritative if this pointer drifts.

## Closeout Gate

The mandatory closeout gate lives in `AGENTS.md §Codex review closeout gate`.

This file intentionally does not duplicate that checklist. Duplication has caused stale role and command text before; future edits should update `AGENTS.md` instead.

## Commit And Execution Boundary

Commit and execution ownership follows `AGENTS.md`.

For Codex:

- execute / repair only the user-authorized or reviewer-required scope
- judge reviewed findings before editing; surface a wrong or out-of-scope instruction instead of blindly implementing
- run `using-superpowers` when available before `执行` / `修复`
- run an independent agent self-review before handing work to Claude Code for `审查`, and record the short proof in the handoff entry

For Claude Code:

- do not edit business code during `审查`
- do not give a clean Pass while a material Required finding is neither fixed nor registered
- after a clean `审查` PASS, stage only the PASS-covered files and commit the reviewed slice before the final reply; if unrelated or overlapping unreviewed changes block safe auto-commit, record the blocker instead of staging them
- no data fetch, materialization, signal search, provider call, production claim, ship-gate evidence, or full-size use is authorized unless the current reviewed artifact and user command explicitly allow it

## Maintenance Rule

Keep this file short. It is now a compatibility pointer, not a parallel protocol. If future role or command rules need to change, update `AGENTS.md` first.
