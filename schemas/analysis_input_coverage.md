# analysis_input 1.0.0 覆盖率说明

Phase 1a 目标：先定义 `analysis_input.json` 的稳定输入合同，再让 `egs_main.py` 在 Phase 1b 按此合同输出数据。

当前结论：`analysis_input.schema.json` 对 v14.2 M0-M6 的字段覆盖率约 **93%**。剩余部分不是 schema 无法表达，而是 v14.2 依赖实时分钟数据、Level-2、外部搜索或账户状态，必须在后续 analyzer/state/Skill 阶段补齐。

## 已建立文件

- `schemas/analysis_input.schema.json`
- `schemas/examples/analysis_input.example.json`
- `schemas/analysis_input_coverage.md`

## 本轮审查修复

- `$schema` 对齐 Draft 7：`http://json-schema.org/draft-07/schema#`
- `schema_name` 新增为 `analysis_input`，`schema_version` 改为 SemVer：`1.0.0`
- `preset` 解锁为 `a_short/us_short/a_long/us_long`
- `market` 解锁为 `A/US`
- `horizon` 解锁为 `short/long`
- `source.screening_engine_version` 从 `const v7.5` 改为版本号 pattern
- `ts_code`、`exchange`、`board` 放宽到可承载 A 股与美股
- `quote.price_time` 改为 ISO 8601 datetime
- 数值字段补充单位说明
- Rule 6 补齐 `rule6_holder_below_5pct`、`rule6_cash_debt_double_high`、`rule6_short_selling_surge`
- `egs_main.py` 从源头补 `low_20d`，下一次完整运行会写入 `egs_full_YYYYMMDD.csv` 和 `analysis_input.json`
- 分数字段导出时裁剪到 0-100，保持 schema 语义不放宽
- `technical.pct_20d` / `technical.pct_5d` 明确为原始涨跌幅
- `technical.pct_20d_n` / `technical.pct_5d_n` 新增为 EGS 评分用处理后涨跌幅
- `liquidity.turnover_rate` 新增为换手率字段
- `result/a_short/YYYYMMDD/candidates.csv` 新增 `run_date` 列
- `snapshot.json` 继续保持 manifest，不承载 per-stock 明细

### 已退休：市场级 `market_context.liquidity`（2026-08-08，用户 2026-08-05 裁定「删」）

`market_context.liquidity.market_turnover_amount` 与 `market_context.liquidity.median_amount_20d` 是**从未生效的兼容占位**：生产者恒写 `null`，全仓没有任何市场级成交额消费者。当前 schema 版本已把整个市场级 `liquidity` 对象从 `market_context` 的 `required` 与 `properties` 中删除，**不保留运行时 alias、不留占位、不新增任何成交额阈值**。

- **逐票 `candidates[].liquidity` 完全不动**（`avg_amount_5d` / `avg_amount_20d` / `turnover_rate`）——短线真正的流动性风险是个股出不去，那道防线由逐票绝对额门槛承担，与本次删除无关。
- **为什么不是「留着标注有意不接」**：v14.2 的 regime 触发条件里没有成交额这一项，硬接等于在规格之外发明判据；而永远为 `null` 的公开字段只会制造「以后也许有用」的假契约。三条备选（接进 regime 判据 / 做个股相对基准 / 保留并标注）当时全部否决。
- **将来要恢复必须另开 schema-first 刀**，触发条件是 forward 账本显示「缩量区间里胜率或盈亏比系统性变差」，并按北向门同一条治理路走（带真实消费者 → 先只记录 → 回看统计 → 用户看过证据拍板 → 通电），同刀定清口径（两市还是含北交所、绝对额还是相对 20 日中位的量比）。
- 旧版 payload 夹带该对象会被 `additionalProperties:false` 拒绝，这是有意的：当前版不接受它。历史产物按既有 legacy migration 路径读取。

## 现有 EGS v7.6 已可直接供给的字段

来自 `A-EGS/Result/egs_tier1_YYYYMMDD.csv`：

- `ts_code`
- `name`
- `l2_name`
- `final_score`
- `tier`
- `pct_20d_n`
- `pct_5d_n`
- `pct_60d`
- `drawdown_20d`
- `cat_score`
- `l4_score`
- `esp_score`
- `l4_flag`
- `cninfo_flag`
- `entry_flag`

