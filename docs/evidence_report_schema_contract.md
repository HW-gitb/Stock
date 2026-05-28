# Evidence Report Schema Contract

**Status**: Phase 7a-5 schema-first baseline.

**Owner role**: evidence report schema owner for immutable decision packets, cost-adjusted return, cash drag, manual override logging, minimal reconciliation, thesis outcome logs, and research experiment logs.

This document routes the reporting contract only. It does not select providers, fetch data, create adapters, implement DataHub tables, change strategy rules, relax ship gates, or authorize broker / OS automation.

## 1. Purpose

Phase 7a-1 through Phase 7a-4 defined lane verdicts, provider priority, provisional benchmark routing, and feasibility controls. Phase 7a-5 closes the evidence workflow shape by requiring every future evidence report to carry enough context to reproduce what was decided, how return was measured, and why a paper or research result cannot silently become live-normalized or full-size evidence.

The machine-checkable owner is `schemas/evidence_report.schema.json` v1.0.0. The example is `schemas/examples/evidence_report.example.json`.

## 2. Scope Locks

The schema scope fixes:

- `phase = 7a-5`,
- `purpose = evidence_report_schema_contract`,
- `contract_status = schema_first_contract_only`,
- `provider_selection_allowed = false`,
- `data_fetch_allowed = false`,
- `provider_adapter_allowed = false`,
- `datahub_table_implementation_allowed = false`,
- `strategy_rule_change_allowed = false`,
- `broker_or_order_automation_allowed = false`,
- `manual_order_only = true`,
- `ship_gate_relaxed = false`.

These locks are intentionally redundant with prior Phase 7a contracts. The evidence report contract is a report shape, not an implementation permission.

## 3. Required Sections

Every evidence report must include:

| Section | Why it exists |
|---|---|
| `immutable_decision_packet` | Captures input refs, schema refs, parameters, code version, provider status, benchmark set, hypothesis ref, and append-only immutability locks before outcomes are known. |
| `cost_adjusted_return` | Separates gross, net, benchmark, and net-excess return, with explicit cost components and missing-cost disclosure. |
| `cash_drag` | Records idle cash, deployed capital, normalization basis, cash drag, and missed-trade opportunity cost. |
| `manual_override_log` | Keeps user manual action differences visible without implying automation. |
| `minimal_reconciliation` | Records recommended versus actual position refs; `live_normalized` evidence requires actual-position reconciliation. |
| `thesis_outcome_log` | Gives long lanes an interim/final thesis outcome path with broken-thesis conditions. |
| `research_experiment_log` | Records isolated experiment lineage, seed, artifacts, and promotion locks so research cannot feed production directly. |

The schema requires all seven sections even when a section is `not_applicable`. That is deliberate: omission should not hide workflow gaps.

## 4. Evidence-Level Rules

Allowed evidence levels are:

- `paper`,
- `research_only`,
- `live_normalized`.

`paper` and `research_only` reports cannot set `ship_gate_claim.claim_status = claimed`. `live_normalized` reports must set `minimal_reconciliation.actual_position_reconciliation_available = true` and `minimal_reconciliation.reconciliation_status = live_reconciled`.

The report itself never authorizes full-size manual use. `ship_gate_claim.full_size_manual_use_authorized_by_this_report` is locked to `false`.

## 5. Prior Contract Consumption

Every report must link to:

- `docs/provider_priority_benchmark_contract.md`,
- `schemas/provider_capability_catalog.schema.json`,
- `docs/evidence_feasibility_controls.md`,
- `schemas/evidence_feasibility_controls.schema.json`.

The report schema also carries the Phase 7a-4 circuit-breaker action vocabulary: `warn`, `size_down`, `pause_new_entries`, `manual_review`, and `reactivation_cooldown`.

## 6. Research Boundary

Research reports must carry:

- hypothesis registration ref,
- dataset refs,
- parameter refs,
- random seed,
- reproducibility artifacts,
- result summary,
- promotion policy.

`research_experiment_log.production_promotion.no_direct_production_feed` is locked to `true`. Promotion into production still requires schema review, Claude review, and user approval.

## 7. Validation Contract

The reviewed baseline is complete when:

1. `schemas/evidence_report.schema.json` validates as Draft 7.
2. `schemas/examples/evidence_report.example.json` validates against the schema.
3. Regression tests prove scope locks, required seven-section coverage, prior contract links, decision-packet immutability, cost-component coverage, circuit-breaker action coverage, paper ship-gate rejection, live-normalized reconciliation requirement, and no direct research-to-production feed.
4. Routing docs point Phase 7a-5 work here.
5. `docs/CURRENT.md` moves the next P0 to Phase 7b provider evidence / drift monitor work.

## 8. Next Use

Phase 7b-1 provider evidence / drift-monitor contracts now live in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`. Phase 7b-2 has P1 public-source and market-data-candidate snapshots in `docs/provider_evidence_p1_us_public_sources_20260528.json` and `docs/provider_evidence_p1_us_market_data_candidates_20260528.json`, but P1 remains partial / blocked and provider capability evidence population must continue before DataHub or runner output contracts rely on it.

Later runner or DataHub output contracts may consume `schemas/evidence_report.schema.json`, but that must be a separate reviewed implementation slice. This Phase 7a-5 baseline does not modify runners or generate production reports.
