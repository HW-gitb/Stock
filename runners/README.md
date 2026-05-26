# Runners

Command entry points will live here after the shared engine exists.

Planned scripts:

- `screen.py`
- `analyze.py`
- `backtest_rank.py`
- `backtest_execution.py` (Phase 5 skeleton exists; full simulator pending)

Current Phase 1/2 entry remains `A-EGS/egs_main.py`.

Validation environment:

- Use the project/local Python that has the repo's data stack installed for
  schema-validating commands, for example:
  `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`.
- Install validation-only dependencies with:
  `python -m pip install -r requirements-dev.txt`.
- The Codex bundled Python runtime is acceptable for syntax checks and unit
  tests, but it may not include `jsonschema`; do not treat bundled runtime
  packages as the project's dependency source.

Existing helpers:

- `backtest_rank.py` — Phase 2 rank 回测入口
- `backtest_execution.py` - Phase 5 execution backtest runner; reads
  `analysis_input.json`, can validate/reference an existing `execution_price_data`
  JSON via `--price-data`, requires explicit `--portfolio-allocation` and
  `--cash-buffer-state` inputs for bucket-aware capital context, reads
  `presets/a_short.yaml` by default via `--preset-path`, validates
  `execution_report.json`, and writes CSV outputs under
  `result/a_short/backtest/execution/`. With `--price-data`, it runs the minimal
  daily-OHLC fill simulation; without `--price-data`, it keeps the skeleton skip
  behavior.
- `aggregate_execution_reports.py` - Phase 5 multi-period aggregation helper;
  reads schema-valid `execution_backtest_report` v1.2.0 files, aggregates
  monthly return / Sharpe / worst drawdown evidence, optionally computes
  benchmark-aware monthly alpha t-stat from a `YYYYMM -> return` JSON, and writes
  schema-valid `execution_aggregate_report` v1.0.0. It is ship-gate evidence
  only and does not rebuild a full continuous portfolio equity curve.
- `materialize_execution_price_data.py` - Phase 5 provider-boundary helper;
  converts a local OHLC CSV into a schema-valid `execution_price_data` JSON for
  `backtest_execution.py --price-data`. It does not fetch Tushare data or
  simulate fills.
- `materialize_execution_price_data_tushare.py` - Phase 5 provider-boundary
  helper; fetches Tushare `daily` / `adj_factor` / `stk_limit` / `trade_cal`
  and writes the same schema-valid `execution_price_data` JSON. It caches the
  provider payload under `result/a_short/backtest/cache/` and still does not
  simulate fills.
- `materialize_benchmark_monthly_returns_tushare.py` - Phase 6b benchmark
  evidence helper; fetches Tushare `index_daily` for CSI1000 / CSI300 and writes
  `YYYYMM -> return` JSON files for `aggregate_execution_reports.py`, plus
  metadata sidecars with provider/API/date-range lineage.
- `materialize_a_short_variant_tracking.py` - Phase 6b tracking-plan helper;
  consumes `schemas/a_short_variant_tracking.schema.json` via the canonical
  example template and writes a schema-valid A-short variant tracking plan under
  `result/a_short/backtest/variants/` by default. It does not compute evidence,
  promote variants, mutate EGS, or implement `burst_lane`.
- `diagnose_tier1_bad_signals.py` — Phase 3.2 Tier1 坏票特征诊断；只读现有 `rank_samples.csv` 和 generated full-rank CSV，不重跑 EGS
- `run_analysis_report.py` — Phase 4 单票 deterministic report runner；读取 `analysis_input.json`，调用 analyzer/state，输出 schema-validated JSON + Markdown 到 `result/a_short/<as_of>/reports/`
- `data_canary.py` — Phase 2.6 旁路跨源对账（Tushare vs akshare）
- `weekly_screening.ps1` — 周五一键脚本：依次跑 `egs_main.py` + `data_canary.py`；canary 失败不影响主流程退出码
