# A-short V14.3 市场环境(regime)分类器 — comparison-only 设计与实现边界

**日期**: 2026-06-11
**来源**: 用户桌面 `regime优化建议.md` + 此前多轮收敛 + Claude 简化。
**类型**: comparison-only 的权威设计边界；已落地 raw classifier、daily-feature/ledger 与 P1 Cut1 纯逻辑，仍**不解冻 V14.2 spec、不碰生产、不接 Phase 5、不改任何风控开关**。当前未完成项只见 §6。

## 0. 定位与边界(最重要)
- **V14.2 M1 仍是冻结的生产基线**;V14.3 是**并行的 comparison-only 候选分类器**,只用于打标 / 差异对比 / 面板展示 / 验证数据积累。
- V14.3 **不得**改变 production 选股、单只/总仓上限、盈亏比、ATR、IV 闸门、新建仓权限,**不得**与 overlay 星级 / M6.7 最终动作 / 建仓结论混写。
- 切换生产 = 遥远、单独切片、审查 + 用户明确确认;**绝不自动切换、绝不在建造轮顺手切**。
- governance `boundary`:`comparison_only=true`、`production_switch_authorized=false`、`changes_phase5_downstream=false`、`v14_2_remains_frozen_baseline=true`。

## 1. 为什么走 V14.3-comparison(而非 V14.2-原样)
V14.2 M1 用含糊的"涨停指数"(3/4 档都依赖它),且收缩窄、震荡非残差、阈值固定、慢阴跌盲、滞后不全。V14.3 用**可精确 PIT 计算的 晋级率 + 炸板率**替代涨停指数——**顺带解决了卡住 V14.2-原样实现的"涨停指数数据源"难题**。故 regime 这块走 V14.3-comparison 更顺。

## 2. 数据层（实现状态见 §6）
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

## 4. 状态机（P1 Cut1 已实现纯逻辑；仍不接 weekly / M6.7 / production）
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

P1 的逐股比较暂以 `defense` / `contraction` 禁止新建仓、现金 0% 作**简化代理**；它不裁决上表“普通防御”的最终生产政策，不能据此切换生产。

## 6. 当前分阶段状态
- **已完成**：schema/governance、raw classifier、daily-feature ledger/比较 runner 及其既有 market-level comparison-only 证据链；生产 `market_context.market_regime.status` 仍可能为 `unknown`，不把它误称为 V14.2 regime-gated baseline。
- **P1 Cut1（2026-07-19）**：`build_stateful_regime_history` / `classify_stateful_regime` 已将本节状态机落为纯逻辑；`build_candidate_effect_record` / `summarize_candidate_effect_records` 以相同周等权汇总逐股净收益、CSI1000 超额与代理操作改善。数据不足输出不可评估并打断确认；历史回放、未成熟收益和 policy fingerprint 不匹配不得计数或混算。
- **P1 Cut2 仍待独立审查 PASS 后才可开始**：只读接入既有 `forward_tracker`，冻结 live 候选并写私有账本/公开汇总；不得改变新建仓授权、EGS、M6.7、账户或正式周报。
- **切换生产(遥远)**:单独切片,动作矩阵接线 + 历史对比 + ≥12 周 forward-live + 审查 + 用户确认。

## 7. switch-candidate 提醒门槛(切片3 规格,本切片入 governance)
仅当全部满足才输出"考虑切换"提醒(**只提醒、不自动切**):forward-live ≥12 周 **且** 独立、PIT 合格的回测 ≥2 年;分歧样本 ≥8 次;分歧样本净改善明显(更早识别防御/收缩、减回撤、不显著错过进攻);经审查非偶然/数据污染。运行时的 D2 自动提醒只证明前瞻动作对比已进入复核窗口，要求补齐这些非自动判定项；它不是本段的最终切换提醒。

**提醒文案固定**:门槛达成且审查确认后,必须向用户明确提示: **"V14.3 regime 可能优于 V14.2，是否进入生产切换审查?"**。若用户确认,再单独起 production-switch 切片;该切片才允许讨论让 V14.3 接管 production regime、接线动作矩阵、更新 EGS/analysis_input/Phase5 消费与测试。未得到用户确认前,继续 comparison-only,绝不自动替换。

## 8. 对刚完成的 overlay/面板的影响
既有面板有一个**常驻、独立、明确 comparison-only 的 "Regime comparison" 段**(`Production: V14.2 X | Candidate: V14.3 Y | comparison-only | 证据 n/12 周`)，**绝不**与 overlay 星级 / M6.7 动作 / 建仓结论混写。

## 9. 当前交付物
- raw/stateful regime：`engine/a_short_regime_classifier.py`、daily/ledger/runner 和既有 schema/governance/test 路由见 `docs/README.md`。
- P1 Cut1：`presets/a_short_regime_action_comparison_governance_20260714.json`、`schemas/a_short_regime_action_comparison_governance.schema.json`、`schemas/a_short_regime_candidate_effect_summary.schema.json`、`engine/a_short_regime_action_comparison.py` 与对应单测。
- **无 P1 weekly 接线、无真实逐股证据文件、无生产改动；V14.2 仍为生产基线。**
