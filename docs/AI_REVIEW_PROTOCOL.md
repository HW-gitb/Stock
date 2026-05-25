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
- updating docs/REVIEW_PACKET.md after each implementation task before Claude review
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
- reading docs/REVIEW_PACKET.md before reviewing Codex's diff
- independently reviewing Codex's diff
- inspecting the actual git diff directly when Claude can access the repo, instead of relying only on pasted chat output
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
6. docs/REVIEW_PACKET.md
7. Codex plan or diff

## Standard Workflow

1. Codex proposes or updates the next smallest task.
2. Claude reviews the task or plan when needed.
3. The user approves the task.
4. Codex implements only that task.
5. Codex runs checks or tests.
6. Codex updates docs/CURRENT.md when the change is meaningful.
7. Codex updates docs/REVIEW_PACKET.md before Claude review.
8. Codex prepends docs/SESSION_LOG.md if the change is non-trivial.
9. Claude reads docs/REVIEW_PACKET.md, then reviews the actual git diff when repo access is available. When the review contains Required fixes, Optional suggestions, open questions, a non-trivial verdict, or a phase/process decision, Claude prepends a review entry to `docs/SESSION_LOG.md` and clearly marks pending user approval items (see §Review Recording below).
10. The user decides whether to accept, request fixes, or defer.
11. Codex fixes only user-approved Required fixes.
12. After Claude returns Pass on the latest iteration, the user invokes `提交`; Codex commits the reviewed working tree as a single coherent commit. Codex must not commit during `执行` or `修复` (see §Commit Timing Rule below).

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

