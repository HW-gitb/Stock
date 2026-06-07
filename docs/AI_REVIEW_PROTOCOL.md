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
- `批准` / `批准修改` addressed to Codex = Codex first records the matching finding as `USER-APPROVED` in `docs/SESSION_LOG.md`, then Claude repairs afterward.

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

Codex review verdicts must be prepended to `docs/SESSION_LOG.md` before replying to the user.

The review entry must include:

- scope manifest: tracked, staged, unstaged, and untracked files reviewed
- verdict: Pass / Fail / Pass with Required fixes
- Required findings with materiality and PIT/scope labels
- Optional findings, if any
- register outcome: material findings fixed, registered in `docs/system_risk_register.md`, non-material, or already covered by an existing risk id
- verification: tests, schema checks, recomputation, guard/mutation checks, and any gaps
- next step

A clean Pass still needs a minimal PASS-only `docs/SESSION_LOG.md` entry so the next actor can find the review verdict from repository state.

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
