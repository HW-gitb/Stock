# Project

股票分析系统项目，目标是构建四套股票分析系统：

- A 股短线
- 美股短线
- A 股长线
- 美股长线

每套系统包含筛选、分析、回测、复盘四组件，共享同一套 engine，通过 preset 区分市场和周期。

## Current Focus

当前主线是 A 股短线样板。

- Phase 1: `analysis_input` 契约和 EGS 导出已完成。
- Phase 2: rank backtest 工程链路通过，策略优化继续。
- Phase 3: minimal analyzer + JSON state + replay/ablation 已完成。
- Phase 4: minimal Skill / deterministic report runner 已完成。
- 下一步: Phase 5 execution backtest 边界设计。

## Key Entry Points

- `AGENTS.md` - AI 协作硬规则
- `docs/CURRENT.md` - 当前状态快照
- `docs/SESSION_LOG.md` - 跨 LLM 认知交接
- `A-EGS/egs_main.py` - A 股短线筛选入口
- `runners/backtest_rank.py` - rank 回测入口
- `runners/run_analysis_report.py` - Phase 4 单票 deterministic report runner

## Important Directories

- `schemas/` - 跨模块数据契约
- `engine/analyzer/` - deterministic analyzer/state 逻辑
- `skills/a_short_analysis/` - A 股短线分析 Skill 使用文档和 prompts
- `runners/` - CLI runner
- `docs/handoff/` - phase 级交接记录
- `result/a_short/` - A 股短线输出
- `state/a_short/` - A 股短线 JSON state
