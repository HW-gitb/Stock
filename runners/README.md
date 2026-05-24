# Runners

Command entry points will live here after the shared engine exists.

Planned scripts:

- `screen.py`
- `analyze.py`
- `backtest_rank.py`
- `backtest_execution.py`

Current Phase 1/2 entry remains `A-EGS/egs_main.py`.

Existing helpers:

- `backtest_rank.py` — Phase 2 rank 回测入口
- `data_canary.py` — Phase 2.6 旁路跨源对账（Tushare vs akshare）
- `weekly_screening.ps1` — 周五一键脚本：依次跑 `egs_main.py` + `data_canary.py`；canary 失败不影响主流程退出码
