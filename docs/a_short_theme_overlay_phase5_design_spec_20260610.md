# A-short 赛道热度 overlay + Phase 5 确定性执行引擎 — 设计切片(design-only)

**日期**: 2026-06-10
**类型**: design-only 设计规格(DESIGN SLICE)。**本文件不授权任何代码改动 / 数据抓取 / 回测运行 / EGS production 权重变更 / 真钱 / ship-gate 主张。** 它只固化设计,审查通过后再分两个实现切片落地。
**冻结边界**: 不修改 `skills/a_short_analysis/reference/v14.2_spec.md`(冻结参考)。V14.2 的所有优化体现在 Phase 5 引擎 + `schemas/deterministic_report_coverage.md`,不动 spec 原文。
**定位前提(已确认)**: A-short steady 当前是 `risk_filter_only`(见 `docs/CURRENT.md` §3),正向 alpha 未验证。本设计不改变这一底色;它让系统更连贯、可读、可测,但"能不能赚钱"仍交给前向证据(§5)。
**修订(2026-06-10)**: 增 §9(周频/EOD 系统边界,Q1)+ §10(定性风险获取分层,Q2,挂用户实际 2000 积分访问);收紧 §4 层级措辞。两节是 Slice B 的写定要求。

---

## 0. 设计目标与立场 contract

**目标**: 面向投资小白的选股 + 单票分析系统。周末用选股系统从主板选出候选,对排名前列的股票逐只分析,**最终只向使用者输出 M6.7**(精简结论区 + 操作建议执行清单)。

**立场(写成 contract)**: **赛道层追强 + 个股层低吸 / 风控不放松。**
- 赛道热度负责**方向**(整体热的赛道 → 提高其核心股排序优先级)。
- V14.2 风控负责**时点与风险**(个股须未过热、回踩支撑、盈亏比合格、硬风控无触发,才进建仓候选)。
- 纯追强 / 纯低吸都不采用。该立场是当前系统本就天然的行为(`cat_score`+`l4_score` 选强,`OVERHEAT/chasing_high/CHASE` 降过热),此前从未显式写明,现固化。

---

## 1. 架构总览

```
EGS v7.10 选股(L0–L5)  ──►  Slice A: industry_theme_heat_overlay(comparison track, 非 production)
        │                              │  重排现有候选池, 输出 overlay 排序
        └──────────────┬───────────────┘
                       ▼
        Slice B: Phase 5 确定性执行引擎(消费 EGS + overlay + IV)
                       ▼
        唯一对外输出: M6.7(精简结论区 + 执行清单)
```

实现拆两个切片(治理域不同),各自走 起草 → 审查 → 提交:
- **Slice A** — EGS 赛道热度 overlay。受 EGS governance(`presets/a_short_screening_threshold_governance_20260602.json`、`egs_runner_change_allowed:false`、parity 测试)约束;additive、非 production、comparison-track。
- **Slice B** — Phase 5 确定性引擎。受 `schemas/deterministic_report.schema.json` / coverage 约束;V14.2 spec 冻结。

---

## 2. Slice A — 赛道热度 overlay 设计

**现状缺口**: `cat_score`(`A-EGS/egs_main.py::score_l3`)已是题材热度,占 `egs_base` 30%,但 ① 只看概念近 5 日强度(窗口太短);② 取所属概念最高值(易被蹭概念标签污染);③ 不衡量"整个行业/赛道相对市场"。同时 `l4_score`(50%)核心是**行业内排名**,把"整个赛道强"中性化。

**字段契约**(实现切片据此建 schema):

