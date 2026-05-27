# Phase 6a kickoff spec handoff

**日期**：2026-05-26
**范围**：Phase 6a boundary kickoff：forward evidence、benchmark monthly returns、forward tracker → aggregate evidence flow、steady / variants / burst / long-spec 边界。
**状态**：kickoff spec 已建立；本文件只锁定边界与证据口径，不改业务代码、schema 或 runner。
**前置 handoff**：`docs/handoff/2026-05-25_phase5_kickoff_spec_handoff.md`（Phase 5 execution backtest、price data materializer、bucket-aware fill simulation、ship-gate evaluation、multi-period aggregation）。

---

## 1. 背景

Phase 5 已形成 A 股短线 execution evidence 的最小链路：

- `schemas/execution_backtest_report.schema.json` v1.2.0
- `schemas/execution_aggregate_report.schema.json` v1.0.0
- `runners/materialize_execution_price_data_tushare.py`
- `runners/backtest_execution.py`
- `runners/aggregate_execution_reports.py`

但 Phase 5 的真实 Tushare smoke 只有 202605 同月 3 个样本，只能证明 plumbing 可运行，不能构成 alpha / Sharpe / ship-gate 证据。`aggregate_execution_reports.py --forward-live-months` 默认 0，且 monthly alpha t-stat 只有传入显式 benchmark monthly return JSON 时才可评估。

Phase 6a 的目标是先定义 forward evidence 的边界，避免后续把历史回测、人工下单选择或单月 smoke 误算成 full-size ship gate 证据。

---

## 2. Phase 6a 边界

Phase 6a = kickoff spec / boundary contract。最小范围包括：

1. 定义什么算 Phase 6 forward evidence。
2. 固定 A 股短线 benchmark monthly return source。
3. 定义 `forward_tracker` 到 execution aggregate evidence 的数据流。
4. 定义 steady lane、bounded variants、`burst_lane`、long specs 的互斥边界。
5. 记录 Phase 6b 后续可执行的最小任务。

明确不做：

- 不改 `A-EGS/egs_main.py`。
- 不改 Phase 3 hard veto。
- 不实现 `burst_lane`。
- 不写 A 股长线 / 美股长线完整 spec。
- 不启动 Phase 7 DataHub / engine modularization。
- 不把单月真实 smoke 或历史 backtest 当成 forward live evidence。
- 不接入券商、OS 自动化或任何自动下单路径。

---

## 3. Boundary inputs

### 3.1 Scope lock

Phase 6 子阶段边界如下：

- **Phase 6a = kickoff spec / boundary contract**：只锁定 forward evidence、benchmark、记录格式、steady / variant / burst / long-spec 边界；不跑观察、不改 runner、不实现 variant。
- **Phase 6b = A 短 maintenance / evidence line**：继续 weekly forward capture、comparison-track accumulator、forward evidence accumulation；不扩新小工具，除非直接服务 evidence clock。六个 A-short variants 仍按 §5.2 路由，但不再独占 Phase 6 设计算力。
- **Phase 6c = A/US `burst_lane` spec**：短线 alpha-source spec，独立 signal、risk lock、sizing gate、ship gate，不继承 steady lane gate。
- **Phase 6d = long alpha spec pack + US-short normalization**：long alpha common spec、A-long annex、US-long annex、US-short spec normalization；长线系统从 alpha 主系统重新设计，美股短线 reference 规范化。
- **Phase 6e = provider / data requirements audit**：列出 4 套 spec 对字段、PIT、频率、lineage、授权/成本/稳定性的要求；不在本步锁最终 provider。

This lock prevents treating Phase 6a kickoff text as Phase 6a observation completion, and establishes spec-parallel / implementation-gated execution: multiple docs-only specs may be drafted in reviewable slices, while production implementation remains single-threaded through the normal review flow.

### 3.2 Forward evidence 定义

Phase 6b forward evidence 必须同时满足：

1. **预先捕获**：候选池必须来自当期真实 screening run 的 `result/a_short/<as_of>/analysis_input.json`，并在结果未知时由 `runners/forward_tracker.py capture --as-of <YYYYMMDD>` 捕获到 `logs/forward_tracker.csv`。
2. **可复现输入**：execution replay 必须读取捕获当期的 `analysis_input.json`，而不是事后人工筛选股票列表。
3. **成熟窗口**：5d / 10d / 20d 或 execution window 的价格路径必须已经自然成熟；未成熟窗口只可记录为 pending。
4. **真实 provider lineage**：price data 和 benchmark returns 必须记录 provider/API/date range。当前 A 股短线使用 Tushare：股票执行价来自 `daily` / `adj_factor` / `stk_limit` / `trade_cal`，benchmark 来自 `index_daily`。
5. **人工交易隔离**：用户实际是否手动下单、是否跳过某票、是否加减仓，不进入 execution aggregate 的 candidate set。execution evidence 只评估当期系统输出在确定性规则下的结果。
6. **按月计数**：`forward_live_months` 只统计具备至少一个有效 live captured `as_of` 且已生成对应 execution report 的自然月。历史 backtest、smoke、未捕获候选池、手工补选都不得增加该计数。

