# Phase 5 kickoff spec handoff

**日期**：2026-05-25
**范围**：Phase 5 execution backtest 启动边界与 contract 规格
**状态**：kickoff spec 已建立；Phase 5 schema / runner / simulator 代码尚未开始。
**前置 handoff**：`docs/handoff/2026-05-25_phase4_kickoff_spec_handoff.md`（Phase 4 minimal 完成：deterministic report schema + runner + Skill 使用文档）

---

## 1. 背景

Phase 4 已完成单票 deterministic report 的最小闭环：

- `schemas/deterministic_report.schema.json` v1.0.0
- `runners/run_analysis_report.py`
- `schemas/deterministic_report_coverage.md`
- `skills/a_short_analysis/SKILL.md`
- prompt 骨架与 enrichment patch contract

但 Phase 4 runner v1 只输出 `skip/watch`，不会输出 `buy`，也不会计算入场价、止损、止盈或仓位。Phase 5 因此不能把 Phase 4 Markdown 或 LLM notes 当成交易指令，也不能把 `watch` 直接解释成买入。

Phase 5 的目标是建立可复现的 execution backtest contract 和模拟器，验证“如果把筛选/分析结果转成可执行交易计划，止损、时间止损、熔断、仓位限制、冷静期会怎样影响结果”。它不是新的选股优化阶段，也不是 Phase 7 DataHub 重构。

---

## 2. Phase 5 边界

Phase 5 = execution 回测。最小范围包括：

1. execution report schema first。
2. deterministic execution plan / decision 来源清楚。
3. 用历史日线 forward data 模拟交易事件。
4. 完整记录 entry、exit、stop、time stop、position、circuit breaker、cooldown 的触发路径。
5. 输出 machine-readable report + CSV 明细，便于 Claude / Codex / 用户复核。

明确不做：

- 不改 `A-EGS/egs_main.py` 选股逻辑。
- 不改 Phase 3 hard veto 规则。
- 不把 LLM enrichment 或 Markdown 自由文本解析成交易指令。
- 不启动 Phase 7 DataHub / ODS-DWD-DWS 重构。
- 不用单一收益切片冒充 execution 回测。
- 不在没有 contract 的情况下直接写撮合模拟大实现。

---

## 3. 第一条后续代码任务

**下一条最小代码任务**：

新增 `schemas/execution_backtest_report.schema.json` v1.0.0，并加最小 schema meta-validation 测试。

该任务只定义 report contract，不写 simulator，不生成交易，不改 rank backtest。

最低字段范围建议：

```text
schema_name: "execution_backtest_report"
schema_version: "1.0.0"
generated_at
preset
mode
settings
inputs
execution_assumptions
data_lineage
outputs
metrics
date_warnings
limitations
```

其中 `execution_assumptions` 必须显式描述：

- entry timing：默认 T+1 open，且沿用 limit-up unbuyable 约束
- price adjustment：qfq via adj_factor
- transaction cost：默认沿用 rank backtest `cost_pct`
- stop loss semantics
- take profit semantics
- time stop days
- position sizing cap
- portfolio circuit breaker
- cooldown / re-entry rules

---

## 4. 输入 contract

Phase 5 不直接读 LLM 自由文本。允许输入来源分三层：

1. `analysis_input.json`：候选池、scores、technical、fundamental、source lineage。
2. Phase 3 analyzer：`run_veto(candidate)` 的 deterministic veto 输出。
3. Phase 4 deterministic report：只读 JSON 结构化字段；如果字段是 `unknown` / `requires_llm` / `not_implemented_phase4`，simulator 必须按规则跳过或标 warning，不能猜。

第一版可以先选择更保守路径：

- 不要求预生成每只股票的 Phase 4 report；
- runner 从 `analysis_input.json` + analyzer/state 直接构造 execution candidate；
- report 仍记录是否引用了 deterministic report，以及缺失原因。

如果后续决定必须消费 Phase 4 report，则应先定义输入路径和 version guard，不得读 Markdown。

---

## 5. 输出位置

Phase 5 输出应隔离在 backtest 目录，避免污染实盘结果目录：

```text
result/a_short/backtest/execution/
├── execution_report.json
├── trades.csv
├── daily_equity.csv
├── order_events.csv
└── skipped_candidates.csv
```

`execution_report.json` 必须先通过 `schemas/execution_backtest_report.schema.json`。

---

## 6. 模拟完成线

Phase 5 不能只复用 rank 回测的 `ret_5d/10d/20d_t1_net`。完成线必须覆盖：

1. **Entry**
   - T+1 open entry。
   - limit-up / no entry 时明确标 `entry_unbuyable`，不产生持仓。
2. **Stop loss**
   - 至少支持固定 stop price 或 schema 中声明的 stop rule。
   - 若输入没有 stop，则交易必须 skipped 或标 `missing_stop`, 不能默认无止损。
3. **Time stop**
   - 到期未触发止盈止损时按 time stop exit。
4. **Take profit**
   - 如果 v1 不支持止盈，report 必须明确 limitation；若支持，触发优先级要写入 assumptions。
5. **Position sizing**
   - 单票仓位上限、总资金约束、现金余额变化必须可追踪。
6. **Circuit breaker**
   - 组合级熔断触发后，新开仓应停止；已有仓位处理规则必须明确。
7. **Cooldown**
   - 同一 ts_code 止损后再入场冷静期必须可模拟或显式 skipped。
8. **Event log**
   - 每笔交易的 entry / exit / stop / time_stop / circuit / cooldown 事件必须有行级记录。

---

## 7. 与 Phase 4 schema v1.1.0 的关系

Claude audit 留下的 Phase 4 schema v1.1.0 设计点仍未决：

- `data_lineage.l3_mode`
- `data_lineage.enrichment_applied`
- `data_lineage.enrichment_source`

Phase 5 schema 设计时必须显式处理这个问题：

- 要么把这些字段纳入 `execution_backtest_report.data_lineage`；
- 要么先单独升级 deterministic report schema；
- 要么记录为 deferred limitation。

不能在 runner 里隐式假设这些字段存在。

---

## 8. 验证要求

第一条 schema 任务完成时至少验证：

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/execution_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; import json; json.load(open('schemas/execution_backtest_report.schema.json',encoding='utf-8')); print('json parse ok')"
```

后续 runner 任务完成时再运行 unittest / smoke，不在 schema 任务里提前写大实现。

---

## 9. 下一步注意事项

1. 下一步只做 `schemas/execution_backtest_report.schema.json` + 最小 schema 测试。
2. 不要在 schema 任务里新建 simulator。
3. 不要改变 rank backtest 输出口径。
4. 不要把 Phase 4 `watch` 当成 Phase 5 `buy`。
5. Claude 需要重点审查：schema 字段是否足够承载 execution 完成线、Phase 4 schema v1.1.0 是否必须先做、输出目录是否与现有 backtest 目录隔离。
