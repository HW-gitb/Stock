# A-short V14.3 市场环境(regime)分类器 — schema-first 设计提案(切片1)

**日期**: 2026-06-11
**来源**: 用户桌面 `regime优化建议.md` + 此前多轮收敛 + Claude 简化。
**类型**: **design-only / schema-first 提案**。**不解冻 V14.2 spec、不碰生产、不接 Phase 5、不改任何风控开关。** 本切片只产出:设计文档 + 数据契约 schema + governance artifact(钉死指标口径/阈值/状态机/下游动作矩阵/边界)+ schema 测试。**无 runner 代码**(那是切片2)。

## 0. 定位与边界(最重要)
- **V14.2 M1 仍是冻结的生产基线**;V14.3 是**并行的 comparison-only 候选分类器**,只用于打标 / 差异对比 / 面板展示 / 验证数据积累。
- V14.3 **不得**改变 production 选股、单只/总仓上限、盈亏比、ATR、IV 闸门、新建仓权限,**不得**与 overlay 星级 / M6.7 最终动作 / 建仓结论混写。
- 切换生产 = 遥远、单独切片、审查 + 用户明确确认;**绝不自动切换、绝不在建造轮顺手切**。
- governance `boundary`:`comparison_only=true`、`production_switch_authorized=false`、`changes_phase5_downstream=false`、`v14_2_remains_frozen_baseline=true`。

## 1. 为什么走 V14.3-comparison(而非 V14.2-原样)
V14.2 M1 用含糊的"涨停指数"(3/4 档都依赖它),且收缩窄、震荡非残差、阈值固定、慢阴跌盲、滞后不全。V14.3 用**可精确 PIT 计算的 晋级率 + 炸板率**替代涨停指数——**顺带解决了卡住 V14.2-原样实现的"涨停指数数据源"难题**。故 regime 这块走 V14.3-comparison 更顺。

## 2. 数据层(切片2 实现;本切片只定契约)
**`a_short_market_regime_daily`**(每交易日一行)。**简化:在 EGS run 内算**(复用内存全量日线 `all_daily` + 一个 `stk_limit` 调用 + L3/指数),落到 a_short lane 桶——**不另起独立日频管线**(同 industry_heat/overlay 的 A 方案)。
字段:`as_of` / `limit_up_count` / `limit_down_count` / `net_limit` / `max_limit_streak` / `promotion_rate` / `failed_limit_rate` / `iv_percentile_252d` / `csi300_ret_1d` / `csi1000_ret_1d` / `pct_above_ma20` / `csi1000_below_ma20`(慢阴跌操作数:CSI1000 收盘 < 其 20d MA;指数缺失则 null + flag `csi1000_unavailable`,**schema if/then 强制**:`csi1000_below_ma20=null` 时 `data_quality_flags` 必含 `csi1000_unavailable`,不得悬空)/ `data_quality_flags`。
**PIT 口径(硬要求,schema/governance 钉死):**
- 涨跌停判定用**未复权 `daily` + `stk_limit` 同口径价**;炸板 = `high >= up_limit*0.999 且 close < up_limit*0.999`(不是 `high==up_limit`);照顾 ±10%/±20%/ST±5% 不同涨跌幅制度。
- 晋级率 = 昨日封板股今日再封板占比;分母过小标 `insufficient_sample`,**不得硬判进攻**。
- universe = 当日可交易**主板** A 股(PIT,不用现存活股回看;沪市 600/601/603/605 + 深市 000/001/002/003,**排除创业板/科创板/北交所**——用户口径"A股只操作主板",复用 `engine/data/a_share_board_scope.py`);所有 252d 分位只用 `<= as_of` 窗口。