来自 `A-EGS/Result/egs_full_YYYYMMDD.csv` 的额外字段：

- 基础行情：`close`, `pct_20d`, `pct_20d_n`, `pct_5d`, `pct_5d_n`, `pct_60d`, `high_20d`, `low_20d`, `drawdown_20d`
- 行业：`l1_name`, `l2_name`, `l1_code`, `l2_code`
- 流动性：`avg_amount_5d`, `avg_amount_20d`, `turnover_rate`
- 估值/财务：`pe`, `pe_ttm`, `pb`, `roe`, `q0_dt_yoy`, `q1_dt_yoy`, `q0_profit_dedt`, `ttm_profit_dedt`, `ttm_ocf_ratio`（Tushare 百分数点；52.505 表示 52.505%）, `q0_dt_profit_ratio`
- 筛选评分：`l1_score`, `l2_flags`, `esp_raw`, `esp_score`, `cat_score`, `l4_score`, `egs_base`, `final_score`
- 风险标记：`reduce_deduct`, `reduce_penalty`, `has_crash_veto`, `chasing_high`, `overheat_flag`, `is_lock`, `is_breakout`

### TTM 扣非净利润语义

`candidates[].fundamental.profitability.ttm_profit_dedt` 保持 CNY nullable，且不改变 `analysis_input` 的 schema 版本或字段形状：

- 当最新可用 `q0` 为年度累计期（`YYYY1231`）时，TTM 直接取该期 `profit_dedt`。
- 当 `q0` 为非年度累计期时，TTM = `q0` 累计值 + 上一年度全年累计值 - 上一年度同期累计值；三项任一缺失、非数字或非有限值时输出 `null`，不使用旧四期重叠求和或 `fillna(0)` 回退。
- 每个 `ts_code/quarter` 只采用决策日（`ann_date <= decision_date`）前最新公告；不读取未来公告，也不改变现有来源、批量拆分重试和缓存身份边界。

### 有意不可用的兼容字段（不是数据缺口）

- `candidates[].fundamental.profitability.q0_net_income` 保留为 nullable 兼容字段，但 A-short 当前不取逐票 `income`，因此有意为空；它不是实时决策输入，也不应被当作“全表漏算”的因子。
- producer 内部的 `ttm_net_income` 同样是兼容性空值，且不发布为 `analysis_input` 叶字段。
- 这是用途替代，不是数值等价替代：非经常性损益质量检查读取 `q0_dt_profit_ratio`，OCF 质量检查读取 `ttm_ocf_ratio`（Tushare 百分数点；52.505 表示 52.505%）；`q0_profit_dedt` 是批量派生的伴随输出，不是 `q0_net_income` 的数值替代。

## EGS 字段到 schema 字段映射

