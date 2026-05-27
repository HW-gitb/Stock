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

1. 本节原推荐“下一条 `执行` 从已证明的 A-share EOD / benchmark surfaces 填充 provider evidence 入手”已由下方 2026-05-27 追加的 Phase 7a alpha-validation route 失效；现下一步先做 schema-first alpha plausibility audit。
2. 不要在下一刀重写 `A-EGS/egs_main.py`、新增 US provider adapter、抓新 provider 数据、建立 DataHub table，或改变任何 strategy runner 行为。
3. 若后续 provider readiness 不足，字段必须保持 `blocked_until_provider_review`、`manual_evidence_only`、`research_only` 或 `deferred`；不得发明 fundamentals 或把 latest-only 数据当 PIT evidence。

## 2026-05-27 追加：Phase 7a alpha-validation route

**改了什么**:

- 新增 `docs/alpha_plausibility_audit.md`，作为 lane objective、alpha plausibility、portfolio-level synthesis、continue / risk-filter / redesign / defer / do-not-implement verdict 的 owner doc。
- 新增 `docs/evidence_capital_policy.md`，作为 `paper` vs `live_normalized` evidence、normalized return、capacity / slippage / scaling validity 和 ship-gate evidence 边界的 owner doc。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/strategy_design_synthesis.md`、`docs/long_alpha_spec.md`、`docs/burst_lane_spec.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md` 的路由与执行顺序。

**为什么改**:

- 原 Phase 7 下一步默认从已证明的 A-share EOD / benchmark surfaces 填充 provider evidence 入手。这是工程上容易的路线，但不是 alpha-leverage-first 的路线。
- 用户目标是 A/US 短线风控 + 爆发赛道、A/US 长线 push alpha。后续 implementation 前必须先判断每条 lane 的 alpha source、data/PIT/provider blockers、detectability horizon 和 portfolio-level contribution。
- 资金治理不变，不能用 temporary global AUM pool 解决 evidence accumulation；必须用 paper / live-normalized evidence level 区分，并禁止 paper-only ship-gate claim。

**验证命令**:

```powershell
git diff --check
```

以及 changed-doc trailing whitespace scan。

**验证结果**:

- 本轮为 docs-only 设计路由修改；最终校验结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一刀默认从 A-share EOD / benchmark provider capability evidence 入手”失效；改为先做 schema-first alpha plausibility audit，再按 alpha leverage / data blocker 排序 provider evidence。
- “Burst lane implementation 必须等 full provider set ready 才能开始”失效；改为 minimal-data paper tier 与 full-data live-eligible tier 分层。
- “Minimal live evidence 可以靠临时总 AUM pool 加速”失效；资金政策不变，ship-gate evidence 走 live-normalized 并记录 capacity / scaling validity。

**下一步注意事项**:

1. 下一条 `执行` 推荐新增 `schemas/alpha_plausibility_audit.schema.json`、example、tests，并产出第一版 audit。
2. Audit 结论再驱动 `long_alpha_spec.md` expected-alpha thesis 完整落地、A-short steady / variants 进一步收紧、provider priority、provisional benchmarks、burst tiering、evidence capital schema updates。
3. 不要在 alpha audit 前新增 provider adapter、抓 provider 数据、建立 DataHub table、或改 strategy runner 行为。

## 2026-05-27 追加：Alpha reality action guide

**改了什么**:

- 新增 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`，作为 Phase 7a+ 当前最高行动指南；`AGENTS.md` 已将其纳入必读路由和固化决策。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/strategy_design_synthesis.md`、`docs/alpha_plausibility_audit.md`、`docs/evidence_capital_policy.md`、`docs/burst_lane_spec.md`、`docs/long_alpha_spec.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`。
- 将最新三轮漏洞分析全部挂到既有 phase：Phase 7a-1 处理 alpha 真实性护栏；Phase 7a-2/7a-4/Phase 8 处理实战可用性；Phase 7a-5/Phase 9 处理工作流闭环；Phase 7b/7c/8 处理 DataHub operation / monitoring。

**为什么改**:

- 用户确认采纳最终设计，要求把设计变成所有后续 LLM 的最高行动指南。
- 原 Phase 7a 路由已经解决 alpha audit 前置，但还需要把 survivorship、multiple testing、statistical power、regime、factor exposure、execution cost、risk-filter effectiveness、decision packet、position reconciliation、data quality drift、kill switch 等业务真实性护栏写入 repo-visible owner docs。
- 这些不是新 design loop，而是防止 ship gate 纸面通过、实战失败的必要边界。

**验证命令**:

```powershell
git diff --check
```

以及 changed-doc trailing whitespace scan、active stale wording scan。

**验证结果**:

- 本轮 docs-only 变更的最终校验结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “Phase 7a audit 只需要 lane objective / provider blocker / verdict 字段”失效；Phase 7a-1 schema 还必须覆盖 alpha 真实性护栏。
- “cost-adjusted return、position reconciliation、decision packet、data quality drift 可以作为后期 polish”失效；这些已分配到 Phase 7a-5、Phase 7b/7c 或首次 live-normalized evidence 前的必修边界。
- “旧 24p t-stat finding 可直接作为显著结论”需加 multiple-testing / power / evidence-window 限定；未修正前只能作为探索性证据。

**下一步注意事项**:

1. 下一条 `执行` 仍然是 Phase 7a-1：写 `schemas/alpha_plausibility_audit.schema.json`、example、tests、lightweight provider status snapshot 和第一版 audit。
2. Phase 7a-1 必须使用 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` 的 mandatory field groups；不要缩水成主观 markdown audit。
3. 在 Phase 7a-1 review 通过前，不要新增 provider adapter、抓 provider 数据、建立 DataHub table、或改 strategy runner 行为。

