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
- `backtest_execution.py` - Phase 5 execution backtest skeleton; reads
  `analysis_input.json`, can validate/reference an existing `execution_price_data`
  JSON via `--price-data`, validates `execution_report.json`, and writes CSV
  shells under `result/a_short/backtest/execution/`. It still does not fetch
  prices or simulate fills.
- `materialize_execution_price_data.py` - Phase 5 provider-boundary helper;
  converts a local OHLC CSV into a schema-valid `execution_price_data` JSON for
  `backtest_execution.py --price-data`. It does not fetch Tushare data or
  simulate fills.
- `materialize_execution_price_data_tushare.py` - Phase 5 provider-boundary
  helper; fetches Tushare `daily` / `adj_factor` / `stk_limit` / `trade_cal`
  and writes the same schema-valid `execution_price_data` JSON. It caches the
  provider payload under `result/a_short/backtest/cache/` and still does not
  simulate fills.
- `diagnose_tier1_bad_signals.py` — Phase 3.2 Tier1 坏票特征诊断；只读现有 `rank_samples.csv` 和 generated full-rank CSV，不重跑 EGS
- `run_analysis_report.py` — Phase 4 单票 deterministic report runner；读取 `analysis_input.json`，调用 analyzer/state，输出 schema-validated JSON + Markdown 到 `result/a_short/<as_of>/reports/`
- `data_canary.py` — Phase 2.6 旁路跨源对账（Tushare vs akshare）
- `weekly_screening.ps1` — 周五一键脚本：依次跑 `egs_main.py` + `data_canary.py`；canary 失败不影响主流程退出码