| EGS/CSV 字段 | analysis_input 字段 | 说明 |
|---|---|---|
| `ts_code` | `candidates[].ts_code` | 股票代码 |
| `name` | `candidates[].name` | 股票名称 |
| `l2_name` | `candidates[].industry.sw_l2_name` | 申万二级行业名称 |
| `l2_code` | `candidates[].industry.sw_l2_code` | 申万二级行业代码 |
| `l1_name` | `candidates[].industry.sw_l1_name` | 申万一级行业名称 |
| `l1_code` | `candidates[].industry.sw_l1_code` | 申万一级行业代码 |
| `close` | `candidates[].quote.close` 和 `candidates[].quote.current_price` | 当前为 Tushare EOD 收盘价 |
| `pct_5d` | `candidates[].technical.pct_5d` | 原始 5 日涨跌幅 |
| `pct_5d_n` | `candidates[].technical.pct_5d_n` | EGS 评分/排序使用的处理后 5 日涨跌幅 |
| `pct_20d` | `candidates[].technical.pct_20d` | 原始 20 日涨跌幅 |
| `pct_20d_n` | `candidates[].technical.pct_20d_n` | EGS 评分/排序使用的处理后 20 日涨跌幅 |
| `pct_60d` | `candidates[].technical.pct_60d` | 60 日涨跌幅 |
| `high_20d` | `candidates[].technical.high_20d` 和 `technical.resistance.price` | 20 日高点 |
| `low_20d` | `candidates[].technical.low_20d` 和 `technical.support.price` | 20 日低点 |
| `drawdown_20d` | `candidates[].technical.drawdown_20d` | 相对 20 日高点回撤 |
| `avg_amount_5d` | `candidates[].liquidity.avg_amount_5d` | 5 日均成交额 |
| `avg_amount_20d` | `candidates[].liquidity.avg_amount_20d` | 20 日均成交额 |
| `turnover_rate` | `candidates[].liquidity.turnover_rate` | 换手率 |
| `big_ratio` | `candidates[].capital_flow.moneyflow.big_order_ratio` | 大单资金比率 |
| `final_score` | `candidates[].scores.final_score` | 最终评分 |
| `esp_score` | `candidates[].scores.esp_score` | 业绩/预期评分 |
| `cat_score` | `candidates[].scores.cat_score` 和 `catalyst.concept_strength_score` | 题材强度评分 |
| `l4_score` | `candidates[].scores.l4_score` | 动量/资金评分 |
| `l2_flags` | `candidates[].scores.l2_flags` | L2 财务/估值标记 |
| `q0_dt_profit_ratio` | `candidates[].fundamental.quality.q0_dt_profit_ratio` | Tushare `fina_indicator.dtprofit_to_profit`；用于非经常性损益质量检查，保留源口径 |
| `q0_net_income` | `candidates[].fundamental.profitability.q0_net_income` | A-short 有意不可用的 nullable 兼容字段；不进入实时决策 |
| `l4_flag` | `candidates[].scores.l4_flag` | L4 动量/形态标记 |
| `reduce_penalty` | `candidates[].event_risk.holder_reduction.reduce_penalty` | 减持扣分 |
| `val_bonus` | `candidates[].fundamental.valuation.val_bonus` | 估值加分 |
| `val_penalty` | `candidates[].fundamental.valuation.val_penalty` | 估值扣分 |
| `entry_flag` | `candidates[].selection.entry_flag` | 观察/确认提示 |
| `cninfo_flag` | `candidates[].selection.cninfo_flag` | 巨潮监管公告检查结果 |

## 文件角色说明

`snapshot.json` 是运行 manifest，只记录本次运行的时间、路径、数量、源文件和列清单。它不承载逐股记录。

逐股记录由以下两个文件承载：

- `result/a_short/YYYYMMDD/candidates.csv`：给人看的候选池表，包含 `run_date`
- `result/a_short/YYYYMMDD/analysis_input.json`：给 analyzer/Skill 读取的结构化输入

因此，任何要求校验 `ts_code/name/final_score/close/run_date/tier` 六字段的任务，验收对象应是 `candidates.csv`，不是 `snapshot.json`。

## v14.2 M0-M6 字段映射

| v14.2 模块 | schema 字段 | 当前状态 |
|---|---|---|
| M0 前置数据采集 | `candidates[].quote`, `candidates[].event_risk`, `candidates[].data_quality` | 已覆盖；实时价/前复权校验 Phase 3 补 |
| M0 板块权限排除 | `candidates[].board`, `event_risk.rule6_checks` | 已覆盖；EGS 当前已排除 300/688 等 |
| M0 Hard Veto 冷静期 | `state_refs.veto_log`, `event_risk.rule6_checks`, `derived_flags.hard_veto` | 已覆盖；状态文件 Phase 3 建 |
| M0 跨市场联动 | `llm_tasks.cross_market_linkage`, `event_risk.rule6_checks`, `market_context` | 已覆盖；数据源/LLM 后续补 |
| M0.5 波动率觉醒 | `market_context.volatility` | 已覆盖；IV feed 由 wrapper 显式五态传递，非 ready 时 EGS/M6.7 fail-closed |
| M1 市场环境 | `market_context.market_regime`, `market_context.breadth`, `market_context.northbound` | 已覆盖；规则计算 Phase 3 |
| Rule 3 IV 过滤 | `market_context.volatility.rule3_status`, `iv_percentile_252d` | 已覆盖；ready feed 由 producer 计算并由读门重算校验，非 ready 不执行 IV 闸门 |
| M2.0 前置否决 | `event_risk.rule6_checks`, `capital_flow`, `fundamental.quality` | 已覆盖；部分字段 Phase 1b/Skill 补 |
| M2.7 粗筛盈亏比 | `technical.support`, `technical.resistance`, `technical.coarse_reward_risk`, `market_context.market_regime.min_reward_risk` | 已覆盖；计算 Phase 3 |
| M2.1-M2.5 生态系统 | `industry`, `catalyst`, `llm_tasks`, `event_risk.regulatory` | 已覆盖；LLM 判断模板 Phase 4 |
| M2.6 10 日回溯 | `capital_flow.margin`, `capital_flow.northbound`, `capital_flow.block_trade` | 已覆盖；复合标记可由 analyzer 计算 |
| M3.1 基本面 | `fundamental`, `industry.industry_trend` | 已覆盖 |
| M3.2 技术面 | `technical`, `liquidity` | 已覆盖；EGS 候选层已由同一 65-session qfq 日线面板接入 MA/RSI/MACD/ATR 快照；Phase5 仍用独立 PIT `price_series` 重算正式指标 |

