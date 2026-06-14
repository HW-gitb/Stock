# deterministic_report 1.2.0 覆盖率说明

Phase 4 目标：先把单票分析输出固定成可回放的机器契约，再让 Skill 和可选 LLM enrich 在这个契约外层工作。

当前结论：`deterministic_report.schema.json` v1.2.0 已覆盖 v14.2 M6.7 报告所需的最小结构；`runners/run_analysis_report.py` 已能从 `analysis_input.json + analyzer + state` 生成 schema-validated JSON + Markdown。v1.1.0 在 v1.0.0 基础上补齐 `data_lineage.l3_mode` / `enrichment_applied` / `enrichment_source`，v1.2.0 进一步补齐 `data_lineage.state_evaluation_time`，让 circuit-breaker state replay 不再依赖 wall-clock now。

> **⚠️ 阅读须知(2026-06-12 刷新):本文「v14.2 映射」表原为 Phase-4 时代撰写**,其中标 `not_implemented_phase4` 的"入场价/止损止盈/仓位/星级/盈亏比/ATR"等,**自 Phase 5 起已在下游实现**——但走的是**另一条下游路径**:`runners/a_short_phase5_engine.py` → `a_short_m67_report`(**非 deterministic_report**),由 `a_short_weekly_pipeline.py` 串联。该路径 **非生产 / not validated alpha / risk_filter_only / 不真钱 / 不接券商 / 不自动下单**;`a_short_m67_report` 的对外动作是 `否决 / 观察 / 建仓`,其中"建仓"是带"**试探仓(edge 未验证)·无条件止损·仅 risk_filter**"诚实护栏的**研究级建议,不是生产买入信号**。下表「当前状态」列已就 Phase 5 覆盖的模块标注「**→ Phase5(M6.7 path)已建·非买入**」。两条下游路径并存:deterministic_report(Phase3/4 analyzer/state)与 a_short_m67_report(Phase5 决策引擎)。

## 已建立文件

- `schemas/deterministic_report.schema.json`
- `schemas/deterministic_report_enrichment.schema.json`
- `schemas/examples/deterministic_report_enrichment.example.json`
- `schemas/deterministic_report_coverage.md`
- `runners/run_analysis_report.py`
- `tests/skill/test_run_analysis_report.py`
- `skills/a_short_analysis/SKILL.md`
- `skills/a_short_analysis/prompts/*.md`
- (Phase 5 路径,非生产)`runners/a_short_phase5_engine.py` / `schemas/a_short_m67_report.schema.json` / `presets/a_short_phase5_engine_governance_20260610.json` / `runners/a_short_weekly_pipeline.py`

## 输出契约

| 字段 | 当前来源 | v1 状态 |
|---|---|---|
| `schema_name/schema_version` | schema + runner 常量 | deterministic |
| `generated_at` | runner | deterministic |
| `preset/as_of/ts_code/name` | `analysis_input.json` | deterministic |
| `decision` | analyzer + state | deterministic；v1 只输出 `skip/watch` |
| `veto` | `engine.analyzer.rule6_hard_veto.run_veto()` | deterministic |
| `entry_plan` | schema 占位 | `unknown` / `not_implemented_phase4` |
| `exit_plan` | schema 占位 | `unknown` / `not_implemented_phase4` |
| `position_size` | schema 占位 | `unknown` / `not_implemented_phase4` |
| `risk_flags` | analyzer diagnostics + state + EGS selection context | deterministic |
| `evidence` | `analysis_input.json` 关键字段 | deterministic |
| `unknowns` | runner | deterministic |
| `llm_notes` | optional enrichment placeholder | `enabled=false` in v1 |
| `data_lineage` | runner + analyzer rule versions + state digests + L3/enrichment metadata | deterministic |
| `analyzer_invocations` | `run_veto()` replay result | deterministic |

## LLM enrichment patch

`schemas/deterministic_report_enrichment.schema.json` v1.2.0 is the only supported patch format for writing LLM notes back through the runner.

The patch can target only:

- `llm_notes.enabled`
- `llm_notes.sections[]`

It must also declare:

- `target.as_of`
- `target.ts_code`
- `target.report_schema_version` = `1.2.0`
- `source.kind`
- `source.prompt_refs`

`runners/run_analysis_report.py --enrichment-path <patch.json>` validates the patch, verifies the target matches the freshly generated report, then merges only `llm_notes` and mirrors patch source metadata into `data_lineage.enrichment_applied/source`. It must not patch `decision`, `veto`, `risk_flags`, `entry_plan`, `exit_plan`, `position_size`, `evidence`, or `analyzer_invocations`.

