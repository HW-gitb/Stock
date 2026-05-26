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
  `analysis_input.json`, validates `execution_report.json`, and writes CSV
  shells under `result/a_short/backtest/execution/`.
- `diagnose_tier1_bad_signals.py` — Phase 3.2 Tier1 坏票特征诊断；只读现有 `rank_samples.csv` 和 generated full-rank CSV，不重跑 EGS
- `run_analysis_report.py` — Phase 4 单票 deterministic report runner；读取 `analysis_input.json`，调用 analyzer/state，输出 schema-validated JSON + Markdown 到 `result/a_short/<as_of>/reports/`
- `data_canary.py` — Phase 2.6 旁路跨源对账（Tushare vs akshare）
- `weekly_screening.ps1` — 周五一键脚本：依次跑 `egs_main.py` + `data_canary.py`；canary 失败不影响主流程退出码
