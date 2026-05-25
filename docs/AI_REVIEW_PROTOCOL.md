# AI Review Protocol

> Status: Active  
> Scope: Multi-LLM review workflow only  
> Priority: AGENTS.md remains the highest-level project rule. If this file conflicts with AGENTS.md, AGENTS.md wins.

## Roles

Codex is the Designer + Implementer.  
Claude is the Independent Reviewer.  
The user is the Final Approver.

## Codex Responsibilities

Codex is responsible for:
- reading AGENTS.md first
- reading docs/AI_REVIEW_PROTOCOL.md before multi-LLM work
- reading docs/CURRENT.md before each work session
- reading the top 1-3 entries of docs/SESSION_LOG.md
- reading relevant docs/handoff files for the current phase
- understanding the existing scripts before changing them
- proposing the next smallest safe task
- implementing one approved task at a time
- running relevant checks or tests
- updating docs/CURRENT.md after meaningful changes
- prepending docs/SESSION_LOG.md when there is a non-trivial commit, key judgement, failed attempt, or open issue

Codex must not:
- override AGENTS.md
- execute more than one task at a time
- rewrite the whole project without user approval
- delete working logic without user approval
- modify files outside the approved task
- follow Claude's review suggestions directly without user approval
- create new handoff files for ordinary small changes
- put code details or git state into Claude memory

## Claude Responsibilities

Claude is responsible for:
- independently reviewing Codex's plan
- independently reviewing Codex's diff
- checking whether Codex followed AGENTS.md
- checking whether docs/CURRENT.md matches the actual project state
- checking bugs, edge cases, tests, security risks, and data risks
- identifying over-engineering or unnecessary rewrites
- giving Pass / Pass with fixes / Fail feedback

Claude must not:
- directly modify code
- directly instruct Codex to execute tasks
- override the user
- expand the project scope
- create unrelated redesign tasks
- treat Claude memory as cross-LLM shared state

## User Responsibilities

The user is responsible for:
- approving whether Codex may execute a task
- deciding whether Claude's Required fixes should be applied
- deciding whether Optional suggestions should be ignored, deferred, or accepted
- deciding when a phase is complete

## Required Reading Order

For Codex:
1. AGENTS.md
2. docs/AI_REVIEW_PROTOCOL.md
3. docs/CURRENT.md
4. docs/SESSION_LOG.md top 1-3 entries
5. relevant docs/handoff files for the current phase
6. task-related code files

For Claude:
1. AGENTS.md
2. docs/AI_REVIEW_PROTOCOL.md
3. docs/CURRENT.md
4. docs/SESSION_LOG.md top 1-3 entries
5. relevant docs/handoff files
6. Codex plan or diff

## Standard Workflow

1. Codex proposes or updates the next smallest task.
2. Claude reviews the task or plan when needed.
3. The user approves the task.
4. Codex implements only that task.
5. Codex runs checks or tests.
6. Codex updates docs/CURRENT.md.
7. Codex prepends docs/SESSION_LOG.md if the change is non-trivial.
8. Claude reviews the diff. When the review contains Required fixes, Optional suggestions, open questions, a non-trivial verdict, or a phase/process decision, Claude prepends a review entry to `docs/SESSION_LOG.md` and clearly marks pending user approval items (see §Review Recording below).
9. The user decides whether to accept, request fixes, or defer.
10. Codex fixes only user-approved Required fixes.

## Review Verdicts

### Pass
The change can be accepted.

### Pass with fixes
The change is mostly acceptable but has Required fixes.

### Fail
The change should not be accepted until the main issues are fixed.

## Review Recording

Claude review output must be recorded in `docs/SESSION_LOG.md` (as a prepended entry per `AGENTS.md §Session log discipline`) when it contains any of:

- Required fixes
- Optional suggestions
- Open questions
- A non-trivial verdict (Pass with fixes / Fail)
- A phase or process decision

Review entries must clearly mark whether fixes are pending user approval (typical mark: `Status: REVIEW VERDICT RECORDED. Required fixes below are PENDING USER APPROVAL.`). Codex must not execute review suggestions directly unless the user has approved them. A review entry in `SESSION_LOG.md` is for cross-LLM continuity — it is **not** a direct execution order to Codex.

A pure Pass verdict with no fixes / no open questions / no process decision does not require a SESSION_LOG entry; the review can stay in chat or commit message.

## Documentation Rules

- docs/CURRENT.md is the current state snapshot.
- docs/SESSION_LOG.md is for cross-LLM cognitive continuity.
- docs/handoff files are for phase or major milestone handoff only.
- Claude memory is not shared with Codex.
- Cross-LLM shared information must be written to AGENTS.md or docs/.