### 3.3 A 短 benchmark monthly return source

已决 benchmark policy：

- **Primary**：CSI1000，Tushare `index_daily/000852.SH`。
- **Secondary**：CSI300，Tushare `index_daily/000300.SH`，mandatory sensitivity report。
- **Primary gate**：`aggregate_execution_reports.py --benchmark-monthly-returns <primary_json>` 的 monthly alpha t-stat 是自动 ship-gate 判定使用的 benchmark-aware alpha。
- **Secondary sensitivity**：同一批 execution reports 必须用 CSI300 monthly returns 跑 sensitivity。CSI300 不进入自动 AND gate，但结论必须可见。

Monthly benchmark return JSON 格式沿用 aggregate runner 现有输入：

```json
{
  "202605": 0.0123,
  "202606": -0.0045
}
```

计算口径：

- 月度收益使用 benchmark 当月首个可交易日 close 到当月最后一个可交易日 close 的 close-to-close return。
- 月份必须覆盖 aggregate report 的 `metrics.monthly_return_series[*].month`。
- 缺月份时不得用 0 填充；缺失月份应让 alpha t-stat 不可评估或触发 coverage warning。
- 当前 aggregate runner 的 Sharpe 是 execution monthly total return Sharpe，不随 benchmark 改变；不要把它解释为 benchmark-excess Sharpe。

### 3.4 `benchmark_sensitive` 触发与输出

Phase 6a 先定义报告语义；是否把字段写入 `execution_aggregate_report` schema 留给后续最小实现决定。没有 schema 字段前，可用 sidecar `benchmark_sensitivity.json` 或 Markdown review section 记录同等信息。

建议 machine-readable 形态：

```json
{
  "primary": "csi1000",
  "secondary": "csi300",
  "primary_source": "tushare:index_daily/000852.SH",
  "secondary_source": "tushare:index_daily/000300.SH",
  "benchmark_sensitive": true,
  "flags": {
    "alpha_gate_disagreement": true,
    "opposite_t_stat_signs": false,
    "t_stat_gap": true,
    "secondary_coverage_missing": false
  },
  "primary_monthly_alpha_t_stat": 2.15,
  "secondary_monthly_alpha_t_stat": 0.80,
  "ship_gate_uses": "primary_only"
}
```

Default merge rule: keep each dimension as its own boolean field, and set `benchmark_sensitive = OR(flags)`. Do not collapse the four dimensions into an unexplainable single boolean.

Set the dimension flags when these conditions hold:

1. Primary and secondary monthly alpha gate results disagree, for example primary `monthly_alpha_t_stat >= 2.0` while secondary `< 2.0`, or the reverse. The `2.0` example refers to the current ship-gate alpha threshold; if the schema or policy later changes that threshold, use the then-current `ship_gate_evaluation` definition.
2. Both t-stats are evaluable and have opposite signs.
3. Both t-stats are evaluable and the absolute t-stat gap exceeds the threshold later defined from Phase 6b evidence.
4. Primary is evaluable but secondary is not because benchmark data coverage is missing for one or more aggregate months.

The exact numeric gap threshold is not locked in Phase 6a. Phase 6b should set it after the first benchmark sensitivity evidence exists.

`benchmark_sensitive=true` is a review escalation flag, not an automatic full-size block by itself. Full-size remains blocked unless the primary AND gate passes and forward live months are at least 12. If the flag is true, Claude/user review must decide whether the evidence is style-beta-sensitive before any promotion.

### 3.5 Primary switch trigger

Primary benchmark remains CSI1000 until a quantified review proposes a switch. Subjective descriptions such as "候选池看起来偏大盘" are insufficient.

A switch proposal may be raised only after all of the following are available:

1. At least 6 forward live months with captured candidate universes. The 6-month minimum is a preliminary review floor: it spans at least two quarters and reduces the chance that a single regime or cohort drift drives a primary-switch proposal.
2. Candidate universe style audit with data lineage for index membership or market-cap proxy.
3. Evidence that at least 3 consecutive monthly cohorts are closer to CSI300 than CSI1000 by the chosen metric.
4. A side-by-side primary/secondary sensitivity report showing why CSI1000 is no longer the right default.

