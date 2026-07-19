# Runners

Command entry points will live here after the shared engine exists.

Planned scripts:

- `screen.py`
- `analyze.py`
- `backtest_rank.py`
- `backtest_execution.py` (Phase 5 offline daily-bar simulator; not production or ship-gate evidence by itself)

Current Phase 1/2 entry remains `A-EGS/egs_main.py`. Direct historical
`--as-of` runs must use `--l3-mode pit` / `neutralize`, or explicitly declare
`--allow-historical-live-l3` for non-evidence live-concept smoke runs. The
engine also rejects non-empty daily payloads that are too incomplete to support
safe suspend inference instead of treating missing rows as suspended stocks.
Suspend coverage observations are written to
`logs/suspend_daily_coverage_<as_of>.json` and mirrored into schema-validated
`data_health` v1.5.0 (`metrics.suspend_daily_coverage`, SW-industry source
observation, watch-pool accounting, and post-L0 rank/source reconciliation);
cached observations are explicitly marked as cache hits, not fresh provider
coverage. Formal EGS runs also publish
`rank_universe_reconciliation.csv`, with one terminal outcome per L0 symbol.

Validation environment:

- `runners\weekly_screening.cmd` is the standard Windows entrypoint: it launches only the sibling `weekly_screening.ps1` with a process-scoped execution-policy bypass, without changing machine or user policy. `runners\weekly_screening.ps1` resolves `-PythonExe`, `STOCK_PYTHON`,
  PATH, or a standard Windows Python install in that order, then runs the
  offline dependency preflight before any provider or private-state access.
- Run the complete offline A-short check with one command:
  `.\runners\a_short_offline_check.ps1`. Missing dependencies are listed
  together; install them once with
  `python -m pip install -r requirements-a-short.txt`, then rerun the command.
- Install mandatory runtime validation dependencies with:
  `python -m pip install -r requirements.txt`.
- Install development / test dependencies with:
  `python -m pip install -r requirements-dev.txt`.
- The Codex bundled Python runtime is acceptable for syntax checks and unit
  tests only after `requirements.txt` is installed there; do not treat bundled
  runtime packages as the project's dependency source.

Existing helpers:

- `backtest_rank.py` — Phase 2 rank 回测入口；smoke-mode historical `today` L3 generation explicitly passes `--allow-historical-live-l3`, while production defaults to L3 neutralization.
- `a_short_preflight.py` / `a_short_offline_check.ps1` - resolve one explicit or standard project Python, report every missing A-short dependency in one offline pass, then run the fixed offline test pack without provider or private-account access.
- `a_short_entry_funnel_calibration.py` - local-only, source-hash-bound evaluator for the preregistered A-short funnel / IV / overlay seen sample; it cannot search or change production thresholds and keeps future confirmatory observations separate.
- `backtest_execution.py` - Phase 5 execution backtest runner; reads
  `analysis_input.json`, can validate/reference an existing `execution_price_data`
  JSON via `--price-data`, requires explicit `--portfolio-allocation` and
  `--cash-buffer-state` inputs for bucket-aware capital context, reads
  `presets/a_short.yaml` by default via `--preset-path`, validates
  `execution_report.json`, and writes CSV outputs under
  `result/a_short/backtest/execution/`. With `--price-data`, it runs a trading-calendar
  daily-OHLC portfolio simulation with T+1, delayed unsellable exits, concurrent
  cash use, and close-to-close mark-to-market; without `--price-data`, it keeps the
  skeleton skip behavior. It rejects cash-state bucket capital above the policy ceiling
  (`market_capital * bucket_ceiling_pct`) before sizing can use it.
- `aggregate_execution_reports.py` - Phase 5 multi-period aggregation helper;
  reads schema-valid `execution_backtest_report` v1.3.0 files, aggregates
  monthly return / Sharpe / worst drawdown evidence, optionally computes
  benchmark-aware monthly alpha t-stat from a `YYYYMM -> return` JSON, and writes
  schema-valid `execution_aggregate_report` v1.1.5. Zero-trade reports with
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
- `weekly_screening.cmd` / `weekly_screening.ps1` — 周实盘一键入口及实现（省略 `-AsOf` 时解析 canonical 决策日）：依次跑 EGS、canary、forward capture、**唯一操作输出 M6.7**、V14.3 comparison sidecar。M6.7 只消费 final marker + byte digest 绑定的当次 EGS 包，最终 JSON/Markdown/receipt/ratchet 同事务发布；请求后 analysis/IV/account/pipeline 任一失败会写 `failed` receipt 并非零退出。语义证据仍 advisory-only，不进生产评分/veto；`-SkipSemanticRisk` 可跳过整段 M6.7。带 `-Account` 时输出进 gitignored private root；无账户仅 observation-only。V14.3 由 `a_short_regime_comparison_runner.py` 运行，仍是 live-only、`comparison-only`、`--bootstrap` 首次建账且失败**非阻断** M6.7，`-SkipRegime` 可关；D2 action summary 达到复核状态时会在控制台和既有 regime panel 自动提示“晋级证据复核”或“退役/继续收集”，绝不自动切生产。historical `-AsOf` 必须显式 `-L3Mode pit|neutralize`，默认拒覆盖既有正式输出。
- `a_short_runtest.ps1` / `us_short_runtest.ps1` — 仅测试用全量入口：每次在 `Stock_runtest_private` 下新建 detached clone，强制无 EGS cache/无 US resume，并把所有固定输出留在胶囊；用法与安全删除见 `docs/runtest_capsule.md`。不得把其产物当正式周报或 ship-gate 证据。