## 3. V14.3 四档 raw 判定(优先级 top-down;最终输出还需状态机防抖)
**① 防御期(任一即触发,向下快):** `iv_percentile_252d>90` / `limit_down_count>=max(P95_252,100)` / `csi1000_ret_1d<=-3.5% 或 csi300_ret_1d<=-3.0%` / `promotion_rate<=10% ∧ net_limit<0 ∧ failed_limit_rate>P75_252`。
**② 收缩期(非防御前提,任一,一般需连续 2 日确认):** `max_limit_streak<=3 ∧ 近3日峰值≥5 ∧ 回落≥2` / `promotion_rate<25% 连续2日 ∧ failed_limit_rate>P75_252` / `pct_above_ma20<30% 连续5日 ∧ csi1000_below_ma20`(覆盖退潮 + 慢阴跌;`csi1000_below_ma20` 是 daily 契约里的显式字段,缺失则 null + flag,不悬空)。
**③ 进攻期(连续 3 日全满足,期间无防御/收缩 raw hit):** `max_limit_streak>=max(P75_252,5)` ∧ `promotion_rate>=max(P60_252,50%)` ∧ `net_limit>0` ∧ **`limit_down_count<=min(50,max(P25_252,10))`** ∧ `failed_limit_rate<=P50_252` ∧ `iv_percentile_252d<=80`。
> **修正(原方案 bug):低风险阈值是上限不是地板** —— 跌停数用 `min(50, max(P25,10))`(上限),不能写 `max(P25,50)`(否则平静期阈值过宽)。
**④ 震荡期 = 残差默认**(不满足①②③的一切)。**删除**旧"涨停指数跌 2-3%"窄带触发。

## 4. 状态机(切片3 实现;本切片只定规格)
- 极端风险(IV>90 / 跌停潮 / 宽基暴跌)**允许任意档跨级直跳防御**(风控不慢半拍)。
- 普通防御从进攻触发 → 先降震荡,次日仍触发再转防御。
- 收缩需连续 2 日 raw、进攻需连续 3 日 raw;防御/收缩退回震荡需连续 2 日 clear。
- 禁止收缩→进攻直跳(须先回震荡再满足进攻确认)。
- 首次默认震荡期。

## 5. 下游动作矩阵(**本切片只文档化 + 入 governance,绝不接线**;切换生产时才裁决/接线)
| regime | 新建仓 | 单只上限 | 总仓上限 | 盈亏比 | ATR |
|---|---|---:|---:|---:|---|
| 进攻期 | 允许 | 50% | 80% | ≥1.5 | 进攻 |
| 震荡期 | 允许 | 40% | 60% | ≥1.5 | 震荡 |
| 普通防御期 | 严格限制/只防御型 | 25% | 50% | ≥2.0 | 防御 |
| 极端防御期 | 禁止 | 0% | 降风险 | N/A | N/A |
| 收缩期 | 禁止 | 0% | 降风险 | N/A | 震荡/收缩 |
**关键未决(留给切换切片):防御期到底"禁建仓"还是"允许极小仓+严格收紧"。** v1 不裁决也不接线(comparison-only)。

