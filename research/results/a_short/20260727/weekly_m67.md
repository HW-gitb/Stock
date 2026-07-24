# A-short 周报 M6.7 — 20260727

> ⚠️ **非生产 / A-short risk_filter_only / edge 未验证**。所有「建仓」均为 **试探仓**,**止损无条件**(盘中由你手动),仅供参考,非买卖指令。

**环境**:震荡期(EGS regime unknown,保守fallback)　|　**波动率**:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
**共 15 只** — 建仓 0 / 持有 0 / 观察 13 / 否决 2
> ⚠️ **市场 regime 未知 → 全员按震荡期保守降级(统一 −1 星)**。星级反映的是**当前市场保守状态**,不是个股质量差;**个股质量看下表「EGS分」列**。(V14.3 regime 分类器接入 production 前,每次实盘都会如此。)
**run**:id=`a-short-20260727-52dd7994f7242f73` | candidate_digest=`52dd7994f7242f737a32b1034a78d35e935d02dd679b8bbc87788ec662f1602e` | stage=complete
**配置**:fingerprint=`935abac736f77a65390c22b71b2351258cbc36a80c7dd044ffca90531a9474e7` | policies=`a_short_screening_runtime_policy_20260715,a_short_m67_runtime_policy_20260715`
> ⚠️ **无账户(account_status=absent):仓位 sizing N/A —— 建仓候选会渲染为「观察」(可建股数/金额不足),这是 **sizing 假象、非真 avoid 信号**;传 `--account` / `-Account`(手工 CSV 转换器生成的 a_short_account_bundle)以获真 sizing/持仓判断。**
**lineage**:analysis_input=`result/a_short/20260727/analysis_input.json` | iv_feed=`research/results/a_short/iv_feed_20260727/iv_feed.json` | account=absent | account_ref=`` | sizing=observation_only_no_account
**IV clock**:status=aligned | IV数据截至 `20260724`
**market regime**:source=`unknown` | effective=`shock` (震荡期) | fallback=true
**price clock**:mode=intraday_prior_settled | 价格数据截至 `20260724` | run_date=`20260724` | 前一交易日 `20260724`
> ⚠️ **价格时钟**:本周报技术指标用的是**前一交易日(20260724)已结算行情**(实盘盘中跑、as_of 20260727 当日 EOD 尚未发布);新闻/语义层窗口仍到 as_of。**价格特征截至 20260724,非 20260727。**
**Comparison v2**: 对比轨 v2：证据不可用或结论未定；不显示旧提醒，生产结论不变。
**P5 行业权重**: P5 行业权重对比：证据积累中；未自动改动生产权重。
**P2/P3/P4 证据提醒**: A-short P2/P3 证据提醒：comparison-only；正式 M6.7 不变。
- P2 目标策略：累计中；目标退出 0/12 周、差异 0/8 周、计划 0/20；突破轨 0/12 周、差异 0/8 周、受影响计划 0/20。
- P3 最终建议验证：仅累计脱敏 forward 证据；不改变正式 M6.7。
- 模型选择与市场基准证据积累中
- 共享受管退出完整 edge 证据积累中
- 待满 26 周且至少 20 个受管计划后提醒 HAC/累计判断
- 尚未达到从首个有效 forward-live 样本起 12 个自然月
- 等待 P3 有效公开裁决及另外两条完整公开裁决后再建设 P3b 总览
- P4a 证据仍在积累；P4b 尚未具备人工升级审查条件。

## 组合集中度与因子共振（M5.5/M5.5B）
- 状态：暂不适用
- 核查口径：tushare:daily_basic+margin_detail+hk_hold+index_member（20260727）
- 最终持仓不足2只，M5.5B不适用

| 标的 | 类型 | 结果 | 最终联动 | 原因 |
|---|---|---|---|---|
| 000899.SZ | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600989.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600499.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 601058.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 601211.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 601336.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600900.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 002440.SZ | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 603049.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600886.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600025.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600233.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600598.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 600100.SH | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |
| 002532.SZ | candidate | 暂不适用 | 不改变操作 | 本行不是最终建仓候选，未进入组合试算 |

