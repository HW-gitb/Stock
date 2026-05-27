# Phase 7 Kickoff Spec Handoff

**Status**: provider capability / field catalog contract baseline established.

**Scope**: Phase 7 schema-first kickoff. This handoff starts the DataHub / provider capability phase without selecting providers, fetching data, adding provider adapters, creating DataHub tables, rewriting `A-EGS/egs_main.py`, changing strategy logic, or relaxing ship gates.

---

## 2026-05-27 Repair: O1 status-axis clarification

**Optional disposition**: O1 accepted with path (a), not merged fields.

**Changed**:
- Added schema descriptions distinguishing `fieldDefinition.automation_status` from `productionUsePolicy.use_status`.
- Added schema descriptions distinguishing `productionUsePolicy.missing_data_rule` from `providerRequirements.fallback_path`.
- Added example field `a_industry.sw_l2_membership` to demonstrate a technically automatable field that remains production-blocked until provider evidence review.
- Added regression coverage proving the descriptions exist and the example can decouple the two status axes.

**Why**:
- `automation_status` is a technical/provider capability axis.
- `production_use_policy.use_status` is the governance axis and can veto production use even when automation looks technically feasible.
- `missing_data_rule` is runtime behavior when a field is missing after policy exists.
- `fallback_path` is design-time routing when provider capability is unsupported, unreliable, or not reviewed.

**Validation result**:
- `tests.schema.test_provider_capability_catalog_schema`: 11 tests passed.
- Full `tests/schema` discovery: 37 tests passed.
- `git diff --check`: passed (CRLF warnings only).
- Changed-file trailing whitespace check: passed.

---

## 1. 改了什么

- 新增 `schemas/provider_capability_catalog.schema.json` v1.0.0，作为 Phase 7 provider capability / field catalog contract。
- 新增 `schemas/examples/provider_capability_catalog.example.json`，用于验证 contract shape；不是 production provider registry。
- 新增 `tests/schema/test_provider_capability_catalog_schema.py`，覆盖 schema meta、example validation、scope lock、status/data-class/system coverage、provider evaluation no-overall-score guard、silent-default rejection、provider-selection rejection。
- 同步 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/provider_data_requirements_audit.md` 的 Phase 7 路由与下一步状态。

---

## 2. 为什么

Phase 6e audit 已经把四套系统的数据需求整理成字段、PIT、频率、lineage、授权 / 成本、稳定性和 fallback 要求。Phase 7 第一刀需要先把这些要求落成机器可校验的 schema contract，后续 provider capability evidence、field catalog population、DataHub table schema、provider adapter 或 implementation 才有统一边界。

该 contract 特意先做 schema-first，而不是直接实现 provider / DataHub：

- 避免 Phase 7 按 A-short 现有 convenience fields 重构。
- 防止 provider gap 被默认值、latest-only 数据或单一 provider score 掩盖。
- 让 A-share、US、long、short、burst、benchmark 和 manual-evidence requirements 在同一个 artifact 里可审查。

---

## 3. Contract 边界

`provider_capability_catalog` v1.0.0 必须记录：

- data class：覆盖 Phase 6e audit 的 14 个 data classes。
- required systems：`a_short_steady`、`a_short_evidence`、`a_share_burst`、`a_long`、`us_short_steady`、`us_burst`、`us_long`、`phase7_shared`。
- requirement status：`structured_required`、`structured_optional`、`manual_evidence`、`research_only`、`deferred`。
- PIT / frequency / history requirement。
- minimum lineage requirements：provider、API / table、request params、fetch timestamp、source date range、frequency、unit、adjustment、PIT status、coverage、missing fields、limitations、authorization、cost、fallback 等。
- provider evaluation dimensions：coverage、PIT、history、corporate actions、units/currency、latency、stability、authorization、cost、fallback。
- production use policy：missing-data rule、silent default lock、latest-only historical evidence lock。

Scope locks:

- `provider_selection_status = not_selected`。
- `data_fetch_allowed = false`。
- `provider_adapter_allowed = false`。
- `datahub_table_implementation_allowed = false`。
- `production_strategy_rule_change_allowed = false`。
- `broker_or_order_automation_allowed = false`。
- `manual_order_only = true`。

---

## 4. 示例边界

`schemas/examples/provider_capability_catalog.example.json` 只用于 schema validation，记录：

- 已证明的 `tushare_current_a_eod` A-share EOD / benchmark helper surface，但不把 Tushare 选为最终 provider。
- `us_fundamentals_provider_tbd` placeholder，用来显式表示 US fundamentals / filings 仍未选择 provider。
- A-share adjusted EOD、A-share CSI monthly returns、US filing / cash-flow fundamentals、manual event evidence 四类 representative fields。

示例不是 production registry，不触发 provider selection、data fetch、adapter、DataHub table 或 production scoring。

---

## 5. 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_capability_catalog_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_capability_catalog_schema tests.schema.test_a_short_variant_tracking_schema tests.schema.test_candidate_universe_overlap_audit_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

```powershell
$files = @(
  'AGENTS.md',
  'docs/CURRENT.md',
  'docs/README.md',
  'docs/datahub_design.md',
  'docs/strategy_design_synthesis.md',
  'docs/provider_data_requirements_audit.md',
  'docs/handoff/2026-05-27_phase7_kickoff_spec_handoff.md',
  'docs/SESSION_LOG.md',
  'schemas/provider_capability_catalog.schema.json',
  'schemas/examples/provider_capability_catalog.example.json',
  'tests/schema/test_provider_capability_catalog_schema.py'
)
foreach ($file in $files) {
  $lines = Get-Content -Encoding utf8 $file
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '\s+$') { "${file}:$($i + 1)" }
  }
}
```

---

## 6. 验证结果

- `tests.schema.test_provider_capability_catalog_schema`：10 tests passed。
- Provider capability catalog + adjacent Phase 6 schema regression (`test_a_short_variant_tracking_schema`, `test_candidate_universe_overlap_audit_schema`)：21 tests passed。
- Full `tests/schema` discovery：36 tests passed。
- `git diff --check`：passed（CRLF warnings only）。
- Changed-file trailing whitespace check：passed。
- Active stale next-step wording scan：passed。

---

## 7. 失效旧结论

- “Phase 7 可以先写 provider adapter 或 DataHub table”失效；先有 capability / field catalog contract。
- “Provider capability 可以用单一 overall score 表示”失效；schema 禁止 `overall_score`，必须保留 dimension-level blockers。
- “缺 provider 字段时可以 silent default / latest-only 回填历史证据”失效；schema 通过 const lock 禁止。
- “US fundamentals provider 可在 implementation 时再顺手决定”失效；US fields 必须先在 provider capability evidence 中显示支持 / 缺失 / manual / research / deferred 状态。
- “Manual evidence 可以直接变成 deterministic factor”失效；schema 要求 observed date / source / reviewer or process tag，且 promotion 前不能成为 deterministic factor。

---

## 8. 下一步注意事项

1. 下一条 `执行` 推荐做 provider capability evidence / field catalog population，优先从已证明的 A-share EOD / benchmark surfaces 开始，使用 `schemas/provider_capability_catalog.schema.json`。
2. 不要在下一刀重写 `A-EGS/egs_main.py`、新增 US provider adapter、抓新 provider 数据、建立 DataHub table，或改变任何 strategy runner 行为。
3. 若后续 provider readiness 不足，字段必须保持 `blocked_until_provider_review`、`manual_evidence_only`、`research_only` 或 `deferred`；不得发明 fundamentals 或把 latest-only 数据当 PIT evidence。
