# deterministic_report 1.0.0 覆盖率说明

Phase 4 目标：先把单票分析输出固定成可回放的机器契约，再让 Skill 和可选 LLM enrich 在这个契约外层工作。

当前结论：`deterministic_report.schema.json` v1.0.0 已覆盖 v14.2 M6.7 报告所需的最小结构；`runners/run_analysis_report.py` 已能从 `analysis_input.json + analyzer + state` 生成 schema-validated JSON + Markdown。v1 仍然是 minimal runner，真实入场价、止损止盈、仓位、星级和新闻/监管/行业判断不硬编，统一显式标记为 `unknown`、`requires_llm` 或 `not_implemented_phase4`。

## 已建立文件

- `schemas/deterministic_report.schema.json`
- `schemas/deterministic_report_enrichment.schema.json`
- `schemas/deterministic_report_coverage.md`
- `runners/run_analysis_report.py`
- `tests/skill/test_run_analysis_report.py`
- `skills/a_short_analysis/SKILL.md`
- `skills/a_short_analysis/prompts/*.md`

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
| `data_lineage` | runner + analyzer rule versions + state digests | deterministic |
| `analyzer_invocations` | `run_veto()` replay result | deterministic |

## LLM enrichment patch

`schemas/deterministic_report_enrichment.schema.json` v1.0.0 is the only supported patch format for writing LLM notes back through the runner.

The patch can target only:

- `llm_notes.enabled`
- `llm_notes.sections[]`

It must also declare:

- `target.as_of`
- `target.ts_code`
- `target.report_schema_version`
- `source.kind`
- `source.prompt_refs`

`runners/run_analysis_report.py --enrichment-path <patch.json>` validates the patch, verifies the target matches the freshly generated report, then merges only `llm_notes`. It must not patch `decision`, `veto`, `risk_flags`, `entry_plan`, `exit_plan`, `position_size`, `evidence`, `data_lineage`, or `analyzer_invocations`.

## v14.2 映射

| v14.2 模块 | deterministic_report 字段 | 当前状态 |
|---|---|---|
| Rule 1 股价零滞后 + 前复权 | `evidence.quote.close` / `unknowns` | EOD close 可记录；实时多源校验 requires_external |
| Rule 3 波动率/情绪过滤 | `unknowns`, future `risk_flags` | schema 可承载；runner v1 不计算 |
| Rule 6 负面优先 | `veto`, `risk_flags`, `analyzer_invocations`, `decision` | 已实现 4 条 Phase 3 hard veto |
| Rule 6.1 盘中量化热插拔 | `risk_flags`, `unknowns` | requires_external；Level-2/分钟数据不在 v1 |
| Rule 7/7A ATR 验证 | `exit_plan`, `unknowns` | not_implemented_phase4 |
| Rule 8 流动性底线 | `evidence`, future `position_size` | 输入可读；仓位承载量计算留 Phase 5 |
| Rule 9 季报跳空处置 | `risk_flags`, `unknowns` | requires_external / future analyzer |
| Rule 10 最低盈亏比 | `entry_plan`, `exit_plan`, `unknowns` | not_implemented_phase4 |
| Rule 11 数据备用协议 | `unknowns`, future `data_lineage` | schema 可承载；搜索审计未实现 |
| Rule 12 组合熔断 | `decision`, `risk_flags`, `data_lineage.state_snapshot_ref` | state stub 可读；真实熔断状态机未实现 |
| Rule 13 再入场协议 | `risk_flags`, `unknowns` | state/schema 可承载；状态机未实现 |
| M0 前置数据采集 | `evidence`, `data_lineage` | 已记录输入和版本；实时数据 requires_external |
| M0.5 波动率觉醒 | `unknowns`, future `risk_flags` | not_implemented_phase4 |
| M1 市场环境 | Markdown summary, `unknowns` | v1 标 unknown |
| M2.0 资金行为 | `veto`, `risk_flags`, `evidence` | 已覆盖 Phase 3 hard-veto 子集 |
| M2.7 盈亏比硬拦截 | `entry_plan`, `exit_plan`, `unknowns` | not_implemented_phase4 |
| M2.1-M2.5 生态系统 | `llm_notes.sections`, prompts | requires_llm / requires_external |
| M2.6 10 日回溯 | `unknowns`, future `risk_flags` | not_implemented_phase4 |
| M3.1 基本面 | `evidence`, `llm_notes.sections` | 部分输入可记录；行业景气判断 requires_llm |
| M3.2 技术面 | `evidence`, `unknowns`, future `entry_plan.type` | 输入可记录；MA/RSI/MACD/ATR 若缺失标 data_missing |
| M3.3 财报与波动率 | `evidence`, `llm_notes.sections` | 财报字段可来自 input；好数据坏反应 requires_llm/analyzer |
| M3.3B IV/HV | `unknowns` | requires_external / not_implemented_phase4 |
| M3.4 分析师目标价 | `llm_notes.sections` | requires_external / requires_llm |
| M3.5 持仓成本 | `risk_flags`, `data_lineage.state_snapshot_ref` | state 可读；持仓详情报告未展开 |
| M3.6 止盈止损 | `exit_plan`, `unknowns` | not_implemented_phase4 |
| M3.7 现价锚定 | `evidence.quote.close`, `entry_plan` | EOD close 可记录；竞价校准 requires_external |
| M4 强制否决检查 | `veto`, `decision`, `analyzer_invocations` | 已覆盖 Phase 3 hard-veto 子集 |
| M5.1-M5.4 动态目标/星级 | `llm_notes.sections`, Markdown priority | requires_llm / not_implemented_phase4 |
| M5.5/M5.5B 组合风险 | `risk_flags`, `unknowns` | state/schema 可承载；计算未实现 |
| M6.3 操作价格表 | `entry_plan`, `exit_plan`, `position_size` | schema 已建；v1 不给买入指令 |
| M6.5 风险提示 | `risk_flags`, Markdown Risk Flags | 已有 analyzer/state/EGS risk flags |
| M6.6 OrderAudit | `risk_flags`, `unknowns` | not_implemented_phase4 |
| M6.7 操作建议汇总 | JSON contract + Markdown table | 已实现 minimal render |
| M6.8 隔离协议 | `decision`, `unknowns` | 输出层可表达；状态清理不在 v1 |

## Unknown 原因约定

| reason | 使用场景 |
|---|---|
| `requires_llm` | 行业景气、监管/政策新闻、隐蔽风险、跨市场联动、季报修复判断等语义判断 |
| `requires_external` | 实时价、多源检索、Level-2、分钟成交、分析师目标价等外部数据 |
| `data_missing` | `analysis_input.json` 中本应可有但当前样本缺失的字段 |
| `not_implemented_phase4` | Phase 4 v1 明确不实现的 deterministic 计算，如 ATR 止损、仓位公式、盈亏比 |

## 验收判定

- `schemas/deterministic_report.schema.json` 通过 JSON Schema meta-validation。
- `runners/run_analysis_report.py` 落盘前强制 schema 校验。
- Optional LLM enrichment patches validate against `deterministic_report_enrichment.schema.json` and merge only `llm_notes`.
- 测试覆盖 analyzer replay、Markdown M6.7 table、schema write path。
- 真实样本 `20260522 / 600415.SH` 可生成 JSON + Markdown。
- v1 不输出 `buy`，不把 LLM 判断伪装成 deterministic 结果。
