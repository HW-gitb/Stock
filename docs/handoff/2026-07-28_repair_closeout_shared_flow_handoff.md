# Repair-closeout shared flow / lane-specific verification handoff

## Scope and decision

The repair-closeout matrix is one shared execution/repair process for A-short and US-short. `matrix=`, `register=`, and `handoff=` record the common closure responsibility; the same `SESSION_LOG` adoption marker and doc-governance guard enforce future repair entries.

`focused=` and `full-lane=` remain lane-specific evidence. They must name the system actually touched, its test package, and its data boundary. A-short preflight, Python, provider, or full-lane commands are not defaults for US-short, and the reverse is also prohibited.

## Full-lane disposition

`full-lane=` is mandatory evidence of the decision, not an unconditional full-regression tax. When AGENTS rule 3 triggers, record the one matching lane run and its result. When it does not trigger, record `not_triggered: AGENTS rule 3; reason=<specific change surface>`.

## Boundary and verification

This clarification changes only process documentation and guard anchors. It changes no A-short/US-short business rule, provider authorization, live weekly operation, account/order path, or ship gate. `git diff --check` is clean; the targeted doc-governance test remains pending because the required pinned project Python is unavailable in this environment.