M3.2 技术快照的 MA/RSI/MACD/ATR 使用固定 qfq 口径；候选 ATR 为固定 ATR14，`atr_window` 表示实际参与平均的 14 个 True Range 观察数，`ex_rights_adjusted` 表示输入价格已做除权/公司行动调整。v14.2 §3.2 的近 14 日除权事件识别、ATR20 延窗和 M6.5 扰动提示尚未实现，详见风险登记中的对应条目；Phase5 正式指标仍沿独立 PIT `price_series` 链路。
| M3.3 财报与波动率 | `fundamental.expectation`, `market_context.volatility`, `volatility` | 已覆盖 |
| M3.3B IV/HV | `candidates[].volatility` | 已覆盖；HV 可由日线算，IV 待数据源 |
| M3.4 分析师目标价 | `analyst` | 已覆盖；数据源/搜索待接 |
| M3.5 持仓成本 | `account_context.positions`, `state_refs.positions` | 已覆盖；state Phase 3 建 |
| M3.6 止盈止损 | `technical.support`, `technical.resistance`, `technical.atr`, `technical.precise_reward_risk` | 已覆盖；计算 Phase 3 |
| M3.7 现价锚定 | `quote.current_price`, `quote.price_source`, `quote.price_time` | 已覆盖 |
| M4 Hard Veto | `event_risk.rule6_checks`, `derived_flags.hard_veto` | 已覆盖 |
| M4 升级审查 | `derived_flags.m4_review_required`, `event_risk.rule6_checks`, `analyst`, `capital_flow` | 已覆盖 |
| M5.1 效率自检 | `scores`, `catalyst`, `portfolio_impact` | 已覆盖；效率替代规则 Phase 3/4 |
| M5.2 时间窗口 | `catalyst.time_window` | 已覆盖 |
| M5.3 账户状态 | `account_context` | 已覆盖 |
| M5.4 星级 | `scores`, `industry.industry_trend`, `derived_flags` | 已覆盖；星级输出属于 deterministic_report |
| M5.5 相关性预演 | `portfolio_impact.same_sw_l2_exposure_after_buy_pct` | 已覆盖 |
| M5.5B 多因子风险 | `portfolio_impact.factor_exposures` | 已覆盖 |
| M6.3 操作价格表 | `account_context`, `liquidity`, `technical`, `market_context.market_regime` | 已覆盖 |
| M6.5 风险提示 | `event_risk.rule6_checks`, `derived_flags`, `portfolio_impact` | 已覆盖 |
| M6.6 OrderAudit | `state_refs`, `technical`, `event_risk`, `market_context` | 已覆盖；输出结果属于 deterministic_report |
| M6.7 操作建议 | 输入字段已覆盖；最终表属于 `deterministic_report.schema.json` | 已覆盖输入，不在本 schema 输出 |
| M6.8 隔离协议 | `state_refs.veto_log`, `derived_flags.hard_veto` | 已覆盖 |

## 7.1 unavailable 分类与当前版本边界（2026-08-18）