A pure Pass verdict (no Required fixes, no Optional suggestions, no open questions, no process decision) **still requires a minimal PASS-only SESSION_LOG entry**, so that `提交` step 3 (verify Claude's latest verdict is Pass) can find it. Without the entry, Codex cannot read the chat where the Pass was given.

Minimal PASS-only entry format (4 fields max, terse):

```markdown
## YYYY-MM-DD — Claude review — Pass (<one-line scope>)

**Commits**: none (review-only entry; reviews <target>: working tree diff vs <ref-commit-or-HEAD>)

**Verdict**: Pass.

**Notes**: <one short sentence — what was verified, or "No Required fixes / no Optional suggestions / no open questions" if pure>.
```

No `Required fixes`, `Optional suggestions`, `Open questions`, `Worked on`, `Alternatives`, or `Next step` sections needed. The entry exists primarily as a Pass marker for downstream `提交`, not as detailed review documentation.

## Commit Timing Rule

Pattern B: commit happens **after** Claude returns Pass, not during `执行` or `修复`.

- `执行` and `修复` modify the working tree only. They must not run `git commit`.
- `审查` reviews the working tree diff (uncommitted) plus `docs/REVIEW_PACKET.md`.
- After Claude returns Pass (or Pass with all Required fixes resolved via approved `修复` rounds reaching a clean Pass), the user invokes `提交` and Codex commits.

Rationale:
- Git history contains only reviewed-and-passed work; bisect / revert never lands on intermediate dirty state.
- Working tree IS the review artifact during `审查`; no need to commit-then-amend if review finds issues.
- If `审查` returns Fail, `git checkout .` cleanly discards; no garbage commit to clean up.

Exception (must be explicitly stated by the user): a work block too large for one review round may use checkpoint commits prefixed with `WIP:`. Default is no exception.

## Review Packet Rule

Codex must update docs/REVIEW_PACKET.md after every implementation task and before Claude review.

docs/REVIEW_PACKET.md must include:
- current task
- user approval status
- files modified
- files intentionally not touched
- change summary
- diff summary
- test or check results
- documentation updates
- open issues
- questions for Claude

Claude must read docs/REVIEW_PACKET.md before reviewing the current diff.

If Claude can access the repo, Claude must inspect the actual git diff directly instead of relying only on pasted chat output.

docs/REVIEW_PACKET.md is short-lived and only represents the latest review round.

docs/REVIEW_PACKET.md is intentionally gitignored. Codex should overwrite it for each review round instead of preserving packet history in git.

If Claude is the transitional Implementer (for example, for protocol-level edits the user directs Claude to make), Claude may either skip the REVIEW_PACKET.md update or fill it with minimal Claude-implementer fields. The SESSION_LOG entry remains the canonical record for that change.

docs/SESSION_LOG.md remains the long-term cross-LLM cognitive log.

Claude review results with Required fixes, Optional suggestions, open questions, or process decisions must still be recorded in docs/SESSION_LOG.md and marked pending user approval.

Codex must not execute Claude review suggestions unless the user approves them.

## Short Command Aliases

The user may use very short commands. These aliases are binding and must be interpreted according to this protocol.

### User command to Codex: 执行

Meaning:

Codex must execute the next approved smallest task.

When the user types only:

执行

Codex must automatically do all of the following:

1. Read AGENTS.md.
2. Read docs/AI_REVIEW_PROTOCOL.md.
3. Read docs/CURRENT.md.
4. Read the top 1-3 entries of docs/SESSION_LOG.md.
5. Read the relevant docs/handoff files for the current phase.
6. Identify the next approved smallest task from docs/CURRENT.md or the current task section.
7. Execute only that one task.
8. Do not execute a second task.
9. Do not rewrite the whole project.
10. Do not delete working logic.
11. Do not modify files outside the approved task.
12. Run relevant tests or checks.
13. Update docs/CURRENT.md if the current state changed.
14. Update docs/REVIEW_PACKET.md completely for Claude review.
15. Prepend docs/SESSION_LOG.md only if there is a non-trivial change, key judgement, failed attempt, open issue, or process decision.
16. Do not create or update handoff files unless this is a phase or major milestone change.
17. Do not commit. Commit is a separate step after Claude `审查` returns Pass; user invokes `提交`. See §Commit Timing Rule.

After finishing, Codex must output only a concise summary:
- Task completed
- Files changed
- Tests/checks run
- docs/REVIEW_PACKET.md updated: Yes / No
- Working tree uncommitted (per Commit Timing Rule): Yes
- Ready for Claude review: Yes / No

### User command to Claude: 审查

Meaning:

The word "审查" means "review the current Codex change". It does not mean Claude should modify code.

When the user types only:

审查

Claude must automatically do all of the following:

1. Read AGENTS.md.
2. Read docs/AI_REVIEW_PROTOCOL.md.
3. Read docs/CURRENT.md.
4. Read the top 1-3 entries of docs/SESSION_LOG.md.
5. Read the relevant docs/handoff files for the current phase.
6. Read docs/REVIEW_PACKET.md.
7. Inspect the current git diff directly if available.
8. Review whether Codex followed the approved task.
9. Review whether Codex modified files outside scope.
10. Review whether existing working logic was broken.
11. Review bugs, edge cases, tests, security, data, and state risks.
12. Review whether docs/CURRENT.md and docs/REVIEW_PACKET.md were updated correctly.
13. Output Verdict: Pass / Pass with fixes / Fail.
14. If there are Required fixes, Optional suggestions, open questions, or process decisions, write the review result into docs/SESSION_LOG.md and mark it pending user approval.
15. Do not directly modify business code.
16. Do not directly instruct Codex to execute fixes.
17. Do not expand the project scope.

Claude output should be concise:
- Verdict
- Required fixes
- Optional suggestions
- Documentation issues
- Pending user approval: Yes / No

### User command: 批准修改

Meaning:

The user approves Claude's pending Required fixes.

When the user types:

批准修改

It means:

1. The user approves all currently pending Required fixes from the latest Claude review.
2. Optional suggestions are not approved unless explicitly stated.
3. Codex may only repair the approved Required fixes.
4. Codex must not expand scope.
5. Codex must not execute Optional suggestions.
6. Codex must update docs/REVIEW_PACKET.md after fixing.
7. If the fix is non-trivial, Codex must prepend docs/SESSION_LOG.md.

If the user wants partial approval, they may type:

批准修改 1,2

Then only Required fixes 1 and 2 are approved.

If the user types:

暂缓修改

Then Codex must not execute any Required fixes.

### User command to Codex: 修复

Meaning:

Codex must repair only the user-approved Required fixes from the latest Claude review.

When the user types only:

修复

Codex must automatically do all of the following:

1. Read AGENTS.md.
2. Read docs/AI_REVIEW_PROTOCOL.md.
3. Read docs/CURRENT.md.
4. Read docs/SESSION_LOG.md top 1-3 entries.
5. Read docs/REVIEW_PACKET.md.
6. Identify which Required fixes are approved by the user.
7. Repair only approved Required fixes.
8. Do not repair unapproved Required fixes.
9. Do not execute Optional suggestions.
10. Do not add new features.
11. Do not refactor unrelated code.
12. Do not modify files outside the fix scope.
13. Run relevant tests or checks.
14. Update docs/CURRENT.md if needed.
15. Update docs/REVIEW_PACKET.md for Claude re-review.
16. Prepend docs/SESSION_LOG.md if the fix is non-trivial.
17. Do not commit. Commit is a separate step after Claude `审查` returns Pass; user invokes `提交`. See §Commit Timing Rule.

After finishing, Codex must output only a concise summary:
- Approved fixes repaired
- Files changed
- Tests/checks run
- docs/REVIEW_PACKET.md updated: Yes / No
- Working tree uncommitted (per Commit Timing Rule): Yes
- Ready for Claude re-review: Yes / No

### User command to Codex: 提交

Meaning:

After Claude `审查` returns Pass, Codex commits the reviewed working tree as a single coherent commit. This finalizes the change set. Codex must not commit during `执行` or `修复`.

When the user types only:

提交

Codex must automatically do all of the following:

1. Read AGENTS.md.
2. Read docs/AI_REVIEW_PROTOCOL.md.
3. Read docs/SESSION_LOG.md top 1-3 entries to verify Claude's latest verdict is Pass.
4. If the latest verdict is Fail, or Pass with unresolved Required fixes (meaning fixes approved by the user but not yet repaired and Claude-re-passed): refuse to commit. Output the reason and instruct user to run `批准修改` + `修复` first.
5. If the latest verdict is Pass: run `git status` to see the change set.
6. If `git status` shows nothing to stage, refuse and output `nothing to commit; no changes pending`.
7. Run `git add -A` to stage all working tree changes. Pattern B assumes the whole working tree has been reviewed; files matching `.gitignore` are skipped automatically.
8. Run `git commit` with a descriptive message that references the latest SESSION_LOG entry and lists the items in the change set.
9. Run `git status` again to verify clean working tree.
10. Do not push. Do not add remotes. Do not amend prior commits unless the user explicitly authorizes.

After finishing, Codex must output only a concise summary:
- Commit hash
- Files committed
- git status clean: Yes / No
- Ready for next `执行`: Yes / No

## Safety Rule for Short Commands

Even when the user uses a one-word command, the full protocol still applies.

Short commands reduce user typing only. They do not reduce required reading, review, documentation, testing, or approval steps.

If a short command is ambiguous or unsafe, stop and ask the user for confirmation.

## Documentation Rules

- docs/CURRENT.md is the current state snapshot.
- docs/REVIEW_PACKET.md is the short-lived Codex-to-Claude review handoff for the current review round. It is intentionally gitignored and may be overwritten each round.
- docs/SESSION_LOG.md is for cross-LLM cognitive continuity.
- docs/handoff files are for phase or major milestone handoff only.
- Claude memory is not shared with Codex.
- Cross-LLM shared information must be written to AGENTS.md or docs/.
