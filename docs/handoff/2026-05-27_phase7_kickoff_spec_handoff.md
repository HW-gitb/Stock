# Phase 7 Kickoff Spec Handoff

## 2026-06-01 append: SR-DATA-001 suspend daily completeness guard

**Changed**:
- Updated `A-EGS/egs_main.py:get_suspend_info` so a non-empty `pro.daily` payload must meet `suspend_daily_min_coverage = 0.95` against the as-of stock universe before missing rows are treated as suspended stocks.
- Bumped the suspend cache key to `suspend_<date>_v2` so old unvalidated suspend-inference caches are not reused.
- Added `tests/phase6/test_egs_main_suspend_guard.py` to cover partial daily rejection, high-coverage suspend inference, v2 cache save behavior, and the existing all-empty daily fallback.
- Marked `SR-DATA-001` resolved in `docs/system_risk_register.md`; the hot queue now moves to the execution-evidence risk group before any execution-backtest evidence or manual sizing conclusion is used.

**Why**:
- The old `all_codes - traded_codes` inference was safe only when the single-day `daily` response was complete enough. A partial provider response could silently remove tradable stocks during L0.
- The smallest safe fix is fail-fast / quarantine for suspicious non-empty daily payloads. Fully empty daily responses still keep the existing startup / non-trading fallback behavior and skip suspend filtering rather than marking the whole market suspended.
- This slice does not run EGS, regenerate cohorts, fetch provider data, change research artifacts, or change alpha conclusions.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_egs_main_suspend_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_egs_main_l3_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests\phase6 -v
git diff --check
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; print(len(Path('docs/CURRENT.md').read_text(encoding='utf-8').splitlines()))"
```

**Validation result**:
- `tests.phase6.test_egs_main_suspend_guard`: 3 tests passed.
- `tests.phase6.test_egs_main_l3_guard`: 4 tests passed.
- `python -m unittest discover -s tests\phase6 -v`: 32 tests passed.
- `git diff --check`: passed with only expected Windows LF-to-CRLF warnings.
- `docs/CURRENT.md` line count: 149 via Python `splitlines()`, below the 150-line snapshot target.

**Invalidated / blocked old conclusion**:
- "`SR-DATA-001` still blocks the next weekly official capture or direct cohort regeneration" is invalid after this reviewed slice.
- "Missing rows in a non-empty `daily` response can be treated as suspended without a completeness gate" is invalid after this reviewed slice.

**Next-step notes**:
- If this slice passes review and is committed, the default next `执行` returns to the risk-register execution-evidence group (`SR-EXEC-003/004/005/007` + `SR-CAP-001` + `SR-CONTRACT-002`) unless the user explicitly approves a narrower override.
- Do not use this fix as authorization to run weekly capture, rerun EGS, fetch provider data, or open a new A-share burst research test.

## 2026-06-01 append: SR-OPS-003 historical L3 engine guard

**Changed**:
- Added an engine-level guard in `A-EGS/egs_main.py`: non-current `--as-of` runs cannot use default `--l3-mode=today` unless the caller explicitly passes `--allow-historical-live-l3`.
- Added the explicit `--allow-historical-live-l3` declaration to `runners/backtest_rank.py` only for smoke-mode historical `today` L3 candidate generation.
- Added focused tests for the direct engine guard and the backtest command contract.
- Marked `SR-OPS-003` resolved in `docs/system_risk_register.md`; hot queue item #1 now leaves `SR-DATA-001` as the remaining blocker before new weekly official capture / direct cohort regeneration.

**Why**:
- `SR-EXEC-001` had already fixed the weekly wrapper, but direct `egs_main.py --as-of <historical>` still defaulted to live concept data through `--l3-mode=today`.
- The fix keeps the default safe while preserving an explicit non-evidence smoke path for local diagnostics.
- This does not run EGS, fetch provider data, regenerate cohorts, change research artifacts, or alter L3 scoring semantics for allowed `pit` / `neutralize` runs.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_egs_main_l3_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_backtest_rank_phase3 -v
```

**Validation result**:
- `tests.phase6.test_egs_main_l3_guard`: 4 tests passed.
- `tests.test_backtest_rank_phase3`: 6 tests passed.

**Invalidated / blocked old conclusion**:
- "`SR-OPS-003` still leaves direct historical `egs_main.py --as-of` silently defaulting to live L3 concepts" is invalid after this reviewed slice.
- "All hot queue #1 blockers are done" is still false: `SR-DATA-001` remains open and must be fixed before new weekly official capture or cohort regeneration used as evidence.

**Next-step notes**:
- If this slice passes review and is committed, the default next `执行` is `SR-DATA-001`.
- Do not use this guard as authorization to run weekly capture, rerun EGS, fetch provider data, or start any new A-share burst research test.

## 2026-06-01 append: SR-OPS-002 forward tracker atomic write

**Changed**:
- Updated `runners/forward_tracker.py:_write_tracker` so tracker persistence writes to a same-directory temp CSV, flushes and `fsync`s the handle, closes it, then atomically replaces `forward_tracker.csv` with `os.replace`.
- Added focused tests in `tests/phase6/test_forward_tracker_cache_guard.py` for same-directory temp naming, atomic replace, sorted schema-column output, successful temp cleanup, and failure-path preservation of an existing tracker file.
- Marked `SR-OPS-002` resolved in `docs/system_risk_register.md` and removed it from the hot queue; `SR-DATA-001` and `SR-OPS-003` remain open blockers before new weekly official capture / direct historical cohort regeneration.
- Updated `docs/CURRENT.md` and `docs/SESSION_LOG.md` with the current routing.

**Why**:
- Direct CSV writes can leave a partial `forward_tracker.csv` if the process is interrupted during forward-evidence capture or backfill.
- The fix is intentionally limited to the tracker writer. It does not change research results, EGS generation, provider access, cache refresh behavior, or any strategy threshold.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_forward_tracker_cache_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests\phase6 -v
git diff --check
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; print(len(Path('docs/CURRENT.md').read_text(encoding='utf-8').splitlines()))"
```

**Validation result**:
- `tests.phase6.test_forward_tracker_cache_guard`: 5 tests passed.
- `python -m unittest discover -s tests\phase6 -v`: 25 tests passed.
- `git diff --check`: passed with only expected Windows LF-to-CRLF warnings.
- `docs/CURRENT.md` line count after R1 trim: 149 via Python `splitlines()`, below the 150-line snapshot target.

**Invalidated / blocked old conclusion**:
- "`SR-OPS-002` still blocks forward-tracker official use because writes are non-atomic" is invalid after this reviewed slice.
- "The whole hot queue #1 is done" is still false: `SR-DATA-001` and `SR-OPS-003` remain open and must be handled before new weekly official capture / direct historical `egs_main.py` cohort regeneration.

**Next-step notes**:
- If this slice passes review and is committed, the default next `执行` returns to hot queue item #1: `SR-DATA-001` or `SR-OPS-003`, unless the user explicitly approves a narrower override.
- Do not use this fix as authorization to run weekly capture, rerun EGS, fetch provider data, or open US provider access.

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

## 2026-06-02 追加：US EGS small sample validation approval boundary

**改了什么**:

- 新增 `schemas/provider_p1_sample_validation_access_approval.schema.json`，把用户批准的 US EGS 小样本验证边界固化为 schema-first artifact：$0、现有 FMP key、SEC EDGAR public API、AAPL / MSFT only、no `yfinance`、no full-market、no paid upgrade、no provider selection、no adapter / DataHub / runner / Phase 7c。
- 新增 `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json`，记录 2026-06-02 用户批准内容与后续 sample-validation packet 的 storage / secret 边界。
- `.gitignore` 新增 `provider_samples/`，确保后续 raw vendor / public API sample rows 只能作为本地样本保存，不进入 git；tracked summary 仍可单独提交。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`AGENTS.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/CURRENT.md`、`docs/README.md`、`docs/datahub_design.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/evidence_feasibility_controls.md`、`docs/evidence_report_schema_contract.md`、`docs/strategy_design_synthesis.md`，把旧的“sample/data fetch 完全未授权”改成“只授权后续 reviewed AAPL / MSFT 小样本验证，其余仍阻断”。
- 新增 `tests/schema/test_provider_p1_sample_validation_access_approval_schema.py`，验证 approval artifact、原 access plan 仍非授权、schema const locks、next-step 不授权 provider selection / Phase 7c。

**为什么改**:

- 用户明确批准：FMP 使用当前账号 / API key，预算上限 $0；允许 SEC EDGAR 公共 API；允许本地保存少量样本和校验结果；只允许抓少数股票小样本；不允许全市场下载、不允许付费升级。
- 需要把 chat approval 转成 durable repo artifact，避免后续 LLM 继续认为 sample validation 完全未授权，或反向误读成可做 provider selection / broad data fetch / Phase 7c。
- 旧 access plan 保持 plan-only；新的 approval artifact 只解决其中最窄的一条 access boundary，不改变 P1 readiness matrix 的 partial / blocked 结论。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_sample_validation_access_approval_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema tests.schema.test_provider_p1_sample_validation_access_approval_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests\schema -v
git diff --check
git check-ignore -v provider_samples/us_egs_sample_validation_20260602/raw.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=[...]; [Path(f).read_text(encoding='utf-8') for f in files]; print('utf8 ok'); print('CURRENT lines', len(Path('docs/CURRENT.md').read_text(encoding='utf-8').splitlines()))"
```

**验证结果**:

- `tests.schema.test_provider_p1_sample_validation_access_approval_schema`: 7 tests ran, 4 passed, 3 skipped because this bundled interpreter lacks `jsonschema`.
- `tests.schema.test_provider_p1_access_decision_plan_schema tests.schema.test_provider_p1_sample_validation_access_approval_schema`: 15 tests ran, 9 passed, 6 skipped because this bundled interpreter lacks `jsonschema`.
- `python -m unittest discover -s tests\schema -v`: failed for environment dependency, not this slice; 5 existing `tests/schema/test_analysis_input_contract.py` tests error because `engine/data/analysis_input_contract.py` requires `jsonschema`, and the available Python runtime does not have it installed. Many schema-validation tests also skip for the same missing dependency.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- UTF-8 read check passed；`docs/CURRENT.md` authoritative line count = 149，低于 150-line snapshot target。
- `git check-ignore -v provider_samples/us_egs_sample_validation_20260602/raw.json`: matched `.gitignore:50:provider_samples/`，raw provider sample path is ignored.

**失效旧结论**:

- “US EGS sample validation 完全没有用户授权”失效；现在只对 AAPL / MSFT、现有 FMP key、SEC EDGAR public API、$0 小样本验证授权。
- “P1 access plan 本身可授权 sample fetch / provider access”仍不成立；计划文件仍是 plan-only，授权只存在于新的 2026-06-02 approval artifact。
- “小样本批准可进入 provider selection / full-market / DataHub / Phase 7c”不成立；这些仍需单独 explicit approval + reviewed decision。

**下一步注意事项**:

1. Claude 复审应重点核对 approval schema / artifact 是否只解锁 AAPL / MSFT 小样本验证，且没有把 `yfinance`、paid access、full-market、provider selection、adapter、DataHub、runner 或 Phase 7c 打开。
2. 如果审查 Pass 并提交，下一条 `执行` 可以实现 narrow sample-validation packet：只检查 `FMP_API_KEY` / `SEC_USER_AGENT` 存在且不打印 secrets，只抓 AAPL / MSFT 的 FMP + SEC EDGAR small samples，raw rows 写到 gitignored `provider_samples/us_egs_sample_validation_20260602/`，tracked summary 不含 secrets 或完整 raw rows。
3. 由于当前可用 Python runtime 缺 `jsonschema`，若复审需要完整 Draft-07 validation，应先在合规环境安装项目 `requirements.txt` 依赖或用已有含 `jsonschema` 的解释器重跑 schema tests。

## 2026-06-02 追加：US EGS AAPL/MSFT sample-validation result

**改了什么**:

- 新增 `runners/us_egs_sample_validation.py`，实现已批准的窄 sample-validation packet：运行时校验 approval artifact、检查 `FMP_API_KEY` / `SEC_USER_AGENT` 存在但不打印值、只抓 AAPL / MSFT、raw payload 只写入 gitignored `provider_samples/us_egs_sample_validation_20260602/`、tracked summary 不含 raw rows 或 secrets。
- 新增 `schemas/provider_p1_us_egs_sample_validation_summary.schema.json`，锁定 summary 的 scope：no provider selection、no full-market、no `yfinance`、no paid access、no DataHub、no production runner consumption、no Phase 7c、no ship-gate claim。
- 真实执行 approved small sample，新增 `docs/provider_evidence_p1_us_sample_validation_summary_20260602.json`。结果为 `completed_with_endpoint_errors`：17 calls within budget；SEC EDGAR company tickers / submissions / companyfacts 对 AAPL 和 MSFT 成功；FMP v3 endpoint families 对两只股票均返回 HTTP 403 legacy-endpoint errors。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`docs/CURRENT.md`、`docs/README.md`，把状态从“待执行小样本”改为“SEC 样本通过，FMP v3 样本未验证通过；下一步需审查 current FMP endpoint mapping 或 FMP account/API boundary”。
- 新增 `tests/provider/test_us_egs_sample_validation.py` 与 `tests/schema/test_provider_p1_us_egs_sample_validation_summary_schema.py`，覆盖 fake-client 小样本、secret 不落 summary、raw root 必须在 ignored `provider_samples/`、SEC 不请求压缩 payload、schema scope locks。