| 字段 | 角色 | 定义 | 数据 |
|---|---|---|---|
| `theme_heat_score` | **加权项** | 概念热度,5d **与** 20d 双窗口成交额加权涨跌的全市场百分位(扩展现有 5d 单窗口);取个股所属概念组合值 | concept_members + daily ✅ |
| `industry_heat_score` | **加权项** | 申万 L2(L1 回退)相对 CSI1000/CSI300/全市场的 20d/60d 强弱,跨行业百分位;按个股 L2 映射 | index_daily / 成分聚合 ✅ |
| `theme_breadth_score` | **门槛** | 赛道内上涨成分占比、放量成分占比 | ✅ |
| `theme_persistence_score` | **乘子(0~1)** | 概念连续多日处高强度 vs 一日脉冲;乘到 `theme_heat_score` | ✅ |
| `candidate_theme_fit_score` | **门槛 + 乘子** | 个股是否真赛道核心:概念成交额权重 / 个股对概念虚拟指数相关性 / 多概念交叉确认;**算不出 → `unknown`** | 🟡 代理可算 |
| `crowding_risk_family` | **风险族** | 归并 `OVERHEAT / chasing_high / CHASE / 高位缩量`;每候选**最多一次硬处理**(降级或转 burst) | ✅ 复用现有标记 |

**正交化**: `industry_heat_score` 对 `theme_heat_score` 残差化(或对"theme+industry"合并贡献设暴露上限),防 40% 只是放大同一个 beta。**进加权的只有 4 项:`esp / l4 / theme_heat⊥ / industry_heat⊥`**;breadth/persistence/fit 不进加权(当门槛与乘子),杜绝共线与过参数化。

**第一版冻结单一权重(comparison track,不做权重搜索)**:
```
overlay_score = esp_score×0.15 + l4_score×0.45 + theme_heat⊥×0.25 + industry_heat⊥×0.15
  其中 theme_heat 已乘 persistence 与 fit; breadth/fit 作门槛; crowding 走风险族(不在此式重复扣分)
```

**赛道优先级提升的硬条件**: `theme_heat / industry_heat / breadth` **≥2 项通过** 且 `candidate_theme_fit ≠ unknown`。

**v1 范围**: **只对现有候选池重排序,不改 L0–L5 准入。** 同时**仪表化**:记录 L0–L5 阶段被丢弃名字的赛道热度分布(被踢 vs 留下),为 v2"是否需改准入"留证据。

**PIT 纪律**: overlay 回测**必须 `--l3-mode pit` + `state/l3_snapshots/`**;无 snapshot 段**只能 forward tracking**,严禁今日概念标签冒充历史(防前视偏差)。

---

## 3. Slice B — Phase 5 确定性执行引擎设计

**V14.2 四层归位(只有第 1 层能终止):**
1. `hard_veto` — Rule 6 核心否决、ST/退市、监管、减持、闪崩、流动性底线、熔断、T+1/涨跌停不可执行、ship-gate/manual-only 边界。**保留严苛。**
2. `downgrade_or_weight_adjustment` — 过热/追高/效率替代、行业逆风、盈亏比偏弱(非明显坏结构)、组合暴露过高。
3. `observe_only` — 数据缺失、分析师目标价不可用、IV 未接入时的占位(可来数据就看)。**盘中/分钟类(Level-2 热插拔、盘口分钟、竞价校准、盘中入场窗口)不归这里,归 §9 `out_of_scope_by_cadence`**——周频系统本就不该依赖它们。
4. `llm_enrichment` — 行业景气、政策、媒体负面、隐蔽风险残差(分层见 §10 Tier C)。**只经 `schemas/deterministic_report_enrichment.schema.json` 写 `llm_notes`,不改 deterministic decision。**

**Rule6 完整性闸门**：Rule6 的每个核查项必须明确为 `pass` / `not_applicable`、`fail` 或待人工复核状态；任一 `fail` 为 `hard_veto`。任何 `pending_data`、`pending_llm`、`unknown`、缺项、重复项或清单漂移，在空仓候选上都必须输出“观察、不得建仓”，并标明待人工复核；不得把未决项当作通过。已有持仓仍走持仓管理，未决 Rule6 项不自动加仓。

