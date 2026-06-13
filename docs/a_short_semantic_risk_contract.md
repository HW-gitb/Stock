# A-short 语义风险层稳定契约

本文件是 A-short semantic-risk advisory 层的稳定契约锚点。详细背景和覆盖说明仍在
`docs/a_short_semantic_risk_coverage.md`;README 只做路由,不要重复本文件的规则矩阵。

## Scope(边界:生产 vs 非生产 M6.7 advisory,2026-06-13 起区分)

- **生产边界(永久禁止)**:语义层**绝不**进 **production EGS** scoring / decision / veto、**绝不**写
  `result/a_short`、**绝不**作为历史回测证据。
- **web_llm 永久 advisory-only**:web/LLM 层**绝不硬否决**、绝不作买入因子;无证据/未检索 → `unknown/unknown/no_action`。
- **official_structured 可进非生产 M6.7 advisory 打分(M6.7 集成)**:经 `_validate_semantic_official` 校验后的
  official_structured,其 **high severity**(立案/处罚/ST/退市)**可**在**非生产 Phase 5 / M6.7** 报告内经
  `semantic_official` risk family 产生 **advisory `否决`**(复用引擎 hard_veto 路径,**绝不救回**);**medium/low** 仅"待核"
  (不扣分/不清/不降星);clear/unknown/无输入 → 中性。**这是 M6.7 advisory 否决,不是 production hard veto** —— 它不改
  EGS 选股、不进 `result/a_short`、不进回测。
- `official_structured` 与 `web_llm` 是两个置信层,不得混成一个状态;M6.7 集成后两层来源在 `machine.layer.semantic_risk` 仍可追溯。
- `unknown` 不能伪装成 clear。未检索、检索失败、证据缺失时保持 unknown(web 侧 `unknown/unknown/no_action`)。
- **迁移说明**:独立 `a_short_semantic_risk_summary` artifact + 周报 .md 单独面板是**迁移期过渡形态**,非最终不变式;最终语义直接体现在 M6.7(见 `docs/a_short_semantic_risk_coverage.md` §融入 M6.7)。

## official_structured

- 来源:巨潮 cninfo `hisAnnouncement/query`(`stock` = `code,orgId`)。
- PIT 口径:披露日必须 canonical 且 `<= as_of`。
- 当前实现提供的是配置 lookback 内的 PIT 官方公告证据;默认 cninfo lookback 为 90 天。
- 当前实现不是精确 48h 新鲜度窗口。精确 48h 时效判断属于 2b-ii-B skill/prompt 或未来
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

## Patch Merge

- `a_short_semantic_risk_web_llm_patch` 只能写入候选的
  `web_llm` / `sources` / `confidence` / `summary`。
- patch 不能新增候选,不能改 `official_structured` / `boundary` / `rank` / `scan_tier` /
  `ts_code` / `coverage`。
- `sources` 和 `summary` 都是替换语义,不是追加语义。候选被 patch 时,旧 web summary 不得残留。
- merge 前必须匹配 `target.as_of`, `target.summary_schema_name`, `target.summary_schema_version`。

## Drift Guard

`tests/test_a_short_semantic_risk_contract_docs.py` 负责把本契约和代码/路由文档钉住:

- 行为探针:空 `sources` 的 `clear_light` / `tailwind` 必须拒绝;空 `sources` 的 `unknown` 必须允许。
- 文档探针:coverage 与 README 不得再写旧口径"只有风险态需要 sources"。
- 48h 探针:coverage 必须明示 official_structured 当前不是精确 48h 窗口。
