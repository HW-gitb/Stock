# Provider Evidence And Drift Monitor Contract

**Status**: Phase 7b-1 schema-first baseline. Phase 7b-2 provider capability evidence population is still pending.

**Owner role**: provider capability evidence population and data quality / provider drift monitoring contract after the Phase 7a provider-priority, feasibility, and evidence-report contracts. This document defines the evidence shape; it does not itself populate real provider capability evidence.

This document routes the Phase 7b-1 contract only. It does not select providers, fetch data, create adapters, implement DataHub tables, change strategy rules, relax ship gates, or authorize broker / OS automation.

## 1. Purpose

Phase 7a established the lane verdicts, provider evidence queue, provisional benchmarks, feasibility controls, and evidence report shape. Phase 7b-1 converts the provider evidence queue into a machine-checkable provider evidence and drift-monitor artifact so later provider population, DataHub, or runner work cannot rely on guessed provider readiness. Phase 7b-2 still needs to populate actual provider capability evidence from reviewed provider documentation, fields, PIT, coverage, cost, fallback, and stability evidence.

The machine-checkable owner is `schemas/provider_evidence_drift_monitor.schema.json` v1.0.0. The example is `schemas/examples/provider_evidence_drift_monitor.example.json`.

## 2. Scope Locks

The schema scope fixes:

- `phase = 7b`,
- `purpose = provider_evidence_drift_monitor_contract`,
- `contract_status = schema_first_contract_only`,
- `provider_selection_allowed = false`,
- `data_fetch_allowed = false`,
- `provider_adapter_allowed = false`,
- `datahub_table_implementation_allowed = false`,
- `strategy_rule_change_allowed = false`,
- `broker_or_order_automation_allowed = false`,
- `manual_order_only = true`,
- `ship_gate_relaxed = false`,
- `production_ready_claim_allowed = false`.

These locks mean the artifact can record evidence status and monitoring requirements, but it cannot approve provider selection or implementation.

## 3. Required Evidence Queue

The artifact must carry all four priorities from `docs/provider_priority_benchmark_contract.md`:

| Priority | Family |
|---|---|
| `P1` | US fundamentals, filings, corporate actions, security master, GICS, and US benchmark readiness |
| `P2` | A-share fundamentals, announcements, restatements, SW history, and A-long benchmark / industry readiness |
| `P3` | Burst full-data event, flow, options, borrow / short-interest, pre-market / after-hours, and manual evidence workflow |
| `P4` | Already-proven A-share EOD, limit, calendar, CSI benchmark, and candidate-universe helper surfaces |

P4 ready helper evidence must be recorded, but it does not authorize broad A-share DataHub implementation ahead of P1-P3 review.

## 4. Provider Evidence Records

Each provider evidence record must state:

- priority and affected lanes,
- market and data class,
- field family,
- provider candidate or placeholder ID,
- source basis,
- capability status and production-use status,
- PIT and observed-date support,
- survivorship / security-master support,
- missing required evidence,
- lineage fields required before implementation can rely on the data,
- drift-monitoring requirement,
- explicit `silent_default_allowed = false`,
- explicit `latest_only_historical_evidence_allowed = false`,
- explicit `provider_selection_made = false`,
- explicit `data_fetch_performed = false`.

The schema intentionally keeps these dimensions separate. A field may be partially supported but still blocked for production use.

## 5. Drift Monitor

The drift monitor must cover at least:

- coverage count,
- freshness / latency,
- schema or field semantics,
- PIT / as-of integrity,
- survivorship / security master,
- corporate action and revision behavior,
- calendar / timezone alignment,
- authorization / cost / quota risk,
- provider incidents,
- outlier and revision rate.

The action set must include `warn`, `block_production_use`, `manual_review`, `fallback_path_review`, `rerun_provider_evidence`, `record_incident`, and `freeze_latest_only_claims`.

Missing benchmark sessions must not be zero-filled, latest-only historical backfill must remain forbidden, and silently changed provider semantics must be logged.

## 6. Validation Contract

The reviewed baseline is complete when:

1. `schemas/provider_evidence_drift_monitor.schema.json` validates as Draft 7.
2. `schemas/examples/provider_evidence_drift_monitor.example.json` validates against the schema.
3. Regression tests prove scope locks, P1-P4 queue coverage, provider evidence no-default locks, drift dimensions and actions, example validation, provider-selection rejection, latest-only / silent-default rejection, and P4 helper-surface containment.
4. Routing docs point Phase 7b-1 contract work here and keep Phase 7b-2 evidence population pending.
5. `docs/CURRENT.md` moves the next P0 to Phase 7b-2 provider capability evidence population.

## 7. Next Use

Phase 7b-2 should consume this contract when populating provider capability evidence. Phase 7c may consume the reviewed Phase 7b-2 evidence when designing DataHub shared-layer schemas, report contracts, and reproducibility plumbing. That must be a separate reviewed implementation slice.

This Phase 7b-1 baseline does not fetch provider data, implement adapters, create DataHub tables, or modify runners.