Candidate metrics for the audit:

- CSI300 / CSI1000 constituent overlap by count.
- Free-float market-cap percentile versus CSI300 and CSI1000 distributions.
- Median / weighted market-cap drift over consecutive monthly cohorts.
- Sector/style concentration that makes one index materially less representative.

Until those data fields exist, no primary switch is allowed. The absence of membership or market-cap data means "insufficient evidence", not permission to switch by judgment.

### 3.6 Considered and deferred benchmarks

CSI500 and size-decile portfolio benchmarks were considered. They are deferred to the A-short maintenance / evidence line or later because Phase 6a's immediate need is to unblock a concrete primary/secondary policy for aggregate alpha t-stat. Adding more benchmarks now would widen the contract before the first forward evidence month exists.

If A-short forward evidence shows CSI1000 / CSI300 sensitivity is unstable, CSI500 or size-decile benchmark construction can be reopened as a bounded research/variant question.

---

## 4. Forward tracker → aggregate evidence flow

The intended A-short forward evidence flow is:

1. Weekly run produces `result/a_short/<as_of>/analysis_input.json`.
2. `weekly_screening.ps1` runs `forward_tracker.py capture --as-of <YYYYMMDD>` and appends candidate rows to ignored `logs/forward_tracker.csv`.
3. After windows mature, `forward_tracker.py backfill` fills 5d / 10d / 20d return columns for diagnostics. These columns support Phase 6b variant and rank-quality analysis; they are not execution ship-gate evidence by themselves.
4. For each valid live `as_of`, materialize execution price data using the captured `analysis_input.json` and a naturally matured forward date range.
5. Run `backtest_execution.py` with the same P0a capital context inputs and per-as-of output directory, producing one schema-valid `execution_report.json` per live `as_of`.
6. Build primary CSI1000 and secondary CSI300 monthly benchmark return JSON files covering the execution report months.
7. Run `aggregate_execution_reports.py` once with primary benchmark returns for the ship-gate evidence artifact.
8. Run the same aggregation with secondary benchmark returns, or compute a sidecar sensitivity report from the same monthly return series.
9. Count `forward_live_months` as the number of distinct calendar months represented by valid captured live evidence, not the number of reports.

Recommended output isolation for future implementation:

```text
result/a_short/backtest/execution/forward/<as_of>/
├── execution_price_data.json
├── execution_report.json
├── trades.csv
├── daily_equity.csv
├── order_events.csv
└── skipped_candidates.csv

result/a_short/backtest/execution/forward_aggregate/
├── benchmark_monthly_returns_csi1000.json
├── benchmark_monthly_returns_csi300.json
├── execution_aggregate_report_csi1000.json
└── benchmark_sensitivity.json
```

These are generated artifacts and should remain ignored unless a later task explicitly adds a small sanitized fixture.

---

## 5. Lane boundaries

### 5.1 Steady A-short lane

Steady lane is the current A-short production-style baseline:

- uses existing screening + analyzer + execution runner contracts,
- keeps bucket-aware `capital_context`,
- treats full-size manual use as blocked until ship gate passes,
- does not relax hard vetoes to chase burst returns.

### 5.2 A-short variants

Phase 6b keeps bounded A-short variants alive as a maintenance / evidence line. Candidate-universe audit, forward evidence accumulation, and benchmark-aware alpha sedimentation are the evidence pipeline supporting that line.

The canonical variant family definitions live in `docs/strategy_design_synthesis.md §2.2`. This table records routing only:

| Variant family | Phase 6b routing |
|---|---|
| `chasing_high_veto` | Track as a veto candidate versus steady baseline. |
| `overheat_veto` | Track as a veto candidate versus steady baseline. |
| `tier1_only_trading` | Track Tier1-only evidence while Tier2 remains observation-only. |
| `esp_cap_or_winsorize` | Track cap / winsorize behavior without turning extreme ESP into an immediate hard veto. |
| `rank_bucket_split` | Track rank buckets separately against the same captured candidate universe. |
| `exit_policy_variants` | Track exit-policy variants against the same entry universe and capital context. |

Variants must compare against the steady baseline and need forward evidence before promotion. Backtest-only improvement is not enough. If forward evidence shows a promotable alpha signal, raise an explicit escape-valve review before reallocating implementation capacity back to A-short.

### 5.3 `burst_lane`

`burst_lane` is Phase 6c. It must have its own signal spec, risk lock, sizing gate, and independent ship gate. It does not inherit the steady lane's gate result and must not be implemented by weakening steady lane filters.

### 5.4 A-long / US-long specs and US-short normalization