- 当前 EGS exporter 输出 `analysis_input` schema `1.6.0`，`EGS_VERSION=v7.15`；`data_quality.completeness_score` 仍按既有 `core_quality_fields` 23 项计算，分类数组只解释缺失原因，不改变分母或分数。
- 当前全局不可用分类固定为三个互不重叠的 field-path 数组：`permanently_unavailable=["capital_flow.northbound"]`、`paid_source_declined=["analyst.target_price_mean"]`、`candidate_output_deferred=["capital_flow.block_trade"]`。三者并集恰为 3 个全局 unavailable 字段，且都保留在 `missing_fields`。
- `capital_flow.block_trade` 的 Rule6 `get_rule6_block_trades()` / `evaluate_block_trade_discount()` 仍然接通；但候选摘要的三个 block-trade 叶仍是 null/unmaterialized，输出语义尚未决定，因此不从 `missing_fields` 移除，也不把 Rule6 metrics 推入候选摘要。
- `capital_flow.northbound` 仍是逐股源永久不可用；`analyst.target_price_mean` 仍是付费源未采购；技术四项已由 6.1 接通，短历史技术 null 只属于候选自身缺失，不进入上述三类。
- `data_quality_shadow` producer 与独立 schema 已升至 `1.1.0`，weekly 只原样 passthrough；shadow 仍 `comparison_only=true`、`production_effect_enabled=false`、`activation=disabled_pending_shadow_review`，不改变 Phase5 动作。
- 本工作树没有可供本轮重读的当前 official `analysis_input.json`；上述状态以当前 producer/schema/consumer 闭合和已有真实产物记录为依据，真实周 artifact 仍须在后续获授权后复核，不把本轮 offline focused/full lane 当成真实周证明。

## Phase 2 待办

- rank 回测必须专门统计 Rule 6 各项的历史预测力
- 增加 `q0_dt_yoy > 200%`、`q1_dt_yoy > 200%`、`esp_raw` 极端值分组，验证低基数高增长标的的未来 20 日收益是否显著优于普通候选
- 若极端同比组没有超额收益，在 `esp_raw` 计算中加入 winsorize 或低基数惩罚
- 统计 `data_quality.completeness_score` 与后验收益的关系，决定哪些缺失字段会让样本退出 rank 回测

## v14.2 初步漏洞/优化提示

1. **M0 要求实时联网价，但 A 股短线系统的数据主干是 Tushare EOD。**  
   后续应把 `analysis_mode` 拆成 `post_close`、`pre_open`、`intraday_manual`，不同模式允许的字段和规则不同。
2. **Rule 6 同时包含硬否决、升级审查、持仓处置三类逻辑。**  
   schema 已用 `group: pre_veto/post_veto/review/risk_note` 拆开，Phase 3 写 analyzer 时必须沿用。
3. **M6.7 输出和 M6.6 OrderAudit 有覆盖关系，但 v14.2 没有独立输出契约。**  
   Phase 3 前必须设计 `deterministic_report.schema.json`。
4. **Level-2/分钟级规则无法由当前 Tushare 日线数据完整支持。**  
   Rule 6.1 当前只能作为持仓盘后近似回溯/低置信度提示，不能作为 Phase 1-4 的硬执行规则。
5. **部分阈值写死在 v14.2 文本中，不应进入代码常量。**  
   ATR 系数、IV 分位、仓位上限、盈亏比、时间止损天数等必须进入 `presets/a_short.yaml`。
6. **M5.4 星级是过程结果，不适合放在 analysis_input 里作为输入真相。**  
   星级应由 analyzer 根据 input 计算，并写入 deterministic_report。
7. **Rule 11 的“搜索失败后触发数据备用协议”需要审计字段。**  
   后续 deterministic_report 应记录搜索词、搜索时间、来源和失败原因。

## Phase 1a + 1b 验收判定

- `analysis_input.schema.json` 存在并通过 JSON Schema 自检
- `analysis_input.example.json` 存在并通过 JSON Schema 校验
- `egs_main.py` 已接入 `analysis_input.json`、`snapshot.json`、`candidates.csv` 导出器
- 最新导出文件通过 schema 校验
- M0-M6 字段覆盖率约 93%，超过 90% 门槛