## v14.2 映射

| v14.2 模块 | deterministic_report 字段 | 当前状态 |
|---|---|---|
| Rule 1 股价零滞后 + 前复权 | `evidence.quote.close` / `unknowns` | EOD close 可记录；实时多源校验 requires_external |
| Rule 3 波动率/情绪过滤 | `unknowns`, future `risk_flags` | **→ Phase5(M6.7 path)已建·非买入**:IV 闸(market_regime 族:IV分位>halve_pct→降级·减半;regime hard_veto)。情绪过滤仍未实现 |
| Rule 6 负面优先 | `veto`, `risk_flags`, `analyzer_invocations`, `decision` | 已实现 4 条 Phase 3 hard veto |
| Rule 6.1 盘中量化热插拔 | `risk_flags`, `unknowns` | `out_of_scope_by_cadence`(周频/EOD 系统本就不依赖盘中 Level-2/分钟,非"缺数据";见 Phase5 设计 §9) |
| Rule 7 ATR 验证 | `exit_plan`, `unknowns` | **→ Phase5(M6.7 path)已建·非买入**:ATR14 + 止损=支撑−ATR_MULT×atr(按 regime) |
| Rule 7A 织布机/盘口分钟 | `risk_flags`, `unknowns` | `out_of_scope_by_cadence`(盘口分钟挂单厚度,周频系统不依赖;见 Phase5 设计 §9) |
| Rule 8 流动性底线 | `evidence`, future `position_size` | 输入可读;**→ Phase5 已建·非买入**:liquidity_execution 族(hard_veto)+ 仓位含冲击成本 |
| Rule 9 季报跳空处置 | `risk_flags`, `unknowns` | requires_external / future analyzer |
| Rule 10 最低盈亏比 | `entry_plan`, `exit_plan`, `unknowns` | **→ Phase5(M6.7 path)已建·非买入**:RR floor 按 regime(rr<floor 直接拒) |
| Rule 11 数据备用协议 | `unknowns`, future `data_lineage` | schema 可承载；搜索审计未实现 |
| Rule 12 组合熔断 | `decision`, `risk_flags`, `data_lineage.state_snapshot_ref`, `data_lineage.state_evaluation_time` | state stub 可读；真实熔断状态机未实现；回放时间固定为 as-of A 股收盘或显式 `--state-now` |
| Rule 13 再入场协议 | `risk_flags`, `unknowns` | state/schema 可承载；状态机未实现 |
| M0 前置数据采集 | `evidence`, `data_lineage` | 已记录输入和版本；实时数据 requires_external |
| M0.5 波动率觉醒 | `unknowns`, future `risk_flags` | not_implemented_phase4 |
| M1 市场环境 | Markdown summary, `unknowns` | 生产 egs_main 仍标 `unknown`(未真算);**V14.3 regime comparison 层(非生产 comparison-only)在补此项** |
| M2.0 资金行为 | `veto`, `risk_flags`, `evidence` | 已覆盖 Phase 3 hard-veto 子集 |
| M2.7 盈亏比硬拦截 | `entry_plan`, `exit_plan`, `unknowns` | **→ Phase5(M6.7 path)已建·非买入**:M2.7 收紧 + RR floor |
| M2.1-M2.5 生态系统 | `llm_notes.sections`, prompts | requires_llm / requires_external;**A-short 语义风险 Top15 enrichment 层(design-only,advisory)拟补** |
| M2.6 10 日回溯 | `unknowns`, future `risk_flags` | not_implemented_phase4 |
| M3.1 基本面 | `evidence`, `llm_notes.sections` | 部分输入可记录;**行业景气(基本面语义)requires_llm → 语义风险 enrichment 层拟补**(≠ 生产 industry_heat 动量热度) |
| M3.2 技术面 | `evidence`, `unknowns`, future `entry_plan.type` | 输入可记录;**→ Phase5(M6.7 path)已建**:MA/RSI14/ATR14/支撑压力(缺则 data_missing) |
| M3.3 财报与波动率 | `evidence`, `llm_notes.sections` | 财报字段可来自 input；好数据坏反应 requires_llm/analyzer |
| M3.3B IV/HV | `unknowns` | **IV feed(批①)+ Phase5 IV 闸已建·非买入(feasibility 级 BS-ATM 常 maturity)**;HV 未实现 |
| M3.4 分析师目标价 | `llm_notes.sections` | requires_external / requires_llm |
| M3.5 持仓成本 | `risk_flags`, `data_lineage.state_snapshot_ref` | state 可读；持仓详情报告未展开 |
| M3.6 止盈止损 | `exit_plan`, `unknowns` | **→ Phase5(M6.7 path)已建·非买入**:exit_and_size(止损=支撑−ATR_MULT×atr、t1/t2) |
| M3.7 现价锚定 | `evidence.quote.close`, `entry_plan` | EOD close 可记录；竞价校准 = `out_of_scope_by_cadence`(周频系统不做盘中竞价,见 Phase5 设计 §9) |
| M4 强制否决检查 | `veto`, `decision`, `analyzer_invocations` | 已覆盖 Phase 3 hard-veto 子集 |
| M5.1-M5.4 动态目标/星级 | `llm_notes.sections`, Markdown priority | **仅 M5.4 简化星级子集已建**(Phase5 `compute_star`:基线3 +overlay赛道红利 −行业逆风 −过热/组合集中,clamp 1-5,非买入)。**未实现**:M5.1 效率替代"放弃"、M5.2 催化剂持有窗口、完整 M5.3 总账户状态、完整 M5.4 防御/regime/类型联动星级公式、M2.1/M4 降级 override |
| M5.5/M5.5B 组合风险 | `risk_flags`, `unknowns` | **→ Phase5 部分已建**:portfolio_concentration 族(降级);完整组合熔断仍未实现 |
| M6.3 操作价格表 | `entry_plan`, `exit_plan`, `position_size` | **→ Phase5(M6.7 path)已建·非买入**:entry/exit/size(试探仓×0.5、单只上限、100股、IV 减半);仍**不发生产买入信号** |
| M6.5 风险提示 | `risk_flags`, Markdown Risk Flags | 已有 analyzer/state/EGS risk flags |
| M6.6 OrderAudit | `risk_flags`, `unknowns` | not_implemented_phase4 |
| M6.7 操作建议汇总 | JSON contract + Markdown table | deterministic_report minimal render 已实现;**Phase5 `a_short_m67_report` 完整 render 已建·非买入(批①②;否决/观察/建仓 + 执行清单 + 诚实护栏)** |
| M6.8 隔离协议 | `decision`, `unknowns` | 输出层可表达；状态清理不在 v1 |

