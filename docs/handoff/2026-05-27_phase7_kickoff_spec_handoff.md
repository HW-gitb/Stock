# Phase 7 Kickoff Spec Handoff

## 2026-06-01 append: US EGS data-source direction

**Changed**:
- Recorded the user-approved US EGS data-source direction in `docs/provider_evidence_drift_monitor.md`: FMP as preferred primary US EGS data-source candidate, SEC EDGAR as fundamentals authority / audit source, and `yfinance` only as an optional low-trust price smoke check after explicit approval.
- Updated active routing in `AGENTS.md`, `docs/README.md`, and `docs/CURRENT.md`.
- Added `SR-PROVIDER-001` in `docs/system_risk_register.md` to make the access / fetch boundary durable.

**Why**:
- The source-role decision affects future provider access, license, storage, sample validation, and data quality gates. Keeping it only in chat would let a later LLM reopen the same provider debate or misread `yfinance` as a fundamentals audit source.
- The decision narrows future candidate roles, but the user has not approved any US data source access, token, trial, paid plan, sample fetch, adapter, DataHub table, or Phase 7c work.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema tests.schema.test_provider_evidence_drift_monitor_schema -v
git diff --check
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
```

**Validation result**:
- Provider access-plan and provider evidence / drift-monitor schema tests passed: 27 tests.
- `git diff --check` passed with only expected Windows LF-to-CRLF warnings.
- `docs/CURRENT.md` remains at 149 lines.

**Invalidated / blocked old conclusion**:
- "P1 US provider evidence has no preferred EGS source direction" is invalid; future reviewed access packets should start from FMP primary candidate + SEC EDGAR fundamentals audit.
- "Use `yfinance` as a fundamentals audit source" is blocked; it may only be a separately approved, low-trust price smoke check.
- This append does not authorize provider selection, FMP token / trial / paid access, SEC parser sample work, `yfinance` scraping, US data fetch, adapter / DataHub implementation, runner changes, production use, or ship-gate claims.

---

## 2026-06-01 append: A-share minimal-data burst audit/spec downgrade

**Changed**:
- Updated `docs/phase7a_alpha_plausibility_audit.json` as a `forward_evidence_changed` rerun superseding `alpha_audit_20260527_initial`; `a_share_burst_minimal_data` is now `redesign_required`, with evidence integrity, cost/return, capital, portfolio contribution, and source refs pointing to the failed full-universe redesigned outcome.
- Updated `docs/burst_lane_spec.md` and `docs/alpha_plausibility_audit.md` so A-share minimal-data burst is no longer described as an active `continue` path.
- Updated schema tests to lock the downgraded verdict and evidence refs.

**Why**:
- The reviewed outcome artifact failed the registered research-continuation thresholds after enough events were available. Leaving the owner audit/spec at `continue` would invite another unreviewed minimal-data A-share burst fishing loop.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_alpha_plausibility_audit_schema -v
```

**Validation result**:
- Focused alpha plausibility audit schema suite passed: 15 tests.
- The actual audit artifact still validates against `schemas/alpha_plausibility_audit.schema.json`, and a new test asserts `a_share_burst_minimal_data = redesign_required`.

**Invalidated / blocked old conclusion**:
- The prior audit/spec statement "`a_share_burst_minimal_data` = `continue`" is invalid.
- This does not change `a_share_burst_full_data = defer_until_provider_ready`; full-data burst remains blocked on reviewed provider/manual evidence and is not authorized by this docs-only downgrade.
- No new research run, provider fetch, US data access, runner change, production claim, live observation, or ship-gate claim is authorized.

---

## 2026-06-01 append: A-share burst full-universe redesigned outcome failed

**Changed**:
- Added the reviewed research-only outcome artifacts for the full-universe redesigned A-share burst test: `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json`, `signal_events.csv`, and `monthly_stats.csv`.
- Updated `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` so the redesigned test now points to the evidence report and is spent as `spent_failed_outcome_threshold`.
- Updated active routing docs and schema tests so the result is no longer treated as outcome-pending.

**Why**:
- The reviewed preflight had passed event-count with `valid_signal_events = 134`, and `SR-DATA-003` benchmark-open input was patched, so the next authorized smallest slice was the unchanged preregistered outcome / benchmark-excess calculation.
- The calculation used frozen local A-share cohorts and the patched local cache only. It did not rerun EGS, change preregistered parameters, full-refresh `forward_daily.pkl`, fetch provider data, or make any production / ship-gate claim.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema tests.schema.test_evidence_report_schema -v
git diff --check
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
```

**Validation result**:
- Outcome metrics: raw signal events `134`, selected signal events `123`, available return events `116`, mean net CSI1000 5d excess `-2.8696001309` pp, monthly clustered t-stat `-0.6312965283`, max monthly signal-excess drawdown `26.5735343137` pp, entry-unbuyable rate `0.0487804878`, decision `falsified_or_redesign_required`.
- Focused schema / artifact tests: 38 tests passed. `CURRENT.md` remains at 149 lines.
- `git diff --check` reported no whitespace errors; Git only printed expected CRLF normalization warnings on this Windows checkout.

**Invalidated / blocked old conclusion**:
- “The full-universe redesign outcome / excess is pending” is invalid. The registered redesigned test is now spent and failed under its own outcome thresholds.
- This does not prove every future A-share burst design has no alpha, but no further redesigned A-share burst test is authorized without a new ledger planned test, user approval, and reviewed preregistration.
- No production use, live observation, minimal-live sizing, full-size sizing, ship-gate evidence, or research-continue verdict is authorized by these artifacts.

---

## 2026-06-01 append: SR-DATA-003 benchmark-only cache patch run

**Changed**:
- Ran the reviewed benchmark-only helper against the ignored local shared cache: `runners/refresh_forward_daily_benchmark_open_tushare.py --dry-run`, then the same command without `--dry-run`.
- Patched `result/a_short/backtest/cache/forward_daily.pkl` so `benchmarks.csi300` and `benchmarks.csi1000` now contain `trade_date/open/close` frames for the existing `20240131..20260228` cache window.
- Updated active routing docs so `SR-DATA-003` is closed for benchmark-open input while the redesigned outcome / excess calculation remains a separate reviewed slice.

**Why**:
- The redesigned A-share burst preflight had enough signal events, but outcome / benchmark-excess calculation needed same-anchor benchmark entry-open input.
- A full forward-daily refresh would refetch stock / limit data unnecessarily; this run consumed only CSI300 / CSI1000 `index_daily` open/close for the existing cache range.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\refresh_forward_daily_benchmark_open_tushare.py --dry-run
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\refresh_forward_daily_benchmark_open_tushare.py
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_refresh_forward_daily_benchmark_open_tushare tests.phase6.test_forward_tracker_cache_guard tests.test_backtest_rank_phase3 tests.execution.test_materialize_benchmark_monthly_returns_tushare -v
```

**Validation result**:
- Dry-run and actual patch both reported `dry_run` as expected, `update_method = benchmark_only_index_daily_open_close_patch`, stock rows preserved at `2681523`, limit rows preserved at `3513895`, and two benchmark frames of 498 rows each.
- Readback of `forward_daily.pkl` shows both benchmarks have columns `trade_date/open/close`, zero open/close nulls, and `meta.benchmark_open_patch` provenance.
- Mocked-provider verification proved `backtest_rank.fetch_forward_daily(['20240131'], 5, refresh=False)` reuses the patched cache without calling the provider.
- Focused regression suite: 18 tests passed.

**Invalidated / blocked old conclusion**:
- "`SR-DATA-003` still needs the benchmark-only cache patch before any outcome / excess" is now invalid for this local workspace; the benchmark-open input is patched and verified.
- This run does not compute redesigned outcome returns, benchmark excess, drawdown, concentration, or ship-gate evidence. The next outcome / excess calculation still requires a separate reviewed slice using the unchanged reviewed preregistration and patched cache input.

---

## 2026-06-01 append: SR-DATA-003 benchmark-only cache refresh helper

**Changed**:
- Added `runners/refresh_forward_daily_benchmark_open_tushare.py`, a narrow helper that reads the existing shared `forward_daily.pkl` date range and fetches only CSI300 / CSI1000 `index_daily` `trade_date/open/close` frames before atomically patching the cache benchmark section.
- Added `tests/phase6/test_refresh_forward_daily_benchmark_open_tushare.py` to prove the helper preserves stock / limit payloads, supports dry-run, and makes the patched cache reusable by `backtest_rank.fetch_forward_daily(..., refresh=False)` without a provider refetch.
- Updated `runners/README.md`, `docs/CURRENT.md`, and `docs/system_risk_register.md` to route the remaining `SR-DATA-003` work through benchmark-only cache patching before any outcome / excess slice.

**Why**:
- The local shared `forward_daily.pkl` already contains stock and limit payloads for the research window but its benchmark frames are close-only. A full `--refresh-forward-daily` would refetch the entire stock / limit / benchmark surface, which is wider than the accepted `SR-DATA-003` input slice.
- The helper creates a reviewable path for the necessary benchmark open input without running outcome / excess or changing the existing return calculation path.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_refresh_forward_daily_benchmark_open_tushare -v
```

**Validation result**:
- `tests.phase6.test_refresh_forward_daily_benchmark_open_tushare`: 3 tests passed.

**Invalidated / blocked old conclusion**:
- "The only way to fix the close-only forward_daily benchmark cache is a full forward-daily refresh" is invalid. The benchmark frames can be patched via a benchmark-only `index_daily` slice.
- This change does not itself fetch provider data, patch the local cache, compute outcome returns, or compute benchmark excess. `SR-DATA-003` remains open until the cache input is actually patched and reviewed; redesigned outcome / excess still requires a later separate reviewed slice.

---

## 2026-06-01 append: SR-DATA-003 forward-tracker cache guard

**Changed**:
- Updated `runners/forward_tracker.py:_check_cache_coverage` to inspect cached CSI1000 / CSI300 benchmark frames before backfill and reject caches that lack same-anchor `trade_date/open/close` fields.
- Added `tests/phase6/test_forward_tracker_cache_guard.py` to lock both close-only benchmark cache rejection and same-anchor benchmark cache acceptance.
- Updated `docs/CURRENT.md` and `docs/system_risk_register.md` so `SR-DATA-003` remains open for benchmark-open outcome input while recording that the tracker refetch guard is handled.

**Why**:
- The tracker is a sidebar and must not trigger a universe-wide Tushare refetch through `fetch_forward_daily(..., refresh=False)` when the shared cache has close-only benchmark frames.
- This is not the redesigned burst outcome / excess slice. It only prevents official `forward_tracker.py backfill` from silently bypassing the `[SKIP]` / remediation-hint path.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_forward_tracker_cache_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_backtest_rank_phase3 -v
```

