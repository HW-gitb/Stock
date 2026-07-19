# 美股中长线系统设计 v3.1 — `us_long`

> 文件：`docs/us_long_system_design.md`（in-repo 单一设计权威）　原稿日期：2026-06-22　入 repo：2026-06-24　修订：2026-07-19（移植自桌面 `v3_us_long_design.md`，桌面稿已退役）
> 系统：`us_long`，美股中长线，持仓周期 3-6 个月。
> 状态：**in-repo 单一设计权威**（对标 `docs/us_short_system_design.md` 之于 us_short）。经需求梳理 + /grill + 多轮独立复核收敛；用户已授权进入 Tier 2，本文件起作为 `us_long` 实现的唯一设计权威——改设计须改本文件，别凭记忆、别另起桌面稿。
> **数据/接入边界（仍生效）**：foundation-first。Tier 2-3 只用本地样例数据，**不抓真实数据、不接 provider、不联网、不接 DataHub**；真实 provider call / provider selection / adapter / DataHub / 联网留 Tier 4+ 单独授权与审查。
> **仓库纪律**：每片 schema-first + tests + 按 `AGENTS.md` 当前角色分工交独立审查；串行不交叉 A 股；不 auto-push（push 仅用户显式指令 + 隐私审计后）。

---

## 0. 一句话定位

`us_long` 是一套**美股中长线成长弹性系统**：一键运行 → 从美股全市场选出 **Top20** → 二次分析输出**最多 5 只**当前值得建仓的票，其余给观察/不推荐理由。重点抓**热门赛道 + 未来成长弹性**（AI 存储、光模块、物理 AI 等），全程**手动操作、不接券商、不用盘中分钟级数据**，所有结论默认 **paper/research-only**，并强制**任何分析因子都必须可追溯地影响最终表格**（不允许悬空）。

---

## 1. 决策记录（单一来源）

| # | 决策点 | 结论 |
|---|--------|------|
| D1 | 选股池 | 美股**全市场·不限市值** + 一道流动性/价格地板（剔除仙股/无法成交微盘/缺数据股）。"大盘"= 整个美股市场，非大市值股；必须覆盖 AAOI/SanDisk 类中小盘成长股。 |
| D2 | 造法顺序 | **foundation-first**：先把契约 + 治理 preset + 纯引擎 + 样例跑通，真数据（FMP/SEC/联网）后续单独授权接入。不拿假数据冒充真推荐。 |
| D3 | 赛道机制 | **种子白名单常驻 + 新赛道分阶段（provisional→confirmed）**。provisional 可进 Top20/观察理由，也可进 Top5 但**本轮最多 1 只 + 过全部质量地板 + 强制标「新赛道试探仓」**，并受 `capital_mode` 约束（默认 paper_only）。 |
| D4 | 打分方式 | **人工透明因子框架，不做统计找因子**。edge 在"早抓热门成长赛道"=定性判断；统计找因子留到很后期、单独 research-only 阶段。 |
| D5 | 因子闭环（核心铁律） | 任何 active/provisional 因子不落到最终表格字段 → **停止运行、不写正式结果**。复用 us_short `field_registry §10 no-dangling` + 运行时血缘账本 + 断路器。持仓专用因子在空持仓时落 `not_applicable`，不误判失败。 |
| D6 | 复用而非另造 | 手填 CSV 转换器 / 私密路径守卫 / 跨 LLM 登记表 / 赛道生命周期 / 决策结果绑定，复用仓库已有模式；但**只复用工程结构，不复用短线动作语义和阈值**。引擎用扁平 `engine/us_long_*.py`。 |
| D7 | 结果路径 | 最终结果只写 `state/us_long/results_private/YYYYMMDD/`，**gitignored** + 白名单文件 + 排他守卫。 |
| D8 | 数据源 | 真实数据阶段候选：**FMP**（主源候选/接入方向，非最终 provider selection）+ **SEC EDGAR**（审计）+ **WebSearch**（赛道/催化/新闻定性，需单独授权）+ **yfinance**（仅授权后 smoke）。任何 provider call / provider selection / adapter / DataHub 仍需单独授权与审查。 |
| D9 | 当前持仓 | 用户当前**无**中长线持仓；持仓 CSV 空表（只表头）也能跑。 |
| D10 | 模拟/失败输出 | 样例/contract run 只写 `staging/mock` 或临时目录；**只有 official real-data PASS run 才写 `results_private`**（其 `capital_mode` 仍可为 `paper_only`，不等于真钱资格）；失败只写 `logs/staging`（`failure_manifest`）。 |
| D11 | 资金状态闸 | 所有输出带 **`capital_mode = paper_only / manual_minimal / ship_gate_eligible`**，默认 `paper_only`。把"推荐建仓"和"真钱下单资格"在机器层面分开。 |
| D12 | 操作建议主轴 | 长线动作由 **thesis 状态 + 估值/预期收益 + 催化兑现 + 风险/数据状态 + 组合约束 + 既往动作**共同决定。价格只可触发复核或保护，不得单独把 thesis 判为破坏。 |
| D13 | 操作记忆 | 每次正式或前向运行都生成不可变 `operation_decision_record`；以后用同一 `decision_id` 绑定 `operation_outcome_record`。不是为展示，而是让系统知道“当时为什么这样建议，后来结果怎样”。 |
| D14 | 结果评估 | 日线 paper 路径必须记录未成交现金、成本后收益、基准超额、MFE/MAE/max drawdown，并显式标记同日止损/止盈都触发的 OHLC 路径歧义；不能把不确定路径包装成精确结果。 |
| D15 | 人工账户账本 | 在 positions-only 快照之外建立事件溯源账本：买卖、费用、现金、分红、拆并股、代码变更/并购分拆、人工调整；只消费手工导入，不接券商。公司行动或 FX 无法核验时 fail-closed。 |
| D16 | 建议稳定器 | 利好升级须确认，thesis-broken/硬风险可立即降级；同一证据不得令动作来回翻转；止损/保护线只允许收紧，不允许无新依据放宽。 |
| D17 | 组合预演 | 每轮把所有拟建仓/加仓建议一起做 pro-forma 暴露检查（单股/行业/赛道/因子/催化簇/US-long bucket）；该层只能收紧建议，不能救回不合格标的，也不能跨 A/US 混池。 |
| D18 | 前向 shadow 校准 | 少量预注册 shadow 变体只积攒 forward 证据；假设、成本、成熟窗口、`no_count` 条件先冻结，禁止边看边改、禁止 shadow 自动切生产、禁止历史回放冒充 live-forward。 |

---

## 2. 目标与边界

一键运行 = 两个子系统：

1. **选股系统**：从美股全市场（过地板的 active-only 美国普通股）选出 **Top20**。
2. **分析系统**：对 Top20 二次分析，输出**最多 5 只**当前值得建仓的票，其余给观察/不推荐理由。

硬边界：

