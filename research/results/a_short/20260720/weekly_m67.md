# A-short 周报 M6.7 — 20260720

> ⚠️ **非生产 / A-short risk_filter_only / edge 未验证**。所有「建仓」均为 **试探仓**,**止损无条件**(盘中由你手动),仅供参考,非买卖指令。

**环境**:震荡期(EGS regime unknown,保守fallback)　|　**波动率**:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
**共 15 只** — 建仓 0 / 持有 0 / 观察 0 / 否决 15
> ⚠️ **市场 regime 未知 → 全员按震荡期保守降级(统一 −1 星)**。星级反映的是**当前市场保守状态**,不是个股质量差;**个股质量看下表「EGS分」列**。(V14.3 regime 分类器接入 production 前,每次实盘都会如此。)
**run**:id=`a-short-20260720-97c019888faa4c01` | candidate_digest=`97c019888faa4c014a5ba82196b3452427e6f05b9e167d5f3b46496e938173df` | stage=complete
**配置**:fingerprint=`935abac736f77a65390c22b71b2351258cbc36a80c7dd044ffca90531a9474e7` | policies=`a_short_screening_runtime_policy_20260715,a_short_m67_runtime_policy_20260715`
> ⚠️ **无账户(account_status=absent):仓位 sizing N/A —— 建仓候选会渲染为「观察」(可建股数/金额不足),这是 **sizing 假象、非真 avoid 信号**;传 `--account` / `-Account`(account-state JSON: cash/positions/Rule12/Rule13)以获真 sizing/持仓判断。**
**lineage**:analysis_input=`result/a_short/20260720/analysis_input.json` | iv_feed=`research/results/a_short/iv_feed_20260720/iv_feed.json` | account=absent | account_ref=`` | sizing=observation_only_no_account
**IV clock**:status=aligned | IV数据截至 `20260717`
**market regime**:source=`unknown` | effective=`shock` (震荡期) | fallback=true
**price clock**:mode=intraday_prior_settled | 价格数据截至 `20260717` | run_date=`20260719` | 前一交易日 `20260717`
> ⚠️ **价格时钟**:本周报技术指标用的是**前一交易日(20260717)已结算行情**(实盘盘中跑、as_of 20260720 当日 EOD 尚未发布);新闻/语义层窗口仍到 as_of。**价格特征截至 20260717,非 20260720。**
**Comparison v2**: 对比轨 v2：证据不可用或结论未定；不显示旧提醒，生产结论不变。

## 组合集中度与因子共振（M5.5/M5.5B）
- 状态：暂不适用
- 核查口径：tushare:daily_basic+margin_detail+hk_hold+index_member（20260720）
- 最终持仓不足2只，M5.5B不适用

| 标的 | 类型 | 结果 | 最终联动 | 原因 |
|---|---|---|---|---|
| 600285.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 601211.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600415.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600233.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600900.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 601058.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 002926.SZ | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 603259.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 002668.SZ | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600329.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600025.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 002468.SZ | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 002603.SZ | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 603882.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600886.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |

## 字段/规则联动台账
- 已登记 26 组：已联动 2；本周未触发 0；不可自动判定、需人工复核 22；刻意独立 2。
> ⚠️ 下列已登记字段/规则当前没有安全的自动结果路径，已明确提示人工复核，不能当作无影响。

