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
- **Phase 6b = A 短观察期**：主轴是六个 A-short variants 并行验证（具体 routing 见 §5.2）；evidence pipeline 支撑包括 (i) candidate-universe overlap audit，(ii) forward evidence accumulation，(iii) benchmark-aware alpha evidence sedimentation。
- **Phase 6c = `burst_lane` spec**：独立 signal、risk lock、sizing gate、ship gate，不继承 steady lane gate。
- **Phase 6d = A-long / US-long specs + US-short normalization**：长线系统从 alpha 主系统重新设计，美股短线 reference 规范化。

This lock prevents treating Phase 6a kickoff text as Phase 6a observation completion, and prevents starting Phase 6b work before the boundary contract is reviewed.

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

CSI500 and size-decile portfolio benchmarks were considered. They are deferred to Phase 6b or later because Phase 6a's immediate need is to unblock a concrete primary/secondary policy for aggregate alpha t-stat. Adding more benchmarks now would widen the contract before the first forward evidence month exists.

If Phase 6b A-short observation shows CSI1000 / CSI300 sensitivity is unstable, CSI500 or size-decile benchmark construction can be reopened as a bounded research/variant question.

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

Phase 6b owns bounded A-short variants as the observation main axis. Candidate-universe audit, forward evidence accumulation, and benchmark-aware alpha sedimentation are the evidence pipeline supporting that axis, not competing main tasks.

The canonical variant family definitions live in `docs/strategy_design_synthesis.md §2.2`. This table records routing only:

| Variant family | Phase 6b routing |
|---|---|
| `chasing_high_veto` | Track as a veto candidate versus steady baseline. |
| `overheat_veto` | Track as a veto candidate versus steady baseline. |
| `tier1_only_trading` | Track Tier1-only evidence while Tier2 remains observation-only. |
| `esp_cap_or_winsorize` | Track cap / winsorize behavior without turning extreme ESP into an immediate hard veto. |
| `rank_bucket_split` | Track rank buckets separately against the same captured candidate universe. |
| `exit_policy_variants` | Track exit-policy variants against the same entry universe and capital context. |

Variants must compare against the steady baseline and need forward evidence before promotion. Backtest-only improvement is not enough.

### 5.3 `burst_lane`

`burst_lane` is Phase 6c. It must have its own signal spec, risk lock, sizing gate, and independent ship gate. It does not inherit the steady lane's gate result and must not be implemented by weakening steady lane filters.

### 5.4 A-long / US-long specs and US-short normalization

Phase 6d owns A-long and US-long specs plus US-short normalization. Long-term systems are alpha-push systems built from scratch; they do not reuse short-term v14.x rules.

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
6. Next work is routed to Phase 6b A-short observation: six A-short variants are the main axis; candidate-universe overlap audit, forward evidence accumulation, and benchmark-aware alpha sedimentation are the supporting evidence pipeline. Phase 6c / 6d remain separate later deliverables.

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
- “Phase 6a kickoff spec complete means Phase 6b observation is done”失效；kickoff spec 只是边界建立，Phase 6b 才承接 audit / forward / alpha / variants 观察。

---

## 10. 下一步注意事项

1. Claude should review whether the benchmark-sensitive triggers are too loose/tight and whether the forward evidence counting rule prevents evidence contamination.
2. Next `执行` after review/commit should start Phase 6b A-short observation boundary or first implementation slice: candidate-universe overlap audit, benchmark monthly-return materialization, forward evidence accumulation, or variant tracking contract.
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