- 不接券商、不自动下单、不接 OS 自动化、不用盘中分钟级数据。
- 运行频率不固定、用户手动触发。
- 首版实现用样例数据跑通端到端，**不接真实 provider、不联网**；样例模式只验证格式与逻辑，不产正式推荐、不写 `results_private`。
- 即使接真数据，真实 Top20/Top5 初期也只是 **paper/research-only**（`capital_mode=paper_only`），不等于 ship-gate 或 full-size 实盘资格。
- 仓库 ship-gate（`AGENTS.md`）：月度 alpha t≥2.0、Sharpe≥1.0、maxDD≤15%、forward live ≥12 个月。
- 资金口径：美股 65% × 长线 bucket 1/3，bucket_ceiling 0.333；A/US cash 不互通。首版实现不做美元级仓位换算（要的是价位 + 提示，不是自动 sizing），sizing 留后续。

---

## 3. 选股池 Universe（D1）

```text
active-only 美国本土普通股
排除 ADR / ETF / 基金 / SPAC / OTC / 优先股 / 权证
地板过滤：低价（仙股）/ 低流动性（日均成交额地板）/ 明显数据缺失
不限市值——覆盖 AAOI、SanDisk 这类中小盘成长弹性股
```

引擎：`engine/us_long_universe.py`。地板阈值是首版实现起点、进登记表待校准（§13）。

---

## 4. 赛道机制（D3）

赛道生命周期状态机（复用 us_short `theme_lifecycle` 概念）：

```text
seed         种子白名单，常驻 active，full weight
provisional  已授权联网/LLM 或本地 fixture 发现的新赛道，降权
confirmed    多轮稳定出现 + 用户确认后转正，升 full weight
cooling/decayed/retired  降温→退役（退役后从评分消失，赛道随文件消失，no-dangling 自然满足）
```

**种子白名单（首版实现起点，进登记表待增删）**：AI 存储、光模块/光通信、物理 AI/机器人、AI 基础设施、数据中心电力/散热、网络安全、国防科技、生物科技催化剂。

**新赛道来源**：`sector_scout` 只读辅助 Agent；**仅在用户单独授权联网后**扫描当下热门，输出结构化 JSON（赛道名/代表标的/证据链接/热度信号）。Tier2/样例阶段禁止联网，只能消费本地 fixture。

**provisional 赛道权限**：

- **可**影响本轮 Top20 排名、`not_recommended_15` 观察理由、登记表命中。
- **可**进入 `recommended_build_5`，但**本轮最多 1 只**、必须过全部质量地板（final_score / technical_entry / risk_control / 数据质量）、且强制标 `新赛道试探仓`。在 `capital_mode=paper_only` 下它只是纸面观察推荐；升到 `manual_minimal` 或更高前必须另有明确授权。
- 必须进登记表 `R-USLONG-THEME-*`，记录"待积攒几轮证据/用户确认后转正或退役"。
- `provisional→confirmed` 促升只能靠：跨多轮稳定出现 + 用户确认；**不**靠单次 LLM 判断自动转正。
- **收紧时间门**：进入真实数据 + 真钱/ship-gate 阶段后，该自动名额收紧为"逐次用户批准 `new_theme_probe_seat`"（登记表 `R-USLONG-THEME-PROBE-TIGHTEN`）。

引擎：`engine/us_long_theme_heat.py`（种子热度）、`engine/us_long_theme_scout.py`（消费 sector_scout JSON / fixture）、`engine/us_long_theme_lifecycle.py`（状态机 + 转正/退役 + 登记表计数）。

大白话：先抓明确热门赛道；新题材当轮最多放 1 只进建仓名单、还得过全部门槛并打「试探仓」标签，且默认只是纸面观察、不等于真钱下单。

---

## 5. Top20 选股评分（D4）

人工透明因子框架。**所有权重都是首版实现起点、不是"最优"，必须进登记表、靠 forward 结果校准。**

```text
selection_score =
  30% 赛道热度        theme_heat_score
  25% 增长加速度      growth_acceleration_score
  20% 3-6月相对强势   momentum_3_6m_score
  10% 预期上修/催化   catalyst_score
  10% 流动性          liquidity_score
   5% 风险/数据质量   risk_data_quality_score   ← 主要做硬门槛/降级，不过度稀释弹性
```

Top20 先过硬门槛再排名：流动性/价格地板、数据质量 blocker、明显不可交易或字段缺失先剔除；`risk_data_quality_score` 的 5% 只处理非阻断级风险/降级，不得让数据 blocker 靠其它高分挤进 Top20。

**Top20 数量合同（实际数量合同，下游计数单一来源）**：`selected_count = min(20, 硬阈值幸存者数)`。不足 20 时先放宽非核心阈值（市值/涨幅）、保留硬阈值（流动性/最低价/非退市/数据齐全）；幸存者 ≥20 取分最高 20，<20 则 `selected_count` = 实际幸存者数 + manifest warning（记 `selected_count` / warning / 原因），**不为凑数放垃圾、不硬停（不因 <20 单独失败）**。下游计数全部由 `selected_count` 派生：`recommended_count ≤ min(5, selected_count)`、`not_recommended_count = selected_count − recommended_count`（文件名 `_15` / `_5` 仅常态标签，实际行数以 manifest 为准）。

引擎：`engine/us_long_selection_score.py`。取分最高至多 20 只 = Top20（`selected_count = min(20, 幸存者)`，数量合同见上）。

---

## 6. Top5 分析评分 + 推荐规则（D4）

Top5 的任务不是再找热门，而是判断**现在能不能买**。

```text
final_score =
  20% Top20选股分带入  selection_score_carry
  20% 增长质量         growth_quality_score
  20% 赛道催化强度     theme_catalyst_score
  20% 技术建仓位置     technical_entry_score
  10% 估值上行空间     valuation_upside_score
  10% 风险控制         risk_control_score
```

推荐规则（先过质量地板，再排名，不硬凑）：

```text
质量地板：
  final_score ≥ 阈值（待校准）
  technical_entry_score ≥ 阈值（待校准）
  risk_control_score 不触发硬拒绝
  数据质量非 blocker

过地板后按 final_score 排名：
  前 5 只 = 推荐建仓（recommended_build_5）
  其余 = 观察 / 不推荐（not_recommended_15）

过地板不足 5 只 → 少报，不硬塞。
```

引擎：`engine/us_long_analysis_score.py`。

---

## 7. 因子闭环 / no-dangling（D5，核心铁律）

**单一声明来源 = `field_registry`（复用 us_short §10），不另设第二套因子状态系统。** `lineage` 是"运行时执行臂"——只**读** field_registry 并验证落点，不重复声明。

三层结构：

**① 声明层**（治理 preset）：`schemas/us_long_field_registry_governance.schema.json` + `presets/us_long_field_registry_governance_YYYYMMDD.json`。每个因子声明：

