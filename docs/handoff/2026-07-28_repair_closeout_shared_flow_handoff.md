# Repair-closeout shared flow / lane-specific verification handoff

## Scope and decision

The repair-closeout matrix is one shared execution/repair process for A-short and US-short. `matrix=`, `register=`, and `handoff=` record the common closure responsibility; the same `SESSION_LOG` adoption marker and doc-governance guard enforce future repair entries.

`focused=` and `full-lane=` remain lane-specific evidence. They must name the system actually touched, its test package, and its data boundary. A-short preflight, Python, provider, or full-lane commands are not defaults for US-short, and the reverse is also prohibited.

## Full-lane disposition

`full-lane=` is mandatory evidence of the decision, not an unconditional full-regression tax. When AGENTS rule 3 triggers, record the one matching lane run and its result. When it does not trigger, record `not_triggered: AGENTS rule 3; reason=<specific change surface>`.

## Boundary and verification

This clarification changes only process documentation and guard anchors. It changes no A-short/US-short business rule, provider authorization, live weekly operation, account/order path, or ship gate.

## 2026-07-28 append: full-pack external dependency preflight (lane-scoped repair)

The first global preflight was rejected: it made A-share-only provider absence block US-short focused work. The repaired `external_test_dependency_error(lane)` selects `REQUIRED_TEST_MODULES_BY_LANE`; `akshare` and `tushare` are a_short-only, while shared modules such as `jsonschema` remain in both sets. The check now exists only in `full_pack_ledger` `run`/`check`, before cache reuse, prepare, or unittest spawn; `bounded_unittest.run_unittest` remains a generic focused runner.

The closure pack has named controls for: A-share provider absence blocks a_short full but not us_short full/focused; shared `jsonschema` absence blocks both full lanes; and hollowing lane routing makes the named a-share/us-short isolation test red. This is tooling only; no provider call, market-system behavior, or full lane run is triggered.