**风险族归并(核心去过严,全局跨 EGS 与 V14.2,每族最多一次 hard action):**
```
overheat_crowding_family     : OVERHEAT / chasing_high / CHASE / 高位缩量
liquidity_execution_family   : 低成交额 / 价差 / 冲击 / 涨跌停锁 / 停牌
negative_event_family        : 减持 / 监管 / ST / 闪崩 / 好数据坏反应
market_regime_family         : IV / 大盘回撤 / 跌停家数 / 熔断
portfolio_concentration_family: SW L2 暴露 / 因子共振 / 单赛道拥挤
```

**M2.7 改造**: 只对明显无效结构 hard stop(分母≤0 / 现价跌破支撑×系数 / 流动性不足);边界情况放行进 M3.6,以精确盈亏比 + ATR 止损 + 支撑压力定夺。**去误杀,非放松。**

**执行字段(只实现 Tushare 喂得动的连贯子集):**
- 优先实现: 前复权价/MA/RSI/MACD/ATR/支撑压力/盈亏比;流动性(5d/20d 成交额、冲击成本、100 股手数);P0a capital context、bucket ceiling、单票上限、总仓位约束;已有 Rule 6 hard-veto 子集;T+1/涨跌停/停复牌/解禁/减持结构化输入;`entry_plan / exit_plan / position_size / star` + 赛道热度字段。
- **暂不实现 / 标 `observe_only` / `requires_external`(真·数据缺失项,可来数据就看)**: 分析师一致预期/目标价;未稳定接入的大宗折价、北向逐股。**盘中/分钟类(Level-2 热插拔、盘口织布机/分钟挂单厚度)不在此列 → 归 §9 `out_of_scope_by_cadence`**(周频系统不依赖,非"缺数据";R-ASHORT-CADENCE-OBSERVE-DRIFT)。
- **IV(已确认补)**: 接入 50ETF 期权 IV feed,算 252 日分位,接进 `market_context`,使 Rule 3 / M0.5 / M1 真正生效。若某次运行 feed 缺失 → coverage 标 `iv_regime_status = observe_only_missing_feed`,**不得让报告假装执行了 IV 风控**。

**阈值参数化**: 凡驱动"买/仓位"的阈值(ATR 系数、盈亏比门槛、跳空、过热线)做成可回测 config 参数,比照选股侧阈值治理。

**唯一对外输出 = M6.7**(精简结论区 + 执行清单表格 `标的|操作|股数|入/盈一/盈二/损|类型|优先级|触发条件`)。M0–M6 分析、证据、lineage、overlay 分数、风险族全部沉机器层。操作语义: 建仓 → 入=买入价、盈一/盈二/损=止盈止损;清仓/减仓 → 入=卖出价、其余 N/A。

---

## 4. 跨切片不变量 → 实现切片必须落的测试

| 不变量 | 测试要求 |
|---|---|
| **消费完整性(无悬挂)** | 任何打分/打旗标的输入,在最终 M6.7 决策里找不到消费点 → 测试 **FAIL**。`unknown/observe_only` 字段允许以"保守调整"(收紧边际 / Rule 11 盈亏比→2.0 / 降试探仓)或"显式 caveat"消费,**不许编假分数** |
| **后向可追溯** | M6.7 每个要素可经 data_lineage 追回驱动它的分析 |
| **诚实护栏** | 因 edge 未验证,M6.7 操作建议行必须自带置信度 + 仓位纪律(试探仓 / edge 未验证 / 止损无条件);**有动作/仓位含义的风险必须折进 M6.7 内部**(操作建议行 / 股数列角标 / 触发条件列),纯信息项才可留 M6.5 隐藏 |
| **热度不覆盖硬风控** | 任一 `hard_veto` 触发 → 赛道热度加分失效;`OVERHEAT` 不能直接变买入理由(→观察/burst) |
| **每族一次硬处理** | 同一风险族不得被 EGS 与 V14.2 连续多次硬扣 |
| **fit 缺失只能 unknown** | 不许从标签/记忆编"核心股" |
| **theme⊥industry** | 正交化或合并暴露上限生效 |
| **突破型纪律** | 须放量突破 + 回踩确认 + 非抛物线,否则 → burst research(不进 steady) |