```text
factor_id            theme_heat_score
status               active | provisional | shadow | disabled
owner_module         us_long_theme_heat
data_source          provider row / SEC / sector_scout JSON / local fixture
calculation_method   …
weight               0.30
applicability_scope  all_symbols | top20_only | recommended_only | position_only | shadow_only
feeds_into[]         selected_top20.赛道, selected_top20.选股分,
                     recommended_build_5.推荐理由, not_recommended_15.理由
reason_template      理由模板（理由字段由模板+因子值生成，杜绝无因子支撑的自由文本）
price_impact         该因子影响哪些价位（buy_zone/stop/target/take_profit 或 none）
risk_impact          该因子产出的风险标签（或 none）
needs_calibration    true
register_ref         R-USLONG-CALIB-THEME-HEAT-WEIGHT
```

**② 运行时层**：`engine/us_long_lineage.py` 血缘账本，pipeline 写每个最终字段时记账：

```text
ledger.record("theme_heat_score", "selected_top20.选股分", symbol)
ledger.record("technical_entry_score", "recommended_build_5.建仓区间", symbol)
ledger.record("atr_stop_loss", "recommended_build_5.止损价", symbol)
ledger.record("unrealized_pct", "positions_review.50%止盈提示", symbol)
```

**③ 断路器**（运行时 validator）：

```text
active/provisional 因子：声明了 feeds_into → 按 applicability_scope / row_scope 实际运行必须 ledger.record()
  → 必须出现在 factor_audit.csv → 每只相关股票 factor_trace 可追溯
recommended_only/top20_only/position_only：只在适用行生效；不适用时必须记录 not_applicable(scope_reason)，不得误判 dangling FAIL
position_only 因子：只对真实持仓行生效；空持仓时记 not_applicable，不触发 dangling FAIL
shadow 因子：豁免断路器消费检查，只落 factor_audit / run_manifest，以"仅观察·未影响决策"显式标注；不写进推荐/不推荐理由；但必须进登记表
disabled：不计算、不输出
最终理由字段：不得出现没有 factor_id / factor_trace 支撑的自由文本结论；否则视为悬空结论
孤儿列反查：每个核心输出列必须反向追溯到 ≥1 因子，否则 OrphanColumnError（与"因子悬空"对称 → 双向 no-dangling）

任一 active/provisional 因子悬空：
  停止运行 → 不写 results_private → failure_manifest + 错误写 logs/ 或 staging/
  正式 run_manifest 只在 PASS 时写入 results_private
```

引擎：`engine/us_long_field_registry.py`（读声明 + 静态校验）、`engine/us_long_lineage.py`（运行时账本 + 断路器）。

大白话：系统算了一个东西，就必须真的改变最后表格里的某个结论；否则直接停、不出正式结果。

---

## 8. 手填持仓 CSV + 持仓恒复核（需求 #5）

**复用 `us_short` 的 `account_state_from_manual_tables` 转换器模式**（不另造）。

手填 CSV（gitignored）：`state/us_long/account_state_csv/`

```text
positions.csv  ticker, account, shares, avg_cost, entry_date, notes, exclude_from_new_buy
trades.csv     （可选，人工成交事件；用于对账和事件账本，不等于券商回报）
cash_events.csv（可选，入金/出金/费用/税费/分红/人工调整）
corporate_actions.csv（可选，拆并股/代码变更/并购/分拆；必须带来源与生效日）
```

- `account` 仅为券商标签（如 IBKR），喂 `positions_review.账户`，非资金字段。
- Tier 2 的最小账户输入仍可只有 `positions.csv`；没有现金事件时不伪造 `available_cash/total_equity`，组合金额/现金利用率一律落 `not_available`。
- 转换器 `runners/us_long_account_state_from_manual_tables.py` → `state/us_long/account_state.json`（positions-only，过 `us_long_account_state.schema.json` 校验）+ lineage sidecar。
- 事件转换器把可用手工表规范化为 append-only `account_event`；最小公共字段为 `event_id / account / event_type / effective_at / observed_at / source_ref / currency`，交易类再带 ticker/quantity/price/fees。账户快照必须由事件重放或 positions-only 起点生成，不允许直接改派生余额来掩盖对账差异。
- 账本至少支持 `cash_deposit / cash_withdrawal / buy / sell / fee / tax / dividend / split / reverse_split / symbol_change / merger / spinoff / manual_adjustment`；成本法每账户冻结为治理选项，v1 默认 `average_cost` 以对齐既有 `avg_cost` 输入（仅为系统复盘口径，不是税务成本建议），以后切 FIFO 须显式迁移与复核。重复事件、超卖、负股数、非有限金额一律拒绝。
- positions-only 起点必须标 `ledger_basis=positions_bootstrap`、`bootstrap_as_of` 与来源 digest；它只证明起点持仓，不反推此前现金流或已实现收益。事件齐全后才可标 `ledger_basis=full_event_replay`。
- US-long 账本以 USD 为基准货币；非 USD 事件缺显式 FX 来源时不得按 1:1 折算，现金/P&L 汇总阻断。公司行动缺 PIT 来源或无法对账时，允许保留原始事件供人工排查，但阻断相关标的新建仓和正式绩效计数。
- ticker 强制美股格式（拒 A 股数字码）；CSV 为 canonical（拒 Excel 强转）；坏输入 fail-fast。
- **当前无持仓（D9）→ 空表只表头也照常跑 Top20/Top5。**

**持仓恒复核**（和 a_short 一致）：CSV 里的持仓**无论在不在本轮 Top20**，都进 `positions_review.csv`；持仓复核**不反向篡改** Top20/Top5。

引擎：`engine/us_long_position_review.py`。

---

## 9. 价格与动作规则（需求 #5、#10）

止损/止盈：**结构位 + ATR 波动保护；盈利 50% 后强制复核“是否分批止盈 + 是否上移保护线”**。价格几何可复用 us_short 的纯计算与守卫模式（日线，无分钟级），但长线动作必须服从 thesis/估值/组合语义，不能照搬短线出场阈值。

```text
建仓区间 entry_band   ← technical_entry_score + support_level + valuation_risk
保护价   protection_price ← support_level + atr_daily + risk_control_score
目标价   target_price ← growth_quality + theme_catalyst + valuation_upside + resistance_level
止盈复核价 take_profit_review_price ← target_price + resistance_level + unrealized_pct(持仓)
```

正式 schema 以 `protection_price / take_profit_review_price` 为机器字段；CSV 可继续显示用户熟悉的“止损价/止盈价”。两者是人工复核/动作触发价，不是自动订单，也不等同于 thesis 已破坏。

**+50% 硬提醒**（需求 #5）：

```text
latest_price >= avg_cost * 1.5  →  profit_50_alert = YES
                                    required_review = profit_take_and_protection_review
                                    position_action 由 thesis/估值/组合风险复核后决定
（硬提醒，不是硬卖出；全手动）
```

**建议动作**：

