# DataHub Design - Phase 2.6 And Phase 7 Guardrail

## Purpose

This document fixes the future data architecture direction for the stock analysis system.

The system will eventually support four products:

- A-share short-term
- US short-term
- A-share long-term
- US long-term

The shared engine must not depend on ad hoc CSV fields, scattered Tushare calls, or market-specific naming conventions. The long-term direction is a reusable DataHub with raw, standardized, and factor layers.

This is a roadmap constraint, not an immediate rewrite mandate.

## Current Decision

The DataHub idea is accepted, but implementation is staged:

- **Phase 2.6**: document the DataHub design and strengthen data lineage in existing reports.
- **Phase 3-6**: continue building the A-share short-term analyzer/state/Skill/closed-loop workflow. Do not split `A-EGS/egs_main.py` into a full DataHub during this period.
- **Phase 6e**: establish `docs/provider_data_requirements_audit.md` so Phase 7 starts from four-system data requirements instead of A-short-only convenience.
- **Phase 7a**: perform schema-first alpha-validation work before broad engine modularization. The current action guide is `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`; the next route is the alpha plausibility audit schema and first audit in `docs/alpha_plausibility_audit.md`.
- **Phase 7b-1**: establish provider capability evidence and data quality / provider drift monitoring contract in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`; this does not populate real provider evidence.
- **Phase 7b-2**: populate provider capability evidence in the P1-P4 order. The current P1 snapshots run through `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`; the P1 readiness matrix is `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`; the P1 access / sample-validation plan is `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json`; the narrow 2026-06-02 sample approval is `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json`. DataHub still cannot rely on P1 fields until that small-sample validation is executed, summarized, and reviewed.
- **Phase 7c**: define the DataHub shared layer, report contracts, reproducibility plumbing, local resource budget, and data quality monitor before broad implementation. Current schema-first baselines are the local job-spec enforcement helper plus `schemas/datahub_shared_layer_contract.schema.json`, `schemas/datahub_report_contract.schema.json`, and `schemas/datahub_reproducibility_manifest.schema.json`; implementation is still separate.
- **Phase 7 implementation**: broad DataHub / engine modularization starts only after provider capability, alpha plausibility, evidence-capital, and early report contracts are reviewed.

Reason: `A-EGS/egs_main.py` v7.10 and `runners/backtest_rank.py` have just passed a 24-period production rank-backtest engineering validation. Large structural rewrites now would add breakage risk before the A-share short-term loop is closed.

## Local Resource Boundary

Four subsystems are real requirements, but the local default must not be "run every market and lane at once." Phase 7c DataHub / runner work must consume `schemas/datahub_local_resource_budget.schema.json`, `docs/datahub_local_resource_budget_contract_20260602.json`, and `schemas/datahub_job_spec.schema.json` before any implementation slice that could create broad refreshes or multi-lane jobs.

Default local operation is `single_slice_incremental`:

- one market by default,
- one lane by default,
- one bounded `as_of_date` or date window by default,
- lazy reads of only the required fields / artifacts,
- incremental cache reuse instead of default full refresh,
- checkpoint / resume for longer reviewed jobs.

The following are not default behavior and require a separate explicit user approval plus reviewed job spec: all-market runs, all-lane runs, full-market refresh, full-history rebuild, high-output batch generation, or parallel jobs that exceed the reviewed local budget profile.

The job-spec contract requires future jobs to declare budget profile, market, lane, as-of/date window, provider family, artifact type, resource estimates, lazy / incremental / checkpoint / abort policy, data boundaries, and approval gates before any executable job is reviewed.

The resource-budget and job-spec contracts now have a code-level enforcement helper at `engine/datahub/job_spec_contract.py`. Future executable DataHub / runner / report jobs must call `validate_datahub_job_spec_contract` or `validate_datahub_job_spec_file` before execution. The helper validates the job spec, the resource-budget artifact, budget-profile consistency, market/lane consistency, bounded as-of / date-window invariants, review gates, heavy-run approval, and no-scope-creep constraints.

This enforcement helper does not fetch provider data, select a provider, implement adapters, create DataHub tables, change production runners, authorize provider access, relax ship gates, or prove the user's machine has enough capacity. It closes the current code-level enforcement gap for local resource budgets; every future executable Phase 7c job still needs a reviewed job spec and must pass this helper before running.

## Phase 7c Schema-First Contracts

`schemas/datahub_shared_layer_contract.schema.json` and `docs/datahub_shared_layer_contract_20260603.json` define the future ODS / DWD / DWS / factor layer boundaries. Plain result: the project now has a checklist for what each layer may consume and output, what metadata must exist, and which PIT / lineage / no-silent-default rules must be visible before implementation.

`schemas/datahub_report_contract.schema.json` and `docs/datahub_report_contract_20260603.json` define future report families: screening report, evidence report, provider evidence summary, and data quality report. Plain result: future reports must say the useful conclusion clearly, but they must not hide provider gaps, raw-data limits, or ship-gate restrictions.

`schemas/datahub_reproducibility_manifest.schema.json` and `docs/datahub_reproducibility_manifest_contract_20260603.json` define the manifest that future executable jobs must be able to produce: job spec ref, validation result, code / schema refs, input hashes, output refs, environment, dependency snapshot, cache / checkpoint refs, and limitations.

These contracts do not fetch data, call providers, create DataHub tables, implement a manifest writer, change runners, authorize production runner consumption, or provide ship-gate evidence. Future implementation must still be a separate reviewed slice with a job spec that passes `engine/datahub/job_spec_contract.py`.

## Layer Design

### ODS: Raw Data Layer

Goal: persist source-level raw data without semantic edits.

Rules:

- Keep original source fields whenever feasible.
- Record provider, API name, request parameters, fetch time, and response date range.
- Do not rename, rescale, winsorize, or infer values in ODS.
- Treat ODS as audit evidence.

Examples:

- `ods_tushare_daily`
- `ods_tushare_daily_basic`
- `ods_tushare_moneyflow`
- `ods_tushare_fina_indicator`
- `ods_tushare_stock_basic`
- `ods_tushare_trade_cal`
- `ods_tushare_stk_limit`
- `ods_tushare_index_daily`
- `ods_tushare_index_member`

### DWD: Standardized Detail Layer

Goal: normalize fields and units into one project-wide contract.

Rules:

- Use one stock-code convention per market.
- Use one date convention: `YYYYMMDD` for trade-date keys unless a datetime is required.
- Add explicit unit descriptions for all numeric financial and market fields.
- Preserve as-of semantics and PIT filters.
- Never mix daily, weekly, and minute data in one table without explicit frequency fields.

Examples:

- `dwd_a_stock_daily`
- `dwd_a_stock_daily_basic`
- `dwd_a_stock_moneyflow`
- `dwd_a_financial_indicator`
- `dwd_a_industry_member`
- `dwd_a_limit_price`

### DWS / Factor Layer

Goal: store reusable computed features.

Rules:

- Factors must be reusable by screening, backtest, analyzer, visualization, and future AI features.
- Factor definitions must be versioned.
- Factor calculation must record input layer, lookback window, as-of date, and whether the value is PIT-safe.

Examples:

- `factor_momentum_20d`
- `factor_drawdown_20d`
- `factor_turnover_rate`
- `factor_big_order_ratio`
- `factor_esp_raw`
- `factor_low_base_growth`
- `factor_industry_momentum`
- `factor_limit_up_unbuyable`

## As-Of And PIT Rules

All historical backtests must separate three ideas:

- **trade_date**: the market date being simulated.
- **as_of_date**: the information cutoff.
- **fetch_date**: the real-world date the data was downloaded.

Required rules:

- Financial data must use `ann_date <= as_of_date`.
- Industry membership must use the member interval active at `as_of_date` when available.
- L3 concept data must use PIT snapshots when available; otherwise use neutralized mode for serious historical backtests.
- Latest revised financial data from Tushare must be explicitly recorded as a limitation when original disclosure revisions are unavailable.

## Phase 2.6 Scope

Phase 2.6 is a low-risk preparation phase. It may add documentation and metadata, but it must not rewrite the screening engine.

Completion criteria:

- `docs/datahub_design.md` exists and documents ODS / DWD / DWS / factor layers.
- `AGENTS.md` names Phase 2.6 and Phase 7 DataHub responsibilities.
- Backtest reports record enough lineage to identify:
  - data provider
  - API families used
  - date range
  - L3 mode
  - PIT limitations
  - forward-return adjustment mode
  - benchmark sources
- No production screening behavior changes are introduced solely for Phase 2.6.

Recommended future additions:

- Add a `data_lineage` object to `rank_backtest_report.json`.
- Add a `data_lineage` object to future `deterministic_report.json`.
- Add a small `docs/data_dictionary.md` once stable DWD fields exist.

## Phase 7 Scope

Phase 7 is the formal provider capability, alpha-validation, and DataHub implementation phase.

Phase 7 starts only after the A-share short-term sample loop is stable enough to avoid losing the validated behavior of `A-EGS/egs_main.py`, and after `docs/provider_data_requirements_audit.md` has a reviewed baseline. Broad DataHub implementation should not start until the Phase 7a alpha plausibility route has clarified lane priority and provider blockers.

Completion criteria:

- Provider capability / field catalog contract exists for the data classes required by A-short, US-short, A-long, US-long, and burst lanes. Current baseline: `schemas/provider_capability_catalog.schema.json` v1.0.0.
- Provider evidence / drift-monitor contract exists for P1-P4 provider evidence records, readiness rollup, and drift-monitor dimensions. Current baseline: `schemas/provider_evidence_drift_monitor.schema.json` v1.1.0. Phase 7b-2 now has six P1 evidence snapshots plus `schemas/provider_p1_readiness_review.schema.json` / `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`, `schemas/provider_p1_access_decision_plan.schema.json` / `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json`, and the narrow `schemas/provider_p1_sample_validation_access_approval.schema.json` / `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json`; P1 remains partial / blocked until the approved small sample is executed, summarized, and reviewed.
- Local resource budget and job-spec contracts exist before DataHub / runner implementation creates broad refreshes or multi-lane jobs. Current baseline: `schemas/datahub_local_resource_budget.schema.json` v1.0.0, `docs/datahub_local_resource_budget_contract_20260602.json`, and `schemas/datahub_job_spec.schema.json` v1.0.0 with `schemas/examples/datahub_job_spec.example.json`; `engine/datahub/job_spec_contract.py` enforces these contracts for future executable jobs. This still does not authorize provider calls, DataHub table implementation, runner changes, production consumption, Phase 7c broad implementation, or ship-gate claims.
- Shared-layer, report, and reproducibility manifest contracts exist before DataHub implementation creates reusable tables, reports, or manifest writers. Current baseline: `schemas/datahub_shared_layer_contract.schema.json`, `schemas/datahub_report_contract.schema.json`, and `schemas/datahub_reproducibility_manifest.schema.json`; they are schema-first contracts only and do not authorize implementation.
- Alpha plausibility audit contract exists and has reviewed lane-level verdicts before large implementation investments.
- Evidence capital policy is reflected in aggregate/report schemas so paper evidence cannot be mistaken for live-normalized ship-gate evidence.
- Data quality / provider drift monitoring exists before provider-backed evidence is treated as stable. It must cover coverage, freshness, schema drift, outliers, revision rate, provider incidents, and silently changed provider semantics.
- Reproducibility plumbing exists for decision packets before live-normalized or production-like claims depend on DataHub outputs.
- `A-EGS/egs_main.py` no longer performs scattered direct provider calls for core reusable data.
- Provider access is centralized under `engine/data/`.
- Standardized data contracts exist for daily history, daily basic, moneyflow, financials, stock basic, industry membership, limit prices, and benchmark indices.
- Reusable factor calculations move under `engine/factors/`.
- Rank backtest and production screening consume the same standardized data/factor layer.
- Any change in output behavior is measured against the last valid Phase 2 findings.

## Guardrails

- Do not start a broad DataHub rewrite during Phase 3-6 unless a concrete bug makes the existing path impossible to maintain.
- Do not duplicate four independent data pipelines for the four systems.
- Do not change field units or naming silently.
- Do not let backtest and production read different definitions for the same factor.
- Do not treat DataHub work as a strategy-performance fix. It improves reproducibility and reuse; it does not by itself prove alpha.
- Do not treat provider readiness as permanent. Provider drift, API schema changes, delayed fields, revised fundamentals, and classification changes must be logged and reviewable.
- Do not make all-system, all-market, all-lane, or full-history refresh the local default. Use reviewed slice / budget profiles first.