---

## 5. 验证纪律(edge 未验证是底色)

- **comparison track**: overlay 与 baseline(现 20/30/50)**同候选池**并行;benchmark excess **同时看 CSI1000 与 CSI300**;判据用月度 clustered t / drawdown / 胜率 / 坏票率 / false-negative,不只看均值。
- **两道门(不混)**:
  1. overlay 的任何启用不由本设计直接裁决；唯一裁决轨为 P4a `overlay_adjudication`，须在正式发布后的对照证据满足其门槛后另行审查，并由用户决定。
  2. **full-size / 真钱** 仍另走 **12 个月 live-normalized ship gate**(t≥2 / Sharpe≥1 / maxDD≤15%,paper 不算)。
- 变体没稳定胜出 → 继续 research,不进 production。失败是有效否定结论,不是白做。

---

## 6. 实现路线(本设计审查通过后)

| 步 | 切片 | 依赖 |
|---|---|---|
| 1 | IV feed 接入(50ETF 期权 IV + 252d 分位 + market_context) | 独立 |
| 2 | Slice A: 赛道热度 overlay(comparison track) | 独立 |
| 3 | Slice B: Phase 5 执行引擎(消费 1、2;只出 M6.7) | 需 1、2 |
| 4 | 周末 pipeline 编排(选股 top10 → 批量分析 → 周报) | 需 2、3 |

工程完成(1–4)= 系统"能用";之后 §5 两道时间门决定"可信"。

---

## 7. 治理与边界

- 改 EGS 评分受管控:Slice A 必须同切片更新 `presets/a_short_screening_threshold_governance_20260602.json` + parity 测试;以 comparison-track / additive 形式保持 non-production。
- V14.2 spec 冻结;Slice B 改动落引擎 + coverage 文档。
- 不接券商 / 不自动下单;所有交易动作人工执行。
- 不因本设计放松 ship gate;paper 不当 ship-gate 证据。
- 本设计 design-only,授权:无代码、无 fetch、无 run、无 production 权重变更、无真钱。

---

## 8. 显式延后 / 开放项

- v2 才考虑 overlay 改 L0–L5 准入(v1 仅重排 + 仪表化)。
- Level-2 / 盘口分钟 / 竞价校准 / 盘中入场窗口 = `out_of_scope_by_cadence`(§9);分析师一致预期 / 未稳定接入的大宗 / 北向逐股 = observe_only 或待 probe(§10)。
- 真钱 forward-live 是未来另行审查的决策,前提是两道门通过。

---

## 9. 周频 / EOD 系统边界(cadence scope)— Q1 固化

**系统节奏 = 周末 + EOD,不是盘中。** 以下规则对周频系统正式标 **`out_of_scope_by_cadence`**(区别于 `observe_only`:不是"以后有数据就看",而是周频系统**本就不该依赖**):Rule 6.1 盘中热插拔(Level-2 特大单)、Rule 7A 织布机(盘口分钟挂单厚度)、M3.7 竞价校准、legacy 第四阶段盘中入场窗口 / 分时确认。

- **系统不监控盘中风险。** 系统只在周末给:预设 entry 区间、止损价、止盈价、仓位上限、周一人工执行类型(低吸/突破)、禁入条件。
- **盘中反应(闪崩/急跌/紧急减仓)= 人工执行 playbook,不是系统能力**;绝不写成系统在承担实时风控。
- **M6.7 必带 caveat**:本报告不监控盘中 Level-2 / 分钟盘口;盘中异常由你按预设止损无条件执行。
- **持仓人工紧急 override**:遇重大监管 / 跌停 / 黑天鹅,不等周末系统,按止损 / 减仓纪律即时处理。
- **真洞补丁(对已持仓)**:EOD 闪崩否决 + 下周重筛只能事后发现;真正的盘中保护靠上面的预设止损价 + 人工 override,系统给级别、人执行。
- v14.2_spec 冻结;这些规则在 Phase 5 引擎 / coverage 标 `out_of_scope_by_cadence`,并**清理 M6.7 / Rule 12 / OrderAudit 对这些盘中字段的交叉引用**(无悬挂引用,实现切片测试守)。