```text
未持仓：分批建仓 / 观察 / 不推荐 / 人工复核
已持仓：继续持有 / 分批加仓 / 暂停加仓 / 分批止盈 / 减仓 / 清仓 / 上移保护线 / 人工复核
```

**长线 thesis 与动作优先级**：

```text
evidence_state = complete / partial / stale / conflicting
thesis_state   = intact / watch / weakened / broken / unknown_due_to_evidence

1. 账户/数据/公司行动无法对账，或关键证据 stale/conflicting
   → 阻断新建仓/加仓，既有持仓转人工复核；不得输出“风险正常”。
2. thesis broken、不可投资、重大治理/偿债风险
   → 清仓或减仓候选，允许立即降级；仍只给人工建议。
3. thesis weakened、估值饱和、催化落空、组合暴露超限
   → 暂停加仓 / 分批止盈 / 减仓。
4. thesis intact 且估值、风险、组合容量仍通过
   → 继续持有；只有新增证据满足预注册条件才可分批加仓。
5. 未持仓标的只有质量地板、预期 alpha thesis、建仓区间和组合预演全通过
   → 分批建仓，否则观察/不推荐。
```

- `thesis_state` 必须绑定书面 thesis、明确证伪条件、下一复核日和 `thesis_outcome_log_ref`；复核节奏遵守 `docs/long_alpha_spec.md`：财报后的季度复核、重大事件触发复核、持有满一个经营周期后的年度 thesis reset。
- 价格下跌或触发保护线可启动复核，但**价格本身不等于 thesis broken**；同样，价格上涨 50% 也不自动等于必须卖出。
- 动作变化必须写 `previous_action / new_action / transition_reason_codes / new_evidence_refs`。正向升级至少连续两次合格观察或一次明确的高置信事件证据；硬风险和 thesis broken 可单次降级。
- `protection_price` 的 ratchet 只能不变或上移；如确需放宽，必须产生 `manual_override`，写原因、操作者、时间与失效日，且不得计入自动规则胜率。

**所有价格必须绑因子**（断路器覆盖）：每个价位都经 `ledger.record()` 记到对应因子，否则停。

**数据新鲜度**：输出带 `as_of` + 价格时钟戳。真实数据模式必须有 `data_freshness_gate`——价格/基本面/新闻或赛道证据超过各自允许窗口时，该字段只能降级为观察或阻断建仓，不能静默进入推荐。

**数据缺失·分字段降级**（降级 ≠ 悬空：降级后的因子仍须被消费 + 进 factor_trace）：

```text
缺价格       → 剔除该股
缺行业分类   → 试备用源；仍缺则标记并降级主题相关因子
缺财报       → 降级评分并标记风险
缺分析师预期 → 不剔除，estimate/catalyst 相关因子降级
缺新闻       → 不剔除，catalyst / 情绪类因子降级
```

引擎：`engine/us_long_price_engine.py`、`engine/us_long_position_review.py`。

---

## 10. 资金状态闸 `capital_mode`（D11）

把"系统给出建仓建议"和"这笔钱可以真投"在机器层面分开，避免"推荐建仓"被误读成"真钱现在买"。对齐 us_short 的 `ship_gate` / `live_permission` 概念。

```text
paper_only          默认。Top20/Top5/建仓区间/价位/动作全是纸面观察与研究，
                    不构成真钱下单依据。首版实现 + Tier5 真数据初期都是此态。
manual_minimal      用户另行明确确认后，可做小额手动建仓观察；系统仍只给建议、不下单。
                    从 paper_only 升上来需明确授权。
ship_gate_eligible  仅当满足仓库 ship-gate（t≥2.0 / Sharpe≥1.0 / maxDD≤15% / ≥12 月 forward live）
                    后才可讨论 full-size。
```

- 每次运行必须在 `run_manifest.capital_mode` 记录当前态，并在 `selected_top20.csv` / `recommended_build_5.csv` / `not_recommended_15.csv` / `positions_review.csv` 增加 `资金状态` 列；不能只藏在 manifest 里。
- 升级条件 + 所需审查证据进登记表 `R-USLONG-CAPITAL-MODE-GATE`。

---

## 10A. 操作建议记忆：decision → account event → outcome（D13-D15）

这一层是给机器积攒前向证据，不是新 UI，也不改变 §11 的 6 文件正式输出白名单。正式 canonical 私密记录落 `state/us_long/operation_memory_private/`，shadow 落 `state/us_long/shadow_private/`，都必须 gitignored；Tier 2-3 的样例/contract 记录只写 staging/mock，不得污染前向账本。

### 10A.1 不可变 `operation_decision_record`

每次 canonical 前向运行对每个入选/持仓标的写一条不可变记录；同一个 `decision_id` 不覆盖、不就地改结论。最小字段：

```text
decision_id, cohort_key, as_of, data_cutoff_at, created_at
system_version, governance_version, input_packet_sha256, output_row_sha256
ticker, account_ref(optional), position_ref(optional), row_source
decision_mode(canonical/shadow), observation_kind(live_forward/historical_replay/research_backfill/manual)
capital_mode, action, previous_action, transition_reason_codes
thesis_state, evidence_state, thesis_ref, thesis_break_conditions, next_review_date
entry_band, protection_price, target_price, take_profit_review_price, order_valid_until
build_tranche_plan, portfolio_overlay_status, factor_trace, source_refs
```

约束：

- `cohort_key` 由 `lane + as_of + ticker + decision_mode + account_scope` 确定；同一 canonical cohort 只能有一条，重跑要么字节等价幂等，要么因 digest 冲突 fail-closed，不能重复计数。
- `input_packet_sha256`、治理版本和 `as_of` 必须绑定当时可见信息，禁止后来数据回填后改写旧决定。
- `shadow` 与 canonical 物理分开；shadow 可比较，不得改正式动作、Top20/Top5、账户或 `capital_mode`。
- 手工实际执行与否不回写 decision；它进入 `account_event`，以免把“系统建议”和“用户实际操作”混成一个事实。

### 10A.2 `operation_outcome_record`

结果记录只能引用既存 `decision_id`，并保留来源 digest。生命周期采用 `pending → matured_evaluable | matured_no_count`；`matured_no_count` 必须有封闭枚举原因（关键价格缺失、公司行动未核验、账户事件冲突、非 canonical 重复、取消/过期未成交等），不得静默丢样本。

最小结果字段：

```text
decision_id, cohort_key, horizon, maturity_as_of, outcome_status, no_count_reason
evidence_kind(paper/manual_minimal/live_normalized), observation_kind
fill_status, fill_price, unfilled_cash_fraction, holding_days
gross_return, total_cost, net_return, benchmark_return, net_excess_return
mfe, mae, max_drawdown, thesis_outcome, manual_override_ref
same_bar_both_triggered, execution_path_ambiguous, outcome_source_sha256
```