Phase 6d owns the long alpha spec pack plus US-short normalization. Long-term systems are alpha-push systems built from scratch; they do not reuse short-term v14.x rules. Phase 6d should split common long-alpha requirements from market annexes so A-long and US-long do not duplicate or implicitly overwrite each other.

### 5.5 Research and DataHub

Research infrastructure is Phase 7.5. DataHub / engine modularization is Phase 7 and must use the four specs to split shared layers from independent rule packs.

---

## 6. Completion line for Phase 6a kickoff spec

Phase 6a kickoff spec is complete when:

1. This handoff exists and is routed from `AGENTS.md` / `docs/CURRENT.md`.
2. `docs/CURRENT.md` no longer carries detailed benchmark trigger text that belongs in the handoff.
3. The A-short benchmark policy is explicit: CSI1000 primary, CSI300 secondary sensitivity.
4. `benchmark_sensitive` semantics and primary switch prerequisites are defined.
5. Forward evidence counting is separated from historical backtest and manual trade decisions.
6. Next work is routed to the Phase 6 spec pack: A-short remains a maintenance / evidence line, while A/US burst, long alpha specs, US-short normalization, and provider/data requirements audit are written as docs-only slices before Phase 7 implementation.

---

## 7. 验证命令

```powershell
git diff --check
```

No unit tests are required for this handoff-only docs change.

---

## 8. 验证结果

- `git diff --check` passed.
- No code, schema, runner, preset, or fixture files changed.

---

## 9. 失效旧结论

- “Phase 6a benchmark-sensitive reporting is still undefined”失效；本 handoff 定义了 trigger 和 output shape。
- “CURRENT.md should carry the full Phase 6a benchmark trigger text”失效；CURRENT.md 只保留 snapshot，完整规则在本 handoff。
- “Forward tracker backfilled 5d/10d/20d returns can directly become ship-gate evidence”失效；它们是 diagnostics，ship-gate evidence must flow through execution reports + aggregate reports.
- “CSI500 / size-decile benchmark must be decided before Phase 6a starts”失效；它们已记录为 considered and deferred.
- “Phase 6a kickoff spec complete means Phase 6b observation is done”失效；kickoff spec 只是边界建立。2026-05-27 route amendment 后，A-short 承接 maintenance / evidence line，Phase 6 spec pack 承接 burst / long / US-short / provider requirements。

---

## 10. 下一步注意事项

1. Claude should review whether the benchmark-sensitive triggers are too loose/tight and whether the forward evidence counting rule prevents evidence contamination.
2. Superseded by the 2026-05-27 route amendment below: next `执行` after that amendment should start the Phase 6 spec pack, while A-short continues only as maintenance / evidence line.
3. Any future code task that adds benchmark monthly return materialization should keep CSI1000 primary and CSI300 secondary artifacts side by side.
4. Do not modify `A-EGS/egs_main.py` for Phase 6a; weekly capture and aggregate evidence should consume existing outputs.
5. Keep generated forward evidence artifacts ignored unless a later test task intentionally creates small sanitized fixtures.

---

## 2026-05-26 追加：Phase 6b variant tracking contract

### 改了什么

- 新增 `schemas/a_short_variant_tracking.schema.json` v1.0.0，作为 Phase 6b A-short 六个 bounded variants 的 tracking-only comparison contract。
- 新增 `schemas/examples/a_short_variant_tracking.example.json`，记录六个 variant family 的初始 track routing。
- 新增 `tests/schema/test_a_short_variant_tracking_schema.py`，覆盖 schema meta validation、六个 family exact set、tracking-only / baseline comparison / no scope-creep boundaries、example validation、missing / extra variant rejection、wrong family id rejection、non-tracking status rejection。
- 修复阶段按项目 schema pattern 将单值 policy fields 从 single-value `enum` 对齐为 `const`：`contract_status`、`track_status`、`evidence_policy.source`。

### 为什么

Phase 6b 的主轴是 A-short variants 并行验证。先落 schema contract，可以让后续 runner / plan materialization 使用同一组 family、同一 steady baseline、同一 forward evidence / benchmark sensitivity / P0a capital context 边界，避免 future LLM 直接写策略逻辑或把 backtest-only improvement 当成 promotion evidence。

### 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_a_short_variant_tracking_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

### 验证结果

- `tests.schema.test_a_short_variant_tracking_schema`：9 tests passed。
- `unittest discover -s tests/schema`：24 tests passed。
- `git diff --check`：passed。

### 失效旧结论