---

## 10. 定性风险获取分层(official_structured vs web_llm_soft_flag)— Q2 固化

**三级证据(Tier A/B/C),权限不同;"互联网能看" ≠ "可稳定/合规/批量抓" ≠ "可硬否决"。**

| 级 | 源 | 权限 |
|---|---|---|
| **Tier A 官方结构化** | EGS 现用且你 2000 积分确认能拿的接口:**减持** `stk_holdertrade`、**解禁** `share_float`(已在跑) | **可进 deterministic hard-veto 候选**,但须:代码精确匹配 ∧ 事件日期在 as-of 窗口内 ∧ 事件类型在已审核映射表 |
| **Tier B 官方网页** | 巨潮 / 上交所 / 深交所 问询函·监管措施页 | **只强风险提示 + 人工确认,绝不自动杀票**;仅 top-N bounded fetch;留 URL/标题/公告日/抓取时间/查询词/命中词;失败标 `unknown`/`source_unavailable`,不标 clear。**监管问询无干净结构化源 → 归此层** |
| **Tier C web+LLM** | 媒体负面 / 行业景气 / 政策 / 隐蔽风险残差 | 走 `llm_enrichment`(`schemas/deterministic_report_enrichment.schema.json`),**只写 `llm_notes`,不改判决**;M6.7 须暴露高风险摘要,但不自动改 deterministic decision |

**挂实际 2000 积分(不假设,逐接口 probe,像 IV 探测那样):**
- **已确认能用**(EGS 在跑):daily / daily_basic / fina_indicator / index_daily / moneyflow / moneyflow_hsgt / margin_detail / share_float / stk_holdertrade / concept / index_classify·member。
- **待 probe**(大概率能但要验):`opt_basic/opt_daily`(IV,由 IV 探测 `执行` 实测)、`block_trade`(大宗)、`pledge_stat/detail`(质押)。
- **存疑 / 多半不在 2000**:公告全文 `anns`、新闻 `news`;监管问询函**无结构化数据集** → 只能 Tier B。
- **接入前先 probe 实际访问再定级**;拿不到的事件**降级到 Tier B/C(软标记),不放 Tier A**。

**铁律:**
- web/LLM 命中(Tier B/C)**绝不自动 hard-veto**(不可复现 / 会过时);只有 Tier A 满足全部条件才自动否决。
- **PIT**:历史 as-of 回测不得用今日网页 / 今日概念标签补历史判断;无 PIT 源 → forward-only。
- **实盘周末 pipeline**:可用当前网页,但记录检索时间 + 来源;没检索就 `unknown` 不 clear。
- 这些定性结论按 §4 消费完整性**必须折进 M6.7**(降级 / observe / 一句话风险),不只躺 `llm_notes`。

**与现有 EGS 上游的衔接(R-ASHORT-REGULATORY-WEB-VETO-LEGACY-CONFLICT):** **Slice 3 已 land(2026-06-20 reconciliation)**——原 EGS Stage3 的 CNINFO 关键词 `REGULATOR-VETO`(问询函/立案调查/监管关注/警示函 命中即剔候选)+ DeepSeek `POL-RISK-VETO` 已处置:**POL-RISK-VETO 整段移除、cninfo 降为 `REGULATOR-ADVISORY`(不再剔候选,仅 advisory 标记)+ 修「空=通过」假清白**。故本节原述「该 EGS 上游 veto 作为 legacy 前置过滤保留原样、本设计不改 production」为**历史设计态、已 superseded**;现状与 §10「Tier B 强提示·不自动杀票」口径一致(上游不再有网页关键词自动否决)。把 cninfo 做成『真』生产监管硬否决 = 未来 opt-in (b)(reviewed EGS-governance:修请求形态 `code,orgId` + PIT + governance),不在本切片。