- paper、manual-minimal、live-normalized 三套证据分开汇总，不能拼成一条更好看的收益曲线。
- 只有 `observation_kind=live_forward`、canonical、来源完整且 `matured_evaluable` 的 cohort 能推进 forward/ship-gate 计数；历史回放和 research backfill 永远不能冒充前向月份。
- 结果汇总必须同时报告 `pending_count / evaluable_count / no_count / ambiguous_count / ambiguous_rate`，不能只报胜率或已完成的好样本。
- 长线结果除价格收益外必须记录 `thesis_outcome = intact/progressed/weakened/broken/unknown`，区分阶段里程碑复核与最终 horizon 复核。

### 10A.3 日线 OHLC 路径歧义

没有分钟数据时，同一交易日若保护价和止盈/目标价都落在 `[low, high]` 内，系统不知道先后顺序：

```text
same_bar_both_triggered = true
execution_path_ambiguous = true
paper 假设 = 采用保守路径，但同时保留歧义标记
```

日线路径顺序冻结为：先处理开盘跳空（越过已生效价位则按不利的开盘可成交价），再处理日内 high/low；若开盘不能确定先后而 high/low 同时覆盖两个价位，才进入上述歧义分支。建仓成交当日又触发保护/止盈也按同一原则标记，不能假装知道分时顺序。

保守假设只能用于不夸大结果，不能让 `ambiguous_rate` 消失。若歧义率过高，相关止损/止盈参数只能保持 shadow/待校准，不能据此宣称可交易优势。

---

## 10B. 组合预演与建议稳定器（D16-D17）

系统先生成单股 provisional action，再把本轮所有拟建仓/加仓动作放进同一个 pro-forma 组合，最后才形成 canonical action：

```text
单股质量/thesis/估值/风险通过
        ↓
拟建仓/加仓集合
        ↓
单股、行业、赛道、因子、催化/宏观簇、US-long bucket 暴露检查
        ↓
canonical action（只能维持或收紧，不得被组合层救回）
```

- Tier 2-3 无真实现金时，用治理中的相对风险单位做样例契约测试，并明确 `cash_sizing_status=not_available`；不得伪造美元仓位或“组合安全”。
- 有可靠账户现金后，必须消费仓库现有 `portfolio_allocation` / `cash_buffer_state` 合同；US-long runner 只拿 US-long bucket ceiling，不得重算顶层资金、不跨市场混池。
- 组合层命中限制时，可把 `分批建仓→观察`、`分批加仓→暂停加仓`、`继续持有→减仓复核`，不能把 `不推荐/清仓候选` 变成买入。
- 建议稳定器比较 `previous_action` 与新证据：无新证据不升级；重复输入必须幂等；硬风险立即降级；保护线只 ratchet。所有变化写结构化 reason code，不依赖 LLM 自由文本解析。

---

## 10C. 前向 shadow 校准（D18）

首批只允许少量、预注册的操作问题进入 shadow，例如：

```text
分几批建仓、每批确认条件
价格保护线只触发复核，还是触发减仓候选
盈利后的分批止盈与保护线 ratchet
建议有效期 / 财报前后暂停新建仓
单股、行业、赛道和催化簇的组合上限
```

每个变体在首个 live-forward cohort 前冻结：`variant_id / hypothesis / canonical comparator / affected actions / cost model / maturity horizon / minimum observations / no_count reasons / review date / stop rule`。运行期只追加记录，禁止改旧 cohort、禁止持续偷看后调阈值、禁止自动 promote。达到预注册时间门和样本门后，才允许人工审查决定 `keep_shadow / redesign / retire / propose_promotion`；即使 `propose_promotion` 也仍需 schema、测试、独立审查和用户授权。

---

## 11. 最终输出（需求 #9 简洁 + #10 不悬空 + #11 排他）

中文列名 + 英文 ticker。最终只写 `state/us_long/results_private/YYYYMMDD/`，**白名单 6 文件**：

```text
selected_top20.csv        selected_count 行选股（正常 20；<20 = 实际只数 + manifest warning，见 §5；带 decision_id）
recommended_build_5.csv   ≤5 行推荐建仓（含资金状态 + 推荐标签 + thesis/证据状态）
not_recommended_15.csv    (selected_count − 推荐数) 行不推荐/观察 + 理由（`_15` 仅常态标签；实际行数以 manifest 为准）
positions_review.csv      持仓恒复核 + thesis/动作变化 + 50%止盈复核提示
factor_audit.csv          每因子→声明落点 vs 实际落点（断路器证据）
run_manifest.json         运行元信息 + dangling_check(PASS) + capital_mode + 计数 + decision/outcome 私密账本引用 + 登记表命中
```

列定义：

```text
selected_top20:     decision_id,运行日期,资金状态,排名,Ticker,公司,行业,细分行业,赛道,赛道状态,现价,选股分,最终分,
                    建议,建仓区间,止损价,3-6个月目标价,止盈价,持仓状态,50%止盈提示,
                    thesis状态,证据状态,下次复核日,核心利好,核心风险,最终理由,数据源,factor_trace
recommended_build_5:decision_id,运行日期,资金状态,推荐标签,排名,Ticker,公司,行业,细分行业,赛道,赛道状态,现价,最终分,
                    thesis状态,证据状态,建仓区间,止损价,3-6个月目标价,止盈价,推荐理由,主要风险,数据源,factor_trace
not_recommended_15: decision_id,运行日期,资金状态,排名,Ticker,公司,行业,细分行业,赛道,赛道状态,现价,最终分,建议,
                    不推荐/观察理由,未通过因子,当前值_vs_门槛,重新观察条件,升级为建仓条件,
                    主要风险,数据源,factor_trace
positions_review:   decision_id,运行日期,资金状态,Ticker,账户,股数,成本价,现价,浮盈比例,50%止盈提示,
                    thesis状态,证据状态,前次动作,持仓动作,动作变化原因,下次复核日,建议止盈价,建议保护价,factor_trace
factor_audit:       运行日期,Ticker,因子ID,因子名,状态,因子值,权重,
                    声明影响字段,实际影响字段,理由片段,最终影响
run_manifest.json:  运行日期,系统版本,数据模式,capital_mode,输入文件,输出文件,
                    selected_count(Top20实际只数),推荐建仓数量,不推荐/观察数量,top20_shortfall_reason,dangling_check(PASS),
                    decision_record_count,decision_store_digest,outcome_due_count,
                    active/provisional/shadow 因子列表,登记表命中项,警告
failure_manifest:   仅失败时写 logs/ 或 staging/，记录 dangling_check(FAIL),错误；不得进入 results_private
```

输出契约 schema：`schemas/us_long_output_contract.schema.json`（冻结列集 + 枚举）。

大白话：用户主要看前三个表；factor_audit + manifest 证明每个结论怎么来的。

---

## 12. 结果目录排他性 + 私密守卫（需求 #11）

