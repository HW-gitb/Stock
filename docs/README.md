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
| Current Phase 7a+ highest action guide: alpha reality guardrails, accepted business gaps, execution roadmap | `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` |
| Strategy architecture: short-term lanes, burst lane, long-term alpha systems, research, coordinator | `docs/strategy_design_synthesis.md` |
| Alpha plausibility, lane objective, portfolio-level continue / redesign / risk-filter decisions | `docs/alpha_plausibility_audit.md` |
| Paper vs live-normalized evidence and capital-governance-safe ship-gate evidence policy | `docs/evidence_capital_policy.md` |
| A/US short-term burst lane detailed baseline | `docs/burst_lane_spec.md` |
| US-short normalized production-facing spec | `docs/us_short_spec.md` |
| Long alpha common spec and A/US long annex skeletons | `docs/long_alpha_spec.md` |
| Provider / data requirements audit before Phase 7 DataHub | `docs/provider_data_requirements_audit.md` |
| Phase 7 provider capability / field catalog schema contract | `schemas/provider_capability_catalog.schema.json` |
| Capital allocation and liquidity policy | `docs/portfolio_allocation_policy.md` |
| DataHub / provider / factor-layer guardrails | `docs/datahub_design.md` |
| Phase-level historical context and validation records | `docs/handoff/README.md`, then the specific handoff named there / in `AGENTS.md` |
| Historical source material not on the active reading path | `docs/archive/README.md` |

## Maintenance Rules

- Keep `CURRENT.md` short. It is a snapshot, not a history file.
- Keep process reasoning in `SESSION_LOG.md`, newest entry first.
- Append to the current phase handoff by default; create a new handoff only for high-threshold events listed in `AGENTS.md`.
- Do not duplicate long policy text across files. Put the detailed policy in the owning document and route to it from `AGENTS.md` / `CURRENT.md`.
- For broad data-layer, provider, factor, or engine modularization work, read `docs/datahub_design.md` first. Full ODS/DWD/DWS implementation is Phase 7.

## Documentation Slimming Policy

1. Keep core owner docs. `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/AI_REVIEW_PROTOCOL.md`, `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`, strategy / lane specs, provider docs, capital policy, and DataHub guardrails currently have distinct owner roles and should not be deleted for size reasons.
2. `docs/CURRENT.md` is a short snapshot. It should not carry long delta history, full file indexes, or full handoff lists. Move those to owner docs, handoffs, or `docs/SESSION_LOG.md`.
3. `docs/SESSION_LOG.md` remains reverse-chronological and single-file for active work. When it spans more than 30 days or becomes a startup burden, archive older entries under `docs/archive/session_log/` while preserving the newest active entries and a pointer to the archive.
4. Handoffs are historical records. Use `docs/handoff/README.md` as the index; do not merge or rewrite old handoffs during ordinary cleanup.
5. `docs/archive/` is historical source material. Archived `.docx` files are not active execution or strategy authority; do not delete them without explicit user approval.
6. Phase 7a dual documents already passed R1 repair and now implement owner boundary lock. Future drift prevention is to preserve the "must not be duplicated here" wording in `docs/alpha_plausibility_audit.md` and keep detailed mandatory field inventory in `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`.