**为什么改**:

- 上一轮 approval artifact 已经 reviewed / committed，只解锁 AAPL / MSFT 小样本验证；本轮把批准边界落实为可复跑 runner + schema + tracked no-secret summary。
- 真实小样本验证发现 FMP v3 legacy endpoint 问题，必须 durable 记录，避免后续 LLM 误把“已有 FMP key”当成“FMP 已验证可用”。
- SEC EDGAR 样本成功只证明公共 filing audit source 的小样本可访问；不证明 FMP、coverage、license、PIT、fallback、DataHub 或 production readiness。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe runners\us_egs_sample_validation.py
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.provider.test_us_egs_sample_validation -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema tests.schema.test_provider_p1_sample_validation_access_approval_schema -v
git diff --check
(Get-Content -Path docs\CURRENT.md -Encoding UTF8).Count
git check-ignore -v provider_samples\us_egs_sample_validation_20260602\raw\financial_modeling_prep\AAPL\income_statement.json
```

**验证结果**:

- `runners/us_egs_sample_validation.py`: wrote `docs/provider_evidence_p1_us_sample_validation_summary_20260602.json`; `validation_status = completed_with_endpoint_errors`; `actual_total_endpoint_calls = 17`; `secrets_logged = false`。
- `tests.provider.test_us_egs_sample_validation`: 5 tests passed.
- Combined summary / approval schema targeted tests: 12 tests ran, 5 passed, 7 skipped because this bundled interpreter lacks `jsonschema`; non-jsonschema scope-lock tests passed.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` line count = 149。
- `git check-ignore`: raw sample path matched `.gitignore:50:provider_samples/`。

**失效旧结论**:

- “AAPL / MSFT sample-validation packet 尚未执行”失效；packet 已执行并生成 tracked no-secret summary。
- “FMP existing API key 已可直接作为 US EGS 主源”不能成立；本轮 sampled FMP v3 endpoint families 均 403，FMP 未被此 packet 验证通过。
- “SEC EDGAR 小样本可访问意味着 provider / DataHub / Phase 7c 可推进”不成立；SEC 成功只支持 fundamentals audit source 的小样本可访问。

**下一步注意事项**:

1. Claude 复审应重点核对 summary 是否没有 raw rows / secrets、raw payload 是否保持 ignored、FMP 403 是否被正确降级为 blocker 而不是失败后 silent retry 或 provider selection。
2. 如果审查 Pass 并提交，下一条 `执行` 的自然候选是 current FMP endpoint mapping / account boundary review；不应直接扩大到 `yfinance`、full-market fetch、paid upgrade、DataHub、production runner consumption 或 Phase 7c。
3. 若要完整 Draft-07 validation，应在含 `jsonschema` 的环境中重跑 summary schema test；当前 bundled Python 仍缺该依赖。

## 2026-06-02 追加：US EGS FMP current endpoint mapping review

**改了什么**:

- 新增 `schemas/provider_p1_fmp_endpoint_mapping_review.schema.json`，锁定 FMP current-endpoint mapping review 的 docs-only 边界：不 live retry、不抓数据、不选 provider、不用 `yfinance`、不 full-market、不 paid upgrade、不建 adapter / DataHub、不改 production runner、不授权 Phase 7c / ship-gate。
- 新增 `docs/provider_evidence_p1_us_fmp_current_endpoint_mapping_review_20260602.json`，基于 FMP 官方 docs 把上一轮失败的 sampled v3 endpoint families 映射到 stable endpoint candidates：profile、income statement、balance sheet、cash flow、key metrics、historical EOD full。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`docs/CURRENT.md`、`docs/README.md`，把状态从“需要 mapping review”改为“stable endpoint candidates 已 docs-only 映射；下一步可做同范围 stable retry，但仍需 review / no broad deployment”。
- 新增 `tests/schema/test_provider_p1_fmp_endpoint_mapping_review_schema.py`，验证 scope locks、六个 endpoint family 覆盖、stable URL 前缀、no retry / no provider selection / no yfinance / no Phase 7c。

**为什么改**:

- 上一轮真实 AAPL / MSFT sample 证明 SEC EDGAR 可访问，但 FMP v3 endpoint families 全部 403。Claude review 指出这是真实 endpoint/account 边界，不是 runner bug。
- 直接改 runner 并 live retry 会把“mapping review”和“数据抓取”混成一刀；本轮只先固化 current stable endpoint candidates 和 retry gate，避免 silent retry / scope creep。
- FMP 官方 docs 当前使用 `https://financialmodelingprep.com/stable/` base URL；旧 `/api/v3/...` 样本不能再被当作当前 endpoint mapping。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema -v
git diff --check
(Get-Content -Path docs\CURRENT.md -Encoding UTF8).Count
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema` ran 6 tests: 3 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope-lock and mapping-coverage tests passed.
- Python313 with `jsonschema`: combined sample-summary + FMP-mapping schema tests ran 11 tests, all passed; the real sample summary and new mapping artifact both validate against their schemas, and scope-creep mutations are rejected.
- `docs/CURRENT.md` line count = 149。
- Full `git diff --check` should be rerun after SESSION_LOG is prepended in the same work round.

**失效旧结论**:

- “FMP endpoint mapping 尚未完成”失效；stable endpoint candidates 已 docs-only mapped。
- “stable endpoint candidates 已 live validated”不成立；本轮没有 FMP live retry，也没有新 data fetch。
- “mapping review 可授权 provider selection / DataHub / Phase 7c”不成立；schema 和 artifact 都显式阻断。

**下一步注意事项**:

1. Claude 复审应核对 mapping artifact 是否只引用官方 docs + tracked sample summary，并没有把 stable candidate 写成 validated provider readiness。
2. 如果审查 Pass 并提交，下一条 `执行` 的自然候选是更新 / parameterize standalone sample-validation runner，用 same-scope AAPL / MSFT stable endpoints 做一次 no-secret retry；不应扩大到 `yfinance`、full-market、paid access、provider selection、DataHub、production runner consumption 或 Phase 7c。
3. 若需要完整 Draft-07 validation，应在含 `jsonschema` 的解释器中重跑新增 schema test。

## 2026-06-02 追加：US EGS FMP stable endpoint retry result

**改了什么**:

- 更新 `runners/us_egs_sample_validation.py`，新增 `--fmp-endpoint-mode stable`，只用已批准的 AAPL / MSFT、现有 FMP key、$0、小样本边界，调用 mapped FMP stable endpoint families；legacy v3 + SEC sample 路径保留。
- 新增 `schemas/provider_p1_fmp_stable_endpoint_retry_summary.schema.json`，锁定 stable retry summary 的 no provider selection、no paid、no `yfinance`、no full-market、no adapter / DataHub、no production runner consumption、no Phase 7c、no ship-gate claim 边界。
- 真实执行 stable retry，新增 `docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json`。结果为 `completed`：12 FMP stable calls within budget；AAPL / MSFT 的 profile、income statement、balance sheet statement、cash-flow statement、key metrics、historical EOD price / volume 均 HTTP 200；summary 不含 secrets 或 request URLs。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`docs/CURRENT.md`、`docs/README.md`，把状态从“stable candidates mapped only”改为“two-symbol stable retry succeeded, but remaining provider blockers stay open”。
- 新增 / 更新测试：`tests/provider/test_us_egs_sample_validation.py` 覆盖 stable fake-client 路径、12-call / no SEC / no yfinance / no secrets / stable field presence；`tests/schema/test_provider_p1_fmp_stable_endpoint_retry_summary_schema.py` 覆盖 schema locks 与真实 summary validation。

**为什么改**:

- 上一轮 mapping review 已经证明旧 `/api/v3` endpoint 不是当前 retry 目标；本轮按 review 后的最小下一刀，把 stable candidate 真正跑一次，验证当前账号 / key 对两只样本股票的 endpoint access 和基本 response shape。
- 这能防止两个错误方向：一是继续误读 v3 403 为 FMP 不可用；二是把 stable docs path 误读成已验证可用。
- 仍然只解决小样本 access / shape；coverage、license / retention、PIT semantics、fallback / incident、provider stability、production readiness 仍不是本轮结论。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.provider.test_us_egs_sample_validation -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fmp_stable_endpoint_retry_summary_schema tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_stable_endpoint_retry_summary_schema tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe runners\us_egs_sample_validation.py --fmp-endpoint-mode stable
git diff --check
git check-ignore -v provider_samples\us_egs_sample_validation_20260602\fmp_stable_retry\raw\financial_modeling_prep\AAPL\income_statement.json
Select-String -Path docs\provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json -Pattern 'apikey=','Bearer ','SEC_USER_AGENT=' -SimpleMatch
```

**验证结果**:

- Real stable retry wrote `docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json`; `validation_status = completed`; `actual_total_endpoint_calls = 12`; `secrets_logged = false`。
- `tests.provider.test_us_egs_sample_validation`: 7 tests passed.
- Bundled Python targeted schema tests: 16 tests ran, 5 passed, 11 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope-lock tests passed.
- Python313 with `jsonschema`: 16 tests passed, including the real stable retry summary validation and scope-creep rejection.
- `git diff --check`: passed before SESSION_LOG entry; rerun after SESSION_LOG is expected.
- `git check-ignore`: stable raw sample path matched `.gitignore:50:provider_samples/`。
- Secret-pattern check for key-bearing URL / bearer / SEC env syntax returned no matches.

**失效旧结论**:

- “FMP stable endpoint candidates 尚未 live retried”失效；AAPL / MSFT same-scope stable retry 已执行并成功。
- “旧 FMP v3 403 足以判断 FMP 当前账号不可用”不成立；当前 stable endpoint families 对 AAPL / MSFT 返回 HTTP 200。
- “FMP stable retry 成功 = provider selected / production ready / Phase 7c 可开工”不成立；本轮只提供两只股票的小样本 access / response-shape evidence。

**下一步注意事项**:

1. Claude 复审应重点核对 summary 是否没有 raw rows / request URLs / secrets，raw payload 是否保持 ignored，stable runner 是否没有调用 SEC / `yfinance` / TSLA / full-market。
2. `SR-PROVIDER-001` 仍 open；后续若要推进 provider work，必须另行处理 coverage、license / storage、PIT semantics、fallback / incident、stability 和 production-readiness evidence。
3. 不要把 sample runner 接入 production runner，也不要进入 DataHub / adapter / Phase 7c，除非用户另有 explicit approval + reviewed decision。

## 2026-06-02 追加：US EGS post-stable-retry remaining blocker plan

**改了什么**:

- 新增 `schemas/provider_p1_remaining_blocker_resolution_plan.schema.json`，把 AAPL / MSFT FMP stable retry 之后仍未解决的 P1 blocker 固化为 schema-first plan：coverage counts、license / storage / retention、PIT / observed-date semantics、price adjustment / corporate actions、SEC EDGAR audit parser feasibility、fallback / incident / stability、production-readiness / Phase 7c gate。
- 新增 `docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json`，记录 stable retry 只关闭 two-symbol access / response-shape sub-blocker；其余 blocker 仍不得 silent default、不得转成 provider selection / DataHub / runner consumption。
- 新增 `tests/schema/test_provider_p1_remaining_blocker_resolution_plan_schema.py`，验证 schema、真实 artifact、scope locks、blocker-track completeness、source refs 和 scope-creep rejection。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`docs/CURRENT.md`、`docs/README.md`，把 active provider routing 从“stable retry result”推进到“remaining blocker plan”，但保持 `SR-PROVIDER-001` open。

**为什么改**:

- Stable retry 成功后，最容易出现的误读是把 12/12 HTTP 200 当作 FMP 可选定或 Phase 7c 可开工。这个 artifact 把剩余 blocker 逐项拆开，明确下一步只能先解决 blocker，而不是扩大抓数或实现。
- 这轮刻意不调用 FMP / SEC / `yfinance`，不扩大 symbol，不接 adapter / DataHub / production runner，不放松 ship gate。
- 安全的后续 docs-only 切片是 license / storage / retention review；安全的 schema-first 切片是 fallback / incident / stability playbook。任何 coverage-count、PIT-row、corporate-action 或 broader sample validation 都必须重新获得 user approval。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
```

**验证结果**:

- Bundled Python: 6 tests ran; 3 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope-lock / blocker / routing tests passed.
- Python313 with `jsonschema`: 6 tests passed, including real artifact validation and scope-creep rejection.

**失效旧结论**:

- “stable retry 之后下一步可以直接 provider selection / DataHub / runner consumption / Phase 7c”不成立。
- “remaining blockers 只需要在 chat 里提醒”失效；现在由 schema-first artifact 路由，Claude review 应直接检查该 artifact 的 blockers 和 scope locks。

**下一步注意事项**:

1. Claude 复审应重点核对 artifact 是否只做 blocker routing，且没有授权新 access / data fetch / `yfinance` / provider selection / DataHub / runner / Phase 7c。
2. 如果审查 Pass 并提交，下一条 provider 方向的 `执行` 默认不抓数据；应先做 FMP / SEC license-storage-retention review，或 fallback / incident / stability playbook schema-first design。

## 2026-06-02 追加：US EGS fallback / incident / stability playbook

**改了什么**:

- 新增 `schemas/provider_p1_fallback_incident_stability_playbook.schema.json`，把 `fallback_incident_stability` blocker 拆成 schema-first playbook contract：field-family fallback order、incident response matrix、drift-monitor bindings、decision gates、prohibited actions。
- 新增 `docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json`，定义 fundamentals、price / volume / liquidity、corporate actions、security master / coverage、SEC EDGAR audit、benchmark / GICS 的默认阻断规则；定义 quota / outage / auth-scope / schema drift / stale rows / PIT ambiguity / corporate-action conflict / SEC audit conflict 的 incident actions。
- 新增 `tests/schema/test_provider_p1_fallback_incident_stability_playbook_schema.py`，验证 schema/artifact、scope locks、field-family completeness、incident completeness、design-only limitations、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 provider routing 从 remaining-blocker plan 推进到 fallback playbook design，但保持 `SR-PROVIDER-001` open。

**为什么改**:

- 上一轮 remaining-blocker plan 明确 safe schema-first next slice 是 fallback / incident / stability playbook。这个 slice 不需要新 provider access，也不需要联网查 license terms。
- Stable retry 的 12/12 HTTP 200 只证明 AAPL / MSFT access / shape；如果没有 default-deny fallback / incident contract，后续 DataHub / runner 容易 silent default 或把 status-page existence 误读成 stability evidence。
- 本轮刻意不执行 provider status polling、不抓新数据、不用 `yfinance`、不实现 fallback execution、不建 adapter / DataHub、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fallback_incident_stability_playbook_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fallback_incident_stability_playbook_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema tests.schema.test_provider_p1_fmp_stable_endpoint_retry_summary_schema tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_fallback_incident_stability_playbook.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_fallback_incident_stability_playbook_schema` ran 7 tests: 4 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope / completeness / no-access tests passed.
- Python313 with `jsonschema`: fallback playbook + remaining-blocker plan + FMP stable retry summary + US EGS sample summary tests ran 23 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 149。
- `git diff --check` passed after the SESSION_LOG entry was prepended; only normal LF/CRLF working-copy warnings.

**失效旧结论**:

- “fallback / incident / stability playbook 尚未定义”失效；default-deny playbook 已 schema-first recorded。
- “playbook design = fallback execution / provider stability evidence”不成立；本轮 artifact 明确不执行 fallback、不轮询 status page、不抓数据、不证明稳定性。
- “有 playbook 就可进 DataHub / runner / Phase 7c”不成立；这些仍被 scope locks 和 `SR-PROVIDER-001` 阻断。

**下一步注意事项**:

1. Claude 复审应重点核对 playbook 是否只定义默认阻断行为，且没有授权 provider status polling、fallback execution、new access、`yfinance`、provider selection、DataHub、runner 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可以是 license / storage / retention review；如果继续 incident 方向，只能先做 incident-log schema contract，仍不得 provider calls。

## 2026-06-02 追加：US EGS incident-log contract

**改了什么**:

- 新增 `schemas/provider_p1_incident_log_contract.schema.json`，把 fallback playbook 里要求的 incident log 进一步固化为未来记录契约：required record fields、incident-type mappings、storage / retention policy、review / replay policy、decision gates、prohibited actions。
- 新增 `docs/provider_evidence_p1_us_incident_log_contract_20260602.json`，记录 planned log root / raw payload root / tracked summary pattern 只是 contract design，不创建日志路径、不写 incident rows、不实现 writer、不授权 storage / retention。
- 新增 `tests/schema/test_provider_p1_incident_log_contract_schema.py`，验证 schema/artifact、scope locks、24 个 required record fields、8 个 playbook incident mappings、storage/review no-authorization locks、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 provider routing 从 fallback playbook 推进到 incident-log contract，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- 上一轮 playbook 已经要求 incident log，但如果只停在字段期望，后续实现容易把 log writer、status polling、fallback execution、storage rights 混在同一刀里。
- 本轮先把记录形状和 review / replay boundary 固化为 schema-first contract，避免 future LLM 把 "record_incident" 误读成已经能写日志或能自动轮询 provider status。
- 本轮刻意不运行 provider status polling、不抓新数据、不用 `yfinance`、不创建日志路径、不实现 writer、不执行 fallback、不建 adapter / DataHub、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_incident_log_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_incident_log_contract_schema tests.schema.test_provider_p1_fallback_incident_stability_playbook_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_incident_log_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_incident_log_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_incident_log_contract_schema` ran 7 tests: 4 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope / completeness / no-access tests passed.
- Python313 with `jsonschema`: incident-log contract + fallback playbook + remaining-blocker plan targeted schema tests ran 20 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count remained 149.
- `git diff --check` passed before SESSION_LOG; the final after-SESSION_LOG check is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**失效旧结论**:

- “incident-log schema contract 尚未定义”失效；future record contract 已 schema-first recorded。
- “incident-log contract = log writer / storage authorization / provider status polling / fallback execution”不成立；本轮 artifact 明确不创建日志、不实现 writer、不授权 storage / retention、不轮询 status page、不抓数据、不执行 fallback。
- “有 incident-log contract 就可进 DataHub / runner / Phase 7c”不成立；这些仍被 scope locks 和 `SR-PROVIDER-001` 阻断。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否只定义未来 record shape，且没有授权 log writer、provider status polling、provider calls、fallback execution、provider selection、DataHub、runner 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 默认应转向 FMP / SEC license / storage / retention review；任何 log-writer implementation、status polling、fallback execution 或 provider call 都需要 separate explicit approval + reviewed decision。

## 2026-06-02 追加：DataHub local resource budget contract

**改了什么**:

- 新增 `schemas/datahub_local_resource_budget.schema.json`，把 Phase 7c 前的本机资源预算边界固化为 schema-first contract：默认 `single_slice_incremental`，单市场 / 单 lane / bounded window、lazy load、incremental cache reuse、heavy job checkpoint / resume、heavy run 必须显式用户批准 + reviewed job spec。
- 新增 `docs/datahub_local_resource_budget_contract_20260602.json`，记录两个 budget profile：`local_interactive_default` 与 `reviewed_heavy_run_optional`；两者都不授权 provider calls、DataHub implementation、runner change、Phase 7c implementation 或 all-system default run。
- 新增 `tests/schema/test_datahub_local_resource_budget_schema.py`，验证 schema/artifact、默认分片增量行为、budget profile、implementation gates、scope-creep rejection。
- 更新 `docs/datahub_design.md`、`docs/README.md`、`docs/CURRENT.md`、`AGENTS.md`，把该 contract 路由为 Phase 7c 前置边界。
- 更新 `docs/system_risk_register.md`，新增 `SR-RESOURCE-001` P2 open：contract 已定义，但未来 DataHub / runner 代码级 enforcement 尚未实现。

**为什么改**:

- 用户明确担心四套系统全设计完后本机带不动；当前设计并不要求一次性跑四套系统，但旧 DataHub guardrail 没有明确禁止“默认全系统 full refresh”。
- 直接写资源管理代码会过早进入 Phase 7c implementation。本轮只先固化 contract，约束后续实现必须分片、增量、可恢复、可审查。
- 该 contract 不解决 `SR-PROVIDER-001`，也不替代 provider license / storage / retention review；它只防止 DataHub / runner 以后把重任务变成默认行为。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_datahub_local_resource_budget_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_local_resource_budget_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\datahub_local_resource_budget.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\datahub_local_resource_budget_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_datahub_local_resource_budget_schema` ran 6 tests: 3 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema default-boundary / budget-profile / gate tests passed.
- Python313 with `jsonschema`: 6 tests passed, including real artifact validation and scope-creep rejection.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145 after slimming old completed-item detail back into risk-register references.
- `git diff --check` passed after the SESSION_LOG entry was prepended; only normal LF/CRLF working-copy warnings.

**失效旧结论**:

- “四套系统设计完成后必须一次性全量运行”不成立；默认运行边界已固化为 single-slice / incremental。
- “有 resource-budget contract 就已经可以进 Phase 7c implementation”不成立；artifact 明确不授权 DataHub table、adapter、runner change、provider call 或 Phase 7c。
- “SR-RESOURCE-001 已关闭”不成立；代码级 enforcement 和 job-spec tests 尚未实现。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否没有授权 provider calls、DataHub implementation、runner change、Phase 7c、ship-gate claim 或全系统默认运行。
2. Provider 方向的自然下一刀仍可回到 FMP / SEC license / storage / retention docs-only review；DataHub implementation 仍需单独 explicit approval + reviewed decision。

## 2026-06-02 追加：US EGS license / storage / retention review

**改了什么**:

- 新增 `schemas/provider_p1_license_storage_retention_review.schema.json`，把 FMP / SEC EDGAR 的 local raw sample、tracked no-secret summary、production raw storage、normalized DataHub storage、derived outputs、non-display use、export / redistribution、retention、professional / business use、broader sample / full-market use 分类为 schema-first review contract。
- 新增 `docs/provider_evidence_p1_us_license_storage_retention_review_20260602.json`，只基于既有 reviewed repo artifacts 做 blocker classification；不做 current provider terms web refresh、不联系 provider、不提供法律建议、不抓数据。
- 新增 `tests/schema/test_provider_p1_license_storage_retention_review_schema.py`，验证 schema/artifact、no-access locks、rights matrix、remaining gates、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 license-storage-retention review 路由进 Phase 7b-2，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- stable retry 只证明 AAPL / MSFT 两只股票 endpoint access / response-shape；它没有回答 FMP current terms、local storage、normalized DataHub storage、derived outputs、retention、non-display use 或 SEC broader reconstruction 的生产边界。
- 本轮先用既有 repo 证据把 “已批准小样本” 与 “生产 / broader use 仍 blocked” 分开，避免后续 LLM 把 sample raw storage 或 tracked summary 误读成 DataHub / runner 存储授权。
- 本轮刻意不刷新当前 provider terms、不做 legal conclusion、不抓新数据、不用 `yfinance`、不建 adapter / DataHub、不改 runner、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_license_storage_retention_review_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_license_storage_retention_review_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema tests.schema.test_provider_p1_incident_log_contract_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_license_storage_retention_review.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_license_storage_retention_review_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_license_storage_retention_review_schema` ran 7 tests: 4 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope / rights / blocker tests passed.
- Python313 with `jsonschema`: license-storage-retention review + remaining-blocker plan + incident-log contract tests ran 20 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145.
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**失效旧结论**:

- “FMP stable retry 成功即可进入 production storage / DataHub / runner consumption”不成立；license-storage-retention review 明确只允许已批准两 symbol sample 范围和 tracked no-secret summary。
- “SEC EDGAR public API 可直接扩成 broader reconstruction / production normalized storage”不成立；仍需 parser / fair-access / artifact-retention contract。
- “本轮 artifact 等于 current terms / legal signoff”不成立；artifact 明确没有 current terms web refresh、provider contact 或 legal advice。

**下一步注意事项**:

1. Claude 复审应重点核对 rights matrix 是否没有把 sample storage、tracked summary、SEC public API、FMP stable retry误读成 production storage / derived output / DataHub / runner 授权。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可转向 SEC EDGAR audit parser feasibility / scope contract 或 FMP PIT / observed-date semantics design；current terms legal review、broader sample、provider call、status polling、DataHub 或 runner consumption 仍需 separate explicit approval + reviewed decision。

## 2026-06-02 追加：SEC EDGAR audit parser scope contract

**改了什么**:

- 新增 `schemas/provider_p1_sec_edgar_audit_parser_scope_contract.schema.json`，把未来 SEC EDGAR audit parser 的 audit-only role、lineage requirements、fair-access expectations、artifact policy、decision gates 和 prohibited actions 固化为 schema-first scope contract。
- 新增 `docs/provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json`，只基于既有 reviewed repo artifacts 和 tracked no-secret sample summary 做 scope contract；不做 SEC API call、不读取或解析 raw payload、不实现 parser、不抓数据。
- 新增 `tests/schema/test_provider_p1_sec_edgar_audit_parser_scope_contract_schema.py`，验证 schema/artifact、no-access locks、audit role boundaries、13 个 lineage requirements、fair-access / artifact policy、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 SEC parser scope contract 路由进 Phase 7b-2，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- 上一轮 license-storage-retention review 已把 SEC broader reconstruction 阻断在 parser / fair-access / artifact-retention contract 之前；本轮先定义 parser 能做什么、不能做什么。
- SEC EDGAR 只保留为 fundamentals anomaly audit / FMP cross-check support；本轮明确它不是 price source、strict free-float authority、production fundamentals provider、security master、alpha-validation artifact 或 DataHub source。
- 本轮刻意不调用 SEC、不解析本地 raw payload、不实现 parser、不建 adapter / DataHub、不改 runner、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema tests.schema.test_provider_p1_license_storage_retention_review_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_sec_edgar_audit_parser_scope_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema no-access / boundary / lineage / policy tests passed.
- Python313 with `jsonschema`: SEC parser scope contract + license-storage review + remaining-blocker plan tests ran 22 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145.
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**失效旧结论**:

- “SEC EDGAR public API sample 成功即可 broader reconstruction / parser implementation”不成立；本轮 contract 明确 broader SEC endpoint call、raw parse、parser implementation 均 blocked。
- “SEC parser scope = price source / strict free-float authority / alpha validation / DataHub source”不成立；这些都被 audit role boundaries 排除或阻断。
- “本轮 artifact 证明 parser feasibility at scale”不成立；它只定义 scope 和 gates，不证明 coverage、PIT normalization、free-float reconciliation 或 production readiness。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否没有授权 SEC endpoint calls、raw-payload parsing、parser implementation、DataHub / runner consumption、provider selection 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可转向 FMP PIT / observed-date semantics design，或继续做 SEC parser field-family mapping contract；任何 actual parser implementation 或 SEC call 仍需 separate explicit approval + reviewed decision。

## 2026-06-02 追加：FMP PIT / observed-date semantics contract

**改了什么**:

- 新增 `schemas/provider_p1_fmp_pit_observed_date_semantics_contract.schema.json`，把 FMP stable retry 之后的 PIT / observed-date 语义边界固化为 schema-first contract：field-family historical-use gates、15 个 PIT lineage requirements、no-silent-default policy、decision gates、prohibited actions。
- 新增 `docs/provider_evidence_p1_us_fmp_pit_observed_date_semantics_contract_20260602.json`，只基于既有 reviewed repo artifacts 做 semantics contract；不做 FMP endpoint call、不读取或解析 raw payload、不实现 field mapping、不抓数据。
- 新增 `tests/schema/test_provider_p1_fmp_pit_observed_date_semantics_contract_schema.py`，验证 schema/artifact、no-access locks、two-symbol evidence calibration、6 个 field-family gates、15 个 lineage requirements、latest-only / missing-date blocking、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 FMP PIT / observed-date semantics contract 路由进 Phase 7b-2，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- FMP stable retry 的 `filingDate` / `acceptedDate` 字段存在只证明 AAPL / MSFT 两只活跃样本的 response shape；它不能证明历史 PIT、amendment / restatement、latest/current endpoint as-of semantics、coverage、price adjustment 或 DataHub eligibility。
- 本轮先把 statement / key metrics / profile / EOD price-volume 的历史使用门槛写成可审查契约，避免后续 LLM 把 stable retry 字段存在误读成 provider selection 或 Phase 7c 可用性。
- 本轮刻意不调用 FMP、不解析 ignored raw payload、不实现 field mapping、不建 adapter / DataHub、不改 runner、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_fmp_pit_observed_date_semantics_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_fmp_pit_observed_date_semantics_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema no-access / field-family / lineage / policy tests passed.
- Python313 with `jsonschema`: FMP PIT semantics contract + SEC parser scope contract + remaining-blocker plan targeted schema tests ran 24 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145.
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**失效旧结论**:

- “FMP stable retry 看到 `filingDate` / `acceptedDate` 就可历史 PIT 使用”不成立；本轮 contract 明确 field-level PIT validation、revision / restatement、as-of eligibility 和 latest endpoint exclusion 仍 blocked。
- “FMP profile / key metrics / EOD 字段存在就可进 DataHub / runner”不成立；profile 不具备 filing-observed semantics，key metrics 需证明派生规则，EOD 需另做 adjustment / corporate-action review。
- “本轮 artifact 证明 FMP production readiness”不成立；它只定义 semantics gates，不证明 coverage、license、price adjustment、fallback、stability 或 production readiness。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否没有授权 FMP endpoint calls、raw-payload parsing、field mapping implementation、provider selection、DataHub / runner consumption 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可转向 FMP price-adjustment / corporate-action semantics contract，或 SEC parser field-family mapping contract；任何 actual FMP PIT row validation、FMP call、SEC call、raw parse 或 field-mapping / parser implementation 仍需 separate explicit approval + reviewed decision。

## 2026-06-02 追加：FMP price-adjustment / corporate-action semantics contract

**改了什么**:

- 新增 `schemas/provider_p1_fmp_price_adjustment_corporate_action_semantics_contract.schema.json`，把 FMP stable historical EOD 之后的 price adjustment / corporate-action 语义边界固化为 schema-first contract：8 个 market-data gate families、18 个 price lineage requirements、no-silent-default policy、decision gates、prohibited actions。
- 新增 `docs/provider_evidence_p1_us_fmp_price_adjustment_corporate_action_semantics_contract_20260602.json`，只基于既有 reviewed repo artifacts 做 semantics contract；不做 FMP endpoint call、不读取或解析 raw payload、不计算 returns、不 reconciliation corporate actions、不实现 field mapping、不抓数据。
- 新增 `tests/schema/test_provider_p1_fmp_price_adjustment_corporate_action_semantics_contract_schema.py`，验证 schema/artifact、no-access locks、two-symbol EOD response-shape calibration、8 个 market-data gates、18 个 lineage requirements、adjustment / split / dividend / delisting / missing-session blocking、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 FMP price / corporate-action semantics contract 路由进 Phase 7b-2，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- FMP stable retry 的 historical EOD rows 只在 AAPL / MSFT 两只活跃样本上证明 OHLCV / change / changePercent / VWAP response shape；它不能证明 adjusted-return semantics、split / dividend handling、delisting / inactive coverage、zero-volume / halt behavior、missing-session policy、liquidity validity 或 DataHub eligibility。
- 上一轮 FMP PIT contract 已明确 EOD price-volume 需另做 adjustment / corporate-action review；本轮先把 return / liquidity 使用门槛写成可审查契约，避免后续 LLM 把 EOD 字段存在误读成 provider selection 或 Phase 7c 可用性。
- 本轮刻意不调用 FMP、不解析 ignored raw payload、不计算 returns、不 reconciliation corporate actions、不实现 field mapping、不建 adapter / DataHub、不改 runner、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fmp_price_adjustment_corporate_action_semantics_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_price_adjustment_corporate_action_semantics_contract_schema tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_fmp_price_adjustment_corporate_action_semantics_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_fmp_price_adjustment_corporate_action_semantics_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_fmp_price_adjustment_corporate_action_semantics_contract_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema no-access / market-data gate / lineage / no-silent-default tests passed。
- Python313 with `jsonschema`: FMP price/corporate-action semantics contract + FMP PIT semantics contract + remaining-blocker plan targeted schema tests ran 24 tests, all passed。
- `json.tool` parsed the new schema and artifact successfully。
- `docs/CURRENT.md` line count = 145。
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round。

**失效旧结论**:

- “FMP stable retry 看到 OHLCV / VWAP 字段就可算 historical returns / liquidity”不成立；本轮 contract 明确 adjustment mode、corporate actions、delisting / inactive status、zero-volume / missing-session policy、calendar / timezone 和 liquidity rules 仍 blocked。
- “FMP price/corporate-action contract = actual adjusted-return validation / corporate-action reconciliation”不成立；它只定义 gates，不调用 FMP、不读 raw payload、不算 returns、不 reconciliation corporate actions。
- “本轮 artifact 证明 FMP production readiness”不成立；它不证明 coverage、license、PIT、price adjustment、fallback、stability 或 production readiness，也不关闭 `SR-PROVIDER-001`。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否没有授权 FMP endpoint calls、raw-payload parsing、return calculation、corporate-action reconciliation、field mapping implementation、provider selection、DataHub / runner consumption 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可转向 SEC parser field-family mapping contract 或 coverage-count access-packet planning；任何 actual FMP adjustment validation、corporate-action sample、coverage-count execution、FMP call、SEC call、raw parse 或 field-mapping / parser implementation 仍需 separate explicit approval + reviewed decision。

## 2026-06-02 append: SEC EDGAR field-family mapping contract

**What changed**:

- Added `schemas/provider_p1_sec_edgar_field_family_mapping_contract.schema.json`, a no-access schema-first contract for future SEC EDGAR audit field-family mapping after the SEC audit parser scope contract.
- Added `docs/provider_evidence_p1_us_sec_edgar_field_family_mapping_contract_20260602.json`, based only on existing reviewed repo artifacts. It defines 10 audit field-family gates, 16 parser lineage requirements, FMP cross-check policy, decision gates, and prohibited actions.
- Added `tests/schema/test_provider_p1_sec_edgar_field_family_mapping_contract_schema.py`, covering schema/artifact validation, no-access locks, complete field-family gates, complete lineage gates, cross-check no-silent-default policy, source refs / limitations, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md` to route this contract while keeping `SR-PROVIDER-001` open.

**Why**:

- The SEC parser scope contract already blocked broader SEC reconstruction pending later lineage / parser / fair-access / artifact work. This slice defines the field-family mapping gates without crossing into parser implementation.
- SEC EDGAR remains fundamentals anomaly audit / FMP cross-check support only. The contract explicitly excludes price-source use, strict free-float authority, production fundamentals provider use, security-master use, alpha-validation claims, DataHub source authority, and Phase 7c authorization.
- This round intentionally performs no SEC API call, no raw-payload parse, no fixture generation, no parser implementation, no field-mapping implementation, no provider call, no adapter / DataHub work, no runner change, and no Phase 7c authorization.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_sec_edgar_field_family_mapping_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_sec_edgar_field_family_mapping_contract_schema tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_sec_edgar_field_family_mapping_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_sec_edgar_field_family_mapping_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Bundled Python: `tests.schema.test_provider_p1_sec_edgar_field_family_mapping_contract_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`.
- Python313 with `jsonschema`: SEC field-family mapping contract + SEC parser scope contract + remaining-blocker plan targeted schema tests ran 24 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145.
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**Invalid conclusions**:

- "SEC sample success means SEC parser / mapping can now be implemented" is false. This contract authorizes no SEC call, raw parse, parser implementation, field mapping, fixture generation, or DataHub consumption.
- "SEC EDGAR can replace FMP as production fundamentals provider" is false. SEC remains audit / cross-check support only.
- "This closes `SR-PROVIDER-001`" is false. Actual SEC access, raw-payload retention, minimized fixtures, parser implementation, field mapping, coverage, license / production storage, PIT, price adjustment, fallback execution, stability evidence, provider selection, DataHub, runner consumption, and Phase 7c remain blocked.

**Next-step notes**:

1. Claude review should focus on whether the new contract accidentally authorizes SEC endpoint calls, raw-payload parsing, fixture generation, parser implementation, field-mapping implementation, provider selection, DataHub / runner consumption, alpha-validation claims, ship-gate claims, or Phase 7c.
2. If review passes and the change is committed, the next safe no-access provider slice is coverage-count access-packet planning. Any actual coverage-count execution, FMP call, SEC call, raw parse, fixture generation, field-mapping / parser implementation, provider status polling, adapter, DataHub, runner, or Phase 7c step still requires separate explicit approval + reviewed decision.

## 2026-06-02 append: Coverage-count access-packet plan

**What changed**:

- Added `schemas/provider_p1_coverage_count_access_packet_plan.schema.json`, a no-access schema-first plan for the future US EGS coverage-count access packet.
- Added `docs/provider_evidence_p1_us_coverage_count_access_packet_plan_20260602.json`, based only on existing reviewed repo artifacts. It defines four planned coverage request profiles, fourteen access-packet requirements, eight count metrics, no-silent-default policy, decision gates, and prohibited actions.
- Added `tests/schema/test_provider_p1_coverage_count_access_packet_plan_schema.py`, covering schema/artifact validation, no-execution locks, profile completeness, access-packet requirements, metric / no-silent-default behavior, source refs / limitations, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md` to route the plan while keeping `SR-PROVIDER-001` open.

**Why**:

- The AAPL / MSFT FMP stable retry proves only two-symbol endpoint access / response shape. It does not prove target-universe coverage, missing-field rates, inactive / delisted behavior, or class coverage.
- This slice defines what a later user-approved coverage-count access packet must contain before any provider call or count execution: bounded symbol universe, endpoint families, call budget, time window, rate / retry policy, SEC fair-access if relevant, storage / retention, no-secret summary, raw-payload gitignore proof, metric definitions, pass / fail thresholds, fallback / incident behavior, and explicit manual approval.
- This round intentionally performs no coverage-count execution, no FMP or SEC endpoint calls, no status polling, no data fetch, no raw-payload parsing, no fixture generation, no fallback execution, no incident-log writer implementation, no provider selection, no adapter / DataHub work, no runner change, and no Phase 7c authorization.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_coverage_count_access_packet_plan_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_coverage_count_access_packet_plan_schema tests.schema.test_provider_p1_sec_edgar_field_family_mapping_contract_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_coverage_count_access_packet_plan.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_coverage_count_access_packet_plan_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Bundled Python: `tests.schema.test_provider_p1_coverage_count_access_packet_plan_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`.
- Python313 with `jsonschema`: coverage-count access-packet plan + SEC field-family mapping contract + remaining-blocker plan targeted schema tests ran 24 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully before docs routing updates.

**Invalid conclusions**:

- "FMP stable retry success means coverage is proven" is false. The plan explicitly says two-symbol response shape cannot imply target-universe coverage.
- "This plan authorizes the coverage-count run" is false. It defines the later access packet required before execution; it performs and authorizes no provider call.
- "This closes `SR-PROVIDER-001`" is false. Actual coverage counts, current terms / production storage rights, PIT row validation, price / corporate-action validation, SEC parser implementation, field mapping, fallback execution, stability evidence, provider selection, DataHub, runner consumption, and Phase 7c remain blocked.

**Next-step notes**:

1. Claude review should focus on whether the new plan accidentally authorizes coverage execution, FMP / SEC calls, raw parsing, fixture generation, provider selection, status polling, fallback execution, DataHub / runner consumption, ship-gate claims, or Phase 7c.
2. If review passes and the change is committed, any actual coverage-count packet must be a separate user-approved and reviewed access request with exact symbols, endpoints, call budget, storage, no-secret summary, and pass / fail thresholds.

## 2026-06-02 append: Approved coverage-count execution packet

**What changed**:

- Added `schemas/provider_p1_coverage_count_access_packet_approval.schema.json` and `docs/provider_evidence_p1_us_coverage_count_access_packet_approval_20260602.json`, recording the user's exact approval for a bounded 5-symbol / 30-call FMP stable coverage-count packet.
- Added `runners/us_egs_coverage_count_packet.py`, a narrow runner that validates the approval artifact, reads only the existing `FMP_API_KEY`, calls only FMP stable endpoint families, writes raw payloads under gitignored `provider_samples/us_egs_coverage_count_20260602/fmp_stable/`, and writes a tracked no-secret summary.
- Added `schemas/provider_p1_coverage_count_execution_summary.schema.json` and generated `docs/provider_evidence_p1_us_coverage_count_execution_summary_20260602.json`.
- Added `tests/provider/test_us_egs_coverage_count_packet.py`, `tests/schema/test_provider_p1_coverage_count_access_packet_approval_schema.py`, and `tests/schema/test_provider_p1_coverage_count_execution_summary_schema.py`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md` to route the executed coverage smoke while keeping `SR-PROVIDER-001` open.