```text
state/us_long/
  account_state_csv/        gitignored — 手填 CSV（真实持仓）
  account_state.json        转换产物
  account_ledger_private/    gitignored — append-only 人工账户事件 + 重放快照 + 对账结果
  operation_memory_private/ gitignored — canonical immutable decision/outcome 记录
  shadow_private/           gitignored — 预注册变体 + forward 比较记录；不得喂 canonical 动作
  staging/YYYYMMDD/         中间产物、样例/mock 输出、失败 manifest（绝不进 results_private）
  llm_review/               LLM 结构化中间输出
  logs/                     错误 / 断路器日志
  results_private/YYYYMMDD/ gitignored — 仅真实正式 PASS run 的白名单 6 文件
```

两道守卫：

1. **私密路径守卫** `engine/us_long_private_paths.py`（复用 us_short 逻辑）：用 `git check-ignore` 真值判定，`results_private / account_ledger_private / operation_memory_private / shadow_private` 必须 gitignored，否则 fail-closed 拒写。
2. **结果目录排他守卫** `engine/us_long_results_guard.py`：写前校验 results_private 目录**只含白名单 6 文件**，出现草稿/中间/测试/非白名单文件 → 失败。

实现相应 slice 时，`.gitignore` 必须覆盖 `state/*/results_private/`、`state/*/account_ledger_private/`、`state/*/operation_memory_private/`、`state/*/shadow_private/`，且由私密路径测试证明；本设计刀不提前创建运行目录。

大白话：最终结果目录干净排他——只放真实正式 PASS 结果；样例、草稿、测试、失败说明一律别进。

---

## 13. 跨 LLM 登记表 + 校准治理（需求 #12）

"所有需要积攒数据才能决定去留/校准/启用/替换的东西都进登记表"，用两个现成机制满足：

1. **风险/gap** → `docs/system_risk_register.md`，ID `R-USLONG-*`（和 us_short `R-USSHORT-*` 同体例）。
2. **前向校准项**（权重/阈值/赛道转正退役/capital_mode 升级）→ `presets/us_long_lifecycle_calibration_governance_YYYYMMDD.json`（对标 us_short §13.1），逐项编号 + 关联引擎 + 校准条件；并在登记表挂指针 `R-USLONG-CALIB-*`。

首版实现必进登记表的项：

```text
selection_score 6 权重 / final_score 6 权重     R-USLONG-CALIB-SCORING-WEIGHTS
质量地板阈值（final_score / technical_entry）   R-USLONG-CALIB-QUALITY-FLOOR
universe 流动性/价格地板                        R-USLONG-CALIB-UNIVERSE-FLOOR
provisional 赛道折扣系数 + 转正条件             R-USLONG-CALIB-THEME-PROMOTION
provisional 入 Top5 名额收紧时间门              R-USLONG-THEME-PROBE-TIGHTEN
capital_mode 升级条件与审查证据                 R-USLONG-CAPITAL-MODE-GATE
data_freshness_gate 窗口 / stale 降级动作        R-USLONG-CALIB-DATA-FRESHNESS
ATR 倍数 / 跟踪止损窗口                         R-USLONG-CALIB-PRICE-GEOMETRY
止损规则：ATR / 固定% / 结构低点 三选一         R-USLONG-CALIB-STOP-RULE
是否纳入分析师一致目标价                         R-USLONG-CALIB-ANALYST-TARGET
是否引入 short interest / insider buying 因子    R-USLONG-CALIB-NEW-FACTORS
生物科技 / 负盈利成长股是否单独估值规则           R-USLONG-CALIB-SPECIAL-VALUATION
FMP 小盘股分析师预期覆盖不足的降级处理           R-USLONG-CALIB-SMALLCAP-COVERAGE
财报日前后风险控制规则                           R-USLONG-CALIB-EARNINGS-DATE
所有 provisional / shadow 因子                  R-USLONG-CALIB-FACTOR-STATUS
分批建仓批次/确认条件/建议有效期                    R-USLONG-CALIB-STAGED-BUILD
thesis 状态转换与正向确认门                         R-USLONG-CALIB-THESIS-TRANSITION
盈利后分批止盈 + protection ratchet               R-USLONG-CALIB-PROFIT-RATCHET
单股/行业/赛道/因子/催化簇组合上限                  R-USLONG-CALIB-PORTFOLIO-CAPS
日线同 bar 路径歧义率与相关参数处置                  R-USLONG-CALIB-OHLC-AMBIGUITY
paper/manual/live_normalized 成本与成熟窗口          R-USLONG-CALIB-OUTCOME-HORIZON
```

---

## 14. 目录结构（需求 #13，对齐 us_short 扁平风格）

引擎用**扁平** `engine/us_long_*.py`（和 us_short 一致）。

```text
engine/
  us_long_universe.py           选股池 + 地板 + 排除
  us_long_theme_heat.py         种子赛道热度
  us_long_theme_scout.py        消费已授权 sector_scout JSON 或本地 fixture（provisional）
  us_long_theme_lifecycle.py    赛道生命周期状态机 + 转正/退役 + 登记表计数
  us_long_selection_score.py    Top20 评分
  us_long_analysis_score.py     Top5 评分 + 质量地板
  us_long_price_engine.py       建仓区间/止损/目标/止盈（结构位+ATR）
  us_long_position_review.py    持仓恒复核 + thesis 状态 + 50%止盈复核 + 动作转换
  us_long_advice_state.py       动作优先级 + 稳定器 + protection ratchet
  us_long_account_ledger.py     人工事件规范化/重放/成本与对账（纯函数，不接券商）
  us_long_operation_record.py   immutable decision/outcome 绑定 + cohort 去重
  us_long_paper_path.py         日线 fill/持有路径 + MFE/MAE/DD + OHLC 歧义
  us_long_portfolio_overlay.py  本轮全部建议的 pro-forma 暴露检查（只收紧）
  us_long_shadow_compare.py     预注册 forward shadow 比较（与 canonical 隔离）
  us_long_field_registry.py     读 field_registry 声明 + 静态校验
  us_long_lineage.py            运行时血缘账本 + 断路器（no-dangling 执行臂）
  us_long_private_paths.py      私密路径守卫（复用 us_short 逻辑）
  us_long_results_guard.py      results_private 排他守卫
runners/
  us_long_pipeline.py                          一键：选股→分析→持仓复核→输出
  us_long_account_state_from_manual_tables.py  CSV→account_state 转换器
schemas/
  us_long_account_state.schema.json
  us_long_account_state_lineage.schema.json
  us_long_account_event.schema.json
  us_long_account_ledger_snapshot.schema.json
  us_long_operation_decision.schema.json
  us_long_operation_outcome.schema.json
  us_long_shadow_governance.schema.json
  us_long_portfolio_overlay.schema.json
  us_long_universe_contract.schema.json
  us_long_output_contract.schema.json
  us_long_field_registry_governance.schema.json
  us_long_theme_governance.schema.json
  us_long_scoring_profile_governance.schema.json
  us_long_lifecycle_calibration_governance.schema.json
presets/
  us_long.yaml                                  （status: reserved_phase_9 → 实现时翻 active）
  us_long_<component>_governance_YYYYMMDD.json
state/us_long/                                  （见 §12）
tests/
  test_us_long_*.py                             （1:1 镜像每个引擎模块）
```

