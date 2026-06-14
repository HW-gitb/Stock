# A-short 语义风险层稳定契约

本文件是 A-short semantic-risk advisory 层的稳定契约锚点。详细背景和覆盖说明仍在
`docs/a_short_semantic_risk_coverage.md`;README 只做路由,不要重复本文件的规则矩阵。

## Scope(边界:生产 vs 非生产 M6.7 advisory,2026-06-13 起区分)

- **生产边界(永久禁止)**:语义层**绝不**进 **production EGS** scoring / decision / veto、**绝不**写
  `result/a_short`、**绝不**作为历史回测证据。
- **web_llm 永久 advisory-only**:web/LLM 层**绝不硬否决**、绝不作买入因子;无证据/未检索 → `unknown/unknown/no_action`。
- **official_structured 可进非生产 M6.7 advisory 打分(M6.7 集成;evidence-full 门,Slice 1b)**:经
  `_validate_semantic_official` 校验后的 official_structured,其 **high severity 且证据齐全**(尤其
  `url_or_pdf` trim 后**非空**)**才可**在**非生产 Phase 5 / M6.7** 报告内经 `semantic_official` risk family 产生
  **advisory `否决`**(复用引擎 hard_veto 路径,**绝不救回**)。**high 但缺 URL/PDF(空 url_or_pdf)→ 降为 pending 待核
  /人工复核,绝不否决**(证据不全不杀)。**medium/low** 仅"待核"(不扣分/不清/不降星);clear/unknown/无输入 → 中性。
  **这是 M6.7 advisory 否决,不是 production hard veto** —— 它不改 EGS 选股、不进 `result/a_short`、不进回测。
- `official_structured` 与 `web_llm` 是两个置信层,不得混成一个状态;M6.7 集成后两层来源在 `machine.layer.semantic_risk` 仍可追溯。
- `unknown` 不能伪装成 clear。未检索、检索失败、证据缺失时保持 unknown(web 侧 `unknown/unknown/no_action`)。
- **迁移说明**:独立 `a_short_semantic_risk_summary` artifact 是**迁移期过渡形态**,非最终不变式;周报 .md 单独面板已 Slice 3b 行内化进 M6.7;最终语义直接体现在 M6.7(见 `docs/a_short_semantic_risk_coverage.md` §融入 M6.7)。

## official_structured

- 来源:巨潮 cninfo `hisAnnouncement/query`(`stock` = `code,orgId`)。
- PIT 口径:披露日必须 canonical 且 `<= as_of`。
- 当前实现提供的是配置 lookback 内的 PIT 官方公告证据;默认 cninfo lookback 为 90 天。
- 当前实现不是精确 48h 新鲜度窗口。精确 48h 时效 / 媒体负面的实质判断属 web_llm advisory(产出路径见 §web_llm 产出路径)或未来
  recency 字段责任。

## web_llm

- 来源:新浪、通用 web、用户上下文等 LIVE-only 证据;不可复现,不得进入历史回测。
- `web_llm.status == "unknown"` 时,`risk_level` 必须是 `unknown`、`action` 必须是 `no_action`(无证据的中性三元组 `unknown/unknown/no_action`,见 Scope),且可以空 `sources`。
- 任何非 `unknown` 的 web 状态都必须带 `sources` 证据:
  `clear_light`, `risk_candidate`, `risk`, `tailwind`, `headwind`。
- `clear_light` 必须配 `risk_level = none`。
- `risk_candidate` / `risk` / `headwind` 必须配 `risk_level = low|medium|high`。
- `tailwind` 只能配 `risk_level = none|low`。
- `action` 只允许 `no_action`, `observe`, `downgrade`, `manual_review_required`;不得表达买入或硬否决。
- **M6.7 集成(Slice 2)**:web 经 DeepSeek **判官**(判已抓取文本,非搜索器)产出后,`risk_candidate`/`risk`/`headwind`
  且有 `sources` 证据 → 在**非生产 M6.7** 经 `semantic_web_llm` 族产 advisory `downgrade`(**绝不 hard_veto、绝不救回**
  过热/IV/流动性/停牌/退市/official 等硬风控);`tailwind`/`clear_light` 不降级、不作买入因子;`unknown`/无输入/
  违反不变式 → 中性化(引擎记 `machine.layer.semantic_risk.web_llm.invalid_neutralized`,非静默)。DeepSeek 不可用
  (缺 key/SDK/异常)绝不失败周报、绝不伪装 clear,该层 `unknown`。来源在 `machine.layer.semantic_risk` 可追溯。

## web_llm 产出路径(单一来源 / single source of run-path)

> 本节是 web_llm「谁产出 / 当前走哪条路 / 哪些是过渡」的**唯一权威陈述**。`coverage` / `README` /
> `runners/weekly_screening.ps1` / `runners/a_short_semantic_risk_summary.py` 等只**指过来**、不复述(防 N 面漂移;
> 守护 `tests/test_a_short_semantic_risk_contract_docs.py`)。

- **当前结论路(current)**:周报 `runners/a_short_weekly_pipeline.py` M6.7 内 **DeepSeek adapter 自动判** web
  (`--confirm-fetch-authorized` 且未 `--skip-semantic` 时自动接入,**主板 Top15** 边界;缺 key/SDK/抓取失败 → `unknown`
  中性、非阻断)。判官判已抓取文本(非搜索器);影响规则见上 §web_llm「M6.7 集成」。
- **过渡路(transitional;Slice 3 退役)**:独立 `a_short_semantic_risk_summary` summary + `weekly_screening.ps1`
  Stage-4 sidecar(只产官方结构化层)。它仍可产 official_structured,**但不是当前结论路**;Slice 3b 已把语义**行内化**进 M6.7 周报、退役独立面板(3b-1);独立 summary / Stage-4 sidecar / weekly_screening 一键串联待 **3b-2**(M6.7 真跑验证后)。**2b-ii skill-patch(`a_short_semantic_risk_web_llm_patch`)路径已在 Slice 3a 退役**(被 M6.7 内 DeepSeek adapter 取代)。
- 不变式见上 §web_llm + §Scope(advisory-only、unknown-not-clear、never hard-veto)。

## Drift Guard

`tests/test_a_short_semantic_risk_contract_docs.py` 负责把本契约和代码/路由文档钉住:

- 行为探针:空 `sources` 的 `clear_light` / `tailwind` 必须拒绝;空 `sources` 的 `unknown` 必须允许。
- 文档探针:coverage 与 README 不得再写旧口径"只有风险态需要 sources"。
- 48h 探针:coverage 必须明示 official_structured 当前不是精确 48h 窗口。