**Execution result**:

- Actual packet used 5 active symbols: `AAPL`, `MSFT`, `NVDA`, `JPM`, `XOM`.
- Actual endpoint budget used: 30 / 30 FMP stable calls.
- Result summary: `validation_status = completed`, `endpoint_success_count = 30`, `endpoint_error_count = 0`, `symbol_all_endpoint_success_count = 5`, `statement_observed_date_endpoint_count = 15`, `price_ohlcv_presence_count = 5`.
- Missing-field result: `missing_required_field_count = 15`, from `peRatio`, `revenuePerShare`, and `netIncomePerShare` missing in FMP stable key-metrics responses across the five symbols; no silent default is used.
- Raw payloads are ignored by `.gitignore:50 provider_samples/`; tracked summary contains no API key, request URL, bearer token, or raw rows.

**Why**:

- The no-access coverage-count plan required exact symbols, endpoint families, call budget, storage, no-secret summary, thresholds, and explicit manual approval before execution.
- The user explicitly said `批准并执行`, so this slice records the approval boundary and executes only that bounded packet.
- The result is deliberately a coverage smoke, not provider selection or production readiness.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.provider.test_us_egs_coverage_count_packet -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_coverage_count_access_packet_approval_schema tests.schema.test_provider_p1_coverage_count_execution_summary_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\us_egs_coverage_count_packet.py
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_coverage_count_access_packet_approval_schema tests.schema.test_provider_p1_coverage_count_execution_summary_schema tests.provider.test_us_egs_coverage_count_packet -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_coverage_count_execution_summary_20260602.json
git check-ignore -v provider_samples\us_egs_coverage_count_20260602\fmp_stable\raw\financial_modeling_prep\AAPL\profile_or_company_metadata.json
Select-String -Path docs\provider_evidence_p1_us_coverage_count_execution_summary_20260602.json -Pattern "apikey=|FMP_API_KEY|Bearer |financialmodelingprep.com" -CaseSensitive
```

**Validation results**:

- Bundled Python provider runner tests: 4 tests passed.
- Bundled Python schema tests: 10 tests ran; 3 passed, 7 skipped because this interpreter lacks `jsonschema`.
- Python313 actual packet: completed; 30/30 endpoint calls succeeded; secrets_logged = false.
- Python313 jsonschema + provider tests: 14 tests passed.
- `json.tool` parsed the execution summary.
- `git check-ignore -v` confirmed raw payloads are covered by `.gitignore:50 provider_samples/`.
- Secret / URL scan of the tracked summary returned no matches.

**Invalid conclusions**:

- "30/30 FMP stable calls mean FMP is selected" is false.
- "This proves full US universe, inactive, delisted, or survivorship-safe coverage" is false.
- "This authorizes Phase 7c, DataHub, adapter, runner consumption, or production storage" is false.
- "Missing key-metrics fields can be silently defaulted" is false; they are recorded as blockers.

**Next-step notes**:

1. Claude review should verify the approval boundary, runner scope, raw gitignore proof, tracked no-secret summary, schema tests, and that `SR-PROVIDER-001` remains open.
2. Any broader FMP / SEC endpoint call, current terms review, production storage decision, PIT row validation, price-adjustment / corporate-action validation, SEC parser implementation, fixture generation, fallback execution, provider selection, adapter, DataHub table, runner consumption, or Phase 7c work still requires separate explicit approval and reviewed decision.

## 2026-06-02 append: Missing key-metrics resolution plan

**What changed**:

- Added `schemas/provider_p1_missing_key_metrics_resolution_plan.schema.json`, a no-access schema-first plan for the three FMP stable key-metrics fields missing in the approved coverage-count summary.
- Added `docs/provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json`, based only on the tracked no-secret coverage summary and existing reviewed repo artifacts. It classifies `peRatio`, `revenuePerShare`, and `netIncomePerShare` as potentially derivable only after separate field-presence and lineage review.
- Added `tests/schema/test_provider_p1_missing_key_metrics_resolution_plan_schema.py`, covering schema/artifact validation, no-access locks, exact missing-field count, candidate derivation status, no-silent-default policy, decision gates, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md` to route the plan while keeping `SR-PROVIDER-001` open.

**Why**:

- The coverage-count smoke found 30/30 FMP stable endpoint successes but also 15 missing key-metrics fields: `peRatio`, `revenuePerShare`, and `netIncomePerShare` missing across AAPL / MSFT / NVDA / JPM / XOM.
- These fields may be derivable from price, statement, and share-count inputs, but the repo must not silently compute them without PIT-safe field presence, formula, denominator, fiscal-period, unit / currency, restatement, and price-adjustment lineage.
- This slice intentionally performs no provider call, no raw-payload parse, no fixture generation, no derivation implementation, no field mapping, no return calculation, no corporate-action reconciliation, no provider selection, no DataHub / runner change, and no Phase 7c authorization.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_missing_key_metrics_resolution_plan_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_missing_key_metrics_resolution_plan_schema tests.schema.test_provider_p1_coverage_count_execution_summary_schema tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_missing_key_metrics_resolution_plan.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Invalid conclusions**:

- "Missing key-metrics fields can be silently computed" is false. Any derivation needs reviewed field-presence and lineage evidence.
- "The resolution plan authorizes raw-payload parsing" is false. Reading existing ignored raw payloads or making fresh provider calls still requires separate explicit approval and reviewed scope.
- "This closes `SR-PROVIDER-001`" is false. Direct ratio availability, safe derivation, current terms / production storage, field-level PIT, price adjustment, SEC parser work, fallback / stability, provider selection, DataHub, runner consumption, and Phase 7c remain blocked.

**Next-step notes**:

1. Claude review should verify that the plan is no-access and does not authorize raw-payload parsing, derivation implementation, field mapping, provider selection, DataHub / runner consumption, ship-gate claims, or Phase 7c.
2. If review passes and the change is committed, the next concrete missing-field step would need a separate user-approved field-presence / lineage packet before any raw parsing or fresh endpoint calls.

## 2026-06-02 append: A-short screening threshold governance parity

**What changed**:

- Added `schemas/a_short_screening_threshold_governance.schema.json`, a schema-first governance contract for A-share short screening thresholds.
- Added `presets/a_short_screening_threshold_governance_20260602.json`, mirroring 13 current literal `A-EGS/egs_main.py::CONF` screening thresholds into a governed preset artifact.
- Updated `presets/a_short.yaml` with a flat `screening_threshold_governance` route to the artifact, source code ref, and parity test.
- Added `tests/schema/test_a_short_screening_threshold_governance_schema.py`, which statically parses `A-EGS/egs_main.py` with AST and asserts exact artifact/code parity without importing EGS or requiring `TUSHARE_TOKEN`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `presets/README.md`, and `docs/system_risk_register.md`; `SR-GOV-001` is resolved.

**Why**:

- `SR-GOV-001` tracked that production-relevant A-short screening thresholds lived only in `A-EGS/egs_main.py::CONF` while `presets/a_short.yaml` still said detailed thresholds would be filled later.
- This slice takes the smaller safe closure path allowed by the risk entry: assert preset / artifact / code parity under test instead of migrating runtime threshold loading now.
- This round intentionally performs no screening run, no research / backtest run, no provider call, no data fetch, no `A-EGS/egs_main.py` runtime change, no DataHub / adapter implementation, no ship-gate claim, and no broker / order automation.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_a_short_screening_threshold_governance_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_a_short_screening_threshold_governance_schema tests.schema.test_datahub_local_resource_budget_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\a_short_screening_threshold_governance.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool presets\a_short_screening_threshold_governance_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Invalid conclusions**:

- "The runtime now loads thresholds from YAML" is false. Current runtime still reads `A-EGS/egs_main.py::CONF`; this slice only adds a reviewed parity gate.
- "This changes candidate selection / scoring / output" is false. `A-EGS/egs_main.py` was not modified.
- "This authorizes provider access, research, DataHub, Phase 7c, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify that the artifact exactly mirrors current `CONF` values and that the test does not import or run `A-EGS/egs_main.py`.
2. Any future runtime preset-loader migration or threshold behavior change must be a separate reviewed slice with behavior-preservation tests.

## 2026-06-02 append: DataHub job spec contract

**What changed**:

- Added `schemas/datahub_job_spec.schema.json`, a Phase 7c precondition schema for future DataHub / runner job specs.
- Added `schemas/examples/datahub_job_spec.example.json`, a schema-only, non-executable example that declares `local_interactive_default`, one market, one lane, one as-of date, resource estimates, lazy / incremental / checkpoint / abort policy, data boundaries, and approval gates.
- Added `tests/schema/test_datahub_job_spec_schema.py`, covering schema/example validation, no-runtime scope locks, budget profile, partition scope, resource estimates, execution policy, approval gates, and scope-creep rejection.
- Updated `docs/datahub_design.md`, `docs/README.md`, `docs/CURRENT.md`, `AGENTS.md`, `docs/system_risk_register.md`, and `docs/datahub_local_resource_budget_contract_20260602.json` to route the job-spec contract while keeping `SR-RESOURCE-001` open.

**Why**:

- The local resource budget contract already required future reviewed job specs, but it did not define the job-spec shape.
- This slice adds the missing schema-first bridge without implementing DataHub, changing runners, or executing any broad job.
- `SR-RESOURCE-001` remains open because future executable DataHub / runner jobs still need code-level enforcement and tests.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_datahub_job_spec_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_job_spec_schema tests.schema.test_datahub_local_resource_budget_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\datahub_job_spec.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\examples\datahub_job_spec.example.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\datahub_local_resource_budget_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Bundled Python: `tests.schema.test_datahub_job_spec_schema` ran 8 tests; non-jsonschema boundary tests passed; jsonschema-dependent checks skipped in this interpreter (`skipped=8` due skipped subtests).
- Python313 with `jsonschema`: `tests.schema.test_datahub_job_spec_schema` + `tests.schema.test_datahub_local_resource_budget_schema` ran 14 tests, all pass.
- `json.tool` parsed the new schema, new example, and updated resource-budget contract artifact.
- `docs/CURRENT.md` line count remained 149.
- `git diff --check` exited 0 with only normal LF/CRLF working-copy warnings.

**Invalid conclusions**:

- "SR-RESOURCE-001 is closed" is false; code-level enforcement does not exist yet.
- "This authorizes Phase 7c implementation" is false.
- "This authorizes provider calls, raw-payload parsing, DataHub tables, runner changes, production runner consumption, full-system runs, or ship-gate claims" is false.

**Next-step notes**:

1. Claude review should verify the new schema/example do not authorize provider access, data fetch, raw parse, full-market refresh, DataHub implementation, runner changes, production consumption, Phase 7c, or ship-gate claims.
2. A future Phase 7c implementation slice must make executable job specs validate against `schemas/datahub_job_spec.schema.json` and enforce the budget / partition / abort policy in code before `SR-RESOURCE-001` can close.

## 2026-06-02 append: DataHub job-spec guardrail hardening

**What changed**:

- `schemas/datahub_job_spec.schema.json` now rejects partition scopes where `market=A` is paired with `us_*` lanes or `market=US` is paired with `a_*` lanes.
- `schemas/datahub_local_resource_budget.schema.json` now caps `budget_profiles[].max_concurrent_lanes` at 2.
- `docs/datahub_local_resource_budget_contract_20260602.json` fixes the limitation reference from `SR-PROVIDER-001` to `SR-RESOURCE-001`.
- `docs/system_risk_register.md` keeps `SR-RESOURCE-001` open but updates mitigation / required-next-action / verification text for market-lane consistency and reviewed lane-concurrency bounds.