最终结果落 `state/us_long/results_private/`（需求 #11 优先于通用 `result/` 约定，因本系统结果天然私密）。

---

## 15. 数据源 / Skill / Agent / MCP（需求 #7、#8）

**没有免费的"Claude 自带金融框架"当数据源**——所谓 Claude 金融连接器是企业级服务连接器，不是免费本地数据源。

真实数据栈（首版实现不接，单独授权那步才接；以下是候选接入方向，不是最终 provider selection）：

```text
候选主源 FMP        股票池/profile/行业/市值/财报/估值/历史日线/分红拆股；需 access packet + 授权审查后才可调用
审计源   SEC EDGAR  10-K/10-Q/companyfacts 交叉验证（公开 API，非价格源）；仍需单独授权后才接入 runner
定性源   WebSearch  赛道/催化/新闻 → 仅单独授权后联网，喂结构化字段
临时     yfinance   仅显式授权后做价格 smoke check，不进正式 provider 链
```

不用：LangGraph/Prefect（过度工程）；当前会话无可用金融 MCP；`skills/us_long_analysis/` 仍 reserved_phase_9，不能当现成分析框架。

后续可设计 3 个**只读辅助 Agent**（都只输出结构化 JSON、不直接定选股）：

```text
us_long_reviewer   查悬空因子 / NaN / 近零爆炸 / 前视偏差 / 输出路径污染
sector_scout       已授权联网赛道观察；Tier2 只用本地 fixture，新赛道先 provisional
provider_reviewer  查 FMP/SEC 字段覆盖 / 授权 / PIT / 缺字段
```

**LLM 边界**（断路器强制）：

```text
可以：识别赛道 / 总结催化 / 提取风险 / 写简短推荐理由 / 输出结构化 JSON
不可以：直接决定 Top20/Top5 / 编造财报或价格或目标价 / 绕过 factor_registry /
       输出没进 factor_trace 的结论
```

---

## 16. 实施分期（foundation-first，真数据 gated）

```text
Tier 1  设计落文档（本稿）。不改项目代码。
Tier 2  机器骨架（样例数据）：schema + 治理 preset + 纯引擎 + runner + CSV/人工事件转换器 + 私密守卫。
        用本地样例跑 Top20/Top5/positions_review、thesis/action 状态、operation decision、pending outcome、
        账户事件重放；明确标"样例·非真推荐"，只写 staging/mock 或临时目录，不写 results_private，不联网。
Tier 3  建议闭环强制：field_registry + lineage + no-dangling 断路器 + outcome 绑定 + 日线 paper path/OHLC 歧义 +
        advice stabilizer + pro-forma portfolio overlay + shadow 隔离。任一 active/provisional 因子或操作结论悬空，
        或 decision/outcome/source digest 对不上 → 停、不写 results_private；FAIL manifest 写 logs/staging。
Tier 4  真实数据源接入计划：FMP/SEC/WebSearch access packet（endpoint/字段覆盖/PIT/存储/缺字段降级/联网边界）。
        只做接入授权包与样本验证计划，不等于 provider selection / adapter / DataHub / runner 生产接入；单独授权 + 审查。
Tier 5  真实数据最小可运行版：真 Top20/Top5 + canonical live-forward decision/outcome 积攒
        （仍 capital_mode=paper_only / research-only；人工实际成交与 paper 结果分轨）。
Tier 6  前向观察 + 校准：所有待校准项进登记表，只用成熟、可评估、canonical live-forward cohort
        定权重/阈值/动作变体/赛道转正/capital_mode 升级；shadow 不自动转生产。
```

每片：schema-first + tests + 按 `AGENTS.md` 当前角色分工交独立审查 + 串行不交叉 A 股 + 不 auto-push（仓库纪律）。
建议实施顺序：Cut 1 核心 schema/治理/账户私密入口 → Cut 2 universe/theme/评分 → Cut 3 thesis/action/价格 → Cut 4 人工事件账本 → Cut 5 decision/outcome/paper path → Cut 6 no-dangling/组合预演/shadow → Cut 7 runner/输出/端到端。可按依赖合并，但不得把跨层合同塞成一个不可审查的大刀。

工程量预估：US-long 当前尚无实现，Tier 2-3 约 **5-7 个独立 slice**；Tier 4-5 约 2-4 个 slice；Tier 6 是时间门（≥3-6 月有体感，12 月才谈 ship-gate），不是多写代码就能提前完成。

---

## 17. 第一版（Tier 2-3）验收标准

```text
1.  一键命令跑通样例全流程。
2.  样例/contract run 只写 staging/mock 或临时目录，不写 results_private。
3.  Tier2-3 只验 official-write 守卫合约存在且会阻断 mock/失败输出；真实写入 results_private 验收留到 Tier5。
4.  selected_top20 = selected_count 行（min(20, 硬阈值幸存者)；正常 20，<20 为实际只数 + manifest warning，见 §5，不硬塞凑数、不因 <20 失败）。
5.  recommended_build_5 ≤5 行，可少于 5。
6.  not_recommended_15 行数 = selected_count − 推荐数（selected_count = Top20 实际只数）。
7.  每行有建仓区间/止损价/3-6月目标价/止盈价。
8.  空持仓 CSV 不阻塞运行。
9.  持仓浮盈 ≥50% → positions_review 必触发“止盈/保护线复核”，但不得仅凭涨幅硬编码卖出动作。
10. factor_audit 记录声明落点 vs 实际落点。
11. PASS run_manifest 记录 dangling_check=PASS、capital_mode、selected_count（+ <20 时 shortfall warning/原因）；四张输出 CSV 显式包含资金状态；失败只写 failure_manifest 到 logs/staging。
12. 任一 active/provisional 因子悬空 → 不写正式结果；position_only 因子空持仓时落 not_applicable。
13. 所有 needs_calibration/provisional/shadow 项进登记表。
14. results_private/account_ledger_private/operation_memory_private/shadow_private 均为 gitignored（私密守卫 PASS）。
15. 每条 canonical 输出行都有 immutable decision_id；重跑同一 cohort 幂等，digest 冲突拒绝，shadow 不能覆盖 canonical。
16. outcome 只能引用既存 decision_id；未成熟为 pending，无法评估显式 no_count；paper/manual/live_normalized 分轨。
17. 日线同 bar 同时触发保护/止盈时，保守计价且 `same_bar_both_triggered` / `execution_path_ambiguous` 为真；汇总披露 ambiguous_rate。
18. 账户事件重放可重建相同快照；重复事件、超卖、负股数、公司行动/FX 未核验都 fail-closed，不伪造余额或收益。
19. 无真实现金时组合层显式 `cash_sizing_status=not_available`；有暴露输入时组合层只可收紧动作，不可救回单股失败。
20. 同输入动作幂等；无新证据不正向升级，硬风险可立即降级，protection_price 只 ratchet。
21. 历史回放/research backfill 不推进 live-forward 计数；shadow 达门也只能提出人工 promotion review，不能自动改生产。
```