**Validation result**:
- `tests.phase6.test_forward_tracker_cache_guard`: 2 tests passed.
- `tests.test_backtest_rank_phase3`: 4 tests passed.

**Invalidated / blocked old conclusion**:
- "Tracker cache coverage only needs date metadata" is invalid. It must also verify same-anchor benchmark `trade_date/open/close` fields.
- This does not resolve the remaining `SR-DATA-003` outcome precondition: a reviewed benchmark-open input slice is still required before any redesigned A-share burst return / excess calculation.

---

## 2026-05-31 append: A-share burst full-universe preflight pass

**Changed**:
- Added `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json`, a research-only pre-outcome preflight over 24 frozen full EGS intermediate cohorts.
- Updated `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json`: the reviewed planned test is now spent by preflight, `valid_signal_events = 134`, and no new test is authorized.
- Updated research routing docs, risk register, and schema tests so the next A-share burst blocker is `SR-DATA-003` benchmark-open input before any outcome / excess calculation.
- Extended `schemas/program_test_budget_ledger.schema.json` with `spent_passed_preflight_outcome_pending` to represent a spent event-count pass with outcome still blocked.

**Why**:
- The reviewed full-universe redesign's only authorized executable step was event-count / input-integrity preflight.
- The frozen Tier1+Tier2 full EGS surface produced enough preregistered events to pass the power gate, but this does not authorize outcome returns, benchmark excess, production use, or ship-gate claims.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**Validation result**:
- `tests.schema.test_research_preregistration_schema`: 23 tests passed.
- `tests/schema` discovery: 132 tests passed.
- `git diff --check`: passed; only Git LF-to-CRLF working-copy warnings.
- `docs/CURRENT.md` line count: 149.

**Invalidated / blocked old conclusion**:
- “The next A-share burst action is only the full-universe preflight” is now spent; the next action is `SR-DATA-003` benchmark-open input plus a separate reviewed outcome / excess slice.
- The preflight pass is not alpha evidence. It records only event-count / input integrity and does not compute outcome, excess, drawdown, concentration, or ship-gate evidence.

---

## 2026-05-31 append: A-share burst ledger-gated redesign preregistration

**Changed**:
- Extended `schemas/research_preregistration.schema.json` to v1.1.0 so a preregistration can be explicitly gated by the singleton program-level test-budget ledger while preserving the original research-only scope locks.
- Appended one planned test to `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` for `a_share_minimal_data_burst_full_universe_redesign_20260531`.
- Added `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json`, a research-only preregistration that moves the A-share minimal-data burst test from the steady Tier1 watchlist to frozen full EGS intermediate candidate surfaces.
- Updated research routing docs and schema tests so the new artifact is visible to future LLMs. After review / commit and the follow-up ledger status sync, only pre-outcome event-count / input-integrity preflight is authorized.

**Why**:
- The corrected-basis A-share burst preregistration spent its single test on a pre-outcome preflight and found `valid_signal_events = 0`. That made direct outcome / benchmark-excess calculation uninformative.
- A useful next burst test changes universe / eligibility and therefore is not a basis-only supersession. It must consume the singleton ledger discipline before it can run.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -v
git diff --check
```

**Validation result**:
- `tests.schema.test_research_preregistration_schema`: 22 tests passed.
- `tests/schema` discovery: 131 tests passed.
- Full unittest discovery: 244 tests passed.
- `git diff --check`: passed; only Git LF-to-CRLF working-copy warnings.

**Invalidated / blocked old conclusion**:
- Do not treat the corrected-basis 5d rerun as the next executable alpha test. That preregistration is spent by zero signal events.
- Do not run outcome / excess for the redesigned preregistration yet. After review / commit and the follow-up ledger status sync, the first executable step is only pre-outcome event-count / input-integrity preflight. Outcome / excess still requires `SR-DATA-003` benchmark-open resolution if the preflight has enough events.

---

**Status**: provider capability / field catalog contract baseline established.

**Scope**: Phase 7 schema-first kickoff. This handoff starts the DataHub / provider capability phase without selecting providers, fetching data, adding provider adapters, creating DataHub tables, rewriting `A-EGS/egs_main.py`, changing strategy logic, or relaxing ship gates.

---

## 2026-05-28 修复追加：Phase 7b label repair

- 上一轮 Phase 7b handoff 中“Phase 7b schema-first baseline 已建立，下一条进入 Phase 7c”表述过宽；本轮修复后应读作：Phase 7b-1 provider evidence / drift monitor schema-first contract 已建立，Phase 7b-2 provider capability evidence population 仍未开始。
- 当前下一条 `执行` 应推荐 Phase 7b-2：按 P1-P4 queue 填充 provider docs / fields / PIT / coverage / cost / fallback / stability evidence；不得把 Phase 7b-1 contract 当成真实 provider evidence population。
- Phase 7c 仍应先做 DataHub shared-layer / report / reproducibility schema-first contract，但只有在 Phase 7b-2 evidence population reviewed 后才进入自然队列；不得先建 adapter / DataHub table / runner integration。

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

## 2026-05-27 追加：Phase 7a-2 owner-spec routing

**改了什么**:

- 更新 `docs/strategy_design_synthesis.md`，把第一版 audit verdict 写成 Phase 7a-2 routing baseline，并把下一步从 Phase 7a-1 改为 Phase 7a-3 / 7a-4 / 7a-5 sequence。
- 更新 `docs/burst_lane_spec.md`，明确 minimal-data burst 只可继续 paper / research，full-data burst 仍 `defer_until_provider_ready`；补 US microstructure、calendar / timezone 和 monitoring contract。
- 更新 `docs/long_alpha_spec.md`，明确 A / US long 四条 sub-lane 全部 `defer_until_provider_ready`；补 calendar / timezone 与 live-normalized 前 monitoring contract。
- 更新 `docs/us_short_spec.md`，明确 `us_short_steady` 仍是 `continue_as_risk_filter`；补 SSR / Reg SHO / LULD / PDT / extended-hours 等 US market microstructure 约束、calendar / timezone 和 monitoring contract。
- 更新 `docs/CURRENT.md`，把当前 P0 推进到 Phase 7a-3 provider priority / provisional benchmark contract。

**为什么改**:

- Phase 7a-1 已产出正式 audit artifact；如果 owner specs 不吸收 verdict，后续 LLM 仍可能按旧 Phase 6 baseline 误读 lane 状态。
- Audit 的 `continue` 只允许 minimal-data burst paper / research，不能被解释成 live sizing 或 ship-gate pass。
- Long alpha 仍是 push-alpha 目标，但当前被 PIT fundamentals、survivorship / security master、observed-date catalyst 和 fraud red-flag evidence 阻塞。
- US-short / US-burst 必须先把市场微结构和日历时区约束写入 spec，否则 paper evidence 到 live-normalized evidence 会失真。

**验证命令**:

```powershell
git diff --check
rg -n "[ \t]+$" docs\strategy_design_synthesis.md docs\burst_lane_spec.md docs\long_alpha_spec.md docs\us_short_spec.md docs\CURRENT.md
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
rg -n "next .*Phase 7a-1|下一条.*Phase 7a-1|Phase 7a-2 spec revisions after first audit|provider capability catalog contract should start Phase 7a|P0a bucket-aware|P0a `portfolio" docs\strategy_design_synthesis.md docs\burst_lane_spec.md docs\long_alpha_spec.md docs\us_short_spec.md docs\CURRENT.md
```

**验证结果**:

- `git diff --check`：passed（CRLF warnings only）。
- Changed-file trailing whitespace scan：passed（no matches）。
- `docs/CURRENT.md` physical line count：144，低于 150 行 snapshot target。
- Stale wording scan：passed（no active stale Phase 7a-1 / P0a bucket wording in touched owner docs）。

**失效旧结论**:

- “下一条 `执行` 继续做 Phase 7a-1 first audit”失效；Phase 7a-1 已完成，下一刀进入 Phase 7a-3 provider priority / provisional benchmark contract。
- “Minimal-data burst continue 可支持 live observation”失效；minimal-data burst 只能 paper / research。
- “Long alpha spec 可进入 implementation wave”失效；四条 long sub-lane 均需先解决 provider/PIT/fraud/survivorship blocker。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7a-3：provider priority reorder + provisional benchmark contract，继续 docs/schema-first。
2. 不要在 Phase 7a-3 选最终 provider、抓数据、建 adapter / DataHub table 或改 runner。
3. Phase 7a-4 再处理 burst minimal-to-full promotion、concentration / ADV sizing、slippage 和 circuit-breaker playbook。

## 2026-05-28 追加：Phase 7a-3 provider priority / provisional benchmark contract

**改了什么**:

- 新增 `docs/provider_priority_benchmark_contract.md`，作为 Phase 7a-3 provider evidence priority 与 provisional evidence benchmark owner。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/strategy_design_synthesis.md`、`docs/provider_data_requirements_audit.md`、`docs/alpha_plausibility_audit.md` 的 routing / current-state wording。
- 更新 `docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/long_alpha_spec.md`，把 provisional benchmark routing 指向 Phase 7a-3 owner contract，并把下一步推进到 Phase 7a-4 / 7a-5。

**为什么改**:

- Phase 7a-1 audit 与 Phase 7a-2 owner specs 已经给出 lane verdict，但 provider evidence priority 和 provisional evidence benchmark 仍分散在 strategy、provider audit、burst / long / US-short specs 中。
- Phase 7a-3 需要把 provider evidence queue 固化为可交接 contract：P1 US fundamentals / filings / security master，P2 A-share fundamentals / announcements / SW history，P3 burst event / flow / options / borrow，P4 already-proven A-share EOD / CSI helpers。
- Provisional benchmark 只用于 evidence accumulation 与 sensitivity reporting；除既有 A-short CSI1000 / CSI300 policy 外，不锁最终 ship-gate benchmark。

**验证命令**:

```powershell
git diff --check
rg -n "[ \t]+$" AGENTS.md docs\ALPHA_VALIDATION_ACTION_GUIDE.md docs\CURRENT.md docs\README.md docs\alpha_plausibility_audit.md docs\burst_lane_spec.md docs\long_alpha_spec.md docs\provider_data_requirements_audit.md docs\strategy_design_synthesis.md docs\us_short_spec.md docs\provider_priority_benchmark_contract.md docs\handoff\2026-05-27_phase7_kickoff_spec_handoff.md docs\SESSION_LOG.md
rg -n "next `执行` should implement Phase 7a-1|next execution slice is Phase 7a-1|下一条 `执行` 推荐 Phase 7a-3|Phase 7a-3 provider priority / provisional benchmark routing for burst data fields|Phase 7a-3 provider priority and provisional benchmark routing" AGENTS.md docs\ALPHA_VALIDATION_ACTION_GUIDE.md docs\CURRENT.md docs\README.md docs\alpha_plausibility_audit.md docs\burst_lane_spec.md docs\long_alpha_spec.md docs\provider_data_requirements_audit.md docs\strategy_design_synthesis.md docs\us_short_spec.md docs\provider_priority_benchmark_contract.md
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `git diff --check`：passed（CRLF warnings only）。
- Changed-file trailing whitespace scan：passed（no matches）。
- Active stale next-step wording scan：passed（no matches）。
- `docs/CURRENT.md` physical line count：146，低于 150 行 snapshot target。

**失效旧结论**:

- “Phase 7a-3 provider / benchmark routing 仍散落在 owner specs 中”失效；现在有 `docs/provider_priority_benchmark_contract.md` 作为单一 owner。
- “下一条 `执行` 仍是 Phase 7a-3”失效；下一条进入 Phase 7a-4 evidence feasibility controls。
- “Already-proven A-share EOD / CSI helper surfaces 是默认下一 implementation sink”继续失效；这些 surface 只作为 P4 ready evidence 记录。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7a-4：burst minimal-to-full promotion criteria、concentration / liquidity / ADV sizing、slippage / borrow / limit-risk feasibility、drawdown / circuit-breaker tiered action playbook。
2. 不要在 Phase 7a-4 选最终 provider、抓数据、建 adapter / DataHub table 或改 runner。
3. Phase 7b provider capability evidence 应按 Phase 7a-3 contract 的 P1-P4 queue 填充，除非后续 reviewed audit 明确反转。

## 2026-05-28 追加：Phase 7a-4 evidence feasibility controls

**改了什么**:

- 新增 `docs/evidence_feasibility_controls.md`，作为 Phase 7a-4 burst minimal-to-full promotion、evidence capital、concentration / liquidity / ADV、slippage / borrow / limit-risk、drawdown / circuit-breaker playbook owner。
- 新增 `schemas/evidence_feasibility_controls.schema.json` v1.0.0、`schemas/examples/evidence_feasibility_controls.example.json` 和 `tests/schema/test_evidence_feasibility_controls_schema.py`。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/strategy_design_synthesis.md`、`docs/alpha_plausibility_audit.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_capital_policy.md`、`docs/provider_priority_benchmark_contract.md` 的 routing / current-state wording。

**为什么改**:

- Phase 7a-3 已经锁定 provider priority 和 provisional benchmarks；下一步不能继续讨论 provider 排序，而要把 burst 赛道进入 full-data / live-normalized evidence 前的 feasibility controls 写成可校验 contract。
- Minimal-data burst 仍只能 paper / research；schema 明确 `paper_only`，并要求 promotion 前有 benchmark-relative evidence、drawdown / false-positive review、非价格确认、成本 / liquidity / spread / borrow / limit feasibility、rejected / failed candidate retention、minimal-vs-full paired comparison。
- Evidence capital 不改变固定资金政策；schema 通过 const lock 禁止 global AUM pool、cross-market pooling、liquidity bucket auto-borrowing 和 paper ship-gate claim。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_evidence_feasibility_controls_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_evidence_feasibility_controls_schema`：10 tests passed。
- Full `tests/schema` discovery、`git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一条 `执行` 推荐 Phase 7a-4”失效；Phase 7a-4 baseline 已建立，下一条进入 Phase 7a-5 evidence report schemas。
- “Minimal-data burst 可因 paper signal 强而进入 live observation”继续失效；minimal tier 默认 `paper_only`，live-normalized evidence 只能走 reviewed full-data path。
- “Circuit breaker 可留到 Phase 8 implementation 再定义”失效；Phase 7a-4 schema 已要求 warn、size_down、pause_new_entries、manual_review、reactivation_cooldown 五类动作。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7a-5：evidence report schemas，覆盖 immutable decision packet、cost-adjusted return、cash drag、manual override、minimal reconciliation、thesis outcome log、research experiment log。
2. Phase 7a-5 应消费 `docs/provider_priority_benchmark_contract.md` 和 `docs/evidence_feasibility_controls.md`，不要重新打开 provider priority 或 burst feasibility design。
3. 不要在 Phase 7a-5 选 provider、抓数据、建 adapter / DataHub table 或改 runner。

## 2026-05-28 追加：Phase 7a-5 evidence report schema contract

**改了什么**:

- 新增 `docs/evidence_report_schema_contract.md`，作为 Phase 7a-5 evidence report schema owner。
- 新增 `schemas/evidence_report.schema.json` v1.0.0、`schemas/examples/evidence_report.example.json` 和 `tests/schema/test_evidence_report_schema.py`。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/strategy_design_synthesis.md`、`docs/alpha_plausibility_audit.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/long_alpha_spec.md`、`docs/evidence_capital_policy.md`、`docs/provider_priority_benchmark_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- Phase 7a-4 已经锁定 burst feasibility controls；下一步需要让未来 evidence reports 不能丢失决策时间、参数、成本、现金拖累、人工 override、最小 reconciliation、thesis outcome 和 research lineage。
- `schemas/evidence_report.schema.json` 明确消费 `docs/provider_priority_benchmark_contract.md` 与 `docs/evidence_feasibility_controls.md`，避免 Phase 7a-5 重新打开 provider priority 或 burst feasibility design。
- Research experiment 仍保持隔离；schema 锁定 `no_direct_production_feed = true`，promotion 仍需 schema review、Claude review 和用户批准。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_evidence_report_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_evidence_report_schema`：12 tests passed。
- Full `tests/schema` discovery：73 tests passed。
- `git diff --check`：passed（CRLF warnings only）。
- Changed-file trailing whitespace scan：passed（no matches）。
- `docs/CURRENT.md` physical line count：141，低于 150 行 snapshot target。

**失效旧结论**:

- “下一条 `执行` 推荐 Phase 7a-5”失效；Phase 7a-5 schema-first baseline 已建立，下一条进入 Phase 7b provider evidence / drift monitor。
- “Evidence reports 可以稍后再补 decision packet / override / reconciliation / research lineage”失效；Phase 7a-5 schema 已要求七个核心 section 即使不适用也必须显式记录。
- “Research experiment result 可以直接喂 production runner”继续失效；schema 通过 const lock 禁止 direct production feed。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7b：按 `docs/provider_priority_benchmark_contract.md` 的 P1-P4 queue 填充 provider capability evidence，并建立 data quality / provider drift monitor。
2. 不要在 Phase 7b silent default、latest-only 回填历史证据，或把 provider status guess 写成 production-ready evidence。
3. 不要在下一刀改 runner、建 adapter / DataHub table、接 broker / OS automation，除非后续 reviewed slice 明确进入对应 implementation scope。
## 2026-05-28 追加：Phase 7b provider evidence / drift monitor contract

**改了什么**:

- 新增 `docs/provider_evidence_drift_monitor.md`，作为 Phase 7b provider evidence / drift monitor owner。
- 新增 `schemas/provider_evidence_drift_monitor.schema.json` v1.0.0、`schemas/examples/provider_evidence_drift_monitor.example.json` 和 `tests/schema/test_provider_evidence_drift_monitor_schema.py`。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/datahub_design.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- Phase 7a-3 已经锁定 provider evidence P1-P4 queue；Phase 7a-5 已经锁定 evidence report shape。Phase 7b 需要把 P1-P4 provider evidence records、provider readiness rollup、data quality / provider drift dimensions 与 action set 写成可校验 contract，避免后续 Phase 7c DataHub / runner work 依赖 provider readiness guess。
- P4 A-share EOD / CSI helper surface 已有 ready evidence，但只能作为 narrow helper evidence 记录；不能因为它方便就绕过 P1-P3 blocker 或成为 broad DataHub implementation 默认起点。
- Drift monitor 必须显式覆盖 coverage、freshness、schema/field semantics、PIT/as-of、survivorship/security master、corporate actions/revisions、calendar/timezone、authorization/cost/quota、provider incidents、outlier/revision rate；否则后续 provider-backed evidence 会缺稳定性边界。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`：11 tests passed。
- Full `tests/schema` discovery、`git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一条 `执行` 推荐 Phase 7b”失效；Phase 7b schema-first baseline 已建立，下一条进入 Phase 7c DataHub shared layer / report contracts / reproducibility plumbing。
- “Phase 7b 可以靠文字约定 provider readiness / drift monitor”失效；现在必须通过 `schemas/provider_evidence_drift_monitor.schema.json` 记录 P1-P4 queue、provider evidence records、readiness rollup 和 drift dimensions/action set。
- “P4 ready A-share helper surface 可以作为 broad DataHub implementation 起点”继续失效；schema example 明确 P4 只记录 ready helper surface，不授权 implementation、provider selection 或 ship-gate claim。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7c：设计 DataHub shared-layer / report / reproducibility contract，消费 Phase 7b provider evidence / drift monitor，不要重开 provider priority。
2. 不要在 Phase 7c 第一刀抓 provider 数据、选 provider、建 adapter / DataHub table 或改 runner；先写 contract。
3. 后续 implementation 若需要使用任何 provider-backed field，必须能引用 Phase 7b 的 evidence record 与 drift-monitor dimension/action。

## 2026-05-28 追加：Phase 7b-2 P1 US public-source provider evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_public_sources_20260528.json`，作为 Phase 7b-2 第一份 P1 US public-source evidence population artifact。
- `schemas/provider_evidence_drift_monitor.schema.json` 升至 v1.1.0：保留 no-selection / no-fetch / no-implementation locks，允许 `provider_evidence_population_snapshot`，并要求 `reviewed_provider_evidence` 记录 `evidence_source_refs`。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一轮 R1 修复明确 Phase 7b-2 才是真实 provider evidence population；本刀开始填 P1，而不是继续停留在 contract 层。
- 仅靠 v1.0.0 的 `schema_first_contract_only` 无法准确表达 evidence snapshot，所以 v1.1.0 增加 snapshot status 和 source refs，避免把来源证据写成不可审查的备注。
- 官方 SEC / Nasdaq / MSCI 文档足以把 P1 从 `unknown` 推进到 `partial`，但不足以解除 implementation blocker：US price、corporate action、delisting/security master、benchmark、paid-provider authorization/cost/stability 仍未完成。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`: 14 tests passed。
- Full `tests/schema` discovery、`git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “Phase 7b-2 provider capability evidence population 尚未开始”失效；现在已有第一份 P1 public-source snapshot。
- “P1 US provider evidence 仍完全 unknown”失效；现在是 `partial`，但仍 blocked。
- “`schemas/provider_evidence_drift_monitor.schema.json` 当前 `1.0.0`”失效；当前为 `1.1.0`。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2，而不是进入 Phase 7c；优先补 P1 US adjusted price、corporate action、delisting/security master、benchmark、authorization/cost/fallback/stability evidence。
2. 不要把 SEC EDGAR / SEC ticker files / Nasdaq symbol directory / GICS methodology 误读为完整 provider selection 或 implementation readiness。
3. 继续不抓 provider data、不选 provider、不建 adapter / DataHub table、不改 runner。