## 字段/规则联动台账
- 已登记 30 组：已联动 3；本周未触发 0；不可自动判定、需人工复核 21；刻意独立 6。
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
| 000899.SZ | 赣能股份 | 观察 | — | 91.54 | ⭐×2 | N/A |  |  |  |  |  |
| 600989.SH | 宝丰能源 | 观察 | — | 88.46 | ⭐×2 | N/A |  |  |  |  |  |
| 600499.SH | 科达制造 | 观察 | — | 80.06 | ⭐×1 | N/A |  |  |  |  |  |
| 601058.SH | 赛轮轮胎 | 观察 | — | 79.91 | ⭐×2 | N/A |  |  |  |  |  |
| 601211.SH | 国泰海通 | 观察 | — | 79.01 | ⭐×2 | N/A |  |  |  |  |  |
| 601336.SH | 新华保险 | 观察 | — | 78.93 | ⭐×2 | N/A |  |  |  |  |  |
| 600900.SH | 长江电力 | 观察 | — | 78.45 | ⭐×2 | N/A |  |  |  |  |  |
| 002440.SZ | 闰土股份 | 观察 | — | 76.97 | ⭐×1 | N/A |  |  |  |  |  |
| 603049.SH | 中策橡胶 | 观察 | — | 76.81 | ⭐×2 | N/A |  |  |  |  |  |
| 600886.SH | 国投电力 | 观察 | — | 76.01 | ⭐×2 | N/A |  |  |  |  |  |
| 600025.SH | 华能水电 | 观察 | — | 74.65 | ⭐×2 | N/A |  |  |  |  |  |
| 600233.SH | 圆通速递 | 否决 | — | 71.6 | — | N/A |  |  |  |  |  |
| 600598.SH | 北大荒 | 观察 | — | 69.57 | ⭐×1 | N/A |  |  |  |  |  |
| 600100.SH | 同方股份 | 观察 | — | 65.87 | ⭐×2 | N/A |  |  |  |  |  |
| 002532.SZ | 天山铝业 | 否决 | — | 63.8 | — | N/A |  |  |  |  |  |

## 逐票
### 000899.SZ 赣能股份 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:10.32 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报趋势对照(资产负债表):应收占比上升;应收占比 3.37%→3.44%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):毛利率同比下滑、净利率同比下滑;毛利率 17.63%→17.49% / 净利率 13.13%→9.02%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:Rule6 未完成核查，需人工复核:rule6_margin_extreme_accumulation,rule6_short_selling_surge。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:Rule6 未完成核查，需人工复核:rule6_margin_extreme_accumulation,rule6_short_selling_surge

### 600989.SH 宝丰能源 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:23.38 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_cash_debt_double_high,rule6_margin_extreme_accumulation,rule6_short_selling_surge
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)｜大宗交易对照(comparison-only,不改决策):近5交易日1笔大宗交易(最近20260722,成交5000.18,1笔,买卖方申万宏源证券有限公司证券投资总部→中信建投证券股份有限公司杭州庆春路证券营业部,折价率+0.00%)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理|未来事件 earnings_disclosure@20260813(公告20260625/manual_review)｜财报趋势对照(资产负债表):应收占比上升、存货占比上升;应收占比 0.01%→0.05% / 存货占比 1.9%→2.01%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:Rule6 未完成核查，需人工复核:rule6_cash_debt_double_high,rule6_margin_extreme_accumulation,rule6_short_selling_surge。降级:EGS market_regime unknown/missing→按震荡期保守处理。｜⚠️ 未来已知事件(1项近端将至):先人工复核/转观察/谨慎建仓,不改 EGS/TopN/生产决策(advisory)
- 触发/说明:Rule6 未完成核查，需人工复核:rule6_cash_debt_double_high,rule6_margin_extreme_accumulation,rule6_short_selling_surge