---

## 18. 需求对照表（14 条原始需求 → 落点，证明无遗漏）

| # | 原始需求 | 落到本稿 |
|---|----------|----------|
| 1 | 选股+分析一键跑完、频率不固定 | §2、§16（`us_long_pipeline.py`）、§9 数据新鲜度 |
| 2 | 不接平台、完全手动 | §2 硬边界、§10 capital_mode |
| 3 | 不涉盘中分钟级 | §2、§9（日线几何） |
| 4 | 写在 D:\cnhea\Stock，与其他系统并存 | §14 目录、头部边界 |
| 5 | 手填 CSV 自动捕捉 + 50% 止盈提示 | §8、§9（+50% 硬提醒） |
| 6 | 重未来成长潜力+幅度、热门赛道（AI存储/物理AI/闪迪/AAOI） | §3 不限市值、§4 赛道、§5 增长加速度/相对强势 |
| 7 | 调研 skill/框架/agent/MCP | §15（3 辅助 Agent + 不用 LangGraph/MCP） |
| 8 | 中长线数据源 / Claude 金融框架 | §15（FMP/SEC/联网/yfinance 为候选接入方向；无免费 Claude 数据框架；不锁最终 provider） |
| 9 | 输出简洁（20/5/15理由） | §11 三主表 |
| 10 | **所有分析结论联动最终输出、不悬空** | §7 因子闭环 + 断路器、§9 价格绑因子 |
| 11 | 最终结果排他放 results_private/运行日期 | §11、§12 排他+私密守卫 |
| 12 | 待积攒数据决定的东西进跨 LLM 登记表 | §13（system_risk_register + 校准治理） |
| 13 | 目录结构与现有系统一致 | §14 扁平 engine/us_long_*.py |
| 14 | 要不要找因子（不懂） | §6/D4 不做统计找因子，用人工框架 |

本次按开源系统讨论增补、但不改变原始 14 条需求的机器闭环：

| 增补目标 | 落到本稿 |
|----------|----------|
| 不做新 UI，先让机器记住每次建议及其依据 | §10A.1 immutable decision record |
| 人工操作后可重放账户事实，不接券商 | §8、§10A.1、§12 account ledger private |
| 建议后来好不好能按同一 decision 回看 | §10A.2 outcome record + live-forward 计数边界 |
| 日线无法知道止损/止盈先后时不装作精确 | §10A.3 OHLC 歧义 + 保守路径 + ambiguous_rate |
| 操作建议减少来回翻转，并考虑组合拥挤 | §9 thesis 优先级、§10B 稳定器与组合预演 |
| 长线参数从现在起积攒前向证据再校准 | §10C、§13、§16 Tier 5-6 |

---

## 19. 设计取舍记录（rejected alternatives，防独立复审无故回退）

记录考虑过、但**未采用**的方案 + 原因；回退到这些方案前需明确新理由。

```text
选股池      限大市值 → 否决（AAOI/SanDisk 是中小盘，会被排除）。选：全市场 + 流动性地板。
造法        mock 输出冒充正式推荐 / 直奔真数据 → 否决（前者污染 results_private；后者违仓库抓数纪律）。选：foundation-first + 样例端到端只写 staging/mock。
赛道        固定白名单只观察 / 纯 LLM 无白名单 → 否决（前者错过新爆发；后者易追伪热点）。选：种子白名单 + provisional。
新赛道入Top5 默认不进 + 每轮手批 new_theme_probe_seat → 否决（与"早抓弹性"冲突，且早期纯 paper 无真钱风险）。
            选：自动限额 1 只 + 标注 + capital_mode 闸；真钱阶段才收紧到手批。
打分        统计找因子 / 纯 LLM 定性 → 否决（前者需多年 PIT 数据且 A 股实测多不可交易；后者违 no-dangling）。选：人工透明框架。
因子闭环    另造 lineage.py + reminder_register_id 双轨 → 否决（与 field_registry 重复）。选：field_registry 单一声明源 + lineage 仅运行时执行臂。
外部借鉴    照搬 [`HW-gitb/dsa_private`](https://github.com/HW-gitb/dsa_private) 的自由文本买卖点、固定止盈止损或自动权重等具体实现 → 否决。
            只借鉴“结构化建议→账户事件→结果复盘→风险约束”的工程思想；阈值、动作语义、长线 thesis 与 ship gate 由本仓库治理。
操作记忆    把 decision/outcome/账户事件塞进 6 个用户结果文件 → 否决（污染简洁输出和排他白名单）。
            选：机器账本走 gitignored 私密状态目录，结果表只留 decision_id 与必要状态。
历史校准    用历史回放补满 forward 月份 / shadow 自动切 canonical → 否决（会把研究结果冒充前向证据）。
            选：observation_kind 明确分轨 + 预注册 + 成熟门 + 人工审查 promotion。
目录        engine/us_long/ 子包 → 否决（与 us_short 扁平不一致）。选：扁平 engine/us_long_*.py。
并行轨      曾考虑 src/us_long + config/us_long 项目骨架 → 否决（仓库无 src/，违需求 #13）；其稳健细节（错误处理/孤儿列反查/reason_template/分字段降级）已吸收，布局未采。
```

---

## 20. 下一步（status）

```text
Tier 1（设计落文档）= 完成。本稿 2026-06-24 入 repo 作 docs/us_long_system_design.md（单一权威），桌面草稿退役。
Tier 2（机器骨架·样例数据）= 已授权、尚未开始实现。当前 repo 只有本设计权威和 reserved preset，没有 us_long engine/runner/schema/tests；按 §16 的 Cut 1-7 逐刀建设，样例端到端只写 staging/mock，不写 results_private、不联网。
数据/接入边界仍生效：Tier 2-3 只用本地样例；真实数据 / provider / adapter / DataHub / 联网留 Tier 4+ 单独授权。
仓库纪律：每片 schema-first + tests + 按 AGENTS.md 当前角色分工交独立审查；串行不交叉 A 股；不 auto-push。
开放项（Cut 1+ reconcile）：既存 presets/us_long.yaml（result_dir=result/us_long，status reserved_phase_9）+ research/results/us_long/README.md（lane_output_root("us_long")）的结果路径与本稿 §14「state/us_long/results_private/」口径不一致——§14 已明确 override 通用 result/ 约定（结果天然私密），待私密/排他守卫刀落地时统一并把 us_long.yaml 翻 active。
```