## 2026-05-28 追加：Phase 7b-2 P1 US market-data candidate evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_market_data_candidates_20260528.json`，作为 Phase 7b-2 第二份 P1 evidence-population artifact。
- 该 artifact 基于 Massive / Polygon 与 Norgate 官方文档，记录 US adjusted OHLCV、ticker / security-master surfaces、corporate actions、market status / exchange metadata、survivorship EOD package claims、index membership package claims 等 candidate evidence。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证两份 P1 evidence artifacts，并断言 market-data snapshot 仍为 partial / non-authorizing。

**为什么改**:

- 上一份 public-source snapshot 只覆盖 SEC / Nasdaq / MSCI 文档，尚未触及 P1 里 price / corporate action / delisting/security-master / benchmark candidate 方向。
- Massive / Polygon 与 Norgate 文档可把 P1 market-data candidate evidence 从完全未审查推进到 source-backed `partial`，但不能解除 implementation blocker。
- 本刀仍严守 Phase 7b-2 边界：不抓 provider data、不选 provider、不建 adapter / DataHub table、不改 runner、不放松 ship gate。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`: 15 tests passed。
- Full `tests/schema` discovery: 89 tests passed。
- Final `git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “Phase 7b-2 只有第一份 P1 public-source snapshot”失效；现在有 public-source + market-data-candidate 两份 P1 snapshots。
- “P1 仍完全未覆盖 US price / corporate action / security-master provider candidates”失效；现在已有 source-backed candidate evidence，但仍 partial / blocked。
- “下一刀应补 US adjusted price / corporate action / delisting security master”需收窄；下一刀应继续补 authorization / cost、sandbox / trial、coverage counts、direct benchmark return sources、issuer-level PIT GICS membership、fundamentals / filing observed-date candidates、fallback / stability。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2 P1，而不是进入 Phase 7c。
2. 不要把 Massive / Polygon 或 Norgate 文档误读为 provider selection、paid-access approval、PIT security-master proof、direct benchmark proof 或 production readiness。
3. 如需 trial / sandbox token、paid access、成本上限或 provider selection，必须另走 reviewed decision；不得在 evidence artifact 中隐式批准。

## 2026-05-28 修复追加：Phase 7b-2 market-data candidate R1 verification trace

**改了什么**:

- 修复 Claude R1：`docs/provider_evidence_p1_us_market_data_candidates_20260528.json` 中 4 条 Massive/Polygon records 的 Massive source refs 已在 `evidence_note` 明确写入 `WebFetched on 2026-05-28 at ...` verification trace。
- Polygon market-data terms refs 也写入 `WebFetched on 2026-05-28 at https://polygon.io/terms/market_data_terms.pdf`。
- Massive source refs 额外声明：这些 trace 只证明 Massive docs page 实际可访问并被审阅，不独立证明 Polygon-to-Massive rebrand / legal continuity，也不授权 provider selection。
- `tests/schema/test_provider_evidence_drift_monitor_schema.py` 新增断言，防止 Massive source refs 再次缺失 WebFetched trace 或 rebrand 非证明声明。
- `docs/provider_evidence_drift_monitor.md` 同步记录 R1 repair note。

**为什么改**:

- 最新 Claude review 指出 Massive/Polygon 双品牌 evidence chain 需要区分“实际打开过 massive.com 文档”与“依赖训练数据 / 假设 rebrand 成立”。
- 用户批准 R1 并指定修复路径 `(c)`，即保留 Massive/Polygon evidence，但把 verification path 写进 evidence_note。
- 修复后 downstream Phase 7b-2 / 7c 可追溯每条 Massive docs evidence 的实际 URL 审阅路径，同时不会把该 trace 误读成 provider selection 或品牌法律连续性的证明。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- 最终验证结果记录在同日 Codex `修复` SESSION_LOG entry。

**失效旧结论**:

- “Massive/Polygon source_url 可能是未验证 / 训练数据来源”这条 R1 风险已修复为可追溯 WebFetched trace。
- “Massive docs trace 可证明 Polygon-to-Massive rebrand / legal continuity”仍不成立；artifact 明确不做该证明。

**下一步注意事项**:

1. Claude re-review 时应重点确认 4 条 Massive records 的 source refs 是否都有 verification trace。
2. 后续若要证明 Polygon-to-Massive rebrand 或做 provider selection，必须另开 reviewed evidence / decision，不得把本次 trace 当作 selection。
3. P1 仍 partial / blocked；下一条 `执行` 仍继续 authorization / cost、sandbox / trial、coverage count、benchmark、PIT GICS、fundamentals observed-date、fallback / stability evidence。

## 2026-05-28 追加：Phase 7b-2 P1 US authorization / cost / stability evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json`，作为 Phase 7b-2 第三份 P1 evidence-population artifact。
- 该 artifact 基于 Massive / Polygon 与 Norgate 官方文档，记录 pricing、API-key / subscription / trial access、license / EULA、export / retention、stability constraints，以及 Norgate current-fundamentals latest-only limitation。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证三份 P1 evidence artifacts，并断言 authorization / cost / stability snapshot 仍为 partial / non-authorizing。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一刀已经补了 market-data candidate evidence，但 P1 仍缺 authorization / cost / trial / access / stability 的 reviewed source basis。
- 官方 terms 显示 Massive / Polygon 与 Norgate 都存在必须单独 review 的使用边界：personal / non-commercial、non-display、local storage、redistribution、subscription lapse、export scope、Windows/plugin access、no-warranty / data-change constraints。
- Norgate current fundamentals 明确为 latest-only，不能被下游误读成 US-long PIT historical fundamentals provider。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`: 16 tests passed。
- Full `tests/schema` discovery: 90 tests passed。
- `git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 的最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “P1 evidence snapshots 只有 public-source + market-data-candidate 两份”失效；现在有 public-source、market-data-candidate、authorization / cost / stability 三份 P1 snapshots。
- “下一刀应继续补 authorization / cost、sandbox / trial”需收窄；下一刀应继续补 coverage counts、direct benchmark return sources、issuer-level PIT GICS membership、fundamentals / filing observed-date candidates beyond latest-only sources、fallback behavior、incident / stability evidence。
- “Norgate current fundamentals 可以作为 US-long historical fundamentals candidate”不成立；本 artifact 明确 latest-only，不得当作 PIT historical fundamentals。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2 P1，而不是进入 Phase 7c。
2. 不要把 Massive / Polygon 或 Norgate 的 pricing / terms / trial evidence 误读为 provider selection、paid-access approval、local-storage approval、non-display approval 或 production readiness。
3. 如需 trial token、paid access、cost ceiling、provider selection、non-display / local-storage permission，必须另走 reviewed decision。

