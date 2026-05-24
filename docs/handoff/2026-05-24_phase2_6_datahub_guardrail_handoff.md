# Phase 2.6 DataHub Guardrail Handoff

Date: 2026-05-24

## Purpose

This handoff records the decision to accept the DataHub / data middle-platform direction while preventing premature rewrites of the current A-share short-term pipeline.

## Files Changed

- Added `docs/datahub_design.md`
- Updated `AGENTS.md`
- Updated `docs/README.md`

## Decision

The DataHub direction is accepted as a staged roadmap item:

- Phase 2.6: DataHub design and data-lineage hardening.
- Phase 3-6: continue A-share short-term analyzer/state/Skill/execution closed-loop work; do not broadly refactor `A-EGS/egs_main.py`.
- Phase 7: formal DataHub and engine modularization before US-short expansion.

## Phase 2.6 Scope

Allowed:

- Maintain `docs/datahub_design.md`.
- Add report lineage metadata such as provider, API families, date ranges, L3 mode, PIT limits, adjustment mode, and benchmark sources.
- Identify data contract gaps.

Not allowed:

- Large ODS/DWD/DWS implementation.
- Moving `A-EGS/egs_main.py` into `engine/`.
- Changing production screening behavior purely for DataHub architecture work.

## Phase 7 Scope

Phase 7 implements:

- ODS raw layer.
- DWD standardized detail layer.
- DWS/factor layer.
- Shared provider access under `engine/data/`.
- Reusable factors under `engine/factors/`.
- Same data/factor definitions for production screening and backtests.

## Reason

`A-EGS/egs_main.py` v7.10 and `runners/backtest_rank.py` have just completed a 24-period production rank-backtest engineering validation. A broad data-layer rewrite now would increase breakage risk before Phase 3-6 closes the A-share short-term loop.

## Next Action

Continue to Phase 3 minimal analyzer/state. If touching report schemas during Phase 3, consider adding a `data_lineage` object, but keep it as metadata only.