**Validation results**:

- Python313 with `jsonschema`: `tests.schema.test_datahub_job_spec_schema` + `tests.schema.test_datahub_local_resource_budget_schema` passed as part of the 30-test forward-live / DataHub suite.
- Bundled Python non-jsonschema checks passed where available; jsonschema-dependent checks skipped in that interpreter.
- `json.tool` parsed both DataHub schemas and the resource-budget contract artifact.
- `git diff --check` exited 0 with only normal LF/CRLF working-copy warnings.

**Invalid conclusions**:

- "The job-spec schema accepts cross-market lane mismatches" is now false.
- "The resource-budget schema has no upper bound for `max_concurrent_lanes`" is now false.
- "SR-RESOURCE-001 is closed" remains false; executable code-level enforcement is still required before Phase 7c / runner implementation.

## 2026-06-02 append: P3 hygiene slice after Phase 6-to-now audit

**What changed**:

- `runners/materialize_benchmark_monthly_returns_tushare.py` now skips boundary months with fewer than two usable `index_daily` rows into metadata `skipped_months` when other months remain usable; fully unusable ranges still raise.
- `runners/forward_tracker.py` now excludes terminal forward statuses from the pending backfill mask and filters work rows by that same mask.
- `runners/backtest_rank.py` now leaves close-to-close diagnostic return empty when the actual as-of bar close / adj_factor is missing, without blocking primary `t1` / `t1_net`.
- `runners/us_egs_sample_validation.py` removed an unused `sys` import and checks endpoint-call budget before each fetch in the approved legacy small-sample and stable retry paths.
- `runners/aggregate_execution_reports.py` collapsed a dead `report_total_return_for_aggregation` branch without behavior change.

**Validation results**:

- Python313: `tests.execution.test_materialize_benchmark_monthly_returns_tushare`, `tests.phase6.test_forward_tracker_cache_guard`, `tests.test_backtest_rank_phase3`, `tests.provider.test_us_egs_sample_validation`, and `tests.execution.test_aggregate_execution_reports` ran 48 tests, all pass.
- Python313: `tests.provider.test_us_egs_coverage_count_packet` ran 4 tests, all pass.
- `git diff --check` exited 0 with only normal LF/CRLF working-copy warnings.
- `rg --files -g 'tmp*' -g '!provider_samples/**'` returned no output.

**Invalid conclusions**:

- "This changes provider authorization, Phase 7c, DataHub, production runner consumption, ship-gate policy, or full-size permission" is false.
- "This closes `SR-PROVIDER-001` or `SR-RESOURCE-001`" is false; both remain open by design.

## 2026-06-03 append: Provider validation authorization packet

**What changed**:

- `schemas/provider_p1_validation_authorization_packet.schema.json` defines the machine-checkable authorization boundary for a future bounded US EGS provider validation packet.
- `docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json` records the user's FMP Basic confirmation and authorization for existing FMP key + SEC EDGAR public API, $0 spend, 5-10 symbols, max 60 calls, active symbols plus inactive / delisted candidates if supported, gitignored raw storage, tracked no-secret summary, and validation-only raw parsing for PIT row / price adjustment / corporate-action / SEC parser / SEC field-mapping / field-presence feasibility.
- `tests/schema/test_provider_p1_validation_authorization_packet_schema.py` validates the new schema / artifact, boundary locks, validation-only permissions, pre-execution gates, prohibited claims, and scope-creep rejection.
- `docs/provider_evidence_drift_monitor.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/system_risk_register.md`, and `AGENTS.md` now route the new packet as the active `SR-PROVIDER-001` authorization boundary for a later reviewed execution packet.

**Validation results**:

- Python313: `json.tool` parsed `schemas/provider_p1_validation_authorization_packet.schema.json` and `docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json`.
- Python313: `tests.schema.test_provider_p1_validation_authorization_packet_schema` ran 8 tests, all pass.
- Python313: adjacent provider schema regression suite ran 34 tests, all pass: sample-validation approval, coverage-count approval / summary, missing key-metrics resolution plan, and the new validation authorization packet.
- `docs/CURRENT.md` line count is 149.

**Invalid conclusions**:

- "This slice executed FMP or SEC calls" is false; it executed no provider calls and created no `provider_samples/` files.
- "This authorizes provider selection, adapter, DataHub, runner consumption, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.
- "FMP Basic is production license clearance" is false; it is only the user-confirmed plan boundary for a later bounded validation packet.
- "SR-PROVIDER-001 is closed" is false; the authorization narrows one approval blocker but leaves current terms, production storage, PIT, price adjustment, corporate action, SEC parser / field mapping, fallback, stability, and production-readiness evidence open.

**Next-step notes**:

1. Claude review should verify that the new schema/artifact allows only the authorized future 5-10 symbol / max 60 call / FMP Basic existing-key / SEC public-API validation packet and does not silently authorize implementation.
2. A future execution slice may consume this authorization only through a reviewed execution packet that fixes exact symbols, endpoints, call budget, raw storage subdir, no-secret summary fields, environment precheck, SEC fair-access handling, gitignore proof, and abort behavior.
3. Any scope beyond this authorization still requires separate explicit approval and reviewed decision.

## 2026-06-03 append: Provider validation execution packet

**What changed**:

- Added `schemas/provider_p1_validation_execution_packet.schema.json`, a schema-first execution-packet contract that consumes the 2026-06-03 provider validation authorization without executing it.
- Added `docs/provider_evidence_p1_us_validation_execution_packet_20260603.json`, fixing the later packet to `AAPL`, `MSFT`, `JPM`, `TWTR`, and `SIVB`, 41 planned calls, zero retries, gitignored raw path `provider_samples/us_egs_validation_packet_20260603/`, tracked no-secret summary, environment precheck, and abort-on-scope-violation gates.
- Added `tests/schema/test_provider_p1_validation_execution_packet_schema.py`, validating schema/artifact shape, exact sample, endpoint family boundaries, zero-call split/dividend candidate families, storage / secret gates, prohibited claims, and scope-creep rejection.
- Updated `docs/provider_evidence_drift_monitor.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/system_risk_register.md`, and `AGENTS.md` to route the execution packet through `SR-PROVIDER-001`.

**Why**:

- The prior authorization packet allowed a future bounded validation run but intentionally did not fix the exact sample / endpoint families / call budget.
- This slice records the execution packet for review before any provider call, preserving the project rule that provider work must be exact-scope, reviewed, no-secret, and manually approved.
- The packet intentionally leaves FMP split / dividend endpoint families at zero calls because no reviewed current FMP corporate-action endpoint template exists in repo evidence; execution must record that blocker unless a later reviewed mapping resolves it.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_validation_execution_packet.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_validation_execution_packet_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_validation_execution_packet_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_validation_authorization_packet_schema tests.schema.test_provider_p1_validation_execution_packet_schema tests.schema.test_provider_p1_missing_key_metrics_resolution_plan_schema -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Invalid conclusions**:

- "This slice executed FMP or SEC calls" is false; it records no provider calls and creates no `provider_samples/` files.
- "Corporate actions are now validated" is false; split / dividend endpoint families are zero-call blocked pending reviewed template mapping.
- "This authorizes provider selection, adapter, DataHub, runner consumption, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify that the execution packet exactly consumes the authorization boundary and still requires a later execute command before network access.
2. If review passes and the change is committed, a later `执行` may run only this exact five-symbol / 41-call packet after environment, gitignore, budget, no-secret, and fair-access prechecks.
3. Any broader symbols, retries, FMP split / dividend endpoint call, implementation, DataHub, Phase 7c, or production claim requires separate explicit approval and reviewed decision.

## 2026-06-03 append: Provider validation execution summary

**What changed**:

- Added `runners/us_egs_validation_packet.py`, a narrow runner that consumes only the reviewed validation execution packet, validates the fixed symbol / endpoint / budget / storage / environment / no-secret boundary, requires explicit review + execute confirmations, and writes raw payloads only under gitignored `provider_samples/us_egs_validation_packet_20260603/`.
- Added `schemas/provider_p1_validation_execution_summary.schema.json` and `tests/schema/test_provider_p1_validation_execution_summary_schema.py` for the tracked no-secret summary.
- Added `tests/provider/test_us_egs_validation_packet.py`, covering fake-client FMP / SEC calls, no-secret summary, SEC CIK skip behavior, missing-env abort-before-fetch, live confirmation gates, and raw-root restriction.
- Executed the reviewed packet after the user's post-review `执行`; generated `docs/provider_evidence_p1_us_validation_execution_summary_20260603.json`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Execution result**:

- Actual calls: 37/41 within budget; 30 FMP stable calls + 7 SEC public calls; zero retries.
- Endpoint outcomes: 32 successes, 5 FMP SIVB HTTP 402 endpoint errors, 6 skips.
- Skips: FMP split / dividend candidate families remain zero-call blocked pending current template review; TWTR / SIVB SEC submissions and companyfacts were skipped because SEC company-tickers mapping did not yield CIKs for those symbols.
- Field-presence clues: active AAPL / MSFT / JPM had all six FMP stable families successful and SEC submissions / companyfacts successful; TWTR had all six FMP stable families successful but no SEC follow-up; SIVB had only FMP profile success and five FMP stable endpoint errors.
- Tracked summary contains no secret, request URL, or raw rows; raw payloads stayed under gitignored `provider_samples/us_egs_validation_packet_20260603/`.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_validation_execution_summary_schema tests.provider.test_us_egs_validation_packet tests.schema.test_provider_p1_validation_execution_packet_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_validation_execution_summary_20260603.json
git diff --check
```

**Invalid conclusions**:

- "The provider validation packet is still unexecuted" is false after this slice.
- "The validation summary selects FMP, authorizes DataHub / Phase 7c, proves inactive / delisted coverage, proves PIT / price adjustment / corporate actions at scale, or supports production / ship-gate evidence" is false.
- "Corporate-action endpoint calls were made" is false; split / dividend families remain zero-call blocked.

**Next-step notes**:

1. Claude review should verify the runner / summary schema / generated summary / docs all preserve the fixed packet scope, no-secret boundary, raw gitignore boundary, and `SR-PROVIDER-001` open status.
2. Future provider work should route from the recorded SIVB FMP endpoint errors, TWTR / SIVB SEC CIK gaps, missing key-metrics direct fields, and still-blocked split / dividend endpoint template review.
3. Do not broaden symbols, endpoints, retries, yfinance, full-market fetches, current terms review, implementation, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence without separate explicit approval and reviewed decision.

## 2026-06-03 append: Inactive / delisted gap resolution plan

**What changed**:

- Added `schemas/provider_p1_inactive_delisted_gap_resolution_plan.schema.json`, a no-access schema for routing the TWTR / SIVB inactive-delisted coverage gap found by the provider validation execution summary.
- Added `docs/provider_evidence_p1_us_inactive_delisted_gap_resolution_plan_20260603.json`, consuming only the tracked no-secret validation summary and existing reviewed contracts.
- Added `tests/schema/test_provider_p1_inactive_delisted_gap_resolution_plan_schema.py`, covering schema / artifact validation, scope locks, exact TWTR / SIVB gap facts, no-silent-default rules, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Why**:

- The first real validation run showed mixed inactive-delisted behavior: TWTR returned all six FMP stable endpoint families but no SEC CIK follow-up; SIVB returned only FMP profile and five FMP HTTP 402 errors, also with no SEC CIK follow-up.
- Those facts are useful, but they must not become a silent coverage pass. The plan splits the blocker into FMP Basic entitlement / endpoint behavior, SEC historical CIK or symbol lookup, security-master source review, alternate-provider or paid-access decision, and a future bounded follow-up packet if the user approves it.
- This slice performs no FMP call, SEC call, raw-payload read / parse, fixture generation, security-master implementation, field mapping, provider selection, DataHub work, Phase 7c authorization, production-readiness claim, alpha evidence, or ship-gate claim.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_inactive_delisted_gap_resolution_plan.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_inactive_delisted_gap_resolution_plan_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_inactive_delisted_gap_resolution_plan_schema -v
git diff --check
```

**Invalid conclusions**:

- "TWTR FMP success proves inactive / delisted coverage" is false.
- "SIVB HTTP 402 can be treated as ordinary missing rows or a safe default" is false.
- "SEC company-tickers misses prove TWTR / SIVB do not exist or that SEC can be used as a historical security master" is false.
- "This plan authorizes another provider call, raw-payload inspection, security-master implementation, provider selection, DataHub, Phase 7c, production readiness, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify this is a no-access plan that uses only the tracked validation summary and keeps `SR-PROVIDER-001` open.
2. Any follow-up inactive / delisted call, raw-payload inspection, SEC historical CIK lookup, security-master source review, paid-access decision, alternate-provider review, DataHub work, or Phase 7c work requires separate explicit approval and reviewed packet / decision.

## 2026-06-03 append: FMP entitlement / corporate-action no-access diagnostic

**What changed**:

- Added `schemas/provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic.schema.json`, a no-access schema for the FMP Basic entitlement / SIVB 402 / split-dividend endpoint-template diagnostic.
- Added `docs/provider_evidence_p1_us_fmp_entitlement_corporate_action_no_access_diagnostic_20260603.json`, using official FMP public docs plus existing tracked validation evidence and existing gitignored SIVB 402 wrappers; no new provider call was made.
- Updated `runners/us_egs_sample_validation.py` so future non-JSON HTTP error bodies are preserved inside gitignored raw wrappers, while tracked summaries still exclude response bodies, request URLs, and secrets.
- Added schema and runner regression tests for scope locks, SIVB 402 hypothesis classification, split / dividend template candidates, no-silent-default policy, and non-JSON HTTP error body capture.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Why**:

- The previous inactive / delisted plan correctly routed SIVB 402 but could not classify whether it was Basic entitlement, SIVB-specific lifecycle behavior, historical / delisted tiering, or transient / quota behavior.
- FMP public docs identify current stable `splits` and `dividends` endpoint templates, so the split / dividend blocker is no longer "template unknown"; it is now "template identified, not called, not entitlement-cleared, not reconciled".
- SIVB 402 is not converted into a paid-wall conclusion or a missing-data default. TWTR success refutes a universal "delisted symbols always unsupported" claim and narrows the problem to SIVB / endpoint-family behavior.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_fmp_entitlement_corporate_action_no_access_diagnostic_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic_schema tests.provider.test_us_egs_sample_validation -v
git diff --check
```

**Invalid conclusions**:

- "SIVB 402 means paid wall" is unproven and prohibited as a direct conclusion.
- "SIVB 402 can be treated as missing data / zero / drop symbol" is false.
- "FMP split / dividend templates are identified, therefore corporate-action evidence is validated" is false; no split / dividend endpoint call, return calculation, or reconciliation was performed.
- "This diagnostic authorizes SIVB re-probe, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify the artifact uses only docs + existing evidence, keeps the SIVB 402 classification open, and leaves `SR-PROVIDER-001` open.
2. A real SIVB re-probe requires a separate reviewed execution packet: SIVB only, the five failed endpoint families only, max 5 calls, zero retry, $0, existing FMP key, gitignored raw capture, tracked no-secret summary, then a later user `执行`.
3. Any split / dividend endpoint call or corporate-action reconciliation also requires separate explicit approval and reviewed decision.

## 2026-06-03 append: SIVB-only FMP 402 re-probe execution packet

**What changed**:

- Added `schemas/provider_p1_sivb_reprobe_execution_packet.schema.json`, a const-locked schema for a future SIVB-only FMP 402 re-probe execution packet.
- Added `docs/provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json`, fixing `SIVB` as the only symbol, the five previously failed FMP endpoint families only, max 5 endpoint calls, zero retry, `$0`, existing FMP key only, gitignored raw body capture, tracked no-secret summary, and review / execute gates.
- Added `tests/schema/test_provider_p1_sivb_reprobe_execution_packet_schema.py`, covering schema validation, SIVB-only scope, exact endpoint families, budget / retry locks, raw / summary boundaries, classification strategy, no-silent-default policy, prohibited claims, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Why**:

- The entitlement diagnostic established that SIVB 402 remains an open hypothesis set and that a useful re-probe must capture the provider's non-JSON error body in gitignored raw storage.
- This packet turns that future call into a reviewable contract before any network access, avoiding silent broadening into active symbols, SEC calls, split / dividend calls, provider selection, DataHub, or Phase 7c.
- The future summary is constrained to category signals only: endpoint entitlement, symbol lifecycle, historical / delisted paid tier, or transient quota / provider incident. It cannot copy body text, request URLs, raw rows, or secrets.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_sivb_reprobe_execution_packet.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_sivb_reprobe_execution_packet_schema -v
git diff --check
```

**Invalid conclusions**:

- "The SIVB re-probe has run" is false.
- "This packet proves why SIVB returned HTTP 402" is false.
- "This packet authorizes active symbols, SEC calls, split / dividend calls, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.
- "The future summary may store response body text or request URLs" is false.

**Next-step notes**:

1. Claude review should verify this artifact is a contract only, with no provider call, no raw read, no runner implementation, and `SR-PROVIDER-001` still open.
2. If review passes and this slice is committed, a later user `执行` may run only the fixed SIVB-only / five-FMP-family / five-call / zero-retry packet.
3. Any broader provider work still requires separate explicit approval and reviewed decision.

## 2026-06-03 append: SIVB-only FMP 402 re-probe execution summary

**What changed**:

- Added `runners/us_egs_sivb_reprobe_packet.py`, a narrow runner that consumes only the reviewed SIVB packet, validates the fixed symbol / endpoint / budget / storage / environment / no-secret boundary, requires explicit review + execute confirmations, and writes raw payloads only under gitignored `provider_samples/us_egs_sivb_reprobe_20260603/`.
- Added `schemas/provider_p1_sivb_reprobe_execution_summary.schema.json` and `docs/provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json` for the tracked no-secret execution summary.
- Added `tests/provider/test_us_egs_sivb_reprobe_packet.py` and `tests/schema/test_provider_p1_sivb_reprobe_execution_summary_schema.py`, covering fake 402 body capture, summary body / URL / secret exclusion, exact SIVB-only URL scope, confirmation gates, missing-env abort-before-fetch, schema validation, and scope-creep rejection.
- Executed the reviewed packet after the user's post-review `执行`; updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Execution result**:

- Actual calls: 5/5 FMP stable calls, SIVB only, zero SEC calls, zero retries.
- Endpoint outcomes: 0 successes, 5 HTTP 402 errors across the five fixed endpoint families.
- Body capture: 5/5 non-JSON bodies captured only under gitignored raw wrappers; tracked summary contains no body text, request URL, raw rows, or secret.
- Category signal: weak `historical_or_delisted_paid_tier` across the five endpoint families. This is not paid-wall proof, not inactive / delisted coverage proof, and not provider readiness.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_sivb_reprobe_execution_summary.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\us_egs_sivb_reprobe_packet.py --dry-run-env
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\us_egs_sivb_reprobe_packet.py --confirm-independent-review-pass --confirm-post-review-execute
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.provider.test_us_egs_sivb_reprobe_packet tests.schema.test_provider_p1_sivb_reprobe_execution_summary_schema -v
```

**Invalid conclusions**:

- "SIVB 402 is now proven paid-wall" is false.
- "Inactive / delisted coverage is proven" is false.
- "This authorizes SEC calls, split / dividend calls, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.
- "Tracked summary may store response body text or request URLs" is false.

**Next-step notes**:

1. Claude review should verify the runner / summary schema / generated summary / docs preserve the five-call boundary, raw gitignore boundary, no-secret summary boundary, weak category-signal wording, and `SR-PROVIDER-001` open status.
2. Future provider work should not rerun or broaden SIVB silently. Any broader inactive / delisted follow-up, FMP split / dividend endpoint call, current terms review, provider selection, DataHub, or Phase 7c work requires separate explicit approval and reviewed decision.

## 2026-06-03 append: FMP paid-tier / license public-docs review

**What changed**:

- Added `schemas/provider_p1_fmp_paid_tier_license_public_docs_review.schema.json`, a const-locked schema for a public-docs-only FMP pricing / endpoint / license review.
- Added `docs/provider_evidence_p1_us_fmp_paid_tier_license_public_docs_review_20260603.json`, recording FMP public pricing-plan, endpoint-doc, and Terms signals without API calls, signup, purchase, trial, account changes, provider contact, raw reads, provider selection, DataHub, Phase 7c, production-readiness, legal-clearance, or ship-gate claims.
- Added `tests/schema/test_provider_p1_fmp_paid_tier_license_public_docs_review_schema.py`, covering schema validation, source refs, plan observations, endpoint-template observations, terms observations, no-route-selection boundaries, no-silent-default policy, prohibited claims, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Plain result**:

- FMP Basic remains usable only for the narrow active-symbol evidence already proven; it does not cover SIVB or complete inactive / delisted needs.
- Paid FMP may help because public pages show higher history / feature tiers, but public pages do not prove SIVB access or inactive / delisted coverage.
- Public Terms review does not clear local raw retention, DataHub storage, redistribution, or legal use.
- No provider route was selected.

**Why**:

- SIVB re-probe narrowed the gap to a subscription / historical-or-delisted signal, but not enough to decide provider or paid tier.
- The earlier 2026-06-02 license-storage review did not perform a current public-terms web refresh; this fills that public-docs gap without replacing user / legal judgment.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_fmp_paid_tier_license_public_docs_review.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_fmp_paid_tier_license_public_docs_review_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_paid_tier_license_public_docs_review_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
git diff --check
```

**Invalid conclusions**:

- "Paid FMP is proven to fix SIVB" is false.
- "Public pricing / endpoint docs prove inactive-delisted coverage" is false.
- "Public Terms review clears storage / license / legal use" is false.
- "This authorizes paid upgrade, API calls, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify this slice is public-docs only, keeps all scope locks false, and leaves `SR-PROVIDER-001` open.
2. Any paid upgrade, account change, provider contact, API call, raw parse, provider selection, DataHub, or Phase 7c work requires separate explicit approval and reviewed decision.

## 2026-06-03 append: temporary US free-data working boundary

**What changed**:

- Current working posture is cost-saving and temporary: no buying / adding specialized US delisted data for now.
- This is not a final provider or spending decision; the user may later buy / connect EODHD, Norgate, Sharadar, paid FMP, or another source.
- Updated `AGENTS.md`, `docs/CURRENT.md`, `docs/system_risk_register.md`, and `docs/SESSION_LOG.md`.

**Plain result**:

- US work may continue with FMP Basic / SEC EDGAR only as exploration, paper, minimal-size, or live-normalized forward-evidence accumulation.
- US historical backtests with inactive / delisted, PIT, price-adjustment, corporate-action, and license / storage gaps are reference-only.
- They cannot prove alpha, support full-size manual use, authorize DataHub / Phase 7c / production readiness, or count as ship-gate evidence.
- A-share 35% / US 65% capital policy remains unchanged. Unvalidated US allocation stays in US cash / paper / minimal buckets unless the user explicitly makes a manual transfer decision.
- Revisit trigger: when a US idea shows forward-live promise, or when the user asks.

**Next-step notes**:

1. Future LLMs must not use free-data US historical backtests to justify full-size US sizing.
2. Any paid data, specialized source, provider selection, DataHub, or Phase 7c work still requires separate explicit approval and reviewed decision.

## 2026-06-03 append: Phase 7c-a DataHub job-spec runtime enforcement

**What changed**:

- Added `engine/datahub/job_spec_contract.py` as the code-level pre-execution validator for future DataHub / runner / report job specs.
- Added `engine/datahub/__init__.py`.
- Added `tests/schema/test_datahub_job_spec_contract.py`, covering the schema example, reviewed executable plans, heavy-run approval, resource-budget profile matching, market/lane mismatch, bounded date windows, blocking gates, scope-creep rejection, resource-budget lane-concurrency bounds, and non-mutation.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/datahub_design.md`, `docs/system_risk_register.md`, and `docs/SESSION_LOG.md` to route the helper.

**Plain result**:

- Future executable DataHub / runner / report jobs must call `validate_datahub_job_spec_contract` or `validate_datahub_job_spec_file` before running.
- This closes the current `SR-RESOURCE-001` code-level enforcement gap.
- It still does not fetch provider data, select a provider, create DataHub tables, implement adapters, change production runners, authorize Phase 7c broad implementation, prove local-machine capacity, or count as ship-gate evidence.
- `SR-PROVIDER-001` remains open.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_job_spec_contract tests.schema.test_datahub_local_resource_budget_schema tests.schema.test_datahub_job_spec_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Python313 DataHub suite: 27 tests, all pass.
- Python313 full unittest discover: 551 tests, all pass.
- `docs/CURRENT.md` line count = 149.
- `git diff --check` passed with only normal LF/CRLF working-copy warnings.

**Invalid conclusions**:

- "Phase 7c DataHub implementation is done" is false.
- "US provider data can now feed DataHub / runner" is false.
- "Full-market / all-lane / full-refresh local jobs are default-allowed" is false.
- "This closes `SR-PROVIDER-001`" is false.

**Next-step notes**:

1. Claude review should verify that the helper cannot be bypassed by future executable job specs in documented routing, and that the helper rejects provider calls, DataHub table implementation authorization, runner changes, production consumption, all-market / all-lane / full-refresh behavior, raw writes, and ship-gate claims.
2. After review and commit, the natural next Phase 7c slice is still implementation-design for the shared layer / report contracts / reproducibility plumbing. It must consume this helper and cannot use unresolved US provider evidence as production input.

## 2026-06-03 append: Phase 7c shared-layer / report / reproducibility contract batch

**What changed**:

- Added `schemas/datahub_shared_layer_contract.schema.json` and `docs/datahub_shared_layer_contract_20260603.json`.
- Added `schemas/datahub_report_contract.schema.json` and `docs/datahub_report_contract_20260603.json`.
- Added `schemas/datahub_reproducibility_manifest.schema.json` and `docs/datahub_reproducibility_manifest_contract_20260603.json`.
- Added `tests/schema/test_datahub_phase7c_contract_batch.py`, validating all three schemas/artifacts, ODS / DWD / DWS / factor coverage, report-family coverage, reproducibility requirements, no-secret / no-raw policies, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, and `docs/datahub_design.md`.

**Plain result**:

- DataHub now has the next schema-first baseline: what shared layers are allowed to contain, what reports must say / must not say, and what a future reproducibility manifest must record.
- This is still not a DataHub implementation. No table was created, no report generator was implemented, no manifest writer was implemented, no runner was changed, and no provider data was consumed.
- Future executable DataHub / runner / report work must still create a reviewed job spec and pass `engine/datahub/job_spec_contract.py` before running.
- `SR-PROVIDER-001` remains open; US provider data is still not production usable.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_phase7c_contract_batch -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_phase7c_contract_batch tests.schema.test_datahub_job_spec_contract tests.schema.test_datahub_local_resource_budget_schema tests.schema.test_datahub_job_spec_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Python313 target test: 6 tests, all pass.
- Python313 DataHub suite: 33 tests, all pass.
- Python313 full unittest discover: 557 tests, all pass.
- `docs/CURRENT.md` line count = 149.
- `git diff --check` passed with only normal LF/CRLF working-copy warnings.

**Invalid conclusions**:

- "Phase 7c implementation is done" is false.
- "DataHub tables / reports / manifest writer now exist" is false.
- "US provider data can now feed DataHub or reports" is false.
- "This authorizes production runner consumption, ship-gate evidence, or full-size sizing" is false.

**Next-step notes**:

1. Claude review should treat this as one coherent batch: three schema-first DataHub contracts plus routing docs and tests.
2. After review and commit, the next natural Phase 7c slice is data-quality monitor contract or a reviewed implementation-design packet for one minimal local A-share-only DataHub read path. Any executable implementation still needs a job spec and must not use unresolved US provider evidence.

## 2026-06-03 append: Phase 7c data-quality monitor + minimal A-share read-path planning batch

**What changed**:

- Added `schemas/datahub_data_quality_monitor_contract.schema.json` and `docs/datahub_data_quality_monitor_contract_20260603.json`.
- Added `schemas/datahub_minimal_a_share_read_path_plan.schema.json` and `docs/datahub_minimal_a_share_read_path_plan_20260603.json`.
- Added `tests/schema/test_datahub_data_quality_and_minimal_read_path_contracts.py`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/datahub_design.md`, and `docs/SESSION_LOG.md`.