## Unknown 原因约定

| reason | 使用场景 |
|---|---|
| `requires_llm` | 行业景气、监管/政策新闻、隐蔽风险、跨市场联动、季报修复判断等语义判断 |
| `requires_external` | 实时价、多源检索、分析师目标价等外部数据(以后有数据就能补) |
| `data_missing` | `analysis_input.json` 中本应可有但当前样本缺失的字段 |
| `not_implemented_phase4` | Phase 4 v1 deterministic_report 不实现的项(ATR 止损/仓位/盈亏比/星级等)。**多数自 Phase 5 起已在 `a_short_m67_report`(非生产·非买入)实现**——见上表「→ Phase5」标注;deterministic_report 本身仍维持 minimal,这些走 Phase5 路径 |

> **`unknowns[].reason` enum 边界(与 `deterministic_report.schema.json` 契约一致)**:上表四个值 = `deterministic_report.schema.json` 允许的 `unknowns[].reason` 全集(`requires_llm` / `requires_external` / `data_missing` / `not_implemented_phase4`)。`run_analysis_report.py::_build_unknowns` 也只产出这四个。
>
> **`out_of_scope_by_cadence` 不是 `unknowns[].reason`**,而是「v14.2 映射」表「当前状态」列用的 **coverage-status 描述标签**(标周频/EOD 系统本就不依赖的盘中/分钟类规则:Rule 6.1 Level-2 热插拔、Rule 7A 织布机盘口分钟、M3.7 竞价校准、legacy 盘中入场窗口;区别于 `requires_external` 的"以后有数据就能补",见 Phase5 设计 §9)。**切勿把它写进 deterministic_report 的 `unknowns[].reason`**——会令报告 schema-invalid。若日后真要让它成为合法 reason,须正式扩 schema enum + runner/_build_unknowns + 测试 + Skill 文档(本 docs-only 切片不做)。

## 验收判定

- `schemas/deterministic_report.schema.json` 通过 JSON Schema meta-validation。
- `runners/run_analysis_report.py` 落盘前强制 schema 校验。
- Optional LLM enrichment patches validate against `deterministic_report_enrichment.schema.json` and merge only `llm_notes`.
- `schemas/examples/deterministic_report_enrichment.example.json` validates against the enrichment schema.
- 测试覆盖 analyzer replay、Markdown M6.7 table、schema write path。
- 真实样本 `20260522 / 600415.SH` 可生成 JSON + Markdown。
- v1 不输出 `buy`，不把 LLM 判断伪装成 deterministic 结果。
