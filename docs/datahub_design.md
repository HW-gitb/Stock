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
- **Phase 7b-2**: populate provider capability evidence in the P1-P4 order. The current P1 snapshots run through `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`; next produce a P1 readiness review matrix before DataHub can rely on the evidence.
- **Phase 7c**: define the DataHub shared layer, report contracts, reproducibility plumbing, and data quality monitor before broad implementation.
- **Phase 7 implementation**: broad DataHub / engine modularization starts only after provider capability, alpha plausibility, evidence-capital, and early report contracts are reviewed.

Reason: `A-EGS/egs_main.py` v7.10 and `runners/backtest_rank.py` have just passed a 24-period production rank-backtest engineering validation. Large structural rewrites now would add breakage risk before the A-share short-term loop is closed.

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
- Provider evidence / drift-monitor contract exists for P1-P4 provider evidence records, readiness rollup, and drift-monitor dimensions. Current baseline: `schemas/provider_evidence_drift_monitor.schema.json` v1.1.0. Phase 7b-2 now has six P1 evidence snapshots, but P1 remains partial / blocked and needs a readiness review matrix before DataHub implementation can rely on it.
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
