# A-short 周报 M6.7 — 20260612

> ⚠️ **非生产 / A-short risk_filter_only / edge 未验证**。所有「建仓」均为 **试探仓**,**止损无条件**(盘中由你手动),仅供参考,非买卖指令。

**环境**:震荡期(EGS regime unknown,保守fallback)　|　**波动率**:IV分位≈50.7937% | Rule3减半:否
**共 15 只** — 建仓 0 / 持有 0 / 观察 15 / 否决 0
> ⚠️ **市场 regime 未知 → 全员按震荡期保守降级(统一 −1 星)**。星级反映的是**当前市场保守状态**,不是个股质量差;**个股质量看下表「EGS分」列**。(V14.3 regime 分类器接入 production 前,每次实盘都会如此。)
> ⚠️ **无账户(account_status=absent):仓位 sizing N/A —— 建仓候选会渲染为「观察」(可建股数/金额不足),这是 **sizing 假象、非真 avoid 信号**;传 `--account` / `-Account`(account-state JSON: cash/positions/Rule12/Rule13)以获真 sizing/持仓判断。**
**lineage**:analysis_input=`result/a_short/20260612/analysis_input.json` | iv_feed=`research/results/a_short/iv_feed_20260612/iv_feed.json` | account=absent | account_ref=`` | sizing=observation_only_no_account

## 一览
| 票 | 名称 | 操作 | EGS分 | 优先级 | 类型 | 入 | 损 | 盈一 | 盈二 | 股数 |
|---|---|---|---|---|---|---|---|---|---|---|
| 000776.SZ | 广发证券 | 观察 | 82.66 | ⭐×2 | N/A |  |  |  |  |  |
| 000722.SZ | 湖南发展 | 观察 | 81.77 | ⭐×2 | N/A |  |  |  |  |  |
| 003025.SZ | 思进智能 | 观察 | 75.94 | ⭐×2 | N/A |  |  |  |  |  |
| 603337.SH | 杰克科技 | 观察 | 71.71 | ⭐×2 | N/A |  |  |  |  |  |
| 601377.SH | 兴业证券 | 观察 | 69.06 | ⭐×2 | N/A |  |  |  |  |  |
| 002078.SZ | 太阳纸业 | 观察 | 65.94 | ⭐×2 | N/A |  |  |  |  |  |
| 000926.SZ | 福星股份 | 观察 | 65.62 | ⭐×2 | N/A |  |  |  |  |  |
| 000686.SZ | 东北证券 | 观察 | 64.66 | ⭐×2 | N/A |  |  |  |  |  |
| 601156.SH | 东航物流 | 观察 | 63.46 | ⭐×2 | N/A |  |  |  |  |  |
| 002436.SZ | 兴森科技 | 观察 | 62.48 | ⭐×2 | N/A |  |  |  |  |  |
| 600025.SH | 华能水电 | 观察 | 58.9 | ⭐×2 | N/A |  |  |  |  |  |
| 002916.SZ | 深南电路 | 观察 | 58.88 | ⭐×2 | N/A |  |  |  |  |  |
| 001389.SZ | 广合科技 | 观察 | 58.88 | ⭐×2 | N/A |  |  |  |  |  |
| 600030.SH | 中信证券 | 观察 | 58.34 | ⭐×2 | N/A |  |  |  |  |  |
| 600522.SH | 中天科技 | 观察 | 56.59 | ⭐×2 | N/A |  |  |  |  |  |

## 逐票
### 000776.SZ 广发证券 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:20.08 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理|语义web/LLM:risk(medium)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web risk/medium/observe·1源·impact=downgrade
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理/语义web/LLM:risk(medium)。
- 触发/说明:未到低吸/突破触发

### 000722.SZ 湖南发展 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:15.07 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 003025.SZ 思进智能 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:16.25 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 603337.SH 杰克科技 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:38.45 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web tailwind/low/no_action·3源·impact=none
- **操作建议**:观察,不建仓。原因:现价跌破 MA5/10/20,等收复。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:现价跌破 MA5/10/20,等收复

### 601377.SH 兴业证券 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:6.0 | 试探仓
- 否决审查触发:语义待核:官方 medium/low 命中(例行件),待复核(未扣分,待 web/LLM 实判)
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·1事件·impact=pending / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 002078.SZ 太阳纸业 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:13.76 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 000926.SZ 福星股份 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:2.17 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:现价跌破 MA5/10/20,等收复。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:现价跌破 MA5/10/20,等收复

### 000686.SZ 东北证券 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:7.83 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 601156.SH 东航物流 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:16.68 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 002436.SZ 兴森科技 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:37.8 | 试探仓
- 否决审查触发:语义待核:官方 medium/low 命中(例行件),待复核(未扣分,待 web/LLM 实判)
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·2事件·impact=pending / web tailwind/none/no_action·1源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 600025.SH 华能水电 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:9.86 | 试探仓
- 否决审查触发:语义待核:官方 medium/low 命中(例行件),待复核(未扣分,待 web/LLM 实判)
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·1事件·impact=pending / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 002916.SZ 深南电路 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:379.5 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 001389.SZ 广合科技 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:178.4 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web tailwind/none/no_action·1源·impact=none
- **操作建议**:观察,不建仓。原因:现价跌破 MA5/10/20,等收复。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:现价跌破 MA5/10/20,等收复

### 600030.SH 中信证券 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:26.29 | 试探仓
- 否决审查触发:无
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发

### 600522.SH 中天科技 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈50.7937% | Rule3减半:否
- 现价与成本:48.6 | 试探仓
- 否决审查触发:语义待核:官方 medium/low 命中(例行件),待复核(未扣分,待 web/LLM 实判)
- 板块资金事件:neutral
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·1事件·impact=pending / web unknown/unknown/no_action·0源·impact=none
- **操作建议**:观察,不建仓。原因:未到低吸/突破触发。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:未到低吸/突破触发