**Plain result**:

- DataHub now has a schema-first quality gate: future outputs cannot silently pass if coverage, freshness, PIT/as-of, survivorship, corporate-action, calendar, incident, or outlier checks are missing or failing.
- The first future read-path is intentionally small: A-share short lane, one as-of day, local cache / fixture only, reviewed job spec, job-spec helper pass, manifest, and data-quality summary.
- This is still not a DataHub implementation. It does not run a monitor, read cache, call Tushare/FMP/SEC, create tables, change runners, authorize production use, or provide ship-gate evidence.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_data_quality_and_minimal_read_path_contracts -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_data_quality_and_minimal_read_path_contracts tests.schema.test_datahub_phase7c_contract_batch tests.schema.test_datahub_job_spec_contract tests.schema.test_datahub_local_resource_budget_schema tests.schema.test_datahub_job_spec_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Python313 target test: 5 tests, all pass.
- Python313 DataHub suite: 38 tests, all pass.
- Python313 full unittest discover: 562 tests, all pass.
- `docs/CURRENT.md` line count = 149.
- `git diff --check` passed with only normal LF/CRLF working-copy warnings; targeted secret scan found only no-secret field names and schema URLs.

**Invalid conclusions**:

- "DataHub quality monitor is implemented" is false.
- "A-share local read-path has run" is false.
- "Provider / Tushare data can now feed DataHub" is false.
- "This authorizes production runner consumption, ship-gate evidence, or full-size sizing" is false.

**Next-step notes**:

1. Claude review should verify all scope locks stay false and that the minimal read-path plan cannot become a provider/Tushare/full-market job by schema mutation.
2. After review and commit, the next natural Phase 7c slice is a separate reviewed implementation packet for the minimal A-share local-cache read path. Any execution still needs a reviewed job spec and must pass `engine/datahub/job_spec_contract.py`.

## 2026-06-03 append: US active-only + forward-validation operating model

**Plain result**: the current US model is active-only universe + live-normalized forward evidence only. US historical backtests are exploration / idea-only and never count as alpha, ship-gate, full-size, DataHub, or production evidence.

**Boundary**: inactive / delisted historical coverage is user-accepted as scoped out for now, not proven solved. Forward universes must be frozen point-in-time at the forward start date, and real halt / delisting / merger / no-trade outcomes during forward validation must be captured. `SR-PROVIDER-001` remains open for license / storage, active PIT if fundamentals are used, active price / corporate-action semantics if used, SEC parser / mapping if used, fallback / stability, provider selection, DataHub / runner consumption, and production readiness.

## 2026-06-03 append: A-short steady alpha re-audit preregistration

**What changed**:

- Added `schemas/a_short_steady_alpha_reaudit_preregistration.schema.json`.
- Added `research/preregistrations/a_short_steady_alpha_reaudit_20260603.json`.
- Added `research/ledgers/a_short_steady_alpha_reaudit_program_test_budget_ledger_20260603.json`.
- Extended `schemas/program_test_budget_ledger.schema.json` so `a_short_steady` can use a planned-test ledger with zero spent tests.
- Added `tests/schema/test_a_short_steady_alpha_reaudit_preregistration_schema.py`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`, `docs/system_risk_register.md`, `research/README.md`, and `docs/SESSION_LOG.md`.

**Plain result**:

- A-short steady alpha is still not proven.
- The next test is frozen: check whether the old 5d CSI1000 clue survives same-anchor correction.
- The future run must also report 20d / CSI300 and check multiple testing, monthly / stock concentration, regime slices, factor exposure, veto/filter usefulness, and PIT / survivorship.
- This slice does not run the result. It only registers the plan and planned-test budget.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_a_short_steady_alpha_reaudit_preregistration_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_a_short_steady_alpha_reaudit_preregistration_schema tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Python313 target test: 8 tests, all pass.
- Python313 target + research regression: 33 tests, all pass.
- Python313 full unittest discover: 570 tests, all pass.
- `docs/CURRENT.md` line count = 148.
- `git diff --check` passed with only normal LF/CRLF working-copy warnings.
- New-file sensitive-pattern scan found no API key, request URL, secret, or credentials text.

**Invalid conclusions**:

- "A-short steady alpha is validated" is false.
- "The outcome run has been authorized" is false.
- "A-short steady can now be full-size" is false.
- "This authorizes DataHub, provider work, runner changes, production use, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify the preregistration is scoped to A-short steady, not a hidden burst rescue or parameter search.
2. If review passes and the user later gives `执行`, run only the frozen same-anchor re-audit on existing local evidence and write a research-only evidence report.

## 2026-06-03 append: A-short steady alpha re-audit outcome repair

**Plain result**:

- The old 5d CSI1000 clue did not survive the repaired same-anchor statistical gate.
- A-short steady remains risk-filter-only / research reference, not alpha evidence.
- It cannot support full-size manual use or ship-gate evidence.

**What changed**:

- Added `runners/a_short_steady_alpha_reaudit.py`.
- Added `tests/test_a_short_steady_alpha_reaudit_runner.py`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/evidence_report.json`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/diagnostics.json`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/monthly_stats.csv`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/metric_summary.csv`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/stock_concentration.csv`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/veto_filter_stats.csv`.
- Updated `research/ledgers/a_short_steady_alpha_reaudit_program_test_budget_ledger_20260603.json` from planned to spent.
- Updated `AGENTS.md`, `docs/CURRENT.md`, `docs/README.md`, `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`, `docs/system_risk_register.md`, `docs/phase7a_alpha_plausibility_audit.json`, `research/README.md`, and `docs/SESSION_LOG.md`.

**Key numbers**:

- 5d CSI1000 true same-anchor net excess mean: `0.6158673222` pp.
- 5d CSI1000 monthly clustered t-stat: `1.7623850474`.
- Old uncorrected 5d CSI1000 monthly t-stat: `2.8769227582`.
- Positive months: 14/23.
- Bonferroni-normal adjusted p: `0.3120170532`.
- 20d CSI1000 monthly t-stat: `-0.0994154668`.
- 5d CSI300 monthly t-stat: `0.9291247792`.

**Important limitation**:

- `runners/a_short_steady_alpha_reaudit.py` now re-derives benchmark entry-open to exit-close returns from local `forward_daily.pkl`; old `rank_samples.csv` excess columns are uncorrected controls only.
- `SR-ALPHA-001` is resolved for this clue because the repaired test failed before promotion; any future candidate still needs preregistered regime / factor checks.

**Invalid conclusions**:

- "A-short steady alpha is proven" is false.
- "The old uncorrected 5d t-stat can be treated as same-anchor evidence" is false.
- "A-short steady can be full-size" is false.
- "This is ship-gate evidence" is false.
- "This authorizes DataHub, provider work, runner consumption, strategy rule changes, or parameter rescue" is false.

**Next-step notes**:

1. Claude review should verify this repaired outcome used the local benchmark-open cache, did not fetch data, rerun EGS, alter production outputs, or overclaim sizing.
2. After review and commit, do not rerun this result. Any new alpha search needs a new reviewed preregistration and user approval.

## 2026-06-03 append: A-long data-integrity audit preregistration

**Plain result**:

- Current active alpha-search route is A-long only.
- A-short 5d is not rescued; it remains risk-filter-only / forward-observation-only after the repaired same-anchor test failed its statistical gate.
- A-long must pass hard data-integrity checks and declare a usable signal-search window before any signal-search preregistration can be created.

**What changed**:

- Added `schemas/a_long_data_integrity_audit_preregistration.schema.json`.
- Added `research/preregistrations/a_long_data_integrity_audit_20260603.json`.
- Added `research/ledgers/a_long_data_integrity_audit_program_test_budget_ledger_20260603.json`.
- Extended `schemas/program_test_budget_ledger.schema.json` with `a_long_data_integrity`.
- Added `tests/schema/test_a_long_data_integrity_audit_preregistration_schema.py`.
- Updated `AGENTS.md`, `docs/CURRENT.md`, `docs/README.md`, `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`, `docs/strategy_design_synthesis.md`, `docs/long_alpha_spec.md`, `docs/provider_data_requirements_audit.md`, `docs/system_risk_register.md`, `research/README.md`, and `docs/SESSION_LOG.md`.

**Frozen audit checks**:

1. Frozen schedule + runner self-tests: monthly last A-share trading day `2018-01-31..2025-12-31`; future runner must prove planted violations fire before trusting real output.
2. PIT fundamentals: Tushare `income`, `balancesheet`, `fina_indicator`; `ann_date > as_of` tolerance = 0 hard fail; missing / invalid `ann_date` is excluded and reported, not a global hard fail.
3. Restatement / revision as-of: same `ts_code + end_date` may use only the version known at the as-of date.
4. PIT universe / survivorship: no replaying today's active list / constituents into history; later delisted or suspended names must not be silently removed from eligible historical periods, and held delisting terminal returns must be captured.
5. Return / benchmark measurement: dividend + `adj_factor` total return, frozen qfq/hfq treatment, same entry/exit anchors, same-anchor benchmark excess, terminal delisting returns, no silent zero fill.
6. Temporal coverage: yearly required fundamental-table coverage is characterized to declare the usable start year; sparse early years do not globally fail the lane.

**Invalid conclusions**:

- "A-long alpha search is authorized" is false.
- This preregistration slice did not run the audit; see the later execution append below for the now-run blocked result.
- "A-long data is proven clean" is false.
- "This permits production / ship-gate / full-size use" is false.

**Next-step notes**:

1. Claude review should verify this is an executable hard-check + usable-window preregistration, not another descriptive contract.
2. Superseded by the later execution append below: the frozen data-integrity audit has now run and is blocked.
3. If any hard check fails or blocks, repair the data route before any signal backtest. If hard checks pass in a future repaired audit, create a separate reviewed A-long signal-search preregistration limited to the declared usable window.

## 2026-06-03 append: A-long data-integrity audit execution

**Plain result**:

- The frozen audit ran local-cache-only after Claude review and user `执行`.
- `research/results/a_long_data_integrity_audit_20260603/audit_report.json` is `blocked_missing_required_source`.
- Self-tests passed 6/6, so the runner can catch planted bad data.
- Real local data is not enough: raw PIT fundamentals, full PIT universe, dividend / total-return handling, and terminal delisting return lineage are missing.
- A-long signal search is still not authorized.

**What changed**:

- Added `runners/a_long_data_integrity_audit.py`.
- Added `schemas/a_long_data_integrity_audit_report.schema.json`.
- Added `tests/test_a_long_data_integrity_audit_runner.py`.
- Wrote `research/results/a_long_data_integrity_audit_20260603/audit_report.json`, `check_summary.csv`, and `coverage_by_year.csv`.
- Updated the A-long ledger to `active_no_new_test_authorized` with status `spent_voided_by_data_integrity_failure`.

**Next-step notes**:

1. Do not rerun the spent A-long data audit without a new reviewed authorization.
2. Repair or replace the A-long data route first: raw PIT fundamentals with `ann_date` / `end_date`, full PIT universe, dividend / total-return treatment, and terminal delisting return lineage.
3. Only after a repaired data route passes a new reviewed audit may A-long create a separate signal-search preregistration.