### Optional O1 disposition

- Claude review O1 accepted. `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` now explicitly assigns drawdown / circuit-breaker tiered action playbook to Phase 7a-4 and to the non-optional later controls list. `AGENTS.md` and `docs/strategy_design_synthesis.md` route summaries now include the same Phase 7a-4 requirement.
- Required future shape: preset or lane contracts must define `circuit_breaker_playbook` tiers such as warn, size down, pause new entries, manual review, and reactivation / cooldown rule before Phase 8 implementation can rely on those lanes.

## 2026-05-27 追加：Phase 7a-1 provider status snapshot

**改了什么**:

- 新增 `docs/phase7a_provider_status_snapshot.json`，作为第一版 alpha plausibility audit 的 lightweight provider readiness input。
- 更新 `docs/README.md` 和 `docs/CURRENT.md` 路由：Phase 7a-1 schema contract 已完成，当前下一刀变为第一版 6 parent / 11 sub-lane audit。
- 更新 `tests/schema/test_alpha_plausibility_audit_schema.py`，验证该 snapshot 可嵌入 `alpha_plausibility_audit` example 并通过 schema 校验，同时确认它仍是 lightweight inventory，不是 provider selection。

**为什么改**:

- `docs/ALPHA_VALIDATION_ACTION_GUIDE.md §4` 要求 audit 在 provider evidence 不完整时使用 lightweight status snapshot，而不是提前启动 provider implementation。
- 第一版 audit 需要统一引用一个 provider readiness baseline，否则每条 lane 会各自猜测 A/US fundamentals、burst full-data、US microstructure 和 A-share EOD helper 的 readiness。
- 该 snapshot 明确区分：A-share EOD / CSI helper surfaces 是 narrow ready evidence；A/US long fundamentals、PIT industry history、US security master、burst full-data event / flow / options / borrow 仍 unknown 或 blocked。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_alpha_plausibility_audit_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan。

**验证结果**:

- `tests.schema.test_alpha_plausibility_audit_schema`：12 tests passed。
- Full `tests/schema` discovery：49 tests passed。
- `git diff --check` 和 trailing whitespace scan 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “第一版 audit 可以直接从 docs 推断 provider readiness”失效；必须引用 `docs/phase7a_provider_status_snapshot.json` 作为当前 readiness baseline。
- “A-share EOD / benchmark helper readiness 可代表 A-share provider readiness”失效；snapshot 仅标记 narrow helper surfaces ready，A-share fundamentals、SW PIT history 和 governance / audit red flags 仍 unknown。
- “US fundamentals / filings provider readiness 可等 implementation 时再判断”继续失效；snapshot 明确其为 unknown，是第一版 audit 的 blocker input。

**下一步注意事项**:

1. 下一条 `执行` 是第一版 alpha plausibility audit artifact，必须覆盖 11 sub-lanes 和 6 parent lanes。
2. Audit 的 `provider_status_snapshot_ref` 应引用 `provider_status_snapshot_20260527_phase7a1`。
3. 不要在 audit 前或 audit 中选择 provider、抓数据、建 adapter / DataHub table、改 runner，或把 paper evidence 写成 ship-gate evidence。

## 2026-05-27 追加：Phase 7a-1 first alpha plausibility audit

**改了什么**:

- 新增 `docs/phase7a_alpha_plausibility_audit.json`，作为第一版正式 schema-first alpha plausibility audit artifact。
- 更新 `tests/schema/test_alpha_plausibility_audit_schema.py`，验证正式 audit 通过 schema、不是 example artifact、引用 `provider_status_snapshot_20260527_phase7a1`，并覆盖 11 sub-lanes / 6 parent lanes。
- 更新 `docs/README.md`、`docs/CURRENT.md`、`docs/alpha_plausibility_audit.md` 路由与当前状态。

**为什么改**:

- Phase 7a-1 已有 schema contract 和 provider status snapshot；下一步必须产出真正的 audit artifact，而不是继续停在 contract / example 层。
- Audit 需要把用户目标拆成可执行 verdict：短线 steady 是否只做 risk filter、burst minimal/full 如何分层、长线是否 provider-blocked、哪些 provider evidence 先做。
- 该 artifact 明确不是 ship-gate evidence；它只决定下一阶段 spec revisions / provider sequencing / evidence horizon。

**当前 audit 结论摘要**:

- `continue_as_risk_filter`：`a_short_steady`、`a_short_variants`、`us_short_steady`。
- `continue`：`a_share_burst_minimal_data`、`us_burst_minimal_data`，均为 paper/research tier，不支持 live sizing。
- `defer_until_provider_ready`：`a_share_burst_full_data`、`us_burst_full_data`、`a_long_core_quality`、`a_long_re_rating_catalyst`、`us_long_core_quality`、`us_long_re_rating_catalyst`。
- 0 条 lane 获得 full-size / ship-gate 资格；固定 ship gate 与 capital policy 不变。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_alpha_plausibility_audit_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan。

**验证结果**:

- `tests.schema.test_alpha_plausibility_audit_schema`：14 tests passed。
- Full `tests/schema` discovery 最终结果记录在同日 Codex SESSION_LOG entry。
- `git diff --check` 和 trailing whitespace scan 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “Phase 7a-1 仍缺 first audit artifact”失效；第一版正式 audit 已存在。
- “下一刀继续产出 first audit”失效；下一刀进入 Phase 7a-2 spec revisions。
- “Minimal burst continue 可解释为 live eligibility”失效；audit 明确 minimal burst 只是 paper/research 继续。

**下一步注意事项**:

1. 下一条 `执行` 应进入 Phase 7a-2：用 audit 更新 `docs/strategy_design_synthesis.md`、`docs/long_alpha_spec.md`、`docs/burst_lane_spec.md` 和必要 routing。
2. 不要把 `continue` 当 ship-gate pass；不要把 `defer_until_provider_ready` 当失败，先转入 provider/PIT evidence sequencing。
3. 不要选 provider、抓数据、建 adapter / DataHub table、改 runner，除非后续 phase 明确进入对应 implementation slice。
