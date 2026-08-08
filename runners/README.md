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

- `runners\weekly_screening.cmd` is the standard Windows entrypoint: it launches only the sibling `weekly_screening.ps1` with a process-scoped execution-policy bypass, without changing machine or user policy. Its resolver validates any legacy interpreter value but always returns the pinned host Python, then runs the offline dependency preflight before any provider or private-state access. It never selects the Codex bundled/PATH Python.
- Run the complete offline A-short check with one command:
  `.\runners\a_short_offline_check.ps1`. Missing dependencies are listed
  together; install them once with
  `powershell -NoProfile -ExecutionPolicy Bypass -File .tools\codex_main_python.ps1 -m pip install -r requirements-a-short.txt`, then rerun the command.
- Install mandatory runtime validation dependencies with:
  `powershell -NoProfile -ExecutionPolicy Bypass -File .tools\codex_main_python.ps1 -m pip install -r requirements.txt`.
- Install development / test dependencies with:
  `powershell -NoProfile -ExecutionPolicy Bypass -File .tools\codex_main_python.ps1 -m pip install -r requirements-dev.txt`.
- Codex must invoke the pinned host interpreter through `.tools\codex_main_python.ps1` (or the test launcher below). The Codex bundled Python is not an accepted project runtime, even if it can import a subset of packages.

Existing helpers:

- `backtest_rank.py` — Phase 2 rank 回测入口；smoke-mode historical `today` L3 generation explicitly passes `--allow-historical-live-l3`, while production defaults to L3 neutralization.
- `a_short_preflight.py` / `a_short_offline_check.ps1` - validate the one pinned host Python (an explicit value is validation-only), report every missing A-short dependency and actual `Asia/Shanghai` timezone capability in one offline pass, then run the fixed offline test pack without provider or private-account access.
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
  reads schema-valid `execution_backtest_report` v1.4.0 files, whose required
  marker preserves the legacy Rule6 hard-veto boundary and excludes an M6.7
  recommendation-performance / production-proxy interpretation, aggregates
  monthly return / Sharpe / worst drawdown evidence, optionally computes
  benchmark-aware monthly alpha t-stat from a `YYYYMM -> return` JSON, and writes
  schema-valid `execution_aggregate_report` v1.1.6. Zero-trade reports with
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
- `a_short_factor_comparison_v2_cache_build.py` - P0 private v2 cache builder;
  only during a live canonical weekly run, it reads frozen selected-union
  captures, incrementally requests the bounded daily/adjustment/limit window,
  records missing adjustment provenance honestly, and atomically writes only
  beneath the gitignored v2 root. It schedules v2 missing rows first, then P5
  industry-weight requests, then P2/P3 and formal-operation execution requests;
  overflow is deferred and never allowed to starve v2 or P5.
  Its failure is comparison-only and non-blocking.
- `a_short_industry_weight_comparison.py` - P5a thin private capture / existing-cache
  settlement / de-identified progress entry. It never calls a provider, reads an
  account, backfills historical evidence, or changes the active EGS profile.
- `a_short_official_operation_evidence.py` - private, append-only capture plus
  decision-level `live_normalized` progress for the already-published M6.7 display.
  It consumes only the P5a shared execution cache and shared managed-exit core; it
  cannot create a portfolio, cash, positions, NAV, manual fill, M6.7, ranking, or order flow.
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
- **序15 IV 接线不变量**：`weekly_screening.ps1` 在 canonical `AsOf/PriceAsOf` 确定后只构建一次 IV feed，再把同一份经 schema、as-of、最新交易日、字节摘要校验的 feed 通过 `--iv-feed` 交给 EGS；EGS 先投影结构化 volatility source/freshness，再写 `analysis_input.json`，M6.7 复用同一路径且不重建。`-SkipSemanticRisk` 不构建 feed，EGS 明确写 `unavailable/not_requested`；feed 失败不得回退旧 feed，M6.7 写失败 receipt 并 fail-closed。
- `weekly_screening.cmd` / `weekly_screening.ps1` — 周实盘一键入口及实现：依次跑 EGS、canary、forward capture + cache-only backfill、唯一操作输出 M6.7、V14.3 comparison sidecar。live canonical 周先由唯一 cache writer 把 v2/P5/P2/P3/正式操作证据缺失窗口按固定优先级原子合并进同一私密 `daily_cache.json`，并把同一路径交给各只读 consumer；各轨 capture/ledger/verdict 不合并，失败不阻断 M6.7。live 周另调用 `a_short_regime_comparison_runner.py`；可用 `-SkipRegime` 跳过，首次无账本时用 `--bootstrap`，全程 comparison-only、非阻断。`-Account` 只接受五张手工 CSV 经转换器生成、摘要绑定的 `a_short_account_bundle`；确认文件精确转发，持仓确认必须与账户 bundle 同用并在私有路径验证。请求后 M6.7 输入失败会写 failed receipt 并非零退出；语义和 V14.3 仍是 advisory/comparison-only，不改生产评分、veto 或建仓授权。historical `-AsOf` 必须显式 `-L3Mode pit|neutralize`。
- `a_short_runtest.ps1` / `us_short_runtest.ps1` — 仅测试用全量入口：每次在 `Stock_runtest_private` 下新建 detached clone，强制无 EGS cache/无 US resume，并把所有固定输出留在胶囊；用法与安全删除见 `docs/runtest_capsule.md`。不得把其产物当正式周报或 ship-gate 证据。
