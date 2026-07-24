# Disposable full-system runtest capsules

## Purpose

`runners/a_short_runtest.ps1` and `runners/us_short_runtest.ps1` run the
existing full entries in a new, detached local clone instead of the main
working tree.  A capsule is always located at:

```text
D:\cnhea\Stock_runtest_private\<a_short|us_short>\<run_id>\repo\
```

The wrapper resolves an exact committed revision, creates the clone, disables
client-side reuse, redirects process temp/cache roots into the capsule, then
preserves the capsule after either success or failure.  The main repository is
not the runtime root.

## Invariants

- Every call needs `-ConfirmRuntest` and a fresh run id (generated when omitted).
- The run manifest says `run_mode=runtest`, `production_eligible=false`, and
  `ship_gate_evidence_allowed=false`; test output must never be used as formal
  weekly output or ship-gate evidence.
- A-short forces `-CachePolicy disabled` and a fresh normal L3 request.  It has
  no runtest option for `--reuse-l3-cache` or stale reuse.
- US-short starts without checkpoint/resume and rejects `--resume`; its private
  root, temporary files, provider samples, checkpoints, paper/shadow/lifecycle
  artifacts and all other fixed paths remain under the cloned repository or
  capsule-private root.
- Optional account/template inputs are copied to `private_inputs/` inside the
  capsule.  Keys/tokens remain process environment values only and are never
  recorded in the manifest.
- Before finalizing, the capsule compares an aggregate guard of the source
  repository's formal/private output roots.  Any source-tree write makes the
  runtest fail and leaves its capsule for inspection.

## Start commands

Use a committed revision explicitly when reproducibility matters.  Omit
`-AsOf` for A-short's ordinary canonical-date resolution.

```powershell
.\runners\a_short_runtest.ps1 -ConfirmRuntest -Commit <full-commit-sha>
```

```powershell
.\runners\us_short_runtest.ps1 -ConfirmRuntest -Commit <full-commit-sha>
```

The US-short command above is the safe dry-run plan.  A provider/live runtest
still requires the ordinary existing inputs and gates; the Pass2 call budget
is derived and frozen inside the same run:

```powershell
.\runners\us_short_runtest.ps1 -ConfirmRuntest -Live -Commit <full-commit-sha> -BatchTemplate <private-template.json> -AccountState <private-account.json> -MomentumTopK <K>
```

The wrappers create no production result directory and do not relax provider,
PIT, quota, account-date, Pass2-budget, or fail-closed checks.

## Inspect and delete

The capsule's signed manifest is stored in its `repo/` directory.  Its HMAC
key is kept outside the capsule (default `%LOCALAPPDATA%\Stock\`), so a marker
copied or edited inside a capsule cannot authorize deletion.  A currently
active, unsigned, tampered, or out-of-root path is rejected.

After a completed or failed run, use the same Python runtime to delete only the
named capsule:

```powershell
& <python.exe> .\runners\runtest_capsule.py --capsule-root D:\cnhea\Stock_runtest_private delete --capsule D:\cnhea\Stock_runtest_private\a_short\<run_id>
```

Deletion recursively removes only that validated capsule.  It never changes
the main repository, any formal result folder, or Git worktree management.
