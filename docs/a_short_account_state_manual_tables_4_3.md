# A-short 4.3：手工持仓表格 → account_state.json（模板 + 列映射 + 边界）

**owner**：A-short 4.3 持仓后管理自动化切片的 in-repo 设计 + 列映射文档（Slice 4.3-A）。
**scope**：4.3-A（模板/映射/样例/边界）+ 4.3-B（转换器 + lineage schema + 测试）+ 4.3-C（M6.7 渲染微调：一览表加「持仓/冷静」列 + 逐票说明,纯渲染派生自 `machine.stateful_risk`,见 §10）+ 4.3-D（trades↔positions 一致性提示,advisory WARN-only,见 §11）已交付。（实时 review/commit gate 见 `docs/SESSION_LOG.md` 顶部,不在本文件。）

## 1. 目的与边界

用户手工维护本地 CSV 表格记录真实持仓事实，转换器把账户状态与 lineage 绑定为一份 `a_short_account_bundle` JSON；内部账户仍过 `schemas/a_short_account_state.schema.json` v1.1.0，周报 `--account` 只接受该单文件 bundle。

- **不新建第二份 account_state 契约**：转换器产出同一份 schema 的 v1.1.0(向后兼容 v1.0.0)，落盘前必过既有 `runners.a_short_weekly_pipeline.validate_account_state`（单一校验真相源）。
- 不接券商、不抓行情、不自动下单、不改 M6.7 行为、不改 egs/V14.2/打分。用户仍手动下单。
- **CSV 为 canonical 输入**（非 `.xlsx`）：可 diff、可测、无 `openpyxl` 依赖，且不被 Excel 静默把 `20260601` / `000001` / `TRUE` 改型。Excel 作为可选用户界面是未来增项（届时把 `.xlsx` 读成同样的 parsed-rows 抽象，复用同一 `build_account_state`）。
- A-short 设计上**只操作主板**：positions / trades 的 `ts_code` 经 `engine.data.a_share_board_scope.is_a_share_main_board` 校验，非主板/B 股 → FATAL（在本工具外管理）。

## 2. 输入目录与文件

```text
state/a_short/account_state_csv/
  account.csv            # 必需，恰好 1 行（组合账户级）
  positions.csv          # 必需（可仅表头=空持仓）
  trades.csv             # 必需（可仅表头=无成交）
  manual_controls.csv    # 必需（可仅表头）
  portfolio_rule12.csv   # 必需且恰好 1 行；缺失/空状态 → FATAL
```

样例见 `schemas/examples/a_short_account_state_csv/`。缺任一**必需**文件 / 必需列 → FATAL。

## 3. 列 → schema 字段映射

所有单元格按**字符串读出再显式 parse**；被强转/非法（如日期变 `20260601.0`、布尔写 `1/是`、股数变小数）→ FATAL。

### 3.1 `account.csv` → 顶层字段（恰好 1 行）

| 列 | → account_state | 解析 | 必填 |
|---|---|---|---|
| as_of | （= facts_as_of，见 §5） | YYYYMMDD | 是 |
| available_cash | available_cash | float ≥ 0；0 只允许继续管理持仓 | 是 |
| total_equity | total_equity | float > 0；供 bucket 上限计算 | 是 |
| current_gross_exposure | current_gross_exposure | float ≥ 0；供剩余额度计算 | 是 |
| manual_order_only | manual_order_only(=true) | 必须 TRUE，否则 FATAL | 是 |
| broker_connection_allowed | broker_connection_allowed(=false) | 必须 FALSE，否则 FATAL | 是 |

bundle 内 `account.as_of` 保留真实 `facts_as_of`；决策日只写 bundle/lineage 的 `decision_as_of`（见 §5）。

### 3.2 `positions.csv` → `positions[]`（按 ts_code 排序，去重）

`ts_code`(主板)/`name`/`shares`(正整数)/`avg_cost`(>0)/`entry_date`(≤决策日)/`stop_loss`(>0,**或留空**=系统算跟踪止损 S3a;v1.1.0 可选、旧 v1.0.0 仍必填)；`take_profit_1/2`(>0或空)/`last_exit_date`(≤决策日或空)/`last_exit_reason`/`manual_notes` 可选。重复 ts_code → FATAL。

### 3.3 `trades.csv` → 推导 `rule13_cooldowns[]`（见 §4）

`trade_date`(≤决策日)/`ts_code`(主板)/`name`/`side`(BUY|SELL)/`shares`(正整数)/`price`(>0)/`reason`(非空)/`order_manual`(必须 TRUE) 必填；`notes` 可选。第一期 positions 为持仓权威来源，不用 trades 重算持仓（trades 只用于推 Rule13）。

