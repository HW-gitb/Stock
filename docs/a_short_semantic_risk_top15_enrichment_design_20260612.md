# A-short 语义风险 Top15 enrichment 修订设计(design-only)

**日期**: 2026-06-12
**来源**: 桌面 `a_short_semantic_risk_top15_coverage_gap_patch.md`(Codex 原设计)+ `a_short_semantic_risk_codex_revision_notes.md`(Codex 修订意见)+ Claude 反馈 `a_short_semantic_risk_design_feedback_from_claude.md`,三方收敛。
**类型**: **design-only**。不解冻 V14.2 spec、不改 production scoring、不接券商。本文是总设计 + 三切片落地计划;具体 schema/runner/skill/测试在各自切片产出。
**前置事实(已读真代码)**: `A-EGS/egs_main.py::stage3_ai_clearing` 已有 ① 巨潮 cninfo 监管公告检查(`hisAnnouncement/query`,关键词 `问询函/立案调查/监管关注/警示函`→`cninfo_flag`,跑 top50、回测跳过)② DeepSeek+东财行业新闻→`POL-RISK-VETO` 行业硬剔除。所以**缺口不是"零覆盖"**。

## 0. 缺口的准确表述
现有 stage3 有 cninfo_flag 与 DeepSeek 政策硬否决,但:仅 4 关键词、只在 production run 内、非 PIT(无披露日证据)、覆盖内部 top50 而非用户观察 Top15、结果未结构化进 M6.7/周报面板、DeepSeek 是 LLM 直接硬否决(advisory 原则相悖)。
> **真缺口 = 缺一个可审计、PIT、Top15 主板全覆盖、可在 M6.7/周报面板消费、且 LLM 部分只 advisory 不硬否决 的语义风险层。** 本设计补这一层,**与现有 production stage3 隔离**(不改其行为)。

## 1.【必答】现有 cninfo_flag / DeepSeek 硬否决如何处理
- **本切片不碰 production stage3**:新语义风险层是**独立 standalone**(同 V14.3 regime runner 的隔离思路),不改 egs_main、不改 stage3 的 cninfo_flag 行为、不改 DeepSeek POL-RISK-VETO。
- **DeepSeek POL-RISK-VETO 标为 legacy-conflict**:它是既有"LLM+web→硬否决"路径,与新层"web+LLM 仅 advisory"原则冲突。本轮**不迁移、不删除、不改**;若日后要把它降级为 advisory 或重新治理为 deterministic veto,**单独走 Slice 3**(analyzer+governance+schema+PIT/forward 论证)。
- **cninfo 取数模式复用**:新结构化层复用 stage3 已验证可用的 `hisAnnouncement/query` 调用模式(同 header/referer),但扩展为 Top15 + 更全公告分类 + **按披露日 PIT** + 带证据(标题/分类/日期/URL),输出为 **advisory 证据**(本切片不据此新增硬否决)。

## 2.【必答】两层架构(明确分开、不同置信等级)
### 2A 官方结构化层(cninfo / 交易所公告)— 可 PIT
- 源:巨潮 cninfo `hisAnnouncement/query`(法定披露平台)优先;交易所/公司公告次之。
- 覆盖:监管问询/关注函、处罚/立案调查、诉讼/仲裁、重大担保/资金占用等公告类。
- 口径:**按披露日 PIT 过滤(≤ as_of)**;cninfo 有历史 → 此层**可 PIT、理论可回测**(区别于实时 web)。公告分类 + 标题关键词映射风险类型。
- 产出:**带证据的 risk marker / hard-veto candidate**(仅候选);是否升级为 deterministic 硬否决 → 另走 Slice 3,不在本层临时拍板。

### 2B Web/LLM advisory 层(新浪/通用 web/用户上下文)— 仅 LIVE
- 源:新浪财经新闻/舆情、通用 web 搜索、用户提供上下文。
- 覆盖:媒体负面、**基本面行业景气**、政策/产业链逆风、隐蔽风险线索。
- 口径:**只 soft flag**;**不进 deterministic 字段**;不改 `decision`/`veto`/hard action;**未检索/失败→`unknown`,绝不伪装 `clear`**;必留 来源/日期/置信度/风险类型/建议动作。
- **PIT 边界**:实时 web/新浪检索**仅 LIVE/forward 决策合法**,**绝不**用于历史回测证据(look-ahead + 不可复现)。

## 3.【必答】为什么先做 probe slice
cninfo/新浪均**非已治理 provider**:无 token、有频率限制、接口/字段/反爬形态未证明(stage3 的 cninfo 调用只验证过 4 关键词、非 PIT、非 Top15)。正式接线前必须独立探针验证:① cninfo 返回字段(标题/公告分类/披露日/URL/证券代码映射)② 分类+标题能否可靠映射监管风险 ③ 新浪可取性 + 信噪比 ④ 失败形态(网络/空/反爬/字段漂移)。**真取数 = 用户授权 `执行`**。探针未过不投全量。

## 4.【必答】Top15 主板覆盖如何保证
- 覆盖对象 = EGS 周频候选**观察池 `watch_n=15`**(非最终 Top5、非内部 top50)。原因:Top6-15 仍是人工观察池,不扫会留口径漏洞。
- **A 股全程主板**:复用 `engine.data.a_share_board_scope.is_a_share_main_board`——只收 canonical 6 位 `.SH 600/601/603/605` + `.SZ 000/001/002/003`,排创业板/科创板/北交所/B 股/畸形码(用户口径"A 股只操作主板")。
- 分层扫描(保留):**Top5 深扫 / Top6-15 轻扫 / Top6-15 命中线索→升级深扫**;检索失败/未检索→`unknown`;无命中但检索成功→`clear_light`(须带 source coverage / checked_at / scope)。

