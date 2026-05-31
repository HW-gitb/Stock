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
- reading docs/system_risk_register.md before each work session
- reading the top 1-3 entries of docs/SESSION_LOG.md
- reading relevant docs/handoff files for the current phase
- understanding the existing scripts before changing them
- proposing the next smallest safe task
- implementing one approved task at a time
- running relevant checks or tests
- updating docs/CURRENT.md after meaningful changes
- updating docs/system_risk_register.md when a material data / PIT / schema / execution / security finding is not fixed in the same reviewed slice
- prepending docs/SESSION_LOG.md when there is a non-trivial commit, key judgement, failed attempt, or open issue
- making each Codex-to-Claude SESSION_LOG handoff reviewable from repository state alone: in the `Worked on` section, tag file lists as `[tracked]` or `[untracked]` (or use equivalent explicit tracked/untracked sub-bullets), then list validation run/result and current review state / expected next reviewer action when the round changes files

Codex must not:
- override AGENTS.md
- execute more than one task at a time
- rewrite the whole project without user approval
- delete working logic without user approval
- modify files outside the approved task
- repair Required fixes without user approval, or dispose Optional suggestions outside the `修复` flow
- create new handoff files for ordinary small changes
- put code details or git state into Claude memory

## Claude Responsibilities

Claude is responsible for:
- independently reviewing Codex's plan
- independently reviewing Codex's working tree, not only `git diff`: mandatory fast path is `git status --short`, `git diff`, every `??` untracked file body, and docs/SESSION_LOG.md top 1-3 entries; staged changes also require `git diff --cached`
- checking whether Codex followed AGENTS.md
- checking whether docs/CURRENT.md matches the actual project state
- checking whether docs/system_risk_register.md was read and updated when the round introduces, resolves, or discovers material risks
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

### Reviewer Behavior Rules

If Claude discovers a self-review finding while drafting or revising Claude's own review entry, Claude must amend the SESSION_LOG review entry directly. Do not ask the user whether to record that self-review finding. Required / Optional classification still follows §Review Recording.

When Claude needs to recommend a workflow path, Claude should give one recommended path with reasoning and mention the override condition if one is useful. Do not present an options menu for the user to choose unless the user explicitly asks for options or repository evidence makes a single recommendation impossible.

## User Responsibilities

The user is responsible for:
- approving whether Codex may execute a task
- deciding whether Claude's Required fixes should be applied
- deciding when a phase is complete

The user is **not** responsible for deciding individual Optional suggestions: those route to Codex disposition per §修复 (as of 2026-05-26). The user retains override via `git revert` or by explicitly directing Codex to reverse a disposition.

## Required Reading Order

For Codex:
1. AGENTS.md
2. docs/AI_REVIEW_PROTOCOL.md
3. docs/CURRENT.md
4. docs/system_risk_register.md
5. docs/SESSION_LOG.md top 1-3 entries
6. relevant docs/handoff files for the current phase
7. task-related code files

For Claude:
1. AGENTS.md
2. docs/AI_REVIEW_PROTOCOL.md
3. docs/CURRENT.md
4. docs/system_risk_register.md
5. docs/SESSION_LOG.md top 1-3 entries
6. relevant docs/handoff files
7. Codex plan or diff (read git diff directly)

## Standard Workflow