- “Phase 6b variants 只有文档 routing、没有机器可校验 contract”失效；现在有 `a_short_variant_tracking` v1.0.0 contract。
- “第一批 variant tracking 可以自行增删 family”失效；contract 要求六个 family exact set。
- “variant tracking 可以顺手修改 EGS、Phase 3 hard veto 或实现 burst lane”失效；contract 明确禁止这些 scope。

### 下一步注意事项

1. 下一条 Phase 6b implementation slice 可围绕该 schema 写最小 plan / materialization runner，或先写 benchmark monthly-return materializer。
2. `a_short_variant_tracking` 只定义 tracking shape，不计算证据、不提供 promotion decision。
3. Future runner must compare variants against `steady_a_short_baseline` and must not treat backtest-only improvement as promotion evidence.

---

## 2026-05-26 追加：Phase 6b variant tracking plan materializer

### 改了什么

- 新增 `runners/materialize_a_short_variant_tracking.py`，作为 `a_short_variant_tracking` v1.0.0 的 first consumer / plan materialization runner。
- Runner 默认读取 `schemas/examples/a_short_variant_tracking.example.json`，刷新 `generated_at`，按 `schemas/a_short_variant_tracking.schema.json` 校验，并写入默认忽略路径 `result/a_short/backtest/variants/a_short_variant_tracking_plan.json`。
- `.gitignore` 新增 `result/*/backtest/variants/`，确保默认 materialized plan / 后续 variant evidence artifacts 不会误入版本控制。
- 新增 `tests/phase6/test_materialize_a_short_variant_tracking.py`，覆盖 CLI 写出 schema-valid plan、默认输出路径、template 不被原地修改、scope-creep template 在写出前被 schema validation 拒绝。
- 更新 `runners/README.md` 与 `docs/CURRENT.md` 的 Phase 6b 状态。

### 为什么

Phase 6b contract 已有机器可校验 schema，但还没有任何 runner 消费它。这个切片只建立 plan materialization 入口，让后续 comparison tracks / evidence materialization 从同一个 canonical plan 出发，避免 future LLM 直接绕过 contract 写 variant 逻辑。

### 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.phase6.test_materialize_a_short_variant_tracking -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_a_short_variant_tracking_schema -v
git diff --check
git check-ignore result/a_short/backtest/variants/a_short_variant_tracking_plan.json
```

### 验证结果

- `tests.phase6.test_materialize_a_short_variant_tracking`：4 tests passed。
- `tests.schema.test_a_short_variant_tracking_schema`：9 tests passed。
- `git diff --check`：passed。
- `git check-ignore result/a_short/backtest/variants/a_short_variant_tracking_plan.json`：confirmed ignored。

### 失效旧结论

- “Phase 6b variant tracking 只有 schema/example、没有 consumer”失效；现在有最小 plan materialization runner。
- “下一步仍是 first consumer / plan materialization”失效；该切片已完成，下一步应转向 comparison tracks / evidence materialization 或 benchmark monthly-return materialization。

### 下一步注意事项

1. `materialize_a_short_variant_tracking.py` 仍只生成 tracking plan，不计算 evidence、不改 EGS、不 promotion、不实现 `burst_lane`。
2. 下一条 Phase 6b implementation slice 可围绕 materialized plan 生成 variant comparison track inputs，或实现 CSI1000 / CSI300 benchmark monthly-return materializer。
3. Generated variant plan artifacts 默认位于 ignored `result/a_short/backtest/variants/`；不要把真实 forward evidence 产物纳入 git。

---

## 2026-05-26 追加：Phase 6b benchmark monthly-return materializer

### 改了什么

- 新增 `runners/materialize_benchmark_monthly_returns_tushare.py`，从 Tushare `index_daily` 生成 Phase 6 A-short benchmark monthly return JSON。
- 默认同时输出 CSI1000 primary (`000852.SH`) 与 CSI300 secondary (`000300.SH`) 两组 artifact：
  - `benchmark_monthly_returns_csi1000.json`
  - `benchmark_monthly_returns_csi1000_metadata.json`
  - `benchmark_monthly_returns_csi300.json`
  - `benchmark_monthly_returns_csi300_metadata.json`
- Return JSON 保持 `aggregate_execution_reports.py --benchmark-monthly-returns` 兼容的 `YYYYMM -> return` 形态；metadata sidecar 记录 provider/API/date range、benchmark role、ts_code、monthly return method、每月首末交易日和 close。
- 新增 `tests/execution/test_materialize_benchmark_monthly_returns_tushare.py`，覆盖 first/last close 月收益计算、primary + secondary CLI 输出、默认路径、benchmark 去重、日期校验、单交易日月份拒绝、缺列拒绝、非正 close 拒绝。
- 更新 `runners/README.md` 与 `docs/CURRENT.md`。

### 为什么

Phase 6a 已锁定 A 短 ship-gate alpha 的 benchmark policy：CSI1000 primary，CSI300 mandatory secondary sensitivity。Phase 5 aggregate runner 已有 `YYYYMM -> return` 输入，但缺少按该 policy 生成月收益的 provider-boundary helper。本切片把 benchmark-aware alpha 所需的月收益输入落成可测 runner，同时保持 aggregate runner 的现有接口不变。

### 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.execution.test_materialize_benchmark_monthly_returns_tushare -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.execution.test_aggregate_execution_reports -v
git diff --check
```