## 2026-05-28 追加：Phase 7b-2 P1 US benchmark / GICS candidate evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json`，作为 Phase 7b-2 第四份 P1 evidence-population artifact。
- 该 artifact 基于 S&P DJI、Nasdaq、FTSE Russell / LSEG、MSCI、S&P Global 官方文档，记录 S&P 500 / Nasdaq-100 / Russell 1000 direct benchmark source candidate evidence 与 GICS taxonomy / GICS History candidate evidence。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证四份 P1 evidence artifacts，并断言 benchmark / GICS snapshot 仍为 partial / non-authorizing。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一刀补了 authorization / cost / stability，但 P1 仍缺 direct benchmark return source 与 issuer-level PIT GICS candidate review。
- 官方 index methodology / index pages 可作为 direct benchmark-source candidate evidence，但不能当成已授权、可本地存储、可回测消费的历史 total-return feed。
- GICS methodology 只能证明 taxonomy context；S&P Global GICS History product docs 只是 issuer-level history candidate，仍需 license、sample rows、data dictionary、coverage counts、identifier mapping 与 as-of semantics 审查。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`: 17 tests passed。
- Full `tests/schema` discovery: 91 tests passed。
- `git diff --check`: passed；仅报告既有 LF/CRLF working-copy warnings。
- Changed-file trailing whitespace scan: no matches。
- `docs/CURRENT.md` line count: 144，低于 150-line snapshot target。

**失效旧结论**:

- “P1 evidence snapshots 只有 public-source + market-data-candidate + authorization / cost / stability 三份”失效；现在有四份 P1 snapshots。
- “下一刀应继续补 direct benchmark return sources、issuer-level PIT GICS membership”需收窄；该方向已有 candidate evidence，但仍非 implementation-ready。下一刀应继续补 coverage counts、fundamentals / filing observed-date candidates beyond latest-only sources、fallback behavior、incident / stability evidence。
- “S&P / Nasdaq / Russell methodology page 可以直接当历史 benchmark return feed”不成立；本 artifact 明确只记录 candidate evidence，不批准数据抓取、授权、存储或 provider selection。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2 P1，而不是进入 Phase 7c。
2. 不要把 official index pages / methodology docs 误读为 licensed historical benchmark return feed。
3. 不要把 GICS methodology / product docs 误读为已可用 issuer-level PIT GICS membership；仍需 license、sample、coverage、identifier 和 as-of 证据。

## 2026-05-28 追加：Phase 7b-2 P1 US fundamentals observed-date candidate evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json`，作为 Phase 7b-2 第五份 P1 evidence-population artifact。
- 该 artifact 基于 SEC、Intrinio、FMP、Nasdaq Data Link / Sharadar 官方文档，记录 SEC EDGAR public reconstruction、Intrinio filing fundamentals accepted-date candidate、FMP SEC filings / as-reported statement candidate、Nasdaq Data Link / Sharadar SF1 candidate context。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证五份 P1 evidence artifacts，并断言 fundamentals observed-date snapshot 仍为 partial / non-authorizing。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一刀补了 benchmark / GICS candidate evidence，但 P1 仍缺 fundamentals / filing observed-date provider candidates beyond latest-only sources。
- SEC EDGAR 能支持 public-source filing/XBRL reconstruction，但需要 accession-level observed-date、taxonomy、amendment、coverage、security-master linking 和 fair-access policy 才能进入 implementation。
- Intrinio 文档明确给出 filing-linked fundamentals 的 `accepted_date` / `filing_date` / `is_latest` / `updated_date` candidate evidence；FMP 和 Nasdaq Data Link / Sharadar 仍只是 candidate context，不能当作 PIT-ready historical fundamentals。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- 最终验证结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “P1 evidence snapshots 只有四份”失效；现在有 public-source、market-data-candidate、authorization / cost / stability、benchmark / GICS、fundamentals observed-date 五份 P1 snapshots。
- “下一刀应补 fundamentals / filing observed-date candidates beyond latest-only sources”需收窄；该方向已有 candidate evidence，但仍非 implementation-ready。
- “latest/current financial statement endpoints 可以直接作为 historical PIT fundamentals”不成立；artifact 明确禁止 latest-only backfill。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2 P1，而不是进入 Phase 7c。
2. P1 剩余主要 blocker 收窄为 coverage counts、fallback behavior、incident / stability evidence、unresolved fundamentals field-level license / sample-row validation。
3. 不要把 SEC / Intrinio / FMP / Nasdaq Data Link / Sharadar 文档误读为 provider selection、paid-access approval、PIT-safe production factors、local-storage approval 或 DataHub implementation readiness。

## 2026-05-28 追加：Phase 7b-2 P1 US coverage / fallback / incident candidate evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`，作为 Phase 7b-2 第六份 P1 evidence-population artifact。
- 该 artifact 基于 Intrinio、FMP、Massive、Norgate、Nasdaq Data Link 官方文档，记录 coverage、status / incident、fallback / error-code、license / sample-row validation evidence。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证六份 P1 evidence artifacts，并断言 coverage / fallback / incident snapshot 仍为 partial / non-authorizing。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一刀补了 fundamentals observed-date candidate evidence，但 P1 仍缺 coverage、fallback、incident-stability、field-level license / sample-row validation 的 reviewed source basis。
- 该切片把 vendor-level coverage claims、public status pages、error-code / call-limit docs、license caveats 和 explicit coverage limitations 写入 machine-checkable artifact，防止后续 DataHub 误把 provider docs 当作 implementation readiness。
- 本刀仍严守 Phase 7b-2 边界：不抓 provider data、不选 provider、不建 adapter / DataHub table、不改 runner、不放松 ship gate。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 JSON parse、changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` authoritative line count check。

**验证结果**:

- 最终验证结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “P1 evidence snapshots 只有五份”失效；现在有六份 P1 snapshots。
- “下一刀应补 coverage / fallback / incident / license-sample evidence”需收窄；该方向已有 documentation-review evidence，但仍非 implementation-ready。
- “vendor-level coverage counts 或 status pages 可以替代 project coverage / sample-row validation”不成立；artifact 明确保持 P1 blocked。

**下一步注意事项**:

1. 下一条 `执行` 应做 P1 readiness review matrix，而不是进入 Phase 7c 或 provider implementation。
2. Readiness review 应 field-by-field 对比 6 份 P1 snapshots，并明确哪些字段仍需 paid license、sample-row validation、coverage-count check 或 provider decision。
3. 不要把任何 provider docs、status page 或 coverage claim 误读为 provider selection、paid-access approval、PIT-safe production factors、local-storage approval 或 DataHub implementation readiness。

## 2026-05-29 追加：Phase 7b-2 P1 readiness review matrix

**改了什么**:

- 新增 `schemas/provider_p1_readiness_review.schema.json`，作为 P1 readiness review matrix 的 schema-first contract。
- 新增 `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`，field-by-field 综合六份 P1 snapshots：security master / survivorship、adjusted EOD / liquidity、corporate actions、fundamentals observed-date / PIT、benchmark returns、GICS PIT membership、coverage counts、authorization / license / cost、fallback / incident / stability、sample-row validation / lineage。
- 新增 `tests/schema/test_provider_p1_readiness_review_schema.py`，验证 matrix schema、artifact、source snapshot / record refs、non-authorizing scope locks、关键 provider blocker 结论和下一步建议。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- Claude 上轮 review 明确 Phase 7b-2 P1 evidence collection 已事实结束，下一刀应从 collect 转向 synthesize / decide。
- 六份 snapshots 已覆盖 P1 docs evidence，但仍不能被 Phase 7c 或 DataHub 当成 provider readiness；matrix 把 blocker disposition 机器化，避免后续把 candidate docs 误读为 selection / implementation。
- 本刀仍严守 Phase 7b-2 边界：不抓 provider data、不选 provider、不建 adapter / DataHub table、不改 runner、不放松 ship gate。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_readiness_review_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 JSON parse、changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` authoritative line count check。

**验证结果**:

- 最终验证结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一刀应做 P1 readiness review matrix”已完成；下一刀应做 P1 access-decision and sample-validation plan。
- “六份 P1 snapshots 可直接进入 Phase 7c consumption”不成立；matrix 明确 `p1_ready_for_phase7c = false`。
- “强 candidate evidence 可当 provider selection”不成立；Intrinio / Norgate / Massive / SEC / benchmark / GICS candidates 仍需 access、license、sample-row、coverage-count 和 fallback / incident review。

**下一步注意事项**:

1. 下一条 `执行` 应准备 P1 access-decision and sample-validation plan，而不是进入 Phase 7c 或 provider implementation。
2. 任何 token、trial、paid subscription、provider data fetch、sample-row collection、provider selection 或 DataHub table 仍需单独 reviewed decision。
3. Matrix 中的 `strong_candidate_but_blocked` 只表示值得后续 access/sample review，不表示 production provider readiness。

## 2026-05-31 追加：P1 access-plan 后 research prereg execution lock

**改了什么**:

- 更新 `docs/CURRENT.md`，把 P0 保持为 Phase 7b-2 P1 access-decision and sample-validation plan，并锁定 P0 reviewed/committed 后的下一条 alpha-validation 刀为 A-share `minimal_data_burst` research-only falsification。
- 更新 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`，新增 research preregistration、single frozen test、program-level test-budget ledger 触发规则，并明确 US-long SEC observed-date / parser feasibility 属于 provider-evidence track，不是 alpha-validation track。
- 更新 `docs/strategy_design_synthesis.md`，只保留短路由说明，把 research preregistration / test-budget 细则交给 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`。
- 未新建大设计文档，未改 schema / runner / provider / DataHub / order execution。

**为什么改**:

- 用户确认采用收敛后的执行方案：先收口 P1 access-decision / sample-validation plan，再启动 A-share minimal-data burst research-only falsification。
- 需要把该方案写进启动必读链路，防止后续 LLM 把 access-decision 继续滚成 provider docs 循环，或把 burst research 做成未预注册的参数 / variant fishing。
- 该修改保持 Phase 7b-2 串行执行边界：P1 access plan 仍是下一刀；research 只在该 reviewed slice 之后启动，且不进入 production、不改 runner、不声称 ship-gate evidence。

**验证命令**:

```powershell
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
git diff --stat
```

**验证结果**:

- `git diff --check` 通过；仅出现 touched docs 的 LF/CRLF working-copy warning。
- `docs/CURRENT.md` authoritative line count = 149，低于 150-line snapshot target。
- 最终 diff / status 记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “P1 access-decision plan 之后下一步未锁定”失效；现在明确锁定为 A-share `minimal_data_burst` research-only falsification。
- “US-long SEC observed-date / parser feasibility 可以作为 alpha-validation 首刀”不成立；该方向归 provider-evidence track。
- “单个 research experiment 可自由扫参数 / benchmark / holding period 而不触发 program-level ledger”不成立；只有 preregistered single frozen test 可豁免 ledger。

**下一步注意事项**:

1. 下一条 `执行` 仍是 P1 access-decision and sample-validation plan；不要跳到 research、Phase 7c、provider selection 或 data fetch。
2. P1 access plan reviewed/committed 后，下一条 alpha-validation `执行` 应先建立 A-share minimal-data burst preregistration artifact，再做 research-only falsification。
3. 如果 burst research 引入第二个 promotion-relevant hypothesis、参数搜索、variant 搜索、benchmark sweep 或 holding-period sweep，必须先建 singleton program-level test-budget ledger。

## 2026-05-31 追加：Phase 7b-2 P1 access-decision / sample-validation plan

**改了什么**:

- 新增 `schemas/provider_p1_access_decision_plan.schema.json`，作为 P1 access-decision / sample-validation plan 的 schema-first contract。
- 新增 `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json`，把 P1 readiness matrix blockers 转成 cost ceiling、access path、license / storage、sample rows、coverage counts、fallback / incident playbook 和 decision gates。
- 新增 `tests/schema/test_provider_p1_access_decision_plan_schema.py`，验证 plan schema、artifact、candidate queue / matrix alignment、10 个 sample workstreams、non-authorizing scope locks、decision gates 和 post-plan alpha-validation route。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一轮已锁定当前最小任务是 P1 access-decision and sample-validation plan；本轮把它变成机器校验 artifact，而不是继续停留在自然语言 next-step。
- 需要防止后续 LLM 把 access plan 误读成 provider selection、trial / token request、paid access、sample fetch、data fetch 或 Phase 7c 授权。
- 计划完成后，下一条 alpha-validation 刀按已批准方案转向 A-share `minimal_data_burst` research-only preregistration / falsification；US-long SEC parser feasibility 仍归 provider-evidence track。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_provider_p1_access_decision_plan_schema`: 8 tests passed.
- `python -m unittest discover -s tests/schema -v`: 109 tests passed.
- `git diff --check`: passed；只出现 tracked docs 的 LF/CRLF working-copy warning。
- `docs/CURRENT.md` authoritative line count = 144，低于 150-line snapshot target。

**失效旧结论**:

- “下一条 `执行` 仍是 P1 access-decision and sample-validation plan”已完成；下一条 alpha-validation `执行` 应转向 A-share `minimal_data_burst` preregistration / research-only falsification。
- “P1 access plan 可授权 token / trial / paid access / sample fetch”不成立；artifact 锁定 approved spend = 0，所有 provider access 均需用户显式批准和后续 reviewed decision。
- “P1 access plan 可启动 Phase 7c / DataHub / runner work”不成立；Phase 7c 仍需单独 schema-first implementation-design slice。

**下一步注意事项**:

1. Claude 应审查本轮 uncommitted schema / JSON / test / routing 变更；重点看 scope locks 是否足以防 provider access 和 Phase 7c 误读。
2. 如果审查 Pass 并提交，下一条 `执行` 应先建立 A-share `minimal_data_burst` preregistration artifact，再做 research-only falsification。
3. 如用户想推进 provider sample / trial / paid access，必须先给出 cost ceiling、access path、license / storage / retention 边界，并仍走单独 reviewed decision。

## 2026-05-31 追加：A-share minimal-data burst preregistration artifact

**改了什么**:

- 新增 `schemas/research_preregistration.schema.json`，作为 single frozen research test preregistration contract。
- 新增 `research/README.md` 与 `research/preregistrations/a_share_minimal_data_burst_20260531.json`，把 A-share `minimal_data_burst` 的首刀 alpha-validation 固定为一个 research-only test：20240131-20251231 月度 A-short generated cohorts、CSI1000 primary benchmark、5 trading days、T+1 open 到 T+5 close、固定 EOD trigger、固定 pass/fail criteria、`test_budget = 1`。
- 新增 `tests/schema/test_research_preregistration_schema.py`，验证 schema / artifact、alpha audit hypothesisRegistration 形状复用、production / provider / Phase 7c scope locks、single frozen test budget、evidence_report ref linkage、singleton ledger trigger 和 fishing mutation reject。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/provider_evidence_drift_monitor.md` 的 routing / current-state wording。

**为什么改**:

- 上一轮已确认 P1 access-decision / sample-validation plan 收口后，下一条 alpha-validation 刀应转向 A-share `minimal_data_burst`，且必须先 preregister。
- 该 artifact 是执行锁，不是研究结果：它防止后续 LLM 在第一次 burst research 中扫参数、扫 benchmark、扫 holding period 或把 CSI300 diagnostic 当成 rescue。
- 本轮保持边界：不跑 research、不改 runner、不抓 provider data、不进 production、不声称 ship-gate evidence。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- 最终验证结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一条 `执行` 应先建立 A-share `minimal_data_burst` preregistration artifact”已完成；下一条 `执行` 才能运行该 frozen research-only falsification。
- “单一 research experiment 可以在首刀内扫 threshold / rank cap / benchmark / holding period 而不建 ledger”不成立；当前 schema / artifact 锁定 `test_budget = 1`。
- “Preregistration 需要修改 `evidence_report.schema.json` 才能被引用”不成立；后续 evidence report 使用现有 `research_experiment_log.hypothesis_registration_ref` 指回该 artifact。

**下一步注意事项**:

1. Claude 应审查本轮 uncommitted schema / artifact / test / routing 变更；重点看 frozen test 是否过窄或仍留 fishing 自由度。
2. 如果审查 Pass 并提交，下一条 `执行` 应只运行 `research/preregistrations/a_share_minimal_data_burst_20260531.json` 中的 frozen falsification，不得调参。
3. 如运行中发现需要改阈值、rank cap、universe、benchmark、holding period、cost model 或 pass/fail criterion，先停下并创建 singleton program-level test-budget ledger。

## 2026-05-31 追加：alpha measurement-basis lock and burst prereg pause

**改了什么**:

- 更新 `docs/CURRENT.md` 和 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`，把下一刀从“运行 A-share minimal-data burst frozen falsification”反转为“先做 alpha measurement integrity / same-anchor benchmark excess correction”。
- 将 `research/preregistrations/a_share_minimal_data_burst_20260531.json` 标记为 `BLOCKED_DO_NOT_RUN`，并在 `research/README.md`、`docs/burst_lane_spec.md`、`docs/provider_evidence_drift_monitor.md`、`docs/strategy_design_synthesis.md`、`AGENTS.md` 和 P1 access plan next_steps 中同步路由。
- 增加 schema regression：当前 prereg 必须含 `BLOCKED_DO_NOT_RUN`、`measurement-basis issue`、`corrected-basis supersession`；P1 access plan 必须把 next alpha slice 指向 measurement integrity，而不是直接运行旧 prereg。
- 修复轮接受 O1：给 4 份 `result/a_short/backtest/Phase2_rank_backtest_findings_*.md` 加 caveat 头，明确所有 benchmark excess surface 在 corrected-basis revalidation 前均为 contaminated / uncorrected。
- 修复轮 O2 accept with modification：不在本轮 bump schema，但在行动指南中锁定未来 runner / automated research command 不能只依赖人读文字 marker，必须显式 reject `BLOCKED_DO_NOT_RUN` 或采用结构化 execution-status schema bump。
- 修复轮 R1：明确当前 A-share CSI1000 / CSI300 benchmark open 可经 Tushare `index_daily` 取得；下一刀必须扩展 benchmark materializer / forward-daily benchmark fetch 取 open，close-to-close 对当前 A-share corrected revalidation 不是可接受 fallback。

**为什么改**:

- 全系统漏洞审查指出旧 5d `excess_csi1000` 线索和当前 burst prereg 存在入场锚点不对称风险：个股使用 T+1 open 语义，而 benchmark 使用 close basis。该混合口径不得支持 promotion-relevant alpha / research-continuation / ship-gate evidence。
- 旧 5d clue 不能直接判定为假，但必须按 measurement-contaminated / uncorrected 处理，直到 same-anchor corrected revalidation 证明不是 artifact。
- 修正只允许改变 benchmark / entry-anchor basis；阈值、universe、holding period、ranking cap、cost model、criteria、`test_budget=1` 不得借机变化，否则必须先建 singleton program-level ledger。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_research_preregistration_schema`: 11 tests passed.
- `tests.schema.test_provider_p1_access_decision_plan_schema`: 8 tests passed.
- `python -m unittest discover -s tests/schema -v`: 120 tests passed.
- `git diff --check`: passed; only normal LF/CRLF working-copy warnings.
- `docs/CURRENT.md` authoritative line count = 146, still under the 150-line snapshot target.
- `rg -n "Measurement caveat \(2026-05-31\)" result\a_short\backtest`: 4 findings files matched.

**失效旧结论**:

- “提交后下一刀 = 运行 `research/preregistrations/a_share_minimal_data_burst_20260531.json`”失效；该 artifact 现在是 `BLOCKED_DO_NOT_RUN`。
- “5d `excess_csi1000 t=+2.88` 是当前唯一显著正 alpha 线索”降级为未校正、疑似 measurement-basis artifact 的线索；corrected basis 重跑前不得当作 validated alpha。
- “benchmark close basis 可与 stock T+1 open entry 混用来支持 research continuation”失效；promotion-relevant evidence 必须同 entry anchor。
- “旧 Phase2 findings 文档中的任一 benchmark excess 表格可继续独立引用”失效；全部 excess surface 需等 corrected basis 重跑后再恢复引用。

**下一步注意事项**:

1. Claude 审查应重点核对所有 current route 是否禁止运行旧 prereg，并确认没有趁 measurement fix 改阈值、universe、holding period、criteria 或 `test_budget`。
2. 如果审查 Pass 并提交，下一条 `执行` 应修复 / 引入 same-anchor benchmark excess：stock T+1 open 与 benchmark T+1 open 到同一 exit close；当前 A-share CSI1000 / CSI300 应扩展 Tushare `index_daily` benchmark materializer / forward-daily benchmark fetch 取 open，不能用 close-to-close fallback。
3. corrected revalidation 只能是 corrected 5d CSI1000 primary；10d / 20d 只能 diagnostic，不得做参数、variant、benchmark、holding-period search。

## 2026-05-31 追加：system risk register and enforcement lock

**改了什么**:

- 新增 `docs/system_risk_register.md`，作为 data / PIT / schema / execution / security / cross-LLM process risks 的 durable queue。
- 更新 `AGENTS.md` 启动必读和 AI 协作守则，要求 material audit finding 必须同轮修复或进入 risk register，open P0 不得被普通 roadmap work 绕过。
- 更新 `docs/AI_REVIEW_PROTOCOL.md`，把 risk register 加入 Codex / Claude required reading、`执行` / `审查` / `修复` steps、review clean-Pass 条件和 documentation rules。
- 更新 `docs/README.md` routing table 与 `docs/CURRENT.md` 当前 P0，把下一步从单一 measurement-basis code fix 调整为 risk-register hot queue：先 `SR-EXEC-001` weekly historical `-AsOf` PIT interlock，再 `SR-MEASURE-001` same-anchor benchmark excess。
- 将两轮系统审查的 open items 进入 register：measurement basis、weekly PIT interlock、PIT contract、schema validation、Claude local permissions、execution-backtest risk-control limitations、threshold governance、US-short reference prompt hygiene、web-news prompt injection、data canary overread、deterministic report wall-clock state、audit#1 revalidation queue。

**为什么改**:

- 用户接受了“先建 tracked vulnerability / risk ledger”的判断。此前审查发现只存在于 chat 或 SESSION_LOG 过程文本里，后续 LLM 读取 CURRENT / README 无法看到完整 open-risk queue。
- Measurement-basis lock 只捕获了 benchmark-entry-basis 问题，不足以约束后续 LLM 对 PIT、schema、weekly operation、security 和 execution evidence 风险的执行优先级。
- 本轮不直接修业务代码，是为了先建立强制路由和 review gate，防止后续继续发现蒸发或绕开 open P0。

**验证命令**:

```powershell
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
rg -n "system_risk_register|SR-EXEC-001|SR-MEASURE-001" AGENTS.md docs\README.md docs\CURRENT.md docs\AI_REVIEW_PROTOCOL.md docs\system_risk_register.md
```

**验证结果**:

- 待本轮 Codex SESSION_LOG entry 记录最终验证结果。

**失效旧结论**:

- “下一条 `执行` 只需直接做 same-anchor benchmark excess code fix”被收紧：same-anchor 仍是 P0，但在 risk register hot queue 中排在 `SR-EXEC-001` weekly historical `-AsOf` PIT interlock 之后，除非用户显式 override。
- “全系统审查发现可只放在 chat / review prose / SESSION_LOG”失效；material finding 必须修复或进入 `docs/system_risk_register.md`。

**下一步注意事项**:

1. Claude 审查本轮时必须确认 risk register 是否覆盖已接受的 audit#1 / audit#2 open findings，并检查 protocol 是否足以让未来 `执行` / `审查` 强制读取该 register。
2. 如果审查 Pass 并提交，下一条 `执行` 默认按 `docs/system_risk_register.md` hot queue 修 `SR-EXEC-001`：weekly screening historical `-AsOf` PIT interlock / official-output overwrite guard。
3. `SR-MEASURE-001` same-anchor benchmark excess 仍然阻断 A-share burst prereg；旧 prereg 继续 `BLOCKED_DO_NOT_RUN`，不得因本 register slice 被解锁。

## 2026-05-31 追加：SR-MEASURE-001 same-anchor benchmark excess

**改了什么**:

- 更新 `runners/backtest_rank.py`：forward-daily benchmark fetch 请求 / 缓存 / 校验 CSI1000 与 CSI300 的 `trade_date,open,close`；close-only benchmark cache 不再复用；benchmark excess 改为 benchmark T+1 entry-date open 到同一 exit-date close。
- 更新 `runners/materialize_benchmark_monthly_returns_tushare.py`：`index_daily` 请求 `open,close`，月度兼容 benchmark return 改为 first open 到 last close，并在 metadata limitations 中说明 per-candidate corrected revalidation 使用 `backtest_rank.py` 的同锚点口径。
- 新增 `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`，作为 blocked 原 prereg 的 corrected-basis supersession；只改 benchmark / entry-anchor basis，阈值、universe、holding period、criteria、`test_budget = 1` 均冻结。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/burst_lane_spec.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json`、`docs/strategy_design_synthesis.md`、`docs/system_risk_register.md`、`research/README.md` 的 routing / current-state wording。
- 更新 tests：`tests/test_backtest_rank_phase3.py` 锁定同锚点 excess 与 close-only fallback reject；`tests/execution/test_materialize_benchmark_monthly_returns_tushare.py` 锁定 index open 字段与 first-open / last-close；`tests/schema/test_research_preregistration_schema.py` 锁定 corrected supersession 只改 measurement basis；`tests/schema/test_provider_p1_access_decision_plan_schema.py` 同步 next alpha route。

**为什么改**:

- 旧 5d `excess_csi1000` clue 与 blocked prereg 的 benchmark leg 使用 close basis，不能和 stock T+1 open entry 混合作为 promotion-relevant alpha / research-continuation evidence。
- 当前 A-share CSI1000 / CSI300 open 可由 Tushare `index_daily` 获取；因此正确修法是同锚点 benchmark T+1 open 到同一 exit close，而不是 close-to-close fallback。
- corrected supersession 必须只修测量 basis；任何顺手改阈值、宇宙、持有期、criteria 或 budget 都会变成 fishing 并触发 singleton program-level ledger。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_backtest_rank_phase3 tests.execution.test_materialize_benchmark_monthly_returns_tushare -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.test_backtest_rank_phase3` + `tests.execution.test_materialize_benchmark_monthly_returns_tushare`: 12 tests passed.
- `tests.schema.test_research_preregistration_schema`: 13 tests passed.
- `tests.schema.test_provider_p1_access_decision_plan_schema`: 8 tests passed.
- `python -m unittest discover -s tests/schema -v`: 122 tests passed.
- `git diff --check`: passed; only normal LF/CRLF working-copy warnings.
- `docs/CURRENT.md` authoritative line count = 148, still under the 150-line snapshot target.

**失效旧结论**:

- “SR-MEASURE-001 仍 open / hot queue 第一项”失效；本 reviewed change set 关闭后，risk register 下一项是 `SR-SEC-001` P1。
- “必须先创建 corrected-basis supersession 才能运行 burst falsification”已完成；下一条 alpha-validation `执行` 可在 review + commit 后运行 corrected artifact。
- “旧 prereg 可直接运行”仍失效；`research/preregistrations/a_share_minimal_data_burst_20260531.json` 继续 `BLOCKED_DO_NOT_RUN`。

**下一步注意事项**:

1. Claude 审查应重点核对 `backtest_rank.py` 是否真正用 benchmark entry open 到 exit close，且 close-only cached benchmark 不会被复用。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 应只运行 `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`，并输出 research-only evidence report；不进 production、不声称 ship-gate evidence。
3. 10d / 20d 只允许 diagnostic；不得做 threshold / variant / benchmark / holding-period / rank-cap / cost search。

## 2026-05-31 追加：SR-EXEC-001 weekly historical PIT interlock

**改了什么**:

- 更新 `runners/weekly_screening.ps1`：新增 `-L3Mode pit|today|neutralize` 和 `-AllowHistoricalOverwrite`；当 `-AsOf` 不等于当前运行日期时，必须显式选择 `pit` 或 `neutralize`，禁止 `today`。
- `-L3Mode pit` 由 wrapper 自动传 `--l3-pit-strict` 给 `A-EGS/egs_main.py`，避免 PIT 缺快照时静默 fallback。
- 历史 `-AsOf` 若会覆盖 `result/a_short/<AsOf>/` 或 `A-EGS/Result/egs_{tier1,full}_<AsOf>` / xlsx 既有官方输出，默认拒绝；只有显式 `-AllowHistoricalOverwrite` 才继续。
- 新增 `tests/phase6/test_weekly_screening_guardrails.py`，覆盖缺失 L3 mode、历史 `today` 模式拒绝、既有官方输出 overwrite guard 和 PIT strict 参数。
- 更新 `docs/system_risk_register.md` / `docs/CURRENT.md` / `runners/README.md` 路由：`SR-EXEC-001` 关闭，下一 open P0 转为 `SR-MEASURE-001`。

**为什么改**:

- `SR-EXEC-001` 的风险不是 `egs_main.py` 的 PIT lookup 本身，而是 weekly wrapper 在 historical `-AsOf` 官方输出路径上默认使用 `--l3-mode=today`，并可能覆盖正式结果目录。
- 修在 wrapper 层最小：不动 `A-EGS/egs_main.py` 筛选逻辑、不改 provider / DataHub、不运行旧 burst prereg，也不改变 canary / tracker 的旁路退出码语义。
- 对 historical replay，用户必须在“严格 PIT 快照”与“L3 neutralize”之间显式选择，不能再由默认 today mode 混入当前概念数据。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_weekly_screening_guardrails -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/phase6 -v
$script = Get-Content -Raw runners\weekly_screening.ps1; $null = [scriptblock]::Create($script); Write-Output 'weekly_screening scriptblock ok'
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.phase6.test_weekly_screening_guardrails`: 4 tests passed.
- `python -m unittest discover -s tests/phase6 -v`: 17 tests passed.
- PowerShell scriptblock parse: `weekly_screening scriptblock ok`.
- `git diff --check`: passed；仅出现 touched files 的 LF/CRLF working-copy warning。
- `docs/CURRENT.md` authoritative line count = 147，低于 150-line snapshot target。

**失效旧结论**:

- “`weekly_screening.ps1 -AsOf <historical>` 可不指定 L3 mode”失效；historical official-output run 必须显式 `-L3Mode pit` 或 `-L3Mode neutralize`。
- “historical weekly run 可以默认覆盖 `result/a_short/<AsOf>/` 或 `A-EGS/Result/egs_*_<AsOf>`”失效；既有官方输出默认拒绝 overwrite。
- “risk register hot queue 第一项仍是 `SR-EXEC-001`”失效；本 reviewed change set 关闭后，下一 open P0 是 `SR-MEASURE-001` same-anchor benchmark excess。

**下一步注意事项**:

1. Claude 审查应重点确认 historical guard 是否在调用 `egs_main.py` 前触发，且没有引入 provider / DataHub / burst research scope。
2. 如果审查 Pass 并提交，下一条 `执行` 默认进入 `SR-MEASURE-001`：same-anchor benchmark excess（CSI1000 / CSI300 benchmark T+1 open 到同一 exit close）。
3. 旧 A-share burst prereg 仍然 `BLOCKED_DO_NOT_RUN`，不得因 weekly wrapper guard 关闭而运行。

## 2026-05-31 追加：confirmed bug audit register split

**改了什么**:

- 更新 `docs/system_risk_register.md` hot queue：corrected-basis 5d revalidation 只有在使用冻结 historical generated cohorts 且不重新跑 `A-EGS/egs_main.py` 时，才不受本轮新增 bug 条目阻塞。
- 将确认后的 bug audit 拆成具体条目：`SR-DATA-001`、`SR-OPS-002`、`SR-OPS-003`、`SR-DATA-002`、`SR-EXEC-003`、`SR-EXEC-004`、`SR-EXEC-005`、`SR-CAP-001`、`SR-OPS-004`、`SR-OPS-005`、`SR-OPS-006`、`SR-RANK-001`。
- 将原汇总项 `SR-EXEC-002` 和 `SR-OPS-001` 标为 `superseded`，避免后续 LLM 误读为已修复，也避免继续面对 vague needs-revalidation bucket。
- 更新 `docs/CURRENT.md`，明确本轮是 docs-only register split，不包含代码修复；corrected 5d 重验不得重新生成 cohort。

**为什么改**:

- 用户接受了对 bug 审查的收敛判断：大部分 finding 成立，但 B3 应写成 missing ceiling validation / clamp，N3 应写成 low / needs-revalidation，B6 应标注 partial daily fetch 低频触发而非持续污染。
- 本项目要求 material audit finding 不能只留在 chat；先进入 durable risk register，后续再按路径和优先级改代码。
- 这批 bug 不阻塞 corrected 5d 的唯一前提是使用已冻结 cohorts；若重新跑筛选器，B6 / B5 会重新进入污染路径。

**验证命令**:

```powershell
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
rg -n "SR-DATA-001|SR-OPS-002|SR-OPS-003|SR-DATA-002|SR-EXEC-003|SR-EXEC-004|SR-EXEC-005|SR-CAP-001|SR-OPS-004|SR-OPS-005|SR-OPS-006|SR-RANK-001|frozen historical generated cohorts|confirmed bug audit" docs\system_risk_register.md docs\CURRENT.md
```

**验证结果**:

- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` authoritative line count = 147，低于 150-line snapshot target。
- `rg` matched all intended new risk IDs and corrected 5d frozen-cohort routing.

**失效旧结论**:

- “`SR-EXEC-002` / `SR-OPS-001` 仍只是待复核汇总项”失效；本轮已拆成具体风险条目，原汇总项仅为 `superseded`，不是已修复。
- “新增 bug 会整体阻塞 corrected 5d 重验”失效；只有重新跑 `A-EGS/egs_main.py` / 生成新 cohort 时才会触发 B6 / B5 污染路径。
- “B6 可写成正在每周污染”失效；登记口径为 real wrong-output path with partial `pro.daily` trigger，频率未证、预计低频。

**下一步注意事项**:

1. Claude 审查应重点核对新增 risk IDs、severity、trigger condition 和 blocking path 是否忠实反映 bug audit 收敛结论。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 可运行 corrected-basis 5d revalidation，但必须使用冻结 historical generated cohorts，不得重新跑 `A-EGS/egs_main.py`。
3. 如果在 corrected 5d 之前必须跑新的 weekly official capture / forward tracker official use，则需先修 `SR-DATA-001` / `SR-OPS-002` / `SR-OPS-003` 或显式暂停该路径。

## 2026-05-31 追加：A-share burst zero-event preflight and ledger gate

**改了什么**:

- 新增 `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json`，记录 corrected-basis preregistration 在冻结 2024-2025 cohorts 上预检失败：`valid_signal_events = 0`。
- 新增 `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json`，把该 preflight 计为第一条 spent test，并锁定后续 redesigned A-share burst 测试必须先进入 singleton ledger + 新 reviewed preregistration。
- 更新 `docs/system_risk_register.md`：新增 `SR-RESEARCH-001`（当前 corrected prereg zero valid events）和 `SR-DATA-003`（未来非零事件 outcome / excess run 仍需要 benchmark open input）。
- 更新 active 路由文档和 preregistration artifacts：不再允许跑当前 corrected outcome / benchmark-excess；下一条 A-share burst alpha action 改为 ledger-gated redesign。
- 更新 schema tests，锁定 preflight counts、ledger spend、access-plan next-step routing 和 corrected prereg 的 zero-event 状态。

**为什么改**:

- 用户提供的二次阻塞审查成立：当前 corrected prereg 的 unchanged steady Tier1 universe + frozen trigger 在 24 个 cohort、305 个 Tier1 rows 中没有任何有效事件，直接运行 outcome / excess 只会得到 underpowered 空结果。
- 这不是 same-anchor measurement basis 问题，而是 burst trigger 被套在 steady watchlist universe 上的结构性测试设计问题；因此不能用“只改 basis”的 supersession 继续推进。
- 重新定义 burst universe / trigger 属于新的 promotion-relevant degree of freedom，必须消耗 program-level test-budget ledger，而不是静默改 prereg 后继续跑。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_research_preregistration_schema`: 15 tests passed.
- `tests.schema.test_provider_p1_access_decision_plan_schema`: 8 tests passed.
- `python -m unittest discover -s tests/schema -v`: 124 tests passed.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` authoritative line count = 148，低于 150-line snapshot target。

**失效旧结论**:

- “提交后下一刀可运行 corrected-basis 5d revalidation”失效；当前 corrected prereg 在 preflight 已经 `valid_signal_events = 0`，不得运行 outcome / excess。
- “corrected 5d 的唯一阻塞是 benchmark open 缺失”失效；benchmark open 仍是未来非零事件 outcome run 的 P1 前置，但在 zero-event 阻塞解决前只是 secondary。
- “现有 steady Tier1 frozen cohorts 可承载 minimal-data burst falsification”失效；它们 L3-clean，但不能检验 burst trigger。

**下一步注意事项**:

1. Claude 审查应重点核对 preflight counts 是否来自冻结 cohorts、是否没有 outcome / benchmark-excess / provider fetch，以及 ledger 是否正确把该 preflight 记为 spent test。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 不是跑 corrected artifact，而是创建 ledger-gated redesigned A-share burst preregistration。
3. 任何未来 redesigned test 必须先明确 universe / trigger / benchmark-open handling，并写入 ledger planned test；不得用 Tier2 rows、relaxed entry flags、changed `is_breakout` logic 或 diagnostic benchmark rescue 当前 artifact。

## 2026-05-31 追加：preflight / ledger schema-first repair

**改了什么**:

- 新增 `schemas/research_preflight_result.schema.json`，锁定 preflight result 的 required fields、no outcome / benchmark-excess / provider-fetch / production / ship-gate 边界、summary counts 和 evaluation result 结构。
- 新增 `schemas/program_test_budget_ledger.schema.json`，锁定 singleton program-level ledger、spent tests、future planned_tests 结构、review / user-approval gate 和 no-silent-rescue 边界。
- 更新 `tests/schema/test_research_preregistration_schema.py`：验证两个新 schema 与现有 artifacts，并新增 scope-creep / cardinality / review-gate relaxation 的 reject 测试。
- 更新 `docs/README.md`、`docs/CURRENT.md`、`research/README.md` 路由，把两个新 schema 纳入 research owner 文件。

**为什么改**:

- Claude O1 指出 `research_preflight_result` 与 `program_test_budget_ledger` 已声明 `schema_name` / `schema_version`，但没有 schema 文件；这与项目 schema-first 纪律不一致。
- ledger 后续会被 append planned tests / spend log，不能只靠当前实例逐值测试，否则下一次 redesign 时结构约束会漂移。
- 同时给 preflight result 建 schema，避免留下另一个正式 artifact 类型无 schema 的缺口。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_research_preregistration_schema`: 19 tests passed.
- `python -m unittest discover -s tests/schema -v`: 128 tests passed.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` authoritative line count = 148，低于 150-line snapshot target。

**失效旧结论**:

- “preflight / ledger 只有实例级测试、没有 schema contract”失效；两个 artifact 类型现在均有 v1.0.0 schema。

**下一步注意事项**:

1. Claude 复审应重点核对两个 schema 是否既锁住当前 no-silent-rescue / no-provider / no-production 边界，又允许未来 reviewed planned_tests append。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 仍是 ledger-gated redesigned A-share burst preregistration，不是运行当前 corrected artifact。

## 2026-05-31 追加：preflight pct max schema domain correction

**改了什么**:

- 更新 `schemas/research_preflight_result.schema.json`：`summary_counts.max_pct_5d_all_rows` 与 `max_pct_5d_tier1` 从 `nonNegativeNumber` 改为普通 `number`。
- 更新 `tests/schema/test_research_preregistration_schema.py`：新增测试证明 negative `max_pct_5d_*` 可通过，同时 `max_amount_ratio_*` 仍保持非负约束。

**为什么改**:

- Claude O1 指出 5 日收益的最大值在全员下跌窗口中可能为负；把 `max_pct_5d_*` 设为非负会在未来 redesigned burst preflight 中产生 false validation failure。
- 金额比值仍应保持非负，因此只放宽 pct return 字段，不放宽 amount ratio 字段。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_research_preregistration_schema`: 20 tests passed.
- `python -m unittest discover -s tests/schema -v`: 129 tests passed.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` authoritative line count = 148，低于 150-line snapshot target。

**失效旧结论**:

- “`max_pct_5d_*` 可按非负数建模”失效；pct return 字段必须允许负值。

**下一步注意事项**:

1. Claude 复审应确认只放宽了 pct return max 字段，未放宽 amount ratio / execution boundary / ledger review gate。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 仍是 ledger-gated redesigned A-share burst preregistration。
