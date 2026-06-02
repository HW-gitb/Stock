# Docs

This directory contains project documentation, phase handoffs, and design policies. Runtime contracts live under `schemas/`; system reference specs live under `skills/*/reference/`.

## Document Routing

Use this routing table instead of guessing which file to read.

| Need | Read |
|---|---|
| Highest-level project rules, fixed decisions, command aliases, required reading order | `AGENTS.md` |
| Current state and next implementation step | `docs/CURRENT.md` |
| Durable open-risk queue for data / PIT / schema / execution / security findings | `docs/system_risk_register.md` |
| Latest cross-LLM reasoning, review verdicts, rejected alternatives, pending Optional disposition | `docs/SESSION_LOG.md` top 1-3 entries |
| Review workflow and exact short-command expansions | `docs/AI_REVIEW_PROTOCOL.md` |
| Current Phase 7a+ highest action guide: alpha reality guardrails, accepted business gaps, execution roadmap | `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` |
| Research-only preregistration, preflight, evidence-report, and test-budget ledger artifacts | `research/README.md`, `schemas/research_preregistration.schema.json`, `schemas/research_preflight_result.schema.json`, `schemas/program_test_budget_ledger.schema.json`, `schemas/evidence_report.schema.json`, `research/preregistrations/a_share_minimal_data_burst_20260531.json`, `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`, `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json`, `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json`, `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json`, `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json`, `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/signal_events.csv`, `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/monthly_stats.csv`, `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` |
| Strategy architecture: short-term lanes, burst lane, long-term alpha systems, research, coordinator | `docs/strategy_design_synthesis.md` |
| Alpha plausibility, lane objective, portfolio-level continue / redesign / risk-filter decisions | `docs/alpha_plausibility_audit.md` |
| Phase 7a-1 alpha plausibility audit artifact schema contract | `schemas/alpha_plausibility_audit.schema.json` |
| Phase 7a-1 lightweight provider status snapshot for the first audit | `docs/phase7a_provider_status_snapshot.json` |
| Phase 7a-1 first formal alpha plausibility audit artifact | `docs/phase7a_alpha_plausibility_audit.json` |
| Phase 7a-3 provider evidence priority and provisional benchmark contract | `docs/provider_priority_benchmark_contract.md` |
| Phase 7a-4 burst promotion, evidence capital, liquidity / ADV, slippage / borrow / limit-risk, and circuit-breaker controls | `docs/evidence_feasibility_controls.md`, `schemas/evidence_feasibility_controls.schema.json` |
| Phase 7a-5 evidence report schema: immutable decision packet, cost-adjusted return, cash drag, manual override, minimal reconciliation, thesis outcome log, research experiment log | `docs/evidence_report_schema_contract.md`, `schemas/evidence_report.schema.json` |
| Phase 7b-1 provider evidence / drift monitor schema-first contract; Phase 7b-2 P1 provider evidence snapshots, readiness matrix, access / sample-validation plan, user-approved narrow sample-validation boundary, and US EGS data-source direction | `docs/provider_evidence_drift_monitor.md`, `schemas/provider_evidence_drift_monitor.schema.json`, `docs/provider_evidence_p1_us_public_sources_20260528.json`, `docs/provider_evidence_p1_us_market_data_candidates_20260528.json`, `docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json`, `docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json`, `docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json`, `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`, `schemas/provider_p1_readiness_review.schema.json`, `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`, `schemas/provider_p1_access_decision_plan.schema.json`, `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json`, `schemas/provider_p1_sample_validation_access_approval.schema.json`, `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json` |
| Paper vs live-normalized evidence and capital-governance-safe ship-gate evidence policy; reviewed forward-live evidence artifact contract | `docs/evidence_capital_policy.md`, `schemas/forward_live_evidence.schema.json` |
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