| 字段/规则组 | 原因 |
|---|---|
| identity_batch_gate | weekly.run_lineage 只保留部分批次身份；preset、provider、L3 和 state_refs 等其余叶字段尚未逐叶证明 M6.7 消费者，整组不得报已联动。 |
| l3_coverage_provenance | 主干新增的 HiThink L3 覆盖与溯源字段尚未逐叶证明被正式 M6.7 消费；必须显式人工复核。 |
| universe_selection | 筛选统计会随候选进入周报，但尚未逐字段证明各统计量对正式 M6.7 的消费者；不能只因本周有候选就报已联动。 |
| market_context | 正式 weekly 当前只读取市场状态等少数字段，整组其余广度、流动性、北向、日历和波动率叶字段尚未逐叶证明消费者；不能报已联动。 |
| account_context | 正式现金分配读取独立账户输入；analysis_input.account_context 尚未逐叶证明为 M6.7 消费者，必须人工核查。 |
| candidate_identity_selection | 代码和名称会展示，但交易所、板块、角色和 selection 尚未逐字段证明为正式 M6.7 消费者；本组必须人工核查。 |
| candidate_quote | weekly 目前只取 quote.close；其余报价叶字段尚未接入，整组不得报已联动。 |
| candidate_industry_classification | 组合模块只使用 SW L2；SW L1 叶字段尚未逐叶证明消费者，整组不得报已联动。 |
| industry_trend | 存在缺失、损坏、串线或陈旧的行业热度信号，已显式人工复核 |
| industry_fundamental_advisory | 主干的行业基本面 LLM advisory 仍是独立的 Phase 3/4 接线；本切片不把它误报为已联动。 |
| candidate_scores | weekly 只转入少数 ESP/L4/总分和质量旗标；其余 scores 叶字段未逐叶证明 M6.7 消费者，整组不得报已联动。 |
| candidate_technical | analysis_input.technical 当前没有被 weekly/Phase5 的候选消费者逐叶读取；不得因候选存在而误报已联动。 |
| candidate_fundamental | 少数基本面叶字段会转成财报质量 advisory 或组合事实，但整组仍有未证明的叶字段；未逐叶拆开前不能报已联动。 |
| candidate_capital_flow | 北向持股比例和融资占比会进入组合事实，但其余资金流叶字段尚无 weekly 消费者；未逐叶拆开前不能报已联动。 |
| candidate_event_risk | weekly 只转入部分减持、退市和停牌事实；监管、解禁及其余事件叶字段尚未逐叶证明消费者，整组不得报已联动。 |
| candidate_catalyst | analysis_input.catalyst 当前没有被 weekly/Phase5 的候选消费者逐叶读取；必须人工核查。 |
| candidate_liquidity | weekly 只使用 5/20 日成交额；其余流动性叶字段尚未逐叶证明消费者，整组不得报已联动。 |
| candidate_volatility | analysis_input.volatility 当前未接入 weekly 的 IV/HV 输入；周报使用的是独立 IV feed，不能误报本组已联动。 |
| candidate_analyst | analysis_input.analyst 当前没有 weekly/Phase5 消费者；必须人工核查。 |
| portfolio_concentration_factor_resonance | M5.5/M5.5B 使用部分因子暴露字段；correlation_action、阈值等其余叶字段尚未逐叶证明消费者，整组不得报已联动。 |
| candidate_derived_flags | weekly 使用多个 derived flag，但 m4_review_required 等叶字段尚未逐叶证明消费者；整组不得报已联动。 |
| candidate_data_quality | analysis_input.data_quality 当前未驱动 weekly 的数据缺失处置或操作；必须人工核查。 |

## 一览
| 票 | 名称 | 操作 | 持仓/冷静 | EGS分 | 优先级 | 类型 | 入 | 损 | 盈一 | 盈二 | 股数 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 600285.SH | 羚锐制药 | 否决 | — | 95.71 | — | N/A |  |  |  |  |  |
| 601211.SH | 国泰海通 | 否决 | — | 89.93 | — | N/A |  |  |  |  |  |
| 600415.SH | 小商品城 | 否决 | — | 88.35 | — | N/A |  |  |  |  |  |
| 600233.SH | 圆通速递 | 否决 | — | 78.11 | — | N/A |  |  |  |  |  |
| 600900.SH | 长江电力 | 否决 | — | 77.86 | — | N/A |  |  |  |  |  |
| 601058.SH | 赛轮轮胎 | 否决 | — | 75.27 | — | N/A |  |  |  |  |  |
| 002926.SZ | 华西证券 | 否决 | — | 74.91 | — | N/A |  |  |  |  |  |
| 603259.SH | 药明康德 | 否决 | — | 74.16 | — | N/A |  |  |  |  |  |
| 002668.SZ | TCL智家 | 否决 | — | 73.59 | — | N/A |  |  |  |  |  |
| 600329.SH | 达仁堂 | 否决 | — | 71.64 | — | N/A |  |  |  |  |  |
| 600025.SH | 华能水电 | 否决 | — | 69.37 | — | N/A |  |  |  |  |  |
| 002468.SZ | 申通快递 | 否决 | — | 69.07 | — | N/A |  |  |  |  |  |
| 002603.SZ | 以岭药业 | 否决 | — | 68.93 | — | N/A |  |  |  |  |  |
| 603882.SH | 金域医学 | 否决 | — | 68.08 | — | N/A |  |  |  |  |  |
| 600886.SH | 国投电力 | 否决 | — | 66.27 | — | N/A |  |  |  |  |  |

