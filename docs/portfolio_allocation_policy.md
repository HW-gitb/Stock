# Portfolio Allocation Policy Draft

**状态**：P0c 决策草案；位于 P0a capital context contract 之前。
**范围**：A 股 / 美股、长线 / 短线 / 流动资金 bucket 的资金政策。本文不是 schema、runner、simulator 或交易信号。
**目的**：Phase 5 fill simulation 不能在 bucket-aware capital context 定义前，把单一 `initial_capital` 账户假设锁进执行回测。

## 已固定输入

用户已经在 `AGENTS.md` 中固定以下项目级规则：

- 每个市场内部拆为 `1/3 长线 + 1/3 短线 + 1/3 流动资金`。
- A 股长线、A 股短线、美股长线、美股短线都是一等子系统。
- 每个 runner 模拟或交易前，必须知道自己 preset 的 capital ceiling。
- 每套系统实盘 ship 前必须给出对应 bucket 的净 alpha evidence。alpha 不足时只能作为风控 filter、minimal-size live process 或 paper trade，不能无声进入 full-size 实盘。

## 为什么它阻塞 fill simulation

当前 Phase 5 execution backtest contract 仍主要用 run-level `settings.initial_capital` 加 `execution_assumptions.position_sizing` 表达资金。如果直接在这个基础上实现 fill simulation，后续再接 portfolio allocation 时，需要重写 report schema、runner inputs、simulator accounting 和 position sizing assumptions。

所以当前下一步不是 fill simulation，而是 P0a：先定义 capital context contracts，让 fill simulation 从第一版真实实现开始就按 bucket capital 运行。

## 建议默认口径

以下是 Codex 建议的起始口径。在写入 schema 或 preset 前，凡涉及用户资金政策的部分均视为待确认。

1. **A 股 vs 美股总资金比例**
   - 代码里不要无声默认。
   - 中性规划假设可以是 `A = 50%`、`US = 50%`，但必须等用户确认后才可作为运行时默认。
   - 如果未确认，P0a 应显式表示 market split 待定，而不是发明默认值。

2. **市场内部 bucket 比例**
   - 每个市场内部：
     - long bucket target: `33.3333%`
     - short bucket target: `33.3333%`
     - liquidity bucket target: `33.3333%`
   - 长线和短线只能按自身 bucket capital 计算仓位，不能按 total account capital 计算。

3. **流动资金 bucket 定位**
   - 默认把 liquidity bucket 视为受保护储备，而不是“闲置可随便调用资金”。
   - P0a schema 起始默认：`hard_floor`。只有 explicit rule 可以穿透该下限；后续如用户确认改为 tolerance band 或 reserve-drawdown 模式，应通过兼容字段扩展完成，避免 breaking change。
   - 任何调用 liquidity 的动作都必须记录 trigger、target bucket、amount 和 audit reason。
   - 短线系统熔断时，默认不得用 liquidity 给短线重新加仓。

4. **A 股 cash vs 美股 cash**
   - 默认不互通。
   - 跨市场 cash transfer 需要显式人工决策，或后续 coordinator 规则。

5. **长线 vs 短线调用 liquidity**
   - 长线系统只有在满足长线框架条件时才可申请 liquidity，例如估值区间或明确 averaging-down 规则。
   - A 股长线 / 美股长线框架尚未建立，因此 P0a 只 reserve 条件字段，例如 `long_liquidity_use_conditions: []`；具体 enum 值等长线 spec 建立后再补，不阻塞 P0a 启动。
   - 短线系统在短线熔断期间不得调用 liquidity 增加新风险。
   - 降低风险的操作允许继续执行，例如退出或降低已有敞口。

6. **极端回撤行为**
   - liquidity 优先保护整体组合。
   - 极端回撤期间，默认冻结新增风险，除非有明确 recovery rule 或长期积累规则允许。

## P0a 契约边界

P0a 应拆清静态政策、动态状态和 report 快照：

- `schemas/portfolio_allocation.schema.json`：静态政策源头。
  - market allocations
  - bucket targets and ceilings
  - liquidity transfer rules
  - ship-gate policy references
- `schemas/cash_buffer_state.schema.json`：动态状态。
  - per-market cash balances
  - available / reserved / locked cash
  - last rebalance metadata
  - drawdown state
  - last update metadata
  - 必须沿用现有 state manager pattern 做 atomic JSON write
- `schemas/execution_backtest_report.schema.json` v1.1.0：本次回测的资金上下文快照。
  - `capital_context` 只记录本次 run 使用的 capital context。
  - 它不能成为资金政策源头。
- `presets/*.yaml`：preset 身份和静态 bucket ceiling reference。
  - market
  - horizon
  - bucket
  - bucket ceiling percent

runner 还需要显式 capital input path，例如 `--portfolio-allocation` + `--cash-buffer-state`，或一个统一的 `--capital-context` wrapper。没有 runner input，report 里的 `capital_context` 就会变成人工拼出的不可复现字段。

## P0a 前必须处理的决策

P0a 可以在以下问题被用户确认，或被 schema 明确表示为 pending 后启动：

1. **A 股 vs 美股总资金比例**：`50/50`、其他比例，还是等美股系统启动前再确认？
2. **流动资金严格度**：P0a 起始按 `hard_floor` 设计；用户仍可确认改为带容忍区间的目标，或可按显式规则动用的储备。
3. **跨市场资金转移**：是否确认 A 股 cash 和美股 cash 默认完全不互通？
4. **长线调用 liquidity 条件**：P0a 不等待长线 spec；先 reserve `long_liquidity_use_conditions: []`，具体条件等 A 股长线 / 美股长线 spec 建立后再补。
5. **Ship gate 阈值**：什么证据足以支持 full-size real-money deployment？

## 下一步顺序

1. 解决或显式 reserve 上述 pending decisions。
2. 实现 P0a capital context contracts。
3. 然后再按 bucket capital 实现 Phase 5 fill simulation。