### 验证结果

- `tests.execution.test_materialize_benchmark_monthly_returns_tushare`：8 tests passed。
- `tests.execution.test_aggregate_execution_reports`：6 tests passed。
- `git diff --check`：passed。

### 失效旧结论

- “Phase 6a benchmark monthly returns 只有 policy，没有 materializer”失效；现在有 Tushare `index_daily` materializer。
- “下一步仍需选择 first consumer vs benchmark monthly-return materializer”失效；二者都已完成。下一步应转向 materialized-plan driven comparison track inputs、candidate-universe overlap audit，或 forward evidence accumulation。

### 下一步注意事项

1. CSI1000 remains the primary benchmark for automatic aggregate alpha gate; CSI300 remains mandatory secondary sensitivity and review escalation.
2. Return JSON intentionally remains a plain `YYYYMM -> return` object for aggregate runner compatibility; lineage lives in the metadata sidecar.
3. The materializer uses first available `index_daily` close to last available `index_daily` close within each requested month. Callers should request date ranges that cover the aggregate execution months completely.
4. Generated benchmark artifacts default under ignored `result/a_short/backtest/execution/forward_aggregate/`; do not commit real forward evidence artifacts.

---

## 2026-05-27 追加：Phase 6b candidate-universe overlap audit

### 改了什么

- 新增 `schemas/candidate_universe_overlap_audit.schema.json` v1.0.0，作为单个 captured A-short candidate universe 与 CSI1000 / CSI300 成分重叠的审计 artifact contract。
- 新增 `runners/audit_candidate_universe_overlap_tushare.py`，读取 `analysis_input.json` 候选 `ts_code`，从 Tushare `index_weight` 拉 CSI1000 primary (`000852.SH`) 与 CSI300 secondary (`000300.SH`) 成分，输出 schema-valid overlap audit JSON。
- Claude review Optional disposition 后，audit `settings` 内联记录 `provider="tushare"` 与 `api_families=["index_weight", "tushare_provider"]`；`index_weight` 空返回优先报 no rows，再区分有数据但缺列。
- 默认输出路径为 ignored `result/a_short/backtest/execution/forward_aggregate/candidate_universe_overlap_audit_<as_of>.json`。
- 新增 `tests/schema/test_candidate_universe_overlap_audit_schema.py` 与 `tests/phase6/test_audit_candidate_universe_overlap_tushare.py`，覆盖 schema meta、provider lineage、primary-switch guard、CSI1000/CSI300 required pair、CLI 写出、latest membership date 选择、重复候选去重、date mismatch、空候选池、空 index_weight、缺列与无 usable membership rows。
- 更新 `runners/README.md` 与 `docs/CURRENT.md`。

### 为什么

Phase 6a 已规定 primary switch 必须有 candidate universe style audit，而不能用主观描述判断候选池“像大盘/小盘”。本切片先把最小可复现 audit artifact 落地：用 captured `analysis_input` 的候选池与 Tushare index membership 做 count overlap。它只提供 benchmark-policy evidence，不切换 primary benchmark，不计算 alpha，不 promotion variant。

