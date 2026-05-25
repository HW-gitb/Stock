# Tasks

本文件记录当前任务队列；权威状态仍以 `docs/CURRENT.md` 为准。

## P0 - Phase 5 Startup

- [ ] 写 Phase 5 kickoff spec handoff。
- [ ] 定义 execution backtest 输入边界。
- [ ] 定义 execution backtest 输出 schema / report contract。
- [ ] 明确撮合假设、成交价、T+1、停牌/涨跌停、手续费/滑点口径。
- [ ] 明确止损、时间止损、熔断、仓位限制、冷静期的模拟完成线。

## P1 - Maintenance

- [ ] 继续每周 forward tracker capture。
- [ ] 累积约 12 期后对比 forward tracker 与 backtest 结论。
- [ ] 保持 Phase 4 runner `skip/watch` 边界，避免 prompt 直接生成买入决策。

## P2 - Later

- [ ] L3 snapshot 累积满 6 个月后跑 PIT 对照。
- [ ] 扩展到 36 期以上后重新评估 regime 和排序权重。
- [ ] LOCK 样本扩到 N >= 15 后再决定是否 hard veto。

## Done Recently

- [x] Phase 4 deterministic report schema v1.0.0。
- [x] Phase 4 single-stock runner。
- [x] Phase 4 coverage doc。
- [x] Phase 4 Skill 使用文档和 prompt 骨架。
- [x] Phase 4 LLM enrichment patch schema/example。
- [x] Phase 4 two-case smoke。