### 3.4 `manual_controls.csv` → Rule13 人工事实（按 ts_code）

`ts_code` 必填；`new_catalyst_confirmed`/`m4_recheck_passed`(TRUE/FALSE，空→FALSE)、`max_reentry_position_pct`(0<x≤1，空→默认 0.5)、`override_status`(**只允许 `manual_block` 或空；`manual_allow` 等放行一律 FATAL**)、`override_reason` 可选。

### 3.5 `portfolio_rule12.csv` → `rule12{}`（组合级，至多 1 行）

`status`(inactive|active_cooldown|recovery_1) 必填；`reason`/`triggered_at`(≤真实事实日)/`cooldown_until`/`recovery_position_multiplier`(0<x≤1)/`consecutive_stop_losses_window`/`drawdown_pct`/`iv_change_abs_1d_pctpt` 可选。**缺表、空表或 status 空一律 FATAL；不得把未知组合状态伪造为 inactive。**

## 4. 自动推进规则（转换器 = 唯一推进层；validator 兜底）

转换器把过期的 active 冷静期推进到下一态；推进**只走更严格或明确安全侧**。validator 的「过期 active→FATAL」保留作 defense-in-depth：转换器输出**永远不应**再触发它。

**Rule13（来自 trades + manual_controls）**：取每只票 `max(trade_date)` 的 SELL；该最近出场若为 `stop_loss` 且当前**不在 positions**（已重新持有 → 持仓管理、不生成冷静期）→ 生成冷静期：
- `exit_date` = 该止损卖出日；`cooldown_until` = `exit_date + rule13_cooldown_calendar_days`（默认 +1 日历日 = v14.2 §Rule13 的 24h）。
- 决策日 `≤ cooldown_until` → `active_cooldown`；
- `> cooldown_until` 且未（`new_catalyst_confirmed && m4_recheck_passed`）→ `pending_recheck`（**仍阻断**）；
- `> cooldown_until` 且两者皆真 → `cleared_for_reentry`（按 `max_reentry_position_pct` 限仓）。
- `requires_new_catalyst` / `requires_m4_recheck` 恒 true；两个 confirmed 标志只来自 manual_controls，系统不猜。
- `override_status=manual_block`：只许更严格——若推到 `cleared_for_reentry` 则降回 `pending_recheck`，**永不放行**。manual_block 挂在没有冷静期、也未持有的票上 → FATAL（通用阻断在 account_state schema 无字段可表达，属未来加性升级）。

**Rule12（来自 portfolio_rule12）**：触发判断（回撤/连续止损/IV）**不自动算**，由用户填状态。仅自动推进：`active_cooldown` 且 `cooldown_until < 决策日` → 自动推进 `recovery_1`（更严格侧，带 `recovery_position_multiplier` 默认 0.5），**绝不**自动到 `inactive`（解除组合冷静须用户显式填 inactive）。`active_cooldown` 缺 `cooldown_until` → FATAL。

## 5. 两个日期（facts_as_of vs decision_as_of）

- `decision_as_of` = 转换器 `--as-of` = 周报 `--as-of`，也是状态推进基准日；只落 bundle/lineage。
- `facts_as_of` = account.csv 的 `as_of`（用户最后更新事实的日期）。
- `facts_as_of > decision_as_of` → FATAL（用了未来事实）；`< ` → 允许但 WARN + lineage 标 `stale_warning`（周一盘中用上周五持仓事实是合法常态，对齐周一收盘前 cadence）。
- bundle 内 `account.as_of == facts_as_of`，周报验证 `decision_as_of == --as-of`、`facts_as_of ≤ decision_as_of`，并重算 `snapshot_digest/snapshot_id` 防错批或篡改。

## 6. 三个 MINOR 决定（已定死）

1. **Rule13 冷静周期 N + 日历口径**：N = 24h → `+1 日历日`，配置在 `presets/a_short.yaml::position_management`（单一来源）。用**日历日**故转换器**离线**、无需 trade calendar。安全不依赖周期长度（到期转 pending_recheck 仍阻断）。
2. **`available_cash ≥ 0`**：0 现金不再中止整轮；已有持仓照常输出持仓管理，新开仓因现金/额度不足归零。
3. **单文件原子 bundle**：lineage 用 sha256 + row_count 记录每张输入表，并与 account 一起写入同一临时文件后 `os.replace`；周报不再读取可缺失的旁产物。