### 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_candidate_universe_overlap_audit_schema tests.phase6.test_audit_candidate_universe_overlap_tushare -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_candidate_universe_overlap_audit_schema tests.phase6.test_audit_candidate_universe_overlap_tushare tests.execution.test_materialize_benchmark_monthly_returns_tushare tests.phase6.test_materialize_a_short_variant_tracking tests.schema.test_a_short_variant_tracking_schema -v
git diff --check
git check-ignore result/a_short/backtest/execution/forward_aggregate/candidate_universe_overlap_audit_20260621.json
```

### 验证结果

- `tests.schema.test_candidate_universe_overlap_audit_schema` + `tests.phase6.test_audit_candidate_universe_overlap_tushare`：11 tests passed。
- Candidate-universe audit + benchmark materializer / variant plan materializer / variant tracking schema regression：32 tests passed。
- `git diff --check`：passed（CRLF warnings only）。
- `git check-ignore ...candidate_universe_overlap_audit_20260621.json`：confirmed ignored。

### 失效旧结论

- “Candidate-universe overlap audit 只有 Phase 6a policy，没有机器可校验 artifact contract”失效；现在有 `candidate_universe_overlap_audit` v1.0.0。
- “候选池风格/指数 overlap 只能靠人工描述”失效；现在有 Tushare `index_weight` provider-boundary helper。
- “单次 overlap audit 可以触发 primary switch”明确失效；schema 和 runner 均锁定 `primary_switch_allowed=false`，primary switch 仍需 Phase 6a §3.5 的 6 个月、多 cohort 和 sensitivity 条件。

### 下一步注意事项

1. 该 runner 只做 count overlap；market-cap percentile、sector/style concentration 仍未实现，后续需要数据字段再扩。
2. 多期审计结果可以作为 primary-switch review 的输入，但单个 audit artifact 不允许切换 CSI1000 primary。
3. Superseded by the following 2026-05-27 route amendment: the next default slice is no longer an A-short Phase 6b slice. A-short comparison-track / forward evidence work remains valid only as maintenance / evidence-clock work.

---

## 2026-05-27 追加：Phase 6 route amendment（spec-parallel / implementation-gated）

### 改了什么

- 修订 `AGENTS.md` Phase roadmap 和已固化决策 #12：Phase 6 改为 **spec 层并行 + implementation 层串行受控**。
- 修订 `docs/CURRENT.md`：P0 从 “Phase 6b A-short observation 独占主线”改为 Phase 6 spec pack；A-short 降为 maintenance / evidence line。
- 修订 `docs/strategy_design_synthesis.md §6`：新增 Phase 6e provider / data requirements audit，并把 Phase 8/9 ordering 改为 `capital weight × alpha leverage × data readiness`。
- 修订本 handoff §3.1 / §5 / §6：同步新的 Phase 6 子阶段边界。

新的 Phase 6 路由：

1. **6b A-short maintenance / evidence line**：weekly forward capture、comparison-track accumulator、forward evidence accumulation；不扩新小工具，除非直接服务 evidence clock。
2. **6c A/US `burst_lane` spec**：短线 alpha-source spec；共用 signal family，分市场定义数据字段差异，独立 risk / sizing / ship gate。
3. **6d long alpha spec pack + US-short normalization**：long alpha common spec、A-long annex、US-long annex、US-short spec normalization。
4. **6e provider / data requirements audit**：列字段、PIT、频率、lineage、授权/成本/稳定性要求；不在本步锁最终 provider。

### 为什么

现有策略架构本身不需要推翻：短线仍是 steady risk-filter lane + bounded variants + independent `burst_lane`，长线仍是 alpha 主系统。但执行序列若继续让 A-short Phase 6b 独占算力，会让占比更高的 US-long / US-short 以及长线 alpha spec 过晚启动，并串行放大 12+ 个月 forward evidence 的等待成本。

本次修订只调整执行重心，不降低任何证据门槛：

- A-short 占总组合约 11.67%，不能无限独占 Phase 6 design capacity。
- `burst_lane` 是短线新 alpha source，不能长期排在 steady variants 内部优化之后才定义。
- 长线 alpha spec 不依赖 DataHub 先实现；相反，DataHub Phase 7 应由四套 spec 和 provider/data requirements audit 反向定义字段。
- DataHub 提高可复现性和复用性，不是 alpha evidence 本身。

### Anti-pattern lock

- 这次重排不是降低 ship gate。Full-size 仍需 monthly alpha t-stat ≥ 2.0、Sharpe ≥ 1.0、max drawdown ≤ 15%、forward live data ≥ 12 个月。
- 这次重排不是跳过 A-short forward evidence。A-short weekly capture 和 mature-window evidence accumulation 必须继续。
- 这次重排不是 implementation 层并行。代码、schema、runner、migration 仍按单 scope、reviewable commit 串行推进。
- 这次重排不是直接 provider 选型。Phase 6e 先做 data requirements audit，最终 provider 选择需要单独证据。
- 这次重排不是把 docs-only spec 当成 production readiness。Spec 只是后续 schema / runner / tests / DataHub 的输入。

### Ship gate 时间现实

Ship gate 的 12 个月 forward live data 是硬约束。即使四套系统尽早开始 paper / minimal evidence clock，full-size 最早也只能在 12+ 个月有效 forward evidence 之后；降低这个门槛不是健康加速路径。健康路径是让多套子系统尽早进入 paper / minimal observation，同时保持 `ship_gate_not_passed` 的 sizing 降级语义。

### A-short escape valve

A-short 默认降为 maintenance / evidence line。但如果 forward evidence 显示可推广 alpha（例如相对 steady baseline 的 risk-adjusted improvement 持续成立，且不依赖单月 / 单 cohort），可显式发起 escape-valve review，重新分配 implementation capacity。该 review 必须引用 forward evidence、benchmark sensitivity、drawdown、capital context 和 ship-gate status，不能只引用历史 backtest 或单次 audit。

### 验证命令

```powershell
git diff --check
```

### 验证结果

- `git diff --check` passed（CRLF warnings only）。

### 失效旧结论

- “Phase 6b A-short variants 是 Phase 6 的唯一主轴，6c / 6d 等 6b 完整做完后再开始”失效。
- “Phase 6b candidate-universe overlap audit 追加段的下一步 #3 表示下一刀默认仍是 A-short Phase 6b slice”失效；A-short comparison-track / forward evidence work 只作为 maintenance / evidence-clock work 保留。
- “DataHub Phase 7 主要按 A-short 当前需求重构”失效；Phase 7 必须等待四套 spec + provider/data requirements audit 给出字段需求。
- “Provider 选型可以在 long spec 之后随手决定”失效；provider/data requirements audit 是单独 Phase 6e 输入，不等于最终 provider 选择。

### 下一步注意事项

1. Superseded by the following 2026-05-27 long-alpha append: `long alpha common spec + US-long annex skeleton` is now completed as a docs-only slice; next default slice is A-long annex.
2. 后续每份 spec 独立一轮 `执行 → 审查 → 修复 → 提交`，避免一次性大文档无法审查。
3. A-short 只保留 evidence clock 相关小步，不继续扩无关辅助工具。
4. Phase 7 DataHub 不应启动，直到 long alpha common spec、A-long annex、US-long annex、A/US burst spec、US-short normalization、provider/data requirements audit 至少都有 reviewed baseline。

---

## 2026-05-27 追加：Long alpha common spec + US-long annex skeleton

### 改了什么

- 新增 `docs/long_alpha_spec.md`，作为 A-long / US-long 长线 alpha 共同规格 owner 文档。
- 写入 long alpha common spec：factor catalog、PIT rules、industry normalization、portfolio construction、thesis-broken exit、quarterly review、validation / promotion、common data requirements。
- 写入 US-long annex skeleton：GICS taxonomy、10-K / 10-Q、FCF margin、ROIC、buyback efficiency、guidance credibility、US benchmark candidates、provider-readiness dependencies。
- 同步 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/strategy_design_synthesis.md` 的路由和下一步状态。