### 600499.SH 科达制造 — 观察　⭐×1
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:15.2 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=headwind (deterministic SW L2 heat; formal -1 star) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:headwind(A-EGS.industry_heat_score; existing headwind→-1 star rule)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报趋势对照(资产负债表):应收占比上升、存货占比上升、商誉减值迹象;应收占比 9.0%→9.8% / 存货占比 17.46%→19.57% / 商誉 859588400.0→845181400.0(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·6事件·impact=pending / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=headwind/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:Rule6 未完成核查，需人工复核:rule6_margin_extreme_accumulation,rule6_short_selling_surge。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:Rule6 未完成核查，需人工复核:rule6_margin_extreme_accumulation,rule6_short_selling_surge

### 601058.SH 赛轮轮胎 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:13.21 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(资产负债表):资产负债率上升、应收占比上升;资产负债率 49.56%→51.24% / 应收占比 13.1%→13.47%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(业绩预告):业绩预告类型「略减」(负面)、预告净利变动上限-15.0%为负(必降);预告净利变动 -15.0~-15.0%(报告期20250630)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):净利率同比下滑;净利率 12.35%→11.17%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·1事件·impact=pending / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:Rule6 未完成核查，需人工复核:rule6_margin_extreme_accumulation,rule6_short_selling_surge。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:Rule6 未完成核查，需人工复核:rule6_margin_extreme_accumulation,rule6_short_selling_surge

### 601211.SH 国泰海通 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:19.22 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge,rule6_ar_growth_gt_revenue_growth
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报趋势对照(资产负债表):资产负债率上升、商誉减值迹象;资产负债率 80.13%→84.45% / 商誉 4070761462.0→4052356186.0(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):净利率同比下滑;净利率 103.98%→39.36%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web tailwind/low/no_action·1源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:Rule6 未完成核查，需人工复核:rule6_margin_extreme_accumulation,rule6_short_selling_surge,rule6_ar_growth_gt_revenue_growth。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:Rule6 未完成核查，需人工复核:rule6_margin_extreme_accumulation,rule6_short_selling_surge,rule6_ar_growth_gt_revenue_growth

### 601336.SH 新华保险 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:63.12 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_cash_debt_double_high,rule6_margin_extreme_accumulation,rule6_short_selling_surge,rule6_ar_growth_gt_revenue_growth
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=tailwind (display only; no positive star bonus) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:tailwind(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报趋势对照(利润表):营收同比下滑;营收 33402000000.0→22133000000.0(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web tailwind/none/no_action·1源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=tailwind/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:非 final，仅观察。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:非 final，仅观察

### 600900.SH 长江电力 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:28.9 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(资产负债表):存货占比上升、商誉减值迹象;存货占比 0.12%→0.15% / 商誉 1150866176.04→1095719577.66(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:非 final，仅观察。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:非 final，仅观察

### 002440.SZ 闰土股份 — 观察　⭐×1
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:11.85 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=headwind (deterministic SW L2 heat; formal -1 star) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:headwind(A-EGS.industry_heat_score; existing headwind→-1 star rule)｜龙虎榜对照(comparison-only,不改决策):近5交易日1次上龙虎榜(最近20260724,净额-22180259.89,席位10家(机构净17897093.59),日跌幅偏离值达到7%的前5只证券)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报趋势对照(资产负债表):应收占比上升;应收占比 9.63%→12.62%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=headwind/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:非 final，仅观察。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:非 final，仅观察

### 603049.SH 中策橡胶 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:47.49 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(资产负债表):应收占比上升;应收占比 14.91%→15.15%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(业绩预告):业绩预告类型「略减」(负面)、预告净利变动上限-6.3%为负(必降);预告净利变动 -11.81~-6.3%(报告期20250630)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web clear_light/none/no_action·2源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:非 final，仅观察。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:非 final，仅观察

### 600886.SH 国投电力 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:14.82 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(资产负债表):商誉减值迹象;商誉 146292117.53→106468305.17(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):营收同比下滑;营收 13121801284.04→12513846246.56(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:非 final，仅观察。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:非 final，仅观察

### 600025.SH 华能水电 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:10.04 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge,rule6_ar_growth_gt_revenue_growth
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报趋势对照(利润表):毛利率同比下滑、净利率同比下滑;毛利率 54.88%→51.99% / 净利率 28.01%→26.78%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 risk[medium]·1事件·impact=pending / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:非 final，仅观察。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:非 final，仅观察

### 600233.SH 圆通速递 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:17.26 | 试探仓
- 否决审查触发:减持进行中|EGS hard_veto(上游聚合,无条件否决)|Rule6 已命中:rule6_holder_reduction
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理|语义web/LLM:risk(low)｜财报趋势对照(资产负债表):资产负债率上升、存货占比上升、商誉减值迹象;资产负债率 31.68%→32.77% / 存货占比 0.4%→0.65% / 商誉 348360416.67→334682789.49(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web risk/low/observe·3源·impact=downgrade
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:减持进行中|EGS hard_veto(上游聚合,无条件否决)|Rule6 已命中:rule6_holder_reduction。
- 触发/说明:减持进行中|EGS hard_veto(上游聚合,无条件否决)|Rule6 已命中:rule6_holder_reduction

### 600598.SH 北大荒 — 观察　⭐×1
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:11.909999999999998 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_cash_debt_double_high,rule6_margin_extreme_accumulation,rule6_short_selling_surge,rule6_ar_growth_gt_revenue_growth
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=headwind (deterministic SW L2 heat; formal -1 star) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:headwind(A-EGS.industry_heat_score; existing headwind→-1 star rule)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报趋势对照(资产负债表):存货占比上升;存货占比 6.24%→7.52%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(业绩预告):业绩预告类型「首亏」(负面)、预告净利变动上限-154.5013%为负(必降);预告净利变动 -154.5013~-154.5013%(报告期20260630)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):毛利率同比下滑、净利率同比下滑;毛利率 65.31%→64.27% / 净利率 56.36%→55.49%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=headwind/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:非 final，仅观察。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:非 final，仅观察

### 600100.SH 同方股份 — 观察　⭐×2
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:6.79 | 试探仓
- 否决审查触发:Rule6待人工核查:rule6_margin_extreme_accumulation,rule6_short_selling_surge
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报趋势对照(资产负债表):资产负债率上升、应收占比上升、存货占比上升、商誉减值迹象;资产负债率 57.79%→58.22% / 应收占比 12.31%→12.55% / 存货占比 15.32%→16.28% / 商誉 91536090.13→88244982.29(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(业绩预告):业绩预告类型「首亏」(负面)、预告净利变动上限-168.7805%为负(必降);预告净利变动 -223.8049~-168.7805%(报告期20260630)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)｜财报趋势对照(利润表):归母净利润为负(亏损)、营收同比下滑、毛利率同比下滑;归母净利-183481203.86 / 营收 2019043512.87→1793211775.17 / 毛利率 28.98%→28.44%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=neutral/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:观察,不建仓。原因:非 final，仅观察。降级:EGS market_regime unknown/missing→按震荡期保守处理。
- 触发/说明:非 final，仅观察

### 002532.SZ 天山铝业 — 否决　—
- 当前环境:震荡期(EGS regime unknown,保守fallback)
- 波动率状态:IV分位≈58.3333% | Rule3减半:否 | IV/HV 0.6246 IV<HV 隐含偏低(情绪偏松/或低估波动)(advisory)
- 现价与成本:12.5 | 试探仓
- 否决审查触发:Rule6 已命中:rule6_ar_growth_gt_revenue_growth
- Rule6人工核查:仅人工核查（不参与自动否决）：rule6_northbound_selloff（仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考）；rule6_good_data_bad_reaction（仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定）；rule6_regulatory_48h（仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决）
- 板块资金事件:industry_trend=neutral (display only) | industry_fundamental_trend=pending_llm (LLM/advisory; no deterministic decision effect)｜行业趋势:neutral(A-EGS.industry_heat_score; display only; no star increase)
- 风控触发:EGS market_regime unknown/missing→按震荡期保守处理｜财报质量对照(comparison-only,不改决策/EGS/选股/股数):EGS扣非净利质量旗标(ESP-Q);扣非净利同比111.78% / 扣非净利2198816692.98 / ROE7.288% / 经营现金流/利润89.333(财报质量红旗,仅 advisory 降优先级参考,绝不否决)｜财报后坏反应:非负/改善财务结果后，个股3日相对中证1000走弱；仅人工复核(advisory)。｜财报趋势对照(资产负债表):应收占比上升;应收占比 0.66%→1.2%(报告期20260331 vs 20250331)(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)
- 语义风险(advisory·非确定·不进确定性字段):官方 clear·impact=none / 监管人工确认 not_required / web unknown/unknown/no_action·0源·impact=none
- 旧任务闭环(确定性/委托；不调用 DeepSeek):industry_trend=neutral/completed；regulatory_check=delegated/delegated；policy_news=未核查(provider_unavailable)；earnings_bad_reaction=negative_manual_review/completed；cross_market_linkage=未核查(provider_unavailable)；hidden_risk=未核查(provider_unavailable)
- **操作建议**:否决,禁止建仓。硬否决:Rule6 已命中:rule6_ar_growth_gt_revenue_growth。
- 触发/说明:Rule6 已命中:rule6_ar_growth_gt_revenue_growth


## 📅 未来已知事件日历(advisory · analysis-only · 不改决策)
| 票 | 名称 | 事件 | 事件日 | 距今(日) | 公告日(PIT) | 建议 | 来源 |
|---|---|---|---|---|---|---|---|
| 600989.SH | 宝丰能源 | earnings_disclosure | 20260813 | 17 | 20260625 | manual_review | tushare.disclosure_date |

## 🐯 龙虎榜(近5交易日 · comparison-only · 不改决策/EGS/选股/股数)
| 票 | 名称 | 上榜日 | 净额(原值) | 席位 | 原因 |
|---|---|---|---|---|---|
| 002440.SZ | 闰土股份 | 20260724 | -22180259.89 | 10席/机构净17897093.59 | 日跌幅偏离值达到7%的前5只证券 |

## 💰 大宗交易(近5交易日 · comparison-only · 不改决策/EGS/选股/股数)
| 票 | 名称 | 成交日 | 成交金额(原值) | 笔数 | 买卖方(最大笔) | 折价率(最大笔) |
|---|---|---|---|---|---|---|
| 600989.SH | 宝丰能源 | 20260722 | 5000.18 | 1 | 申万宏源证券有限公司证券投资总部→中信建投证券股份有限公司杭州庆春路证券营业部 | +0.00% |

## 📊 财报质量趋势(candidate-only · comparison-only · 不改决策/EGS/选股/股数)
| 票 | 名称 | 报表 | 报告期 | 公告日(PIT) | 红旗摘要 |
|---|---|---|---|---|---|
| 000899.SZ | 赣能股份 | 资产负债表 | 20260331 | 20260428 | 应收占比上升;应收占比 3.37%→3.44%(报告期20260331 vs 20250331) |
| 000899.SZ | 赣能股份 | 利润表 | 20260331 | 20260428 | 毛利率同比下滑、净利率同比下滑;毛利率 17.63%→17.49% / 净利率 13.13%→9.02%(报告期20260331 vs 20250331) |
| 002440.SZ | 闰土股份 | 资产负债表 | 20260331 | 20260429 | 应收占比上升;应收占比 9.63%→12.62%(报告期20260331 vs 20250331) |
| 002532.SZ | 天山铝业 | 资产负债表 | 20260331 | 20260429 | 应收占比上升;应收占比 0.66%→1.2%(报告期20260331 vs 20250331) |
| 600025.SH | 华能水电 | 利润表 | 20260331 | 20260429 | 毛利率同比下滑、净利率同比下滑;毛利率 54.88%→51.99% / 净利率 28.01%→26.78%(报告期20260331 vs 20250331) |
| 600100.SH | 同方股份 | 资产负债表 | 20260331 | 20260429 | 资产负债率上升、应收占比上升、存货占比上升、商誉减值迹象;资产负债率 57.79%→58.22% / 应收占比 12.31%→12.55% / 存货占比 15.32%→16.28% / 商誉 91536090.13→88244982.29(报告期20260331 vs 20250331) |
| 600100.SH | 同方股份 | 业绩预告 | 20260630 | 20260715 | 业绩预告类型「首亏」(负面)、预告净利变动上限-168.7805%为负(必降);预告净利变动 -223.8049~-168.7805%(报告期20260630) |
| 600100.SH | 同方股份 | 利润表 | 20260331 | 20260429 | 归母净利润为负(亏损)、营收同比下滑、毛利率同比下滑;归母净利-183481203.86 / 营收 2019043512.87→1793211775.17 / 毛利率 28.98%→28.44%(报告期20260331 vs 20250331) |
| 600233.SH | 圆通速递 | 资产负债表 | 20260331 | 20260423 | 资产负债率上升、存货占比上升、商誉减值迹象;资产负债率 31.68%→32.77% / 存货占比 0.4%→0.65% / 商誉 348360416.67→334682789.49(报告期20260331 vs 20250331) |
| 600499.SH | 科达制造 | 资产负债表 | 20260331 | 20260424 | 应收占比上升、存货占比上升、商誉减值迹象;应收占比 9.0%→9.8% / 存货占比 17.46%→19.57% / 商誉 859588400.0→845181400.0(报告期20260331 vs 20250331) |
| 600598.SH | 北大荒 | 资产负债表 | 20260331 | 20260429 | 存货占比上升;存货占比 6.24%→7.52%(报告期20260331 vs 20250331) |
| 600598.SH | 北大荒 | 业绩预告 | 20260630 | 20260714 | 业绩预告类型「首亏」(负面)、预告净利变动上限-154.5013%为负(必降);预告净利变动 -154.5013~-154.5013%(报告期20260630) |
| 600598.SH | 北大荒 | 利润表 | 20260331 | 20260429 | 毛利率同比下滑、净利率同比下滑;毛利率 65.31%→64.27% / 净利率 56.36%→55.49%(报告期20260331 vs 20250331) |
| 600886.SH | 国投电力 | 资产负债表 | 20260331 | 20260430 | 商誉减值迹象;商誉 146292117.53→106468305.17(报告期20260331 vs 20250331) |
| 600886.SH | 国投电力 | 利润表 | 20260331 | 20260430 | 营收同比下滑;营收 13121801284.04→12513846246.56(报告期20260331 vs 20250331) |
| 600900.SH | 长江电力 | 资产负债表 | 20260331 | 20260430 | 存货占比上升、商誉减值迹象;存货占比 0.12%→0.15% / 商誉 1150866176.04→1095719577.66(报告期20260331 vs 20250331) |
| 600989.SH | 宝丰能源 | 资产负债表 | 20260331 | 20260424 | 应收占比上升、存货占比上升;应收占比 0.01%→0.05% / 存货占比 1.9%→2.01%(报告期20260331 vs 20250331) |
| 601058.SH | 赛轮轮胎 | 资产负债表 | 20260331 | 20260428 | 资产负债率上升、应收占比上升;资产负债率 49.56%→51.24% / 应收占比 13.1%→13.47%(报告期20260331 vs 20250331) |
| 601058.SH | 赛轮轮胎 | 业绩预告 | 20250630 | 20250819 | 业绩预告类型「略减」(负面)、预告净利变动上限-15.0%为负(必降);预告净利变动 -15.0~-15.0%(报告期20250630) |
| 601058.SH | 赛轮轮胎 | 利润表 | 20260331 | 20260428 | 净利率同比下滑;净利率 12.35%→11.17%(报告期20260331 vs 20250331) |
| 601211.SH | 国泰海通 | 资产负债表 | 20260331 | 20260425 | 资产负债率上升、商誉减值迹象;资产负债率 80.13%→84.45% / 商誉 4070761462.0→4052356186.0(报告期20260331 vs 20250331) |
| 601211.SH | 国泰海通 | 利润表 | 20260331 | 20260425 | 净利率同比下滑;净利率 103.98%→39.36%(报告期20260331 vs 20250331) |
| 601336.SH | 新华保险 | 利润表 | 20260331 | 20260430 | 营收同比下滑;营收 33402000000.0→22133000000.0(报告期20260331 vs 20250331) |
| 603049.SH | 中策橡胶 | 资产负债表 | 20260331 | 20260421 | 应收占比上升;应收占比 14.91%→15.15%(报告期20260331 vs 20250331) |
| 603049.SH | 中策橡胶 | 业绩预告 | 20250630 | 20250705 | 业绩预告类型「略减」(负面)、预告净利变动上限-6.3%为负(必降);预告净利变动 -11.81~-6.3%(报告期20250630) |

## 🏭 行业基本面(advisory-only · 基于本周候选聚合③④财报红旗 · 非全行业普查 · 不改决策/EGS/选股)
| SW二级行业 | 候选数 | 有红旗 | 红旗候选 | 摘要 |
|---|---|---|---|---|
| 专用设备 | 1 | 1 | 600499.SH | 专用设备:1 候选中 1 只有财报红旗(商誉减值迹象、存货占比上升、应收占比上升) |
| 保险 | 1 | 1 | 601336.SH | 保险:1 候选中 1 只有财报红旗(营收同比下滑) |
| 化学制品 | 1 | 1 | 002440.SZ | 化学制品:1 候选中 1 只有财报红旗(应收占比上升) |
| 化学原料 | 1 | 1 | 600989.SH | 化学原料:1 候选中 1 只有财报红旗(存货占比上升、应收占比上升) |
| 工业金属 | 1 | 1 | 002532.SZ | 工业金属:1 候选中 1 只有财报红旗(应收占比上升) |
| 汽车零部件 | 2 | 2 | 601058.SH、603049.SH | 汽车零部件:2 候选中 2 只有财报红旗(净利率同比下滑、应收占比上升、资产负债率上升) |
| 物流 | 1 | 1 | 600233.SH | 物流:1 候选中 1 只有财报红旗(商誉减值迹象、存货占比上升、资产负债率上升) |
| 电力 | 4 | 4 | 000899.SZ、600025.SH、600886.SH、600900.SH | 电力:4 候选中 4 只有财报红旗(净利率同比下滑、商誉减值迹象、存货占比上升、应收占比上升、毛利率同比下滑、营收同比下滑) |
| 种植业 | 1 | 1 | 600598.SH | 种植业:1 候选中 1 只有财报红旗(净利率同比下滑、存货占比上升、毛利率同比下滑) |
| 计算机设备 | 1 | 1 | 600100.SH | 计算机设备:1 候选中 1 只有财报红旗(商誉减值迹象、存货占比上升、应收占比上升、归母净利润为负(亏损)、毛利率同比下滑、营收同比下滑、资产负债率上升) |
| 证券 | 1 | 1 | 601211.SH | 证券:1 候选中 1 只有财报红旗(净利率同比下滑、商誉减值迹象、资产负债率上升) |

## 本轮上游过滤摘要(批次级 · 无 M6.7 个股行 · 仅计数不含个股/持仓 · 共 160 只)
本轮上游过滤(无 M6.7 个股行,批次级;按原因计数、可能重叠、非去重票数): 10日减持 92 只、大额解禁 60 只、停牌 5 只、次新/relisted 3 只。
| 原因 | stage | 类型 | 只数 |
|---|---|---|---|
| holder_reduction_veto_10d | l0_filter | production_hard_veto | 92 |
| share_float_unlock | l0_filter | production_hard_veto | 60 |
| suspended | l0_filter | production_hard_veto | 5 |
| relisted | l0_filter | production_hard_veto | 3 |