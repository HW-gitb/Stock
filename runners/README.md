# Runners

Command entry points will live here after the shared engine exists.

Planned scripts:

- `screen.py`
- `analyze.py`
- `backtest_rank.py`
- `backtest_execution.py` (Phase 5 skeleton exists; full simulator pending)

Current Phase 1/2 entry remains `A-EGS/egs_main.py`. Direct historical
`--as-of` runs must use `--l3-mode pit` / `neutralize`, or explicitly declare
`--allow-historical-live-l3` for non-evidence live-concept smoke runs. The
engine also rejects non-empty daily payloads that are too incomplete to support
safe suspend inference instead of treating missing rows as suspended stocks.
Suspend coverage observations are written to
`logs/suspend_daily_coverage_<as_of>.json` and mirrored into schema-validated
`data_health` v1.2.0 `metrics.suspend_daily_coverage`; cached observations are
explicitly marked as cache hits, not fresh provider coverage.

Validation environment:

- Use the project/local Python that has the repo's data stack installed for
  schema-validating commands, for example:
  `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`.
- Install mandatory runtime validation dependencies with:
  `python -m pip install -r requirements.txt`.
- Install development / test dependencies with:
  `python -m pip install -r requirements-dev.txt`.
- The Codex bundled Python runtime is acceptable for syntax checks and unit
  tests only after `requirements.txt` is installed there; do not treat bundled
  runtime packages as the project's dependency source.

Existing helpers:

- `backtest_rank.py` — Phase 2 rank 回测入口；smoke-mode historical `today` L3 generation explicitly passes `--allow-historical-live-l3`, while production defaults to L3 neutralization.
- `backtest_execution.py` - Phase 5 execution backtest runner; reads
  `analysis_input.json`, can validate/reference an existing `execution_price_data`
  JSON via `--price-data`, requires explicit `--portfolio-allocation` and
  `--cash-buffer-state` inputs for bucket-aware capital context, reads
  `presets/a_short.yaml` by default via `--preset-path`, validates
  `execution_report.json`, and writes CSV outputs under
  `result/a_short/backtest/execution/`. With `--price-data`, it runs the minimal
  daily-OHLC fill simulation; without `--price-data`, it keeps the skeleton skip
  behavior. It rejects cash-state bucket capital above the policy ceiling
  (`market_capital * bucket_ceiling_pct`) before sizing can use it.
- `aggregate_execution_reports.py` - Phase 5 multi-period aggregation helper;
  reads schema-valid `execution_backtest_report` v1.2.0 files, aggregates
  monthly return / Sharpe / worst drawdown evidence, optionally computes
  benchmark-aware monthly alpha t-stat from a `YYYYMM -> return` JSON, and writes
  schema-valid `execution_aggregate_report` v1.1.4. Zero-trade reports with
  null `total_return` are excluded from return statistics rather than counted
  as 0.0% months. Full-size permission remains blocked until execution reports
  provide capacity/concurrency-adjusted returns; production-mode inputs,
  `schemas/forward_live_evidence.schema.json`-valid reviewed forward-live
  evidence refs that match aggregate capital context and source-window coverage,
  and at least the required monthly observation count for alpha / Sharpe are
  necessary but not
  sufficient. Smoke aggregates and bare
  `--forward-live-months` values remain diagnostic. It is ship-gate evidence
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
- `refresh_forward_daily_benchmark_open_tushare.py` - SR-DATA-003 benchmark-only
  cache helper; reads the existing shared `forward_daily.pkl` date range, fetches
  only CSI300 / CSI1000 `index_daily` `trade_date/open/close`, and patches the
  cache benchmark frames without refreshing stock daily, adj_factor, stk_limit,
  or trade_cal payloads.
- `audit_candidate_universe_overlap_tushare.py` - Phase 6b benchmark-policy
  audit helper; reads one captured `analysis_input.json`, fetches Tushare
  `index_weight` membership for CSI1000 / CSI300, and writes a schema-valid
  candidate-universe overlap audit under the ignored forward aggregate output
  area. It cannot switch the primary benchmark or promote variants.
- `materialize_a_short_variant_tracking.py` - Phase 6b tracking-plan helper;
  consumes `schemas/a_short_variant_tracking.schema.json` via the canonical
  example template and writes a schema-valid A-short variant tracking plan under
  `result/a_short/backtest/variants/` by default. It does not compute evidence,
  promote variants, mutate EGS, or implement `burst_lane`.
- `diagnose_tier1_bad_signals.py` — Phase 3.2 Tier1 坏票特征诊断；只读现有 `rank_samples.csv` 和 generated full-rank CSV，不重跑 EGS
- `run_analysis_report.py` — Phase 4 单票 deterministic report runner；读取 `analysis_input.json`，调用 analyzer/state，默认用 as-of A 股收盘时间评估 JSON state（可用 `--state-now` 覆盖），输出 schema-validated JSON + Markdown 到 `result/a_short/<as_of>/reports/`
- `data_canary.py` — Phase 2.6 advisory-only 旁路跨源对账（Tushare vs akshare）；exit 0 / warning 不能当作 data_passed、alpha、production-readiness 或 ship-gate evidence。
- `weekly_screening.ps1` — 周五一键脚本：依次跑 `egs_main.py` + `data_canary.py` + `forward_tracker.py` + **M6.7 advisory**(Slice 3b-2: build market IV feed + `a_short_weekly_pipeline.py`, 语义 cninfo+DeepSeek 行内 -> `research/results/a_short/<as_of>/weekly_m67.json`; `-Account` 传手工账户状态 JSON: cash/positions/Rule12/Rule13,供 sizing 与已有持仓/冷静期判断,不接券商; `-SkipSemanticRisk` 可关, advisory 旁路非阻断) + **V14.3 regime 比较 sidecar**(`a_short_regime_comparison_runner.py`:comparison-only 非生产、V14.2 仍冻结,不碰选股/M6.7/否决/生产;**只在实盘当天跑**(`as_of == 运行日`,历史回放跳过——账本是 forward 累积的已结算交易日证据)、**advisory 旁路非阻断**;无 `research/results/a_short/regime_daily_ledger.json` → 一次性 `--bootstrap` 252日回填(首跑数分钟)、有 → increment ~5日;runner 把 as_of 收敛到最新已结算交易日(盘中周一→上周五),有则复用本次 IV feed;`-SkipRegime` 可关)；historical `-AsOf` requires explicit `-L3Mode pit` / `neutralize`, rejects `today`, and refuses to overwrite existing official outputs unless `-AllowHistoricalOverwrite` is passed.