## 7. provenance / lineage（不进 M6.7）

provenance 与 account 同处一个原子 bundle；周报消费 `snapshot_id/digest/facts_as_of`，并把 lineage 的关键持仓对账告警转成 `account_integrity`。完整明细仍只留私密 bundle，不进入 tracked 周报。

## 8. owner 文件

- 转换器：`runners/a_short_account_state_from_manual_tables.py`（核心纯函数 `build_account_state`）。
- account_state 契约：`schemas/a_short_account_state.schema.json` **v1.1.0**(S3a:stop_loss 可选 + enum/if-then 向后兼容 v1.0.0)+ `runners/a_short_weekly_pipeline.py::validate_account_state`（校验真相源）。
- bundle/lineage 契约：`schemas/a_short_account_bundle.schema.json` + `schemas/a_short_account_state_lineage.schema.json`。
- 模板样例：`schemas/examples/a_short_account_state_csv/*.csv`。
- 配置：`presets/a_short.yaml::position_management`。
- 测试：`tests/test_a_short_account_state_from_manual_tables.py` + `tests/schema/test_a_short_account_state_lineage_schema.py`。

## 9. 验收（§10 of 设计）

给定一份样例（一只持仓 + 一只刚止损 active + 一只 Rule13 pending + 一只 Rule12 recovery）→ 转换器产出单文件原子 bundle；周报读后：持仓显示持仓管理 / 硬风险仍否决 / 刚止损阻断再入 / 冷静过期未复核仍阻断 / Rule12 active 阻断空仓新开仓 / recovery_1 限仓。空 Rule12 表必须拒跑，0 现金持仓必须仍可管理。

## 10. 4.3-C：M6.7 渲染微调（render-only）

`runners/a_short_m67_render.py` 从 `machine.stateful_risk`（引擎已写入每票产物，无需改引擎/schema）派生展示：

- **一览表新增「持仓/冷静」列**：持仓 → `已持仓`;无账户/老报告 → `—`;空仓候选**并列所有适用标签**——组合级 Rule12(`Rule12冷静`/`Rule12恢复`)在前 + per-stock Rule13(`Rule13冷静`/`Rule13待复核`/`Rule13可再入`)在后,如 `Rule12冷静 + Rule13待复核`;都不命中 → `空仓`。**重叠时两态都显示,不让 Rule13 盖掉组合级 Rule12**(R-ASHORT-43C-HOLDING-STATE-MULTILABEL-DROP;持仓态按设计保留单一 `已持仓`,组合级 Rule12 原因仍进逐票说明,不丢信息)。
- **逐票区**：仅在持仓/冷静态(非空仓、非 `—`)加一行 `持仓/冷静:<态>（<reasons>）`,reasons 取自 `stateful_risk.reasons`（含 Rule12+Rule13 全部原因）。空仓/无账户不加,避免噪音。
- **不渲染「状态来源」**（§7 Route A）：来源信息与 account 一起绑定在 bundle.lineage，周报只消费其快照身份与对账完整性，不把本地文件路径渲染进用户报告。
- **只解释、不改结论**：该列/行**不反向改写** action / star / hard_veto / sizing（有反向测试钉死）。owner：`runners/a_short_m67_render.py`、`tests/test_a_short_m67_render.py::HoldingStateTests`。

## 11. 4.3-D：trades↔positions 一致性门（已有持仓继续管理；新开仓 fail-closed）

`runners/a_short_account_state_from_manual_tables.py::reconcile_trades_positions(trades, positions)`:把 trades 按 ts_code 净额(BUY +、SELL −)与 `positions.shares` 对账。差异可能来自历史成交不全 / 分红拆股 / 费用，因此**绝不自动覆盖 positions**；但在人工闭环前不能证明可用敞口，故所有新开仓 fail-closed，已有持仓仍继续管理。

- `net_buy_not_in_positions`:某票 trades 净买入 > 0 但 positions 未登记(可能漏登持仓)。
- `shares_mismatch`:某**有近期成交**的持仓,trades 净额 ≠ `positions.shares`(带「可能历史不全/分红拆股/费用」caveat)。无近期成交的旧持仓不在净额里、不提醒;净卖出后空仓(正常出场 / Rule13)不提醒。
- 警告落 bundle.lineage `consistency_warnings`。`net_buy_not_in_positions` / `shares_mismatch` 会把账户完整性标为 blocked：**禁止所有新开仓，但已有持仓继续管理**；positions 仍是持仓数量权威，不被自动覆盖。
