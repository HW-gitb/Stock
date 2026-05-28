# Provider Evidence And Drift Monitor Contract

**Status**: Phase 7b-1 schema-first baseline plus Phase 7b-2 first P1 public-source evidence snapshot. Broader provider capability evidence population is still in progress.

**Owner role**: provider capability evidence population and data quality / provider drift monitoring contract after the Phase 7a provider-priority, feasibility, and evidence-report contracts. This document defines the evidence shape and routes reviewed evidence snapshots.

This document does not select providers, fetch data, create adapters, implement DataHub tables, change strategy rules, relax ship gates, or authorize broker / OS automation.

## 1. Purpose

Phase 7a established the lane verdicts, provider evidence queue, provisional benchmarks, feasibility controls, and evidence report shape. Phase 7b-1 converts the provider evidence queue into a machine-checkable provider evidence and drift-monitor artifact so later provider population, DataHub, or runner work cannot rely on guessed provider readiness. Phase 7b-2 uses that contract to populate actual provider capability evidence from reviewed provider documentation, fields, PIT, coverage, cost, fallback, and stability evidence.

The machine-checkable owner is `schemas/provider_evidence_drift_monitor.schema.json` v1.1.0. The example is `schemas/examples/provider_evidence_drift_monitor.example.json`. The first evidence-population artifact is `docs/provider_evidence_p1_us_public_sources_20260528.json`.

## 2. Scope Locks

The schema scope fixes:

- `phase = 7b`,
- `purpose = provider_evidence_drift_monitor_contract`,
- `contract_status = schema_first_contract_only` or `provider_evidence_population_snapshot`,
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

Records with `source_basis = reviewed_provider_evidence` must carry `evidence_source_refs` with reviewed source URL, source type, review date, and evidence note.

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

The reviewed contract baseline is complete when:

1. `schemas/provider_evidence_drift_monitor.schema.json` validates as Draft 7.
2. `schemas/examples/provider_evidence_drift_monitor.example.json` validates against the schema.
3. Regression tests prove scope locks, P1-P4 queue coverage, provider evidence no-default locks, reviewed-evidence source refs, drift dimensions and actions, example validation, provider-selection rejection, latest-only / silent-default rejection, and P4 helper-surface containment.
4. Evidence-population snapshots validate against the schema and preserve the no-selection / no-fetch / no-implementation locks.

## 7. First P1 Public-Source Snapshot

`docs/provider_evidence_p1_us_public_sources_20260528.json` is the first Phase 7b-2 evidence-population artifact. It reviews official public documentation for:

- SEC EDGAR submissions and XBRL data APIs,
- SEC current CIK / ticker / exchange static files,
- Nasdaq Trader current-day symbol directory sources,
- MSCI / S&P GICS methodology.

Verdict: P1 moves from `unknown` to `partial`, but remains implementation-blocked. SEC EDGAR is useful for filing metadata and XBRL source review; SEC / Nasdaq ticker files are current-reference aids, not historical survivorship-safe security masters; GICS methodology is not issuer-level PIT membership history. The artifact does not cover US adjusted prices, delistings, full corporate actions, benchmark returns, paid-provider licensing, sandbox tokens, or DataHub implementation.

## 8. Next Use

Phase 7b-2 should continue populating provider capability evidence in P1 before moving to P2-P4. Phase 7c may consume the reviewed Phase 7b-2 evidence when designing DataHub shared-layer schemas, report contracts, and reproducibility plumbing. That must be a separate reviewed implementation slice.

This Phase 7b baseline does not fetch provider data, implement adapters, create DataHub tables, or modify runners.
