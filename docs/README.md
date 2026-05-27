# Docs

This directory contains project documentation, phase handoffs, and design policies. Runtime contracts live under `schemas/`; system reference specs live under `skills/*/reference/`.

## Document Routing

Use this routing table instead of guessing which file to read.

| Need | Read |
|---|---|
| Highest-level project rules, fixed decisions, command aliases, required reading order | `AGENTS.md` |
| Current state and next implementation step | `docs/CURRENT.md` |
| Latest cross-LLM reasoning, review verdicts, rejected alternatives, pending Optional disposition | `docs/SESSION_LOG.md` top 1-3 entries |
| Review workflow and exact short-command expansions | `docs/AI_REVIEW_PROTOCOL.md` |
| Strategy architecture: short-term lanes, burst lane, long-term alpha systems, research, coordinator | `docs/strategy_design_synthesis.md` |
| A/US short-term burst lane detailed baseline | `docs/burst_lane_spec.md` |
| US-short normalized production-facing spec | `docs/us_short_spec.md` |
| Long alpha common spec and A/US long annex skeletons | `docs/long_alpha_spec.md` |
| Provider / data requirements audit before Phase 7 DataHub | `docs/provider_data_requirements_audit.md` |
| Phase 7 provider capability / field catalog schema contract | `schemas/provider_capability_catalog.schema.json` |
| Capital allocation and liquidity policy | `docs/portfolio_allocation_policy.md` |
| DataHub / provider / factor-layer guardrails | `docs/datahub_design.md` |
| Phase-level historical context and validation records | `docs/handoff/<phase>_handoff.md` files named in `AGENTS.md` |

## Maintenance Rules

- Keep `CURRENT.md` short. It is a snapshot, not a history file.
- Keep process reasoning in `SESSION_LOG.md`, newest entry first.
- Append to the current phase handoff by default; create a new handoff only for high-threshold events listed in `AGENTS.md`.
- Do not duplicate long policy text across files. Put the detailed policy in the owning document and route to it from `AGENTS.md` / `CURRENT.md`.
- For broad data-layer, provider, factor, or engine modularization work, read `docs/datahub_design.md` first. Full ODS/DWD/DWS implementation is Phase 7.