## 6. 简化的分阶段落地(Claude 砍法 —— 别一次性全建)
- **切片1(本切片)**:design + schema(daily 契约 + governance)+ 测试。纯提案,零生产。
- **切片2**:v1 comparison-only —— EGS run 内算 raw regime + 每周记一行 `v14_2 / v14_3_raw / 是否分歧 / 后续 1/3/5/10 日表现`(原始数据)+ 面板加**独立、标 comparison-only 的 regime 对比段**。**启动证据时钟。**
  - **切片2a(已起草,2026-06-11):纯 raw-classifier 逻辑核**。`engine/a_short_regime_classifier.py` 的 `classify_raw_regime(history)` 吃 daily-feature 历史 → 出 per-day raw regime(top-down 优先级,忠实实现切片1 governance 阈值;分位 resolver 镜像 const 串并 parity-test;连续日算子遇 null 断;attack 须全满足、任一 null 即不判;窗口不足 / CSI1000 缺失诚实标 flag)。**不含状态机 / confirm-days / 评分**(切片3;但记录 per-day 命中供切片3 在其上做确认)。`build_comparison_record` = 周度 v14_2-vs-v14_3_raw + 分歧 + 前向 1/3/5/10 日收益(未到期 null,后续回填,绝不 look-ahead),契约 `schemas/a_short_regime_comparison_weekly.schema.json`。**纯逻辑、无数据抓取、无 EGS 接线、无生产改动。** **证据契约硬化(Codex 审查后):** `v14_2_regime` 钉到生产枚举 `{attack,shock,defense,contraction,unknown}`、`v14_3_fired_rule` 钉到合法规则集、**前向收益基准 const-pin** `forward_return_basis`(CSI1000 `000852.SH` / forward close-to-close simple return / h1·h3·h5·h10=1·3·5·10 交易日 / unit=percent / index_close_unadjusted / gross / market-level regime indicator —— 不混 raw/excess、decimal/percent、gross/cost);跨字段不变式(divergence==(v14_2≠v14_3_raw)、pending 恰等空值 horizon、backfill_complete==无空值、fired_rule 属对应 regime)由 `validate_comparison_record` 强制(JSON Schema 表达不了),producer 落盘前自校验。
  - **切片2b(待 cadence 决策后起草):in-EGS daily-feature 生产 + 接线 + 面板。** **可行性缺口(切片1 未解):** §3 阈值要 **252 交易日滚动分位**,但 EGS run 是**周频**、当日只产一行,拿不到 252 日 breadth 历史。`index_daily` 取 CSI300/1000(ret_1d、MA20)+ IV(已在 market_context)是廉价的,但 **breadth 分位历史**须解决:**方案 = 持久化一个增量 daily-feature ledger(落 a_short lane,一次性回填 252 交易日,之后每周只补新增 ~5 日,252d 分位从 ledger 读)**,而非每周回算 252×(daily+stk_limit) 调用。该 ledger 是新的受管状态文件,属实质设计新增,切片2b 起草前须把它定下来并审查。另注:生产 `market_context.market_regime.status` 当前=`unknown`(EGS 未真算 V14.2 M1),故 v14_2 一侧多为 `unknown` —— 对比记录的 `v14_2_regime` 契约已允许 `unknown`,分歧统计仍有意义(V14.3 何时判防御/收缩而生产仍 unknown/震荡)。
- **切片3(推迟到有数据)**:跨周持久化状态机 + 自动评分 + switch-candidate 提醒(累积 ≥12 周再建评分器,避免无数据先造打分器)。
- **切换生产(遥远)**:单独切片,动作矩阵接线 + 历史对比 + ≥12 周 forward-live + 审查 + 用户确认。

## 7. switch-candidate 提醒门槛(切片3 规格,本切片入 governance)
仅当全部满足才输出"考虑切换"提醒(**只提醒、不自动切**):forward-live ≥12 周 或 回测 ≥2 年;分歧样本 ≥8 次;分歧样本净改善明显(更早识别防御/收缩、减回撤、不显著错过进攻);经审查非偶然/数据污染。

**提醒文案固定**:门槛达成且审查确认后,必须向用户明确提示: **"V14.3 regime 可能优于 V14.2，是否进入生产切换审查?"**。若用户确认,再单独起 production-switch 切片;该切片才允许讨论让 V14.3 接管 production regime、接线动作矩阵、更新 EGS/analysis_input/Phase5 消费与测试。未得到用户确认前,继续 comparison-only,绝不自动替换。

## 8. 对刚完成的 overlay/面板的影响
面板加一个**常驻、独立、明确 comparison-only 的 "Regime comparison" 段**(`Production: V14.2 X | Candidate: V14.3 Y | comparison-only | 证据 n/12 周`),**绝不**与 overlay 星级 / M6.7 动作 / 建仓结论混写。切片2 实现。

## 9. 本切片交付物
- 本设计文档。
- `schemas/a_short_market_regime_daily.schema.json`(daily 特征契约,PIT 字段)。
- `presets/a_short_v14_3_regime_governance_20260611.json`(钉死指标口径/阈值/状态机/动作矩阵/门槛/边界)+ `schemas/a_short_v14_3_regime_governance.schema.json`(const-pin parity)。
- `tests/test_a_short_v14_3_regime_governance.py`(schema 合法 + governance 过 schema + boundary comparison-only + 阈值/动作矩阵齐全)。
- **无 runner / 无生产改动 / V14.2 不动。**
