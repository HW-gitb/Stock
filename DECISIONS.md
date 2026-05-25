# Decisions

本文件是已固化决策索引；详细背景见 `AGENTS.md` 与 `docs/handoff/`。

## Architecture

- 共享 engine + preset 分离，不按市场复制独立系统。
- A 股短线先跑通 Phase 1-6，再扩展美股和长线。
- `A-EGS/egs_main.py` Phase 7 前不搬迁。
- DataHub / engine modularization 是 Phase 7，不在 Phase 3-6 做大重构。

## Data And State

- `analysis_input.json` 是筛选到分析的输入契约，当前 schema version 为 `1.1.0`。
- state 使用 JSON，不使用 Excel。
- 回测分两层：rank backtest 先做，execution backtest 后做。
- 正式运行默认刷新 L3；搭建/测试才允许复用 L3 cache。

## Analyzer And Skill

- v14.2 是规格说明书，不是运行时提示词。
- Phase 3 hard veto 首批规则：`chasing_high`、`overheat`、`l2_unknown`、`esp_non_positive`。
- missing 不等于 negative；缺失/空值/不可解析不自动 hard veto。
- Phase 4 Skill 是使用文档；deterministic executor 是 `runners/run_analysis_report.py`。
- Phase 4 runner v1 只输出 `skip/watch`，不硬做 `buy`。
- LLM enrichment 只能通过 enrichment patch 写入 `llm_notes`，不得覆盖 deterministic 字段。

## Backtest Interpretation

- Phase 2 工程链路通过，不等于策略可实盘部署。
- 24 期结果显示框架当前更像“过滤坏票”而非“稳定挑好票”。
- 旧 12 期 Top 5 显著性结论已撤回。
- 当前 Phase 5 前不得把 prompt 输出升级成买入决策。