## 逐票
### 600285.SH 羚锐制药 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:22.4 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv,rule6_ar_growth_gt_revenue_growth|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓 | 语义待核:官方 medium/low 命中(例行件),待复核(未扣分,待 web/LLM 实判)
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(资产负债表):资产负债率上升、应收占比上升;资产负债率 38.2%→38.22% / 应收占比 8.01%→9.24%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·1事件·impact=pending / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv,rule6_ar_growth_gt_revenue_growth|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv,rule6_ar_growth_gt_revenue_growth|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 601211.SH 国泰海通 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:18.3 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报趋势对照(资产负债表):资产负债率上升、商誉减值迹象;资产负债率 80.13%→84.45% / 商誉 4070761462.0→4052356186.0(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):净利率同比下滑;净利率 103.98%→39.36%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web tailwind/low/no_action·1源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 600415.SH 小商品城 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:10.59 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报趋势对照(资产负债表):资产负债率上升、应收占比上升、存货占比上升;资产负债率 43.38%→45.73% / 应收占比 0.97%→0.98% / 存货占比 3.54%→3.58%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):毛利率同比下滑、净利率同比下滑;毛利率 36.18%→33.78% / 净利率 25.41%→21.56%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 600233.SH 圆通速递 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:17.11 | 试探仓
- 否决审查触发:减持进行中|EGS hard_veto(上游聚合,无条件否决)|Rule6 已命中:rule6_holder_reduction,rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:语义web/LLM:risk(low)｜财报趋势对照(资产负债表):资产负债率上升、存货占比上升、商誉减值迹象;资产负债率 31.68%→32.77% / 存货占比 0.4%→0.65% / 商誉 348360416.67→334682789.49(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web risk/low/observe·3源·impact=downgrade
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:减持进行中|EGS hard_veto(上游聚合,无条件否决)|Rule6 已命中:rule6_holder_reduction,rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:减持进行中|EGS hard_veto(上游聚合,无条件否决)|Rule6 已命中:rule6_holder_reduction,rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 600900.SH 长江电力 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:27.99 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(资产负债表):存货占比上升、商誉减值迹象;存货占比 0.12%→0.15% / 商誉 1150866176.04→1095719577.66(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 601058.SH 赛轮轮胎 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:13.54 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓 | 语义待核:官方 medium/low 命中(例行件),待复核(未扣分,待 web/LLM 实判)
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(资产负债表):资产负债率上升、应收占比上升;资产负债率 49.56%→51.24% / 应收占比 13.1%→13.47%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(业绩预告):业绩预告类型「略减」(负面)、预告净利变动上限-15.0%为负(必降);预告净利变动 -15.0~-15.0%(报告期20250630)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):净利率同比下滑;净利率 12.35%→11.17%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·1事件·impact=pending / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 002926.SZ 华西证券 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:8.44 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报趋势对照(资产负债表):资产负债率上升;资产负债率 76.23%→77.69%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=window_incomplete/window_incomplete；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 603259.SH 药明康德 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:117.89 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)｜大宗交易对照(comparison-only,不改决策):近5交易日2笔大宗交易(最近20260715,成交2455.01,1笔,买卖方国信证券股份有限公司深圳后海分公司→瑞银证券有限责任公司上海花园石桥路证券营业部,折价率+0.00%)
- 风控触发:财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。|未来事件 earnings_disclosure@20260804(公告20260625/manual_review)｜财报趋势对照(资产负债表):存货占比上升、商誉减值迹象;存货占比 7.68%→9.28% / 商誉 972053972.22→863384053.29(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):净利率同比下滑;净利率 38.03%→37.4%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。｜⚠️ 未来已知事件(1项近端将至):先人工复核/转观察/谨慎建仓,不改 EGS/TopN/生产决策(advisory)
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 002668.SZ TCL智家 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:9.92 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓 | 语义待核:官方 medium/low 命中(例行件),待复核(未扣分,待 web/LLM 实判)
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(利润表):净利率同比下滑;净利率 6.56%→6.28%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[low]·1事件·impact=pending / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 600329.SH 达仁堂 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:37.91 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv,rule6_ar_growth_gt_revenue_growth|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报趋势对照(资产负债表):资产负债率上升、应收占比上升;资产负债率 26.38%→27.92% / 应收占比 9.72%→12.26%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(业绩预告):业绩预告类型「预减」(负面)、预告净利变动上限-66.0%为负(必降);预告净利变动 -68.0~-66.0%(报告期20260630)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=window_incomplete/window_incomplete；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv,rule6_ar_growth_gt_revenue_growth|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv,rule6_ar_growth_gt_revenue_growth|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 600025.SH 华能水电 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:9.84 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓 | 语义待核:官方 medium/low 命中(例行件),待复核(未扣分,待 web/LLM 实判)
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报趋势对照(利润表):毛利率同比下滑、净利率同比下滑;毛利率 54.88%→51.99% / 净利率 28.01%→26.78%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·1事件·impact=pending / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 002468.SZ 申通快递 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:13.82 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓 | 语义待核:官方 medium/low 命中(例行件),待复核(未扣分,待 web/LLM 实判)
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:未来事件 limit_unlock@20260805(公告20250806/manual_review)｜财报趋势对照(资产负债表):应收占比上升、存货占比上升;应收占比 4.87%→5.78% / 存货占比 0.37%→0.39%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·3事件·impact=pending / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=window_incomplete/window_incomplete；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。｜⚠️ 未来已知事件(1项近端将至):先人工复核/转观察/谨慎建仓,不改 EGS/TopN/生产决策(advisory)
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 002603.SZ 以岭药业 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:16.5 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报趋势对照(资产负债表):商誉减值迹象;商誉 107953261.39→101716533.36(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 603882.SH 金域医学 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:26.37 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报趋势对照(资产负债表):资产负债率上升、存货占比上升、商誉减值迹象;资产负债率 28.79%→29.54% / 存货占比 1.95%→1.99% / 商誉 52205371.01→42056653.43(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):营收同比下滑;营收 1466504705.88→1350977738.08(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓

### 600886.SH 国投电力 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈96.0317% | Rule3减半:否 | IV/HV 0.8149 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:14.76 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=unknown (fail-closed; manual review, no star adjustment) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:unknown(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(资产负债表):商誉减值迹象;商誉 146292117.53→106468305.17(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):营收同比下滑;营收 13121801284.04→12513846246.56(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=unknown/unknown；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓。
- 触发/说明:Rule6 已命中:rule6_50etf_iv|EGS market_regime unknown/missing→按震荡期保守处理|IV分位96.0317>90.0 不可建仓


## 📅 未来已知事件日历(advisory · analysis-only · 不改决策)
| 票 | 名称 | 事件 | 事件日 | 距今(日) | 公告日(PIT) | 建议 | 来源 |
|---|---|---|---|---|---|---|---|
| 603259.SH | 药明康德 | earnings_disclosure | 20260804 | 15 | 20260625 | manual_review | tushare.disclosure_date |
| 002468.SZ | 申通快递 | limit_unlock | 20260805 | 16 | 20250806 | manual_review | tushare.share_float |

## 🐯 龙虎榜(近5交易日 · comparison-only · 不改决策/EGS/选股/股数)
> 本周已查:候选+持仓近5交易日无上龙虎榜记录。

## 💰 大宗交易(近5交易日 · comparison-only · 不改决策/EGS/选股/股数)
| 票 | 名称 | 成交日 | 成交金额(原值) | 笔数 | 买卖方(最大笔) | 折价率(最大笔) |
|---|---|---|---|---|---|---|
| 603259.SH | 药明康德 | 20260715 | 2455.01 | 1 | 国信证券股份有限公司深圳后海分公司→瑞银证券有限责任公司上海花园石桥路证券营业部 | +0.00% |
| 603259.SH | 药明康德 | 20260714 | 2439.06 | 1 | 国泰海通证券股份有限公司深圳深南大道京基一百证券营业部→瑞银证券有限责任公司上海花园石桥路证券营业部 | +0.00% |

## 📊 财报质量趋势(candidate-only · comparison-only · 不改决策/EGS/选股/股数)
| 票 | 名称 | 报表 | 报告期 | 公告日(PIT) | 红旗摘要 |
|---|---|---|---|---|---|
| 002468.SZ | 申通快递 | 资产负债表 | 20260331 | 20260428 | 应收占比上升、存货占比上升;应收占比 4.87%→5.78% / 存货占比 0.37%→0.39%(报告期20260331 vs 20250331) |
| 002603.SZ | 以岭药业 | 资产负债表 | 20260331 | 20260428 | 商誉减值迹象;商誉 107953261.39→101716533.36(报告期20260331 vs 20250331) |
| 002668.SZ | TCL智家 | 利润表 | 20260331 | 20260421 | 净利率同比下滑;净利率 6.56%→6.28%(报告期20260331 vs 20250331) |
| 002926.SZ | 华西证券 | 资产负债表 | 20260331 | 20260423 | 资产负债率上升;资产负债率 76.23%→77.69%(报告期20260331 vs 20250331) |
| 600025.SH | 华能水电 | 利润表 | 20260331 | 20260429 | 毛利率同比下滑、净利率同比下滑;毛利率 54.88%→51.99% / 净利率 28.01%→26.78%(报告期20260331 vs 20250331) |
| 600233.SH | 圆通速递 | 资产负债表 | 20260331 | 20260423 | 资产负债率上升、存货占比上升、商誉减值迹象;资产负债率 31.68%→32.77% / 存货占比 0.4%→0.65% / 商誉 348360416.67→334682789.49(报告期20260331 vs 20250331) |
| 600285.SH | 羚锐制药 | 资产负债表 | 20260331 | 20260428 | 资产负债率上升、应收占比上升;资产负债率 38.2%→38.22% / 应收占比 8.01%→9.24%(报告期20260331 vs 20250331) |
| 600329.SH | 达仁堂 | 资产负债表 | 20260331 | 20260430 | 资产负债率上升、应收占比上升;资产负债率 26.38%→27.92% / 应收占比 9.72%→12.26%(报告期20260331 vs 20250331) |
| 600329.SH | 达仁堂 | 业绩预告 | 20260630 | 20260715 | 业绩预告类型「预减」(负面)、预告净利变动上限-66.0%为负(必降);预告净利变动 -68.0~-66.0%(报告期20260630) |
| 600415.SH | 小商品城 | 资产负债表 | 20260331 | 20260423 | 资产负债率上升、应收占比上升、存货占比上升;资产负债率 43.38%→45.73% / 应收占比 0.97%→0.98% / 存货占比 3.54%→3.58%(报告期20260331 vs 20250331) |
| 600415.SH | 小商品城 | 利润表 | 20260331 | 20260423 | 毛利率同比下滑、净利率同比下滑;毛利率 36.18%→33.78% / 净利率 25.41%→21.56%(报告期20260331 vs 20250331) |
| 600886.SH | 国投电力 | 资产负债表 | 20260331 | 20260430 | 商誉减值迹象;商誉 146292117.53→106468305.17(报告期20260331 vs 20250331) |
| 600886.SH | 国投电力 | 利润表 | 20260331 | 20260430 | 营收同比下滑;营收 13121801284.04→12513846246.56(报告期20260331 vs 20250331) |
| 600900.SH | 长江电力 | 资产负债表 | 20260331 | 20260430 | 存货占比上升、商誉减值迹象;存货占比 0.12%→0.15% / 商誉 1150866176.04→1095719577.66(报告期20260331 vs 20250331) |
| 601058.SH | 赛轮轮胎 | 资产负债表 | 20260331 | 20260428 | 资产负债率上升、应收占比上升;资产负债率 49.56%→51.24% / 应收占比 13.1%→13.47%(报告期20260331 vs 20250331) |
| 601058.SH | 赛轮轮胎 | 业绩预告 | 20250630 | 20250819 | 业绩预告类型「略减」(负面)、预告净利变动上限-15.0%为负(必降);预告净利变动 -15.0~-15.0%(报告期20250630) |
| 601058.SH | 赛轮轮胎 | 利润表 | 20260331 | 20260428 | 净利率同比下滑;净利率 12.35%→11.17%(报告期20260331 vs 20250331) |
| 601211.SH | 国泰海通 | 资产负债表 | 20260331 | 20260425 | 资产负债率上升、商誉减值迹象;资产负债率 80.13%→84.45% / 商誉 4070761462.0→4052356186.0(报告期20260331 vs 20250331) |
| 601211.SH | 国泰海通 | 利润表 | 20260331 | 20260425 | 净利率同比下滑;净利率 103.98%→39.36%(报告期20260331 vs 20250331) |
| 603259.SH | 药明康德 | 资产负债表 | 20260331 | 20260428 | 存货占比上升、商誉减值迹象;存货占比 7.68%→9.28% / 商誉 972053972.22→863384053.29(报告期20260331 vs 20250331) |
| 603259.SH | 药明康德 | 利润表 | 20260331 | 20260428 | 净利率同比下滑;净利率 38.03%→37.4%(报告期20260331 vs 20250331) |
| 603882.SH | 金域医学 | 资产负债表 | 20260331 | 20260425 | 资产负债率上升、存货占比上升、商誉减值迹象;资产负债率 28.79%→29.54% / 存货占比 1.95%→1.99% / 商誉 52205371.01→42056653.43(报告期20260331 vs 20250331) |
| 603882.SH | 金域医学 | 利润表 | 20260331 | 20260425 | 营收同比下滑;营收 1466504705.88→1350977738.08(报告期20260331 vs 20250331) |

## 🏭 行业基本面(advisory-only · 基于本周候选聚合③④财报红旗 · 非全行业普查 · 不改决策/EGS/选股)
| SW二级行业 | 候选数 | 有红旗 | 红旗候选 | 摘要 |
|---|---|---|---|---|
| 一般零售 | 1 | 1 | 600415.SH | 一般零售:1 候选中 1 只有财报红旗(净利率同比下滑、存货占比上升、应收占比上升、毛利率同比下滑、资产负债率上升) |
| 中药 | 3 | 3 | 002603.SZ、600285.SH、600329.SH | 中药:3 候选中 3 只有财报红旗(商誉减值迹象、应收占比上升、资产负债率上升) |
| 医疗服务 | 2 | 2 | 603259.SH、603882.SH | 医疗服务:2 候选中 2 只有财报红旗(净利率同比下滑、商誉减值迹象、存货占比上升、营收同比下滑、资产负债率上升) |
| 汽车零部件 | 1 | 1 | 601058.SH | 汽车零部件:1 候选中 1 只有财报红旗(净利率同比下滑、应收占比上升、资产负债率上升) |
| 物流 | 2 | 2 | 002468.SZ、600233.SH | 物流:2 候选中 2 只有财报红旗(商誉减值迹象、存货占比上升、应收占比上升、资产负债率上升) |
| 电力 | 3 | 3 | 600025.SH、600886.SH、600900.SH | 电力:3 候选中 3 只有财报红旗(净利率同比下滑、商誉减值迹象、存货占比上升、毛利率同比下滑、营收同比下滑) |
| 白色家电 | 1 | 1 | 002668.SZ | 白色家电:1 候选中 1 只有财报红旗(净利率同比下滑) |
| 证券 | 2 | 2 | 002926.SZ、601211.SH | 证券:2 候选中 2 只有财报红旗(净利率同比下滑、商誉减值迹象、资产负债率上升) |

## 闪崩否决追踪（只做对比，不影响本周选股）
> 口径：决策日下一交易日开盘模拟买入，第5/第10个交易日收盘比较；前复权并扣0.16%双边成本。
- 一周：一周还没走完（待到期 245 只），现在下结论太早。
- 两周：两周还没走完（待到期 245 只），现在下结论太早。
- 旧4日口径官方被拦组（20260714，245只）：证据还没走完或可比样本不足，暂时不改设计，继续按周积累。
- 新增第5日实际多拦组（20260714，55只）：证据还没走完或可比样本不足，暂时不改设计，继续按周积累。
- 当前口径官方被拦组（20260720，340只）：证据还没走完或可比样本不足，暂时不改设计，继续按周积累。
- **最终结论：旧245只或新增第5日影响组尚未完成一周/两周对比，暂时不改设计，继续按周积累。**
> 这里只给观察结论；即使显示“建议复审”，系统也不会自动改阈值或放行股票。

## 本轮上游过滤摘要(批次级 · 无 M6.7 个股行 · 仅计数不含个股/持仓 · 共 162 只)
本轮上游过滤(无 M6.7 个股行,批次级;按原因计数、可能重叠、非去重票数): 10日减持 119 只、大额解禁 36 只、停牌 6 只、次新/relisted 1 只。
| 原因 | stage | 类型 | 只数 |
|---|---|---|---|
| holder_reduction_veto_10d | l0_filter | production_hard_veto | 119 |
| share_float_unlock | l0_filter | production_hard_veto | 36 |
| suspended | l0_filter | production_hard_veto | 6 |
| relisted | l0_filter | production_hard_veto | 1 |