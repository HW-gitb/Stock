# Portfolio Allocation Policy Draft

**状态**：P0c 用户确认决策；位于 P0a capital context contract 之前。
**范围**：A 股 / 美股、长线 / 短线 / 流动资金 bucket 的资金政策。本文不是 schema、runner、simulator 或交易信号。
**目的**：Phase 5 fill simulation 不能在 bucket-aware capital context 定义前，把单一 `initial_capital` 账户假设锁进执行回测。

## 已固定输入

用户已经在 `AGENTS.md` 中固定以下项目级规则：

- 顶层市场资金比例为 `A = 35%`、`US = 65%`。
- 每个市场内部拆为 `1/3 长线 + 1/3 短线 + 1/3 流动资金`。
- A 股 cash 与美股 cash 默认不互通。
- A 股长线、A 股短线、美股长线、美股短线都是一等子系统。
- 每个 runner 模拟或交易前，必须知道自己 preset 的 capital ceiling。
- 每套系统支持 full-size 手动实盘使用前，必须通过多 metric AND ship gate。alpha 不足时只能作为风控 filter、minimal-size manual-use support 或 paper trade，不能无声进入 full-size 手动实盘。
- 本系统只做分析、筛选、回测、复盘和报告；用户手动下单，不接券商、操作系统或自动化工具做自动下单。

## 为什么它阻塞 fill simulation

当前 Phase 5 execution backtest contract 仍主要用 run-level `settings.initial_capital` 加 `execution_assumptions.position_sizing` 表达资金。如果直接在这个基础上实现 fill simulation，后续再接 portfolio allocation 时，需要重写 report schema、runner inputs、simulator accounting 和 position sizing assumptions。

所以当前下一步不是 fill simulation，而是 P0a：先定义 capital context contracts，让 fill simulation 从第一版真实实现开始就按 bucket capital 运行。

## 用户确认口径

以下口径已经由用户在 2026-05-26 确认。P0a schema / preset 可据此编码；未列入确认的长线细则仍按 reserve 字段处理。

1. **A 股 vs 美股总资金比例**
   - `A = 35%`
   - `US = 65%`
   - 这是 P0a 的静态政策输入，不再使用 `50/50` 中性占位。

2. **市场内部 bucket 比例（within-market percentage）**
   - 每个市场内部：
     - long bucket target: `33.3333%`
     - short bucket target: `33.3333%`
     - liquidity bucket target: `33.3333%`
   - 长线和短线只能按自身 bucket capital 计算仓位，不能按 total account capital 计算。
   - 示例：A 股 long bucket = total portfolio × `35%` × `33.3333%` ≈ total portfolio 的 `11.67%`。

3. **流动资金 bucket 定位**
   - 默认把 liquidity bucket 视为受保护储备，而不是“闲置可随便调用资金”。
   - P0a schema 起始默认：`hard_floor`。只有 explicit rule 可以穿透该下限；后续如用户确认改为 tolerance band 或 reserve-drawdown 模式，应通过兼容字段扩展完成，避免 breaking change。
   - 任何调用 liquidity 的动作都必须记录 trigger、target bucket、amount 和 audit reason。
   - 短线系统熔断时，默认不得用 liquidity 给短线重新加仓。

4. **A 股 cash vs 美股 cash**
   - 默认不互通。
   - P0a 先按 per-market cash state 设计，不做 unified cash pool，不做自动 currency conversion。
   - 跨市场 cash transfer 需要显式人工决策，或后续 coordinator 规则。

5. **长线 vs 短线调用 liquidity**
   - 长线系统只有在满足长线框架条件时才可申请 liquidity，例如估值区间或明确 averaging-down 规则。
   - A 股长线 / 美股长线框架尚未建立，因此 P0a 只 reserve 条件字段，例如 `long_liquidity_use_conditions: []`；具体 enum 值等长线 spec 建立后再补，不阻塞 P0a 启动。
   - 短线系统在短线熔断期间不得调用 liquidity 增加新风险。
   - 降低风险的操作允许继续执行，例如退出或降低已有敞口。
   - 实际 cash 调拨决策由用户手动执行；系统只生成 signal / recommendation，不直接 transfer capital between buckets。

6. **极端回撤行为**
   - liquidity 优先保护整体组合。
   - 极端回撤期间，默认冻结新增风险，除非有明确 recovery rule 或长期积累规则允许。

7. **Ship gate**
   - full-size 手动实盘使用必须同时满足：
     - monthly alpha t-stat ≥ `2.0`
     - Sharpe ratio ≥ `1.0`
     - max drawdown ≤ `15%`
     - forward live data ≥ `12` 个月
   - 这是 AND 条件。任一不达标时，该子系统只能作为 paper trade、minimal-size 手动使用支持或 risk-control filter。
   - A 股短线当前证据不足以支持 full-size 手动实盘；这不否定系统作为筛选分析和风控 filter 的价值。

8. **执行边界**
   - 系统输出分析、筛选、回测、复盘和报告。
   - 用户之后手动下单。
   - 禁止接入券商、操作系统或自动化工具做自动下单。
   - Phase 5 execution backtest 用于模拟交易规则和风控结果，不是 live trading/order execution engine。

## P0a 契约边界

P0a 应拆清静态政策、动态状态和 report 快照：

- `schemas/portfolio_allocation.schema.json`：静态政策源头。
  - market allocations
  - bucket targets and ceilings
  - liquidity transfer rules
  - ship-gate policy references
  - manual-execution-only boundary
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

## P0a 启动状态

P0c 中真正阻塞 P0a 的用户决策已经确认：

1. **A 股 vs 美股总资金比例**：`A = 35%`、`US = 65%`。
2. **流动资金严格度**：P0a 起始按 `hard_floor + explicit exception rules` 设计。
3. **跨市场资金转移**：A 股 cash 与美股 cash 默认不互通。
4. **长线调用 liquidity 条件**：P0a 不等待长线 spec；先 reserve `long_liquidity_use_conditions: []`，具体条件等 A 股长线 / 美股长线 spec 建立后再补。
5. **Ship gate 阈值**：采纳多 metric AND：monthly alpha t-stat ≥ 2.0、Sharpe ≥ 1.0、max drawdown ≤ 15%、forward live data ≥ 12 个月。
6. **执行边界**：系统只支持分析筛选与回测复盘；用户手动下单，不做自动下单集成。

## 下一步顺序

1. 实现 P0a capital context contracts。
2. 然后再按 bucket capital 实现 Phase 5 fill simulation。
3. fill simulation 输出用于评估手动交易计划和风控边界，不用于自动下单。