## 5.【必答】M6.7 / weekly 可见 artifact
新增 weekly Top15 级结构化产物 **`a_short_semantic_risk_summary.json`**(落 guard-safe research lane,绝不 `result/a_short`),字段(Slice 2 出正式 schema):
`as_of` / `universe`(main-board Top15 watch pool)/ `coverage`(checked/unknown/failed count)/ `candidates[]`{`ts_code`,`rank`,`scan_tier`(deep/light/upgraded),`official_structured`{`status`(clear/risk/unknown),`events[]`(source,title,category,disclosure_date,url_or_pdf,risk_type)},`web_llm`{`status`(clear_light/risk_candidate/risk/tailwind/headwind/unknown),`risk_level`(none/low/medium/high/unknown),`action`(no_action/observe/downgrade/manual_review_required)},`sources[]`(title,url,published_at,fetched_at,source_type),`confidence`,`summary`,`boundary`(advisory_only,not_deterministic_veto)}。
- **消费/可见**:M6.7/周报面板渲染其摘要(官方结构化风险态、web/LLM 风险态、基本面景气态、是否需人工复核、observe/downgrade/manual_review 原因、关键来源数+最新日期),并**明标"advisory·非确定·不可复现(web/LLM 部分)"**。
- **架构边界**:软标记走既有 enrichment channel 精神(不进 `deterministic_report` 确定性字段);本 artifact 是**独立 advisory 产物**,面板引用它而非把软标记混入确定性报告。

## 6. 行业景气 ≠ 生产 industry_heat
- `industry_heat`(生产打分):SW L2 行业 beta / **动量热度**,已 live(balanced profile)。
- `semantic industry trend`(本设计):LLM/web/公告语义层面的**基本面景气/逆风**。
- **两者不得混算、不得重复加权**;本层产出独立标注,绝不回写生产 industry_heat 或 scoring。

## 7.【必答】禁止行为
Web+LLM 直接硬否决;`unknown`→伪装 `clear`;改 `v14.2_spec.md` 原文;结果进入 production scoring / `decision`/`veto`;自动下单/接券商;实时 web/LLM 进历史回测;非主板进入 universe;只写 `llm_notes` 不进面板;把官方结构化与 web/LLM 混成同一置信等级。

## 8. 三切片落地计划
- **Slice 1 — provider/probe**(先行,纯评估,不改生产):cninfo probe runner/design + 新浪/news probe design-or-runner + probe summary schema + 测试(字段存在、PIT 日期、失败→unknown、不写 production、主板 Top15 输入过滤);真取数 = 授权 `执行`。边界:不硬否决/不改 EGS scoring/不改 Phase5 decision/不做历史回测证据。
- **Slice 2 — semantic risk advisory 正式层**(待 Slice 1 探针过):`a_short_semantic_risk_summary` schema + Top15 主板消费 + Top5deep/Top6-15light/命中升级 + enrichment/skill 契约(复用 `skills/a_short_analysis/prompts/*`)+ weekly/M6.7 面板渲染 + 测试(Top15 全覆盖 / 命中升级 / unknown 不伪装 clear / web+LLM 不硬否决 / soft 不进确定性字段 / sources·date·confidence·action 必填 / 主板过滤)+ coverage 文档。**结构化层 = headless runner;web+LLM 层 = skill 在环**(headless 跑不了 web+LLM)。
  - **⚠️ 本切片必须顺手加的 CI 守护测试(register `deferred-open` anti-forget 项的强制化,只在本切片做、不要更早)**:加一个 CI 级测试,作 **tracker-present anti-forget 守护**——断言"**只要 advisory 层代码已存在(本 Slice 2 已落地),register 里 `A-short semantic-risk layer ↔ production reconciliation` 这条 reconciliation tracker 就必须仍在场(带 `DEFERRED, DO NOT CLOSE` 标记 + 仍点名 Slice 3 / POL-RISK-VETO / cninfo),不得被静默删除/降级;测试只在 tracker 缺失或被静默移除时 FAIL**。**注意(刻意的解释)**:**不**做字面"只要 reconciliation 仍 open 就 FAIL"——那会 build-block 同一设计要求的分阶段交付(Slice 3 在 advisory 层建成+验证**之后**才做)。本守护只保证"别忘 Slice 3",不强制"先做 Slice 3";Slice 3 落地时把 tracker flip `resolved`,守护随之更新/退场。同 `tests.test_route_doc_ledger_status_consistency` 的 doc-consistency tripwire 精神。**Slice 1/probe 阶段不要加**(那时 advisory 层还不存在,加了恒绿无意义)。
- **Slice 3 — optional deterministic promotion**(仅当决定把 cninfo 官方命中升级为硬否决):analyzer rule + governance + schema/coverage + 回测/PIT 或 forward-only 论证。边界:不与 web+LLM advisory 混切;不让实时 web/LLM 进历史回测;此切片才可能触碰/治理既有 DeepSeek POL-RISK-VETO legacy-conflict。

## 9. 本切片(本设计文档)交付物
- 本设计文档(回答 Codex 六必答 + 三切片计划 + 边界)。
- 无 schema/runner/skill 代码(在各自切片产出)。V14.2 frozen 不动;production stage3 不动。