### 为什么

Phase 6 route amendment 已把 spec pack 定为下一阶段主线，且要求 DataHub Phase 7 由四套 spec + provider/data requirements audit 反向定义字段。长线是 push alpha 主战场；先建立 common spec 可以避免 A-long / US-long 各自重复定义 factor semantics、PIT 规则、行业归一化、exit 和 ship-gate 边界。US-long skeleton 同步写入，是因为 US-long 是最大单 bucket，且其 provider/data 需求会直接影响后续 Phase 6e audit。

### Scope lock

- 本切片是 docs-only。
- 不新增 schema、runner、migration、provider、DataHub implementation。
- 不锁定 numeric factor weights、thresholds、exact US universe、primary US benchmark 或 provider choice。
- 不降低 ship gate；full-size 仍需 monthly alpha t-stat ≥ 2.0、Sharpe ≥ 1.0、max drawdown ≤ 15%、forward live data ≥ 12 个月。
- 不改变 manual-order-only 边界。

### 验证命令

```powershell
git diff --check
```

### 验证结果

- `git diff --check` passed（CRLF warnings only）。

### 失效旧结论

- “长线 alpha spec 只有 strategy synthesis 摘要，没有 owner 文档”失效；现在 owner 是 `docs/long_alpha_spec.md`。
- “Phase 6d 第一刀仍待定”失效；第一刀已完成为 common spec + US-long skeleton，下一刀默认转向 A-long annex。
- “US-long spec 必须等 provider 选择后才能写”失效；本切片只列 data requirements 和 readiness dependencies，provider 选择留给 Phase 6e。

### 下一步注意事项

1. 下一条 `执行` 推荐在 `docs/long_alpha_spec.md` 内补 A-long annex，仍保持 docs-only，不新增 schema / runner。
2. Phase 6e provider/data requirements audit 应引用本文件 §9 / §10.4，但不能把本文件视为 provider selection verdict。
3. 后续 US-long 完整 annex 仍需补 exact universe、primary benchmark、provider evidence、numeric factor weights / thresholds 和 report/schema interfaces。