1. Codex proposes or updates the next smallest task.
2. Claude reviews the task or plan when needed.
3. The user approves the task.
4. Codex implements only that task.
5. Codex runs checks or tests.
6. Codex updates docs/CURRENT.md when the change is meaningful, and updates docs/system_risk_register.md when material risks are introduced, resolved, or discovered but not fixed.
7. Codex prepends docs/SESSION_LOG.md if the change is non-trivial (Codex's entry IS the handoff to Claude; there is no separate REVIEW_PACKET). For file-changing rounds, the entry's `Worked on` section must tag file lists as `[tracked]` or `[untracked]` (or equivalent explicit tracked/untracked sub-bullets), and must include validation run/result plus current review state / expected next reviewer action.
8. Claude reviews the actual working tree plus the top SESSION_LOG entry. Working-tree review mandatory fast path: `git status --short`, `git diff`, every `??` untracked file body, and docs/SESSION_LOG.md top 1-3 entries. If status shows staged changes, Claude also inspects `git diff --cached`. When the review contains Required fixes, Optional suggestions, open questions, a non-trivial verdict, or a phase/process decision, Claude prepends a review entry to `docs/SESSION_LOG.md` marking Required fixes as PENDING USER APPROVAL and Optional suggestions as PENDING CODEX DISPOSITION (see §Review Recording below). A pure Pass writes a minimal PASS-only entry (see §Review Recording).
9. The user decides Required fixes (approve via `批准修改` / defer via `暂缓修改`). Optional suggestions skip user approval and route to Codex disposition during the next `修复` round.
10. Codex repairs user-approved Required fixes AND disposes of each Optional suggestion (accept / accept with modification / reject + reason). See §修复.
11. After Claude returns Pass on the latest iteration, the user invokes `提交`; Codex commits the reviewed working tree as a single coherent commit. Codex must not commit during `执行` or `修复` (see §Commit Timing Rule below).

## Review Verdicts

### Pass
The change can be accepted.

### Pass with fixes
The change is mostly acceptable but has Required fixes.

### Fail
The change should not be accepted until the main issues are fixed.

## Optional Re-raise Constraint

(Established 2026-05-26.)

When Claude re-reviews a `修复` round and a prior Optional was disposed as `reject` (per §修复), Claude must not re-raise the same Optional unless Claude has materially new information — for example, the reject reason itself contains a logic error, or new diff evidence invalidates Codex's rationale.

Rationale: Codex is the Designer; Optional suggestions are advisory. Re-raising rejected Optionals turns review into "I know your design better than you do" loops. Claude's review lane is correctness, scope, contract, risk — not overriding Designer judgment on advisory items.

`accept with modification` deviations may be re-flagged if Claude believes the modification missed the Optional's original intent. Mark such items as a **new** Optional that explicitly references the prior Optional ID (e.g., "Re-flagging prior O3's accept-with-modification: the deviation skipped the entry/exit coverage requirement"). Do not re-state the original rejected Optional verbatim.

If Claude believes a rejected Optional should be elevated to Required (rare — usually means it was mis-classified the first round), Claude must explicitly explain the elevation rationale in the new review entry, not silently re-add it under the same Optional category.

## Review Recording

Claude review output must be recorded in `docs/SESSION_LOG.md` (as a prepended entry per `AGENTS.md §Session log discipline`) when it contains any of:

- Required fixes
- Optional suggestions
- Open questions
- A non-trivial verdict (Pass with fixes / Fail)
- A phase or process decision

Review entries must clearly mark pending status separately for Required fixes and Optional suggestions:

- Required fixes (if any) → PENDING USER APPROVAL — Codex must not repair until user invokes `批准修改`.
- Optional suggestions (if any) → PENDING CODEX DISPOSITION — Codex decides accept / accept with modification / reject + reason during the next `修复` round, no user approval needed (see §修复).

Typical mark: `Status: REVIEW VERDICT RECORDED. Required fixes (if any) PENDING USER APPROVAL; Optional suggestions (if any) PENDING CODEX DISPOSITION.`

A review entry in `SESSION_LOG.md` is for cross-LLM continuity — it is **not** a direct execution order to Codex.

A pure Pass verdict (no Required fixes, no Optional suggestions, no open questions, no process decision) **still requires a minimal PASS-only SESSION_LOG entry**, so that `提交` step 3 (verify Claude's latest verdict is Pass) can find it. Without the entry, Codex cannot read the chat where the Pass was given.

Minimal PASS-only entry format (4 fields max, terse):

```markdown
## YYYY-MM-DD — Claude review — Pass (<one-line scope>)

**Commits**: none (review-only entry; reviews <target>: working tree status/diffs/untracked files vs <ref-commit-or-HEAD>)

**Verdict**: Pass.

**Notes**: <one short sentence — what was verified, or "No Required fixes / no Optional suggestions / no open questions" if pure>.
```

No `Required fixes`, `Optional suggestions`, `Open questions`, `Worked on`, `Alternatives`, or `Next step` sections needed. The entry exists primarily as a Pass marker for downstream `提交`, not as detailed review documentation.

## Commit Timing Rule

Pattern B: commit happens **after** Claude returns Pass, not during `执行` or `修复`.

- `执行` and `修复` modify the working tree only. They must not run `git commit`.
- `审查` reviews the uncommitted working tree (status, unstaged diff, cached diff, and untracked files) plus the top SESSION_LOG entry written by Codex.
- After Claude returns Pass (or Pass with all Required fixes resolved via approved `修复` rounds reaching a clean Pass), the user invokes `提交` and Codex commits.

Rationale:
- Git history contains only reviewed-and-passed work; bisect / revert never lands on intermediate dirty state.
- Working tree IS the review artifact during `审查`; no need to commit-then-amend if review finds issues.
- If `审查` returns Fail, `git checkout .` cleanly discards; no garbage commit to clean up.

Exception (must be explicitly stated by the user): a work block too large for one review round may use checkpoint commits prefixed with `WIP:`. Default is no exception.

### Commit Documentation Hygiene

Default `提交` path stays small and should produce **one commit** for a single reviewed scope:

1. Verify the latest SESSION_LOG review verdict is a clean Claude Pass.
2. Run `git status --short`.
3. If the working tree is single-scope, run `git add -A`. If it contains two or more independent scopes, use §Multi-scope Commit Splitting instead.
4. Run `git commit`.
5. Run `git status --short`.

Before `审查` / `提交`, Codex must phrase `docs/CURRENT.md` and `docs/SESSION_LOG.md` so they remain true after the reviewed change is committed. This is the default way to avoid extra post-commit cleanup work. Prefer stable wording such as:
- "the reviewed change set adds ..."
- "after this reviewed change is committed, the next natural step is ..."
- "Phase 5 step 3 added ..." for an intermediate step in a longer phase

Avoid wording that becomes stale immediately after commit, such as:
- "current uncommitted work ..."
- "pending review / pending commit ..."
- "latest commit will be ..."
- "today / this round added ..." when a phase or step identifier would be more stable

Do not try to write the new commit hash into the same commit that creates it. The final Codex response and `git log` carry the hash. Do not create a second commit merely to add the new hash when the committed docs already identify the scope and next task clearly.

#### Post-commit exception

Do **not** create a routine post-commit documentation sync commit.

Post-commit doc sync is an exception only when the just-created commit leaves `docs/CURRENT.md` or `docs/SESSION_LOG.md` materially misleading for the next LLM and the issue could not reasonably have been avoided by stable pre-commit wording. Concrete triggers:
- a committed doc still says the already-committed work is pending review, pending commit, or only in the working tree
- `docs/CURRENT.md` Latest Delta has a commit chain or current-state statement that would point the next LLM at the wrong next task without the just-created hash or state correction
- a handoff or session entry says "next round does X" when the just-created commit already did X

Non-triggers:
- adding the new hash when the committed docs already identify the scope and next task clearly enough
- polishing wording that is not misleading
- keeping a chronological hash list perfectly complete when it is not needed for the next handoff decision

If the exception is needed, keep the sync docs-only, small, and prefixed `[trivial]`; explain both hashes in the final response. This exception is not part of the normal `提交` flow, and repeated use means the prior `执行` / `修复` documentation was written too transiently.

### Multi-scope Commit Splitting

A scope is one coherent, reviewable change set. A working tree is multi-scope when it contains two or more independent topics that can be reviewed, reverted, or shipped separately, for example a business-code fix plus an unrelated protocol rule change.

When the working tree is multi-scope:

1. Do not use `git add -A` to create one mixed commit.
2. Prefer path-limited staging (`git add <paths>`) when each scope lives in distinct files.
3. If the same file contains multiple independent scopes, split it before committing. Use the least risky local method available: apply a partial patch, edit the file down to one scope and restore the remaining scope after commit, or make a temporary backup while splitting.
4. Commit one scope at a time, then run `git status --short` before deciding whether another scope remains.
5. If scopes depend on each other, commit the prerequisite first and state that relationship in the commit message.

## Lightweight Track Exemption

For trivial changes the standard review cycle is over-engineered. Codex may self-route to the lightweight track:

Criteria (ALL must hold):
- No business logic touched
- No schema / contract change
- No new files (small docs OK)
- No new code paths added or removed
- Roughly <20 lines diff

Procedure:
- Codex executes the fix immediately. No `执行` alias needed, no `修复` alias needed.
- Codex commits directly with message prefixed `[trivial]` (e.g., `[trivial] Fix typo in CURRENT.md L11`). This is the only case where Codex commits without a prior Claude `审查` Pass.
- SESSION_LOG entry may be skipped for purely cosmetic changes. If the change includes any meaningful clarification, write a one-line SESSION_LOG entry.

Claude behavior:
- Claude does not review `[trivial]` commits during normal `审查`. User reviews via git log periodically.
- If Claude is invoked for `审查` and the top recent commits are all `[trivial]`, Claude says "no review-eligible work since last Pass".

Hard exclusions (never `[trivial]`, must use standard cycle):
- AGENTS.md changes (highest rule, always reviewed)
- AI_REVIEW_PROTOCOL.md changes (workflow itself, always reviewed)
- Business code in `A-EGS/` `engine/` `runners/`
- Schema files in `schemas/`
- State files in `state/`
- Handoff files in `docs/handoff/`
- Any change touching commit-flow / role-separation logic

Safety: if Codex is uncertain whether a change qualifies as `[trivial]`, default to standard cycle.

User override: user may revert any `[trivial]` commit with `git revert` if they disagree.

## Review Continuity Without Packet

After removing the short-lived REVIEW_PACKET document (decision 2026-05-25), all Codex-to-Claude handoff information lives in the SESSION_LOG entry written by Codex after each `执行` or `修复`.

Claude review has four mandatory fast-path steps before any verdict:

1. Run `git status --short`.
2. Inspect `git diff` directly.
3. Read the body of every file listed as `??` by `git status --short`.
4. Read docs/system_risk_register.md and docs/SESSION_LOG.md top 1-3 entries, including the top Codex handoff for this round.

Staged-change add-on: if `git status --short` shows staged changes, Claude also inspects `git diff --cached`.

That is sufficient for Claude to review. There is no separate short-lived file to consult or update.

Codex must not repair Required fixes unless the user approves them. Optional suggestions are disposed by Codex during `修复` per this protocol; they are not executed directly from review text.

### Working Tree Completeness Guard

Claude review must treat `git status --short` as the source of truth for review scope. `git diff` alone is incomplete because it omits untracked files, and `git diff --cached` may contain staged changes that are not visible in the unstaged diff.

If `git status --short` contains `??` files, Claude must inspect their contents before issuing a verdict. If a `??` file is binary or too large to read safely, Claude must flag it as a review blocker or scope/ignore issue instead of issuing Pass. Intentional source, schema, example, test, or docs files are fully in scope.

If `git status --short` contains staged changes, Claude must inspect `git diff --cached` in addition to `git diff`. A Pass verdict is invalid if it ignores staged or untracked files that are part of the working tree under review.

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
4. Read docs/system_risk_register.md and identify open P0/P1 entries relevant to the next task.
5. Read the top 1-3 entries of docs/SESSION_LOG.md.
6. Read the relevant docs/handoff files for the current phase.
7. Identify the next approved smallest task from docs/CURRENT.md, docs/system_risk_register.md, or the current task section. Open P0 entries in the register outrank normal roadmap work unless the user explicitly approves a narrower override.
8. Execute only that one task.
9. Do not execute a second task.
10. Do not rewrite the whole project.
11. Do not delete working logic.
12. Do not modify files outside the approved task.
13. Run relevant tests or checks.
14. Update docs/CURRENT.md if the current state changed.
15. Update docs/system_risk_register.md if the round fixes, introduces, or discovers a material risk.
16. Prepend docs/SESSION_LOG.md if there is a non-trivial change, key judgement, failed attempt, open issue, or process decision. This entry IS the handoff to Claude (no separate REVIEW_PACKET).
17. Do not create or update handoff files unless this is a phase or major milestone change.
18. Do not commit. Commit is a separate step after Claude `审查` returns Pass; user invokes `提交`. See §Commit Timing Rule.

After finishing, Codex must output only a concise summary:
- Task completed
- Files changed
- Tests/checks run
- SESSION_LOG entry prepended: Yes / No
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
4. Read docs/system_risk_register.md.
5. Read the top 1-3 entries of docs/SESSION_LOG.md.
6. Read the relevant docs/handoff files for the current phase.
7. Read the top SESSION_LOG entry written by Codex for this round.
8. Run `git status --short` and use it as the review scope index.
9. Inspect `git diff` directly.
10. Inspect `git diff --cached` directly.
11. Read every `??` untracked file body listed by `git status --short`; if a `??` file is binary or too large to read safely, flag it as a review blocker or scope/ignore issue.
12. Confirm the top Codex SESSION_LOG entry's `Worked on` section tags file lists as `[tracked]` and `[untracked]` (or equivalent explicit tracked/untracked sub-bullets), and lists validation run/result plus current review state / expected next reviewer action.
13. Review whether Codex followed the approved task.
14. Review whether Codex modified files outside scope.
15. Review whether existing working logic was broken.
16. Review bugs, edge cases, tests, security, data, and state risks.
17. Review whether docs/CURRENT.md, docs/system_risk_register.md, and the SESSION_LOG entry were updated correctly.
18. If the review discovers a material risk not fixed in the change, require it to be added to docs/system_risk_register.md or explain why an existing entry already covers it; otherwise do not issue a clean Pass.
19. Output Verdict: Pass / Pass with fixes / Fail.
20. If there are Required fixes, Optional suggestions, open questions, or process decisions, write the review result into docs/SESSION_LOG.md using the separate Required / Optional pending statuses from §Review Recording. For pure Pass, write a minimal PASS-only entry (see §Review Recording).
21. Do not directly modify business code.
22. Do not directly instruct Codex to execute fixes.
23. Do not expand the project scope.

Claude output should be concise:
- Verdict
- Required fixes
- Optional suggestions
- Documentation issues
- Pending user approval: Yes / No

### User command: 批准修改

Meaning:

The user approves Claude's pending Required fixes. `批准修改` applies only to Required fixes — Optional suggestions are not user-approved; they route to Codex disposition during `修复` (see §修复).

When the user types:

批准修改

It means:

1. The user approves all currently pending Required fixes from the latest Claude review.
2. `批准修改` does not apply to Optional suggestions; Codex disposes of each Optional during the next `修复` regardless of user action here.
3. Codex may repair the approved Required fixes during the next `修复`.
4. Codex must not expand scope beyond approved Required fixes + Optional dispositions.
5. If the repair is non-trivial, Codex must prepend docs/SESSION_LOG.md (this is the handoff for Claude re-review).

If the user wants partial Required approval, they may type:

批准修改 1,2

Then only Required fixes 1 and 2 are approved; Optional disposition still proceeds automatically during `修复`.

If the user types:

暂缓修改

Then Codex must not execute any Required fixes, but may still dispose of Optional suggestions during `修复`.

### User command to Codex: 修复

Meaning:

Codex must repair user-approved Required fixes from the latest Claude review AND dispose of each Optional suggestion as the Designer.

When the user types only:

修复

Codex must automatically do all of the following:

1. Read AGENTS.md.
2. Read docs/AI_REVIEW_PROTOCOL.md.
3. Read docs/CURRENT.md.
4. Read docs/system_risk_register.md.
5. Read docs/SESSION_LOG.md top 1-3 entries.
6. Identify which Required fixes are approved by the user.
7. Repair only user-approved Required fixes.
8. Do not repair unapproved Required fixes.
9. For each Optional suggestion in the latest Claude review, decide one of:
   a. **accept** — implement as Claude described
   b. **accept with modification** — implement with deviation; record exact deviation and reason
   c. **reject** — do not implement; record reason
   Codex is the Designer and has authority to decide each Optional. No user approval needed.
10. Do not add new features beyond Required fixes + Optional dispositions.
11. Do not refactor unrelated code.
12. Do not modify files outside Required fix scope + Optional disposition scope.
13. Run relevant tests or checks.
14. Update docs/CURRENT.md if needed.
15. Update docs/system_risk_register.md if the repair fixes, defers, or adds a material risk.
16. Prepend docs/SESSION_LOG.md (this entry IS the handoff to Claude for re-review). The entry must include an `Optional disposition` section listing one line per Optional from the prior Claude review:
    - `O1 accept` (no further detail needed)
    - `O2 accept with modification — change: <what>; reason: <why>`
    - `O3 reject — reason: <why>`
    If the prior Claude review had zero Optionals, skip this section.
17. Do not commit. Commit is a separate step after Claude `审查` returns Pass; user invokes `提交`. See §Commit Timing Rule.

After finishing, Codex must output only a concise summary:
- Approved Required fixes repaired (count)
- Optional dispositions: <N accepted, M accepted with modification, K rejected>
- Files changed
- Tests/checks run
- SESSION_LOG entry prepended: Yes / No (must include `Optional disposition` section if there were Optionals)
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
4. If the latest verdict is Fail, Pass with unresolved Required fixes, or a review entry still has unresolved `PENDING CODEX DISPOSITION` Optional suggestions (meaning Codex has not yet run `修复` and reached a clean re-review Pass): refuse to commit. Output the reason and instruct user to run `批准修改` if Required fixes are pending, then `修复`, then `审查`.
5. If the latest verdict is a clean Pass with no pending Required fixes or Optional dispositions: run `git status` to see the change set.
6. If `git status` shows nothing to stage, refuse and output `nothing to commit; no changes pending`.
7. If the reviewed working tree is single-scope, run `git add -A` to stage all working tree changes; files matching `.gitignore` are skipped automatically. If it is multi-scope, follow §Multi-scope Commit Splitting and commit one scope at a time.
8. Run `git commit` with a descriptive message that references the latest SESSION_LOG entry and lists the items in the change set.
9. Run `git status` again to verify clean working tree.
10. Do not push. Do not add remotes. Do not amend prior commits unless the user explicitly authorizes.
11. Do not create a post-commit sync commit by default. Use §Commit Documentation Hygiene / Post-commit exception only if the committed docs would materially mislead the next LLM.

After finishing, Codex must output only a concise summary:
- Commit hash(es)
- Files committed
- git status clean: Yes / No
- Ready for next `执行`: Yes / No

## Safety Rule for Short Commands

Even when the user uses a one-word command, the full protocol still applies.

Short commands reduce user typing only. They do not reduce required reading, review, documentation, testing, or approval steps.

If a short command is ambiguous or unsafe, stop and ask the user for confirmation.

## Documentation Rules

- docs/CURRENT.md is the current state snapshot.
- docs/CURRENT.md must avoid transient "pending review / pending commit / current uncommitted work" wording when the same reviewed change is expected to be committed immediately after Claude Pass; write stable state statements so the reviewed change can land in a single commit.
- docs/system_risk_register.md is the durable open-risk queue. It must track material data / PIT / schema / execution / security findings that are not fixed immediately. Keep entries concise, evidence-linked, and status-driven.
- docs/SESSION_LOG.md is for cross-LLM cognitive continuity. The top entry written by Codex after each `执行` / `修复` doubles as the Codex-to-Claude review handoff (no separate REVIEW_PACKET file as of 2026-05-25).
- docs/handoff files are for phase or major milestone handoff only.
- Claude memory is not shared with Codex.
- Cross-LLM shared information must be written to AGENTS.md or docs/.
