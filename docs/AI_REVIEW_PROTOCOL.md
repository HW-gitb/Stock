# AI Review Protocol

> Status: Active compatibility pointer
> Scope: Multi-LLM review workflow only
> Priority: `AGENTS.md` is the single source of truth for roles, short-command binding, adversarial review standards, closeout gates, and commit/execute boundaries. If this file conflicts with `AGENTS.md`, `AGENTS.md` wins.

## Source Of Truth

Do not maintain a second role map in this file.

Current binding lives in `AGENTS.md`:

- Codex = independent reviewer.
- Claude = designer + implementer + executor + committer.
- User = final approver.
- `审查` addressed to Codex = independent adversarial review, with no business-code edits.
- `修复` / `执行` / `提交` addressed to Claude = implementation, execution, and commit work.
- `批准` / `批准修改` is NOT required between a Codex `审查` and a Claude `修复` (2026-06-07 update): the user's `修复` directly authorizes repairing the reviewed Required findings, and Claude records that user-directed authorization in `docs/SESSION_LOG.md`. `批准` remains only for a standalone strategic / spend approval the user explicitly chooses to record.

The old Codex-implements / Claude-reviews workflow has been removed from this file to prevent stale cross-session instructions.

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

Codex review verdicts must be prepended to `docs/SESSION_LOG.md` before replying to the user, using the minimal review-cycle template (see Single-source recording below).

Review depth is governed by `AGENTS.md §Codex adversarial review standard`, especially the first-review slice-complete rule and the one-pass defect-class matrix rule. A Codex review must not be delta-only on the first pass, and must not stop at the first obvious issue when same-class variants remain unreviewed.

A review must CAPTURE the following — but split by destination, never duplicated:

- **In `docs/system_risk_register.md` (full detail, single source):** scope manifest (tracked/staged/unstaged/untracked files reviewed), each Required finding with materiality + PIT/scope labels + Required repair + boundary, Optional findings, register outcome (fixed / registered / non-material / covered by existing id), and closure evidence.
- **In the `docs/SESSION_LOG.md` minimal entry:** verdict (Pass / Fail / Pass-with-Required), the Required ID(s) pointing to the register, the verification run (tests / schema / recompute / guard-mutation + any gaps) in one line, and next step.

A clean Pass still needs a minimal PASS-only `docs/SESSION_LOG.md` entry so the next actor can find the verdict from repository state.

**Single-source recording (2026-06-13):** a material finding's FULL detail (scope manifest, Required text, materiality/risk, repair conditions/boundary, closure evidence) lives in `docs/system_risk_register.md` ONLY. **EVERY review-cycle `docs/SESSION_LOG.md` entry — including the first `审查` FAIL that introduces a Required ID, every `修复`, and PASS — uses the minimal template** in `AGENTS.md §Session log discipline → 评审循环 entry 极简模板` (verdict / Required-ID pointer / verify command / next; `修复` adds the one-line Pre-Codex Proof-of-use, which is NOT optional) and must NOT re-narrate the register's full analysis. There is **no first-review exemption**: the first FAIL records full findings in the register and only the minimal entry in SESSION_LOG, so the duplicate mutable fact never exists. A session-level handoff that genuinely needs broader context is a SEPARATE entry and still must not duplicate register findings. Double-writing + the minimal template are guarded by `tests/test_doc_governance_guard.py` (marker-gated compliant zone). `AGENTS.md` remains authoritative if this pointer drifts.

## Closeout Gate

The mandatory closeout gate lives in `AGENTS.md §Codex review closeout gate`.

This file intentionally does not duplicate that checklist. Duplication has caused stale role and command text before; future edits should update `AGENTS.md` instead.

## Commit And Execution Boundary

Commit and execution ownership follows `AGENTS.md`.

For Codex:

- do not run `修复`, `执行`, or `提交` business implementation work
- do not edit business code during `审查`
- do not give a clean Pass while a material Required finding is neither fixed nor registered

For Claude:

- implementation, execution, and commit work must respect the latest Codex review verdict, user approvals, singleton ledger discipline, and the system risk register
- no data fetch, materialization, signal search, provider call, production claim, ship-gate evidence, or full-size use is authorized unless the current reviewed artifact and user command explicitly allow it

## Maintenance Rule

Keep this file short. It is now a compatibility pointer, not a parallel protocol. If future role or command rules need to change, update `AGENTS.md` first.
