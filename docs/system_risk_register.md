# System Risk Register

Status: Active

Owner role: tracked queue for material security, data, PIT, schema, execution, and cross-LLM process risks that are not fixed immediately in the same reviewed slice.

This file exists to prevent audit findings from living only in chat. `docs/SESSION_LOG.md` records reasoning and review verdicts; this register records the durable open-risk queue. Do not use it as authorization to batch-fix everything at once. Each fix still follows `docs/AI_REVIEW_PROTOCOL.md`.

## Enforcement Rules

- Every material review or audit finding that affects data integrity, PIT safety, schema contract, execution simulation, security, ship-gate evidence, or cross-LLM continuity must be either fixed in the same reviewed slice or entered here before the round ends.
- `执行` must check this register before choosing the next task. Open P0 items outrank normal roadmap work unless the user explicitly approves a narrower override.
- `审查` must verify that new material findings were either fixed or registered here, and that resolved entries include concrete verification.
- `修复` may update this register only for approved Required fixes or Optional dispositions being handled in that repair round.
- A risk entry is not closed by intent. Closure requires file / test evidence and a reviewed commit or an explicit accepted-risk decision from the user.

## Status And Severity

Severity:
- P0: blocks the next unsafe execution path or can contaminate evidence / official outputs.
- P1: high risk before broader implementation, provider work, long-lane work, or production-like use.
- P2: medium risk; must be queued and fixed before the affected subsystem is promoted.
- P3: low risk or documentation hygiene.

Status:
- `open`: accepted for tracking; not fixed.
- `in_progress`: current reviewed change is addressing it.
- `blocked`: needs user decision or external dependency.
- `resolved`: fixed and verified.
- `superseded`: replaced by more specific open / resolved entries; the underlying risk is not fixed merely because the parent summary was split.
- `accepted_risk`: user explicitly accepted the residual risk.
- `needs_revalidation`: audit claim is plausible enough to track, but line-level repo validation is still required before implementation.

## Hot Queue

Current routing note: the corrected-basis A-share burst preregistration failed a frozen-cohort preflight with `valid_signal_events = 0`; do not run outcome / benchmark-excess for that artifact. The ledger-gated full-universe redesigned test used the patched benchmark-open cache, then failed its registered outcome thresholds with `decision = falsified_or_redesign_required`. Owner audit/spec now mark `a_share_burst_minimal_data` as `redesign_required`. No further redesigned A-share burst test is authorized without a new ledger planned test, user approval, and reviewed preregistration. For US EGS data, the reviewed AAPL / MSFT sample-validation packet has run under the user's $0 approval: SEC EDGAR succeeded, but FMP v3 endpoint families returned HTTP 403 legacy-endpoint errors. A docs-only mapping review identified current FMP stable endpoint candidates, and the same-scope AAPL / MSFT stable retry returned 12/12 HTTP 200 with no secrets in the tracked summary. The remaining-blocker plan routes coverage, license / storage, PIT, price-adjustment, SEC audit, fallback / stability, and production-readiness blockers without authorizing new access; the fallback / incident / stability playbook now defines default-deny design behavior; the incident-log contract now defines future incident record shape. These no-access artifacts do not authorize status polling, fallback execution, provider calls, log-writer implementation, storage / retention, or implementation. This closes only the current-endpoint access / response-shape sub-blocker for two symbols and narrows playbook / incident-log design sub-blockers; `yfinance`, full-market fetch, paid upgrade, provider selection, adapters, DataHub, runner consumption, Phase 7c, and production-readiness claims remain blocked by `SR-PROVIDER-001`.

1. `SR-DATA-004` - Maintenance watch item before affected subsystem promotion; requires real weekly suspend-coverage logs.
2. `SR-PROVIDER-001` - Use the remaining-blocker plan, fallback playbook, and incident-log contract before any provider work: coverage, license / storage rights, PIT semantics, incident-log writer, executed fallback / incident behavior, stability evidence, and production-readiness evidence remain required before any new token / trial / paid access / `yfinance` check / full-market fetch / provider status polling / provider selection / adapter / DataHub / runner consumption / Phase 7c use.

## Entries

### SR-RESOURCE-001 - DataHub broad jobs lack code-level local resource budget enforcement

- Severity: P2
- Status: open
- Owner phase: Phase 7c DataHub / local execution stability
- Evidence: `docs/datahub_design.md` accepts a future shared DataHub for four subsystems, but before this reviewed slice there was no contract requiring slice-first local execution, partitioned reads, lazy materialization, incremental cache reuse, checkpoint / resume, or explicit user approval before all-market / all-lane / full-refresh jobs.
- Accepted calibration: this is not proof that the user's machine cannot run the system. The intended operating mode does not require all four systems to run at once. The risk is future implementation drift: a DataHub or runner slice could accidentally make full-system refresh the default and overload local execution or make review / debugging unstable.
- Mitigation evidence: this reviewed slice adds `schemas/datahub_local_resource_budget.schema.json` and `docs/datahub_local_resource_budget_contract_20260602.json`, and routes them through `docs/datahub_design.md`, `docs/README.md`, `docs/CURRENT.md`, `AGENTS.md`, and the Phase 7 handoff. The contract requires default `single_slice_incremental` behavior and blocks default all-system / all-market / all-lane / full-refresh runs.
- Required next action: before any Phase 7c DataHub table, adapter, runner, or report job implementation, enforce the contract in code / job specs with tests that require budget profile, market, lane, `as_of_date` or date window, estimated input / output sizes, cache policy, checkpoint / abort behavior, and explicit approval for heavy runs.
- Verification: `tests.schema.test_datahub_local_resource_budget_schema` validates the schema / artifact, default slice-first behavior, budget profiles, implementation gates, and scope-creep rejection.

### SR-META-001 - Audit findings were not durably tracked

- Severity: P0
- Status: resolved
- Owner phase: process / cross-LLM workflow
- Evidence: before this register, repo routing had `CURRENT.md` and `SESSION_LOG.md` entries for measurement-basis only; no tracked vulnerability / risk ledger existed.
- Accepted calibration: measurement-basis lock was necessary but did not capture the wider audit backlog.
- Closure evidence: commit `4e88b7c Add system risk register enforcement` added this register and routed it from `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, and `docs/AI_REVIEW_PROTOCOL.md`.

### SR-MEASURE-001 - Benchmark excess entry-anchor mismatch

- Severity: P0
- Status: resolved
- Owner phase: alpha measurement integrity / A-share burst research
- Evidence: current A-share burst preregistration is `BLOCKED_DO_NOT_RUN`; `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` requires stock T+1 open and benchmark T+1 open to the same exit close.
- Accepted calibration: old 5d `excess_csi1000` is measurement-contaminated / uncorrected, not proven false.
- Closure evidence: the reviewed change set updates `runners/backtest_rank.py` so benchmark excess requires benchmark `open` and `close`, fetches CSI1000 / CSI300 `index_daily` with `trade_date,open,close`, ignores close-only cached benchmark frames, and computes benchmark return from benchmark T+1 entry-date open to the same exit-date close. It updates `runners/materialize_benchmark_monthly_returns_tushare.py` to request / validate index open and compute monthly compatibility returns from first open to last close.
- Verification: `tests.test_backtest_rank_phase3` covers same-anchor benchmark excess and rejects close-only benchmark fallback; `tests.execution.test_materialize_benchmark_monthly_returns_tushare` covers `index_daily` open fields, first-open / last-close monthly returns, and open/close validation; `tests.schema.test_research_preregistration_schema` validates the corrected-basis superseding preregistration and proves it changed only the measurement basis, not thresholds / universe / holding period / criteria / test budget.

### SR-EXEC-001 - Historical weekly screening can contaminate official outputs

- Severity: P0
- Status: resolved
- Owner phase: A-short operation / Phase 6b maintenance
- Evidence: `runners/weekly_screening.ps1` calls `A-EGS/egs_main.py --as-of $AsOf` without `--l3-mode`; `A-EGS/egs_main.py` defaults `--l3-mode` to `today` and writes official `result/a_short/<trade_date>/` outputs by default.
- Accepted calibration: `pit` lookup itself uses the effective as-of date after `set_asof`; the risk is the weekly script defaulting to `today` for historical `-AsOf` and allowing official-output overwrite.
- Closure evidence: the reviewed change set updates `runners/weekly_screening.ps1` so historical `-AsOf` runs must pass `-L3Mode pit` or `-L3Mode neutralize`, reject `-L3Mode today`, pass `--l3-pit-strict` for PIT mode, and refuse to overwrite existing `result/a_short/<AsOf>/` or `A-EGS/Result/egs_*_<AsOf>` official outputs without `-AllowHistoricalOverwrite`.
- Verification: `tests.phase6.test_weekly_screening_guardrails` covers missing historical L3 mode, rejected historical `today` mode, existing official-output overwrite refusal, and strict PIT argument wiring.

### SR-PIT-001 - PIT invariants are not enforceable in the root input contract

- Severity: P1
- Status: resolved
- Owner phase: Phase 7c DataHub / report contract precondition; long-lane blocker
- Evidence: `schemas/analysis_input.schema.json` has `trade_date` and L3 metadata but cannot express `ann_date <= trade_date` for fundamentals, cannot compare `source.l3_snapshot_date <= trade_date`, and does not require PIT snapshot presence when `source.l3_mode = pit`.
- Accepted calibration: `A-EGS/egs_main.py` currently filters `fina_indicator.ann_date <= TODAY_DT`; the risk is contract-level non-enforcement and future producer regression, not proof of current look-ahead.
- Required next action: no active `SR-PIT-001` action. Future `analysis_input` date-bearing fundamentals fields must be added to the adjunct validator or to a schema version that can enforce the same PIT boundary.
- Closure evidence: the reviewed change set adds `engine/data/analysis_input_contract.py`, which validates the payload against `schemas/analysis_input.schema.json` and applies adjunct PIT invariants that JSON Schema cannot express: `source.l3_mode = pit` requires `source.l3_snapshot_date`, rejects snapshots after `trade_date`, and rejects `candidate.fundamental.expectation.earnings_report_date` after `trade_date`.
- Verification: `tests.schema.test_analysis_input_contract` covers valid payload validation, schema-required-field rejection, missing PIT snapshot rejection, future PIT snapshot rejection, and future earnings-report-date rejection.

### SR-CONTRACT-001 - Producer and consumer do not validate `analysis_input` against schema

- Severity: P1
- Status: resolved
- Owner phase: Phase 1 / Phase 4 contract hardening
- Evidence: `A-EGS/egs_main.py` writes `analysis_input.json` without jsonschema validation; `runners/run_analysis_report.py` loads `analysis_input` and validates only its own output report.
- Accepted calibration: `build_data_health` performs some bespoke checks, but it is not equivalent to schema validation at producer and consumer boundaries.
- Required next action: no active `SR-CONTRACT-001` action. Any new `analysis_input` producer / consumer should call the shared contract validator at its boundary.
- Closure evidence: `A-EGS/egs_main.py:export_analysis_input` now validates `analysis_input` before writing it, and `runners/run_analysis_report.py:load_analysis_input` now validates the file on read through the shared contract helper. `requirements.txt` declares `jsonschema>=4.0` as a mandatory runtime validation dependency, with `requirements-dev.txt` including it.
- Verification: `tests.phase6.test_egs_analysis_input_contract` covers producer-side rejection before write and valid exported payload validation. `tests.skill.test_run_analysis_report` covers consumer-side valid load, malformed payload rejection, and future PIT snapshot rejection. `tests.schema.test_analysis_input_contract` locks the runtime dependency declaration.

### SR-CONTRACT-002 - Forward-live evidence artifact lacks a schema-first contract

- Severity: P2
- Status: resolved
- Owner phase: Phase 6 forward evidence / Phase 5 aggregate ship-gate contract
- Evidence: `runners/aggregate_execution_reports.py` v1.1.x correctly requires `--forward-live-evidence-ref` as a necessary ship-gate input and v1.1.2 additionally blocks `full_size_allowed` until capacity / concurrency-adjusted returns are evaluable, but the referenced forward-live evidence artifact is still validated only inline for `review_status == "reviewed"` and non-negative integer `forward_live_months`. No `schemas/forward_live_evidence.schema.json` contract yet defines provenance fields such as reviewer, source window, tracker artifact ref, captured-month basis, or review lineage.
- Accepted calibration: this is not an active blocker because no 12-month forward-live artifact exists yet and SR-EXEC-006's inline validation closes the current smoke / bare-CLI gate bug. It becomes material before any real Phase 6 forward-live evidence artifact is produced or used for aggregate full-size permission.
- Closure evidence: the reviewed change set adds `schemas/forward_live_evidence.schema.json` v1.0.0 and `schemas/examples/forward_live_evidence.example.json`, requiring reviewed live-normalized evidence, source window, captured-month basis, tracker artifact refs, review lineage, actual-position reconciliation, and manual-only / no-full-size-by-artifact scope locks. `runners/aggregate_execution_reports.py` now validates `--forward-live-evidence-ref` against that schema before using `forward_live_months`; `execution_aggregate_report` is bumped to v1.1.3 to document the bound evidence-ref contract.
- Verification: `tests.schema.test_forward_live_evidence_schema` validates schema meta, the example, reviewed / live-normalized / reconciliation locks, and required tracker refs. `tests.execution.test_aggregate_execution_reports` rejects the old ad hoc two-field forward evidence JSON and accepts schema-valid reviewed evidence while preserving the concurrency not-evaluable gate. `tests.schema.test_execution_aggregate_report_schema` validates v1.1.3 and its new forward-live evidence schema reference.
- Required next action: no active `SR-CONTRACT-002` action. Before a real 12-month forward-live artifact is produced, fill the schema-required provenance, review, tracker refs, and actual-position reconciliation with real reviewed artifacts; do not use the example as evidence.

### SR-SEC-001 - Broad local Claude Bash allow rules

- Severity: P1
- Status: resolved
- Owner phase: local AI tooling security
- Evidence: root `.claude/settings.local.json` allows broad `Bash(python *)`; `A-EGS/.claude/settings.local.json` allows `Bash(python -c ' *)`. These files are local and currently untracked.
- Accepted calibration: this is local automation exposure, not repository business-code behavior.
- Closure evidence: the reviewed change set narrows ignored local Claude settings. Root `.claude/settings.local.json` removes `Bash(python *)` and `Bash(pip install *)`, leaving only `Bash(pip show *)` plus the fixed-path PowerShell listing rule. `A-EGS/.claude/settings.local.json` removes `Bash(python -c ' *)`, leaving only concrete `egs_main.py` and log-writing rules. Both local settings files were restored to read-only after editing.
- Verification: both settings files parse as JSON; `Select-String` finds no remaining `Bash(python *)`, `Bash(python -c`, or `Bash(pip install` allow rules; `git check-ignore -v` confirms both files are ignored local settings under `.gitignore:75`.
- Required next action: no active `SR-SEC-001` action. Future broad local automation allow rules should be rejected or re-entered in this register.

### SR-RESEARCH-001 - Corrected A-share burst preregistration has zero valid signal events

- Severity: P0
- Status: resolved
- Owner phase: A-share burst research / alpha-validation preflight
- Evidence: `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json` evaluated the frozen 20240131-20251231 generated cohorts against `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`. It found 360 total rows, 305 Tier1 rows, 301 rows after hard filters, 17 `pct_5d >= 6.0` rows, 38 amount-expansion rows, 7 breakout rows, and 0 rows satisfying all three preregistered burst signals. The preregistered `valid_signal_events >= 30` gate fails before any return / benchmark outcome can be informative.
- Accepted calibration: this is not proof that a future redesigned A-share burst universe has no alpha. It proves only that the current steady Tier1 watchlist universe cannot test the frozen all-pass burst trigger. The current corrected-basis preregistration is spent as `failed_preflight_zero_signal_events`; changing universe, entry flags, Tier2 inclusion, breakout definition, thresholds, or signal conjunction is a new promotion-relevant degree of freedom.
- Required next action: resolved for event-count routing. Do not run outcome / benchmark-excess calculation for the current corrected-basis preregistration. Any new redesigned hypothesis still requires a ledger append and reviewed preregistration before it runs.
- Closure evidence: `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json` and its ledger planned test were reviewed / committed; `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json` records a pre-outcome preflight pass with `valid_signal_events = 134`; subsequent `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json` records `decision = falsified_or_redesign_required` under the registered outcome thresholds.

### SR-DATA-003 - Corrected same-anchor burst test needs benchmark open input

- Severity: P1
- Status: resolved
- Owner phase: A-share burst research input / benchmark measurement / forward-tracker cache guard
- Evidence: `result/a_short/backtest/cache/forward_daily.pkl` predates the same-anchor fix and stores `benchmarks.csi300` / `benchmarks.csi1000` with only `trade_date,close`. `runners/backtest_rank.py` now requires benchmark `trade_date,open,close`; missing benchmark open makes `_benchmark_returns` return `None`, while naïve cache refresh would refetch the full stock / limit / benchmark forward surface.
- Additional forward-tracker evidence: before this slice, `runners/forward_tracker.py:_check_cache_coverage` read only `forward_daily.pkl` metadata date range and was blind to benchmark `open` / `close` fields. It could return `ok`, then `forward_tracker.py:backfill` called `fetch_forward_daily(..., refresh=False)`, which rejected close-only benchmark frames through `runners/backtest_rank.py:_benchmark_frame_has_same_anchor_fields` and refetched the shared forward surface. That bypassed the tracker comment that backfill must not trigger a universe-wide Tushare refetch on its own, and the user did not see the intended `[SKIP]` / hint path.
- Accepted calibration: this was the active input blocker before the full-universe redesigned A-share burst preregistration could compute outcome / excess returns. The benchmark-open input is now patched locally, and the subsequent outcome / benchmark-excess slice used the patched cache and failed its registered thresholds.
- Required next action: resolved for benchmark-open input. No further action is required for `SR-DATA-003` unless the local benchmark-open cache is invalidated or a new reviewed research test explicitly requires a different benchmark input.
- Closure evidence: `runners/forward_tracker.py:_check_cache_coverage` rejects cached benchmark frames lacking same-anchor `trade_date/open/close`; `runners/refresh_forward_daily_benchmark_open_tushare.py` provides the benchmark-only cache patch path; `tests/phase6/test_forward_tracker_cache_guard.py` and `tests/phase6/test_refresh_forward_daily_benchmark_open_tushare.py` cover close-only rejection, benchmark-only patching, dry-run non-mutation, and post-patch cache reuse without refetch. On 2026-06-01, `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\refresh_forward_daily_benchmark_open_tushare.py --dry-run` and then the same command without `--dry-run` fetched only CSI300 / CSI1000 `index_daily` `trade_date/open/close` for `20240131..20260228`. Readback of ignored local `result/a_short/backtest/cache/forward_daily.pkl` shows stock rows `2681523`, limit rows `3513895`, both benchmark frames as 498 rows with columns `trade_date/open/close`, and `meta.benchmark_open_patch.update_method = benchmark_only_index_daily_open_close_patch`; a mocked-provider check proved `fetch_forward_daily(['20240131'], 5, refresh=False)` reuses the cache without provider refetch.

### SR-PROVIDER-001 - US EGS data-source direction is not access authorization

- Severity: P1
- Status: open
- Owner phase: Phase 7b / US provider access and Phase 7c precondition
- Evidence: the user has stated no US data source is currently enabled and accepted the US EGS source direction of FMP as primary candidate plus SEC EDGAR as fundamentals audit source. `docs/provider_evidence_drift_monitor.md` §15 records that `yfinance` is only an optional low-trust price smoke check and cannot replace EDGAR for fundamentals validation. On 2026-06-02 the user approved a $0 small-sample boundary: use the current FMP account / API key, allow SEC EDGAR public APIs, allow local storage of small samples and validation results, only a few symbols, no full-market download, and no paid upgrade. That boundary is recorded in `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json`. The sample packet `docs/provider_evidence_p1_us_sample_validation_summary_20260602.json` ran 17 endpoint calls, kept raw payloads under gitignored `provider_samples/us_egs_sample_validation_20260602/`, logged no secrets, found SEC EDGAR company-ticker mapping / submissions / companyfacts success for AAPL and MSFT, and found HTTP 403 legacy-endpoint errors on all sampled FMP v3 endpoint families. The docs-only mapping review `docs/provider_evidence_p1_us_fmp_current_endpoint_mapping_review_20260602.json` identifies current FMP stable endpoint candidates for the failed endpoint families. The same-scope retry summary `docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json` records 12 FMP stable endpoint calls for AAPL / MSFT, all HTTP 200, within budget, with raw payloads only under ignored `provider_samples/us_egs_sample_validation_20260602/fmp_stable_retry/` and no secrets or request URLs in the tracked summary. `docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json` routes the remaining coverage, license / storage, PIT, price-adjustment, SEC audit, fallback / stability, and production-readiness blockers without authorizing new access. `docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json` defines no-access default-deny fallback / incident / stability behavior, and `docs/provider_evidence_p1_us_incident_log_contract_20260602.json` defines future incident-log record shape, but neither executes fallback, polls status pages, fetches data, creates log storage, implements a writer, or implements anything.
- Accepted calibration: the approval, SEC sample run, FMP mapping review, FMP stable retry, remaining-blocker plan, fallback playbook, and incident-log contract prove only a narrow two-symbol access / response-shape sample plus routing, default-deny design, and future-record contract artifacts. They do not prove FMP coverage, license sufficiency, PIT semantics, local-storage / retention rights beyond the approved small sample, SEC parser feasibility at scale, free-float reconciliation, incident-log writer behavior, executable fallback behavior, provider stability, or production readiness. They also do not authorize `yfinance`, full-market fetch, provider status polling, provider selection, adapters, DataHub tables, runner consumption, Phase 7c, or ship-gate claims.
- Required next action: do not rerun or broaden the sample silently. Use `docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json`, `docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json`, and `docs/provider_evidence_p1_us_incident_log_contract_20260602.json` as routing sources; any new token, trial, paid access, `yfinance` check, full-market download, provider status polling, provider selection, adapter, DataHub table, runner consumption, fallback execution, incident-log writer implementation, or Phase 7c use requires separate explicit approval and reviewed decision. Remaining P1 provider work must address coverage / license / PIT / incident-log writer / executable fallback / stability evidence before implementation can consume FMP.

### SR-DATA-001 - Suspend inference can silently drop tradable stocks on partial daily response

- Severity: P1
- Status: resolved
- Owner phase: A-short weekly operation / Phase 6b maintenance
- Evidence: `A-EGS/egs_main.py:get_suspend_info` computes `suspended = all_codes - traded_codes` from single-day `pro.daily` responses and later `filter_l0` removes that set from candidates. There is no row-count / completeness sanity check before treating missing `daily` rows as suspended stocks.
- Accepted calibration: this is a real wrong-output path, but the trigger is a partial `pro.daily` bulk response. Frequency is not proven and is expected to be low; impact is silent and high when it fires. It does not block corrected 5d revalidation if that revalidation uses frozen historical generated cohorts and does not rerun `A-EGS/egs_main.py`.
- Required next action: resolved for the suspend-inference path. No further action is required for `SR-DATA-001` unless the suspend source / daily completeness policy is redesigned.
- Closure evidence: the reviewed change set updates `A-EGS/egs_main.py:get_suspend_info` to validate non-empty `pro.daily` payloads against `suspend_daily_min_coverage = 0.95` before inferring `suspended = all_codes - traded_codes`; below-threshold partial responses now raise instead of silently filtering candidates. The suspend cache key is bumped to `suspend_<date>_v2` so old unvalidated suspend-inference caches are not reused.
- Verification: `tests.phase6.test_egs_main_suspend_guard` covers partial daily rejection, valid high-coverage daily inference, cache-key v2 save behavior, and the existing all-empty daily fallback that skips suspend filtering rather than marking the whole market suspended.

### SR-DATA-004 - Suspend daily completeness threshold may false-fail on large-scale suspension days

- Severity: P3
- Status: open
- Owner phase: A-short weekly operation / Phase 6b maintenance
- Evidence: `SR-DATA-001` resolved the partial-`daily` silent drop path by requiring non-empty `pro.daily` payload coverage to meet `suspend_daily_min_coverage = 0.95`. Claude review accepted the fail-safe behavior but noted the threshold assumes normal-day suspensions stay below 5%; rare market-stress days with unusually broad suspensions could push true traded-code coverage below 95% and abort the run even when the provider response is complete.
- Accepted calibration: this is a low-risk operational watch item, not evidence that normal weekly runs are broken. A clear abort is safer than silently inferring missing rows as suspended stocks, and `suspend_daily_min_coverage` is already a configurable threshold.
- Mitigation evidence: the current observability slice makes `A-EGS/egs_main.py:get_suspend_info` write `logs/suspend_daily_coverage_<asof>.json` on pass, low-coverage fail, cache-hit, and no-daily skip paths; schema-validated `data_health` v1.2.0 `metrics.suspend_daily_coverage` mirrors the same latest observation. This does not close the watch item because no real weekly run has been reviewed yet.
- Required next action: monitor the first real weekly runs' `logs/suspend_daily_coverage_<asof>.json` and `data_health.metrics.suspend_daily_coverage`; if legitimate market-wide suspension conditions trip the threshold, tune the threshold or add a reviewed calendar / incident override with a focused regression test.

### SR-OPS-002 - Forward tracker writes are non-atomic

- Severity: P1
- Status: resolved
- Owner phase: A-short forward evidence / Phase 6b maintenance
- Evidence: `runners/forward_tracker.py:_write_tracker` sorts and writes the tracker with direct `to_csv(TRACKER_CSV, ...)`; an interruption can leave a partial file.
- Accepted calibration: this is an operational integrity issue, not a strategy-alpha finding. It does not affect corrected 5d revalidation if that run does not consume or update the forward tracker.
- Required next action: resolved for the forward-tracker write path. No further action is required for `SR-OPS-002` unless the tracker storage path or writer is redesigned.
- Closure evidence: the reviewed change set updates `runners/forward_tracker.py:_write_tracker` to write `SCHEMA_COLUMNS` to a same-directory temp CSV, flush and `fsync` the handle, close it, then atomically replace `forward_tracker.csv` with `os.replace`; failures unlink the temp file and leave the existing tracker untouched.
- Verification: `tests.phase6.test_forward_tracker_cache_guard` covers same-directory temp-file naming, one atomic replace call, sorted schema-column output, cleanup of the temp path after success, and preservation of the existing tracker when CSV serialization fails. `python -m unittest discover -s tests\phase6 -v` passed with 25 tests.

### SR-OPS-003 - Direct historical `egs_main.py --as-of` still defaults to live L3 concepts

- Severity: P1
- Status: resolved
- Owner phase: A-short historical replay / Phase 6b maintenance
- Evidence: `A-EGS/egs_main.py` argparse still defaults `--l3-mode` to `today`; `SR-EXEC-001` fixed the weekly wrapper but not direct engine invocation.
- Accepted calibration: current `runners/weekly_screening.ps1` protects historical official-output runs, so this is now a direct-engine / ad hoc replay risk. It does not block corrected 5d revalidation if no cohort regeneration occurs.
- Required next action: resolved for direct engine invocation. No further action is required for `SR-OPS-003` unless the L3 CLI contract is redesigned.
- Closure evidence: the reviewed change set adds `A-EGS/egs_main.py --allow-historical-live-l3` and rejects non-current `--as-of` + `--l3-mode=today` unless that explicit non-evidence / live-concept declaration is present. `runners/backtest_rank.py` now passes the declaration only for smoke-mode historical `today` L3 generation; production/default evidence paths stay on `neutralize` / `pit`.
- Verification: `tests.phase6.test_egs_main_l3_guard` covers historical default rejection, `pit` / `neutralize` acceptance, explicit live-L3 declaration, and current-date `today` acceptance. `tests.test_backtest_rank_phase3` covers the smoke command adding `--allow-historical-live-l3` only when requested.

### SR-DATA-002 - Severe daily-data insufficiency degrades to neutral stats that can pass filters

- Severity: P2
- Status: resolved
- Owner phase: A-short data quality / screening maintenance
- Evidence: `A-EGS/egs_main.py:precompute_stock_stats` returns `_neutral_stats_df` when `all_daily` is empty or too small; neutral rows include `has_crash_veto=False`, and `filter_l0` can skip amount filtering when liquidity fields are all NaN / zero.
- Accepted calibration: this is not evidence that normal runs are contaminated; it is a severe-data-insufficiency path that should not emit normal-looking candidate output.
- Required next action: no active `SR-DATA-002` action. Future daily-stat fallback redesigns must preserve a reviewed non-evidence / hard-fail boundary and must not reintroduce normal-looking neutral pass-through stats.
- Closure evidence: the reviewed change set updates `A-EGS/egs_main.py:precompute_stock_stats` so empty `all_daily`, fewer than `daily_stats_min_rows`, insufficient rows after matching the stock universe, or no valid close rows now raise `RuntimeError` before L0 can treat neutral liquidity / crash-veto defaults as normal evidence. The former get-daily-all log that promised neutral defaults now states that downstream stat computation will abort.
- Verification: `tests.phase6.test_egs_main_daily_stats_guard` covers empty daily payload rejection, tiny payload rejection, no stock-universe match rejection, and a sufficient payload still computing stats.

### SR-EXEC-003 - Execution drawdown misses open-position mark-to-market

- Severity: P1
- Status: resolved
- Owner phase: Phase 5 execution backtest / ship-gate readiness
- Evidence: `runners/backtest_execution.py:simulate_execution` initializes `daily_equity` with `market_value = 0`, appends equity points only around realized exit events, and computes `max_drawdown` from realized cash-only equity. Open-position mark-to-market drawdown is not represented.
- Accepted calibration: current ship-gate status remains default-deny / not-evaluable because other required metrics are missing; the risk is future execution or ship-gate evidence overreading a realized-only drawdown.
- Closure: current execution reports publish `metrics.max_drawdown = null`, and `ship_gate_evaluation.metric_results.max_drawdown.value/passed = null` with an explicit mark-to-market not-evaluable reason. `daily_equity.csv` may still contain realized exit-date cash drawdown diagnostics, but those diagnostics are not used as ship-gate drawdown evidence.
- Verification: `tests.execution.test_backtest_execution` covers the time-stop and multi-trade paths with null drawdown evidence until mark-to-market equity exists.
- Required next action: no active SR-EXEC-003 action. If daily mark-to-market equity is later implemented, add reviewed tests before re-enabling numeric execution drawdown evidence.

### SR-EXEC-004 - Execution assumptions report cooldown / circuit breaker controls that are not simulated

- Severity: P1
- Status: resolved
- Owner phase: Phase 5 execution backtest / Phase 8 monitoring
- Evidence: `runners/backtest_execution.py:build_execution_assumptions` reports cooldown and portfolio circuit breaker controls as enabled, while the simulation loop does not enforce those controls.
- Accepted calibration: this is primarily an evidence overclaim / report-contract defect. It does not currently authorize full-size use, but it must be fixed before execution evidence is cited as if these controls were tested.
- Closure: current execution reports set `portfolio_circuit_breaker.enabled = false`, `new_entries_blocked = false`, `existing_positions_action = not_implemented`, and `cooldown.enabled = false`. The declared event-code coverage no longer includes `circuit_breaker` or `cooldown_block`, and report limitations state these controls are not simulated or safety evidence.
- Verification: `tests.execution.test_backtest_execution` covers the generated assumptions and limitations for unimplemented circuit breaker / cooldown controls while preserving schema-valid report output.
- Required next action: no active SR-EXEC-004 action. If these controls are later implemented, add reviewed simulator behavior and event-log tests before reporting them as enabled.

### SR-EXEC-005 - Zero-trade execution reports are aggregated as 0.0% monthly returns

- Severity: P1
- Status: resolved
- Owner phase: Phase 5 execution aggregation / ship-gate readiness
- Evidence: `runners/aggregate_execution_reports.py:report_total_return_for_aggregation` returns `0.0` for zero-trade reports when total return is absent, causing those months to enter monthly return, t-stat, and Sharpe calculations as flat observations.
- Accepted calibration: this does not currently pass the full ship gate because other metrics remain missing / not-evaluable; it can still inflate sample count or compress variance when execution evidence is later summarized.
- Closure evidence: the reviewed change set updates `runners/aggregate_execution_reports.py:report_total_return_for_aggregation` so zero-trade reports with null `metrics.total_return` remain missing / not evaluable for return statistics instead of being imputed as `0.0`. The monthly series, `monthly_return_count`, total-return mean, alpha t-stat, and Sharpe now consume only reports with an explicit numeric `total_return`. The aggregate report contract is bumped to `execution_aggregate_report` v1.1.1 and states the corrected zero-trade semantics.
- Verification: `tests.execution.test_aggregate_execution_reports` reverses the old zero-trade invariant: an input month with `trade_count = 0` and null `total_return` remains in input `month_count` but is excluded from `monthly_return_series` / `monthly_return_count` / `total_return_mean`. `tests.schema.test_execution_aggregate_report_schema` validates v1.1.1 and its zero-trade exclusion description.
- Required next action: no active `SR-EXEC-005` action. If a future reviewed cash-return model emits an explicit numeric return for zero-trade reports, add tests before allowing those observations into return statistics.

### SR-EXEC-006 - Execution aggregate can turn smoke / unbound forward-month inputs into full-size permission

- Severity: P1
- Status: resolved
- Owner phase: Phase 5 execution aggregation / ship-gate evidence integrity
- Evidence: `runners/aggregate_execution_reports.py:validate_compatible_reports` only checks that reports share the same `capital_context` summary and `mode`; it does not require `mode == production` for ship-gate permission. `--forward-live-months` is a plain CLI integer with no reviewed forward-tracking evidence artifact / ref binding. `build_ship_gate_evaluation` sets `full_size_allowed = status == "pass"`, and current tests include `tests/execution/test_aggregate_execution_reports.py:test_aggregate_with_benchmark_and_forward_months_can_pass_gate`, which can assert `full_size_allowed == true` from two default smoke reports plus a bare `--forward-live-months 12`.
- Accepted calibration: there is no broker or automatic order path, and current burst research is blocked before execution evidence is used. The risk is evidence / manual-sizing overclaim: the core `>= 12 months forward live` ship-gate requirement can be bypassed by an unbound CLI value, and smoke diagnostics can be presented as full-size manual-use permission.
- Closure evidence: the reviewed change set updates `runners/aggregate_execution_reports.py` so `execution_aggregate_report` v1.1.0 reads a reviewed `--forward-live-evidence-ref` JSON, validates `review_status='reviewed'`, derives / checks `forward_live_months` from that artifact, and keeps bare `--forward-live-months` diagnostic. The original smoke / bare-forward-month bypass is closed: smoke aggregates remain `not_evaluable` for ship-gate permission even if their numeric diagnostics pass, and bare CLI months cannot satisfy the forward-live metric. The later `SR-EXEC-007` closure further keeps `full_size_allowed` false until capacity / concurrency-adjusted returns are evaluable.
- Verification: `tests.execution.test_aggregate_execution_reports` now reverses the old smoke / bare-forward-month pass invariant, covers production reports without reviewed forward evidence staying `not_evaluable`, covers smoke reports with reviewed evidence staying `not_evaluable`, covers reviewed-evidence month matching, and rejects CLI / evidence month mismatches. `tests.schema.test_execution_aggregate_report_schema` validates the v1.1.0+ schema and required `forward_live_evidence_source` field.

### SR-EXEC-007 - Execution simulator serializes overlapping candidates and reuses bucket cash

- Severity: P2
- Status: resolved
- Owner phase: Phase 5 execution simulator / capacity and concurrency modeling
- Evidence: `runners/backtest_execution.py:simulate_execution` loops candidates sequentially. For each candidate it enters, subtracts cash, computes the full exit inside the same iteration, and adds cash back before the next candidate is sized. `calculate_shares` therefore sees cash after the prior candidate has already been closed, even when real holding windows would overlap. The code discloses "does not yet model concurrent open positions" in `limitations`, but there is no durable register gate for the resulting capacity / return distortion.
- Accepted calibration: this is distinct from `SR-CAP-001` bucket-ceiling validation. The risk is concurrency and cash-lock modeling: overlapping trades can reuse the same bucket capital serially, overstating capacity-adjusted returns if execution results are later used as ship-gate-like evidence.
- Closure evidence: the reviewed change set updates `runners/aggregate_execution_reports.py` and `schemas/execution_aggregate_report.schema.json` to v1.1.2. Aggregates still publish serialized execution return diagnostics, but `ship_gate_evaluation.status` remains `not_evaluable` and `full_size_allowed` remains false because capacity / concurrency-adjusted returns are not evaluable while input reports come from the serialized Phase 5 simulator. Production-mode reports with benchmark, reviewed forward-live evidence, and otherwise passing numeric diagnostics no longer unlock full-size permission.
- Verification: `tests.execution.test_aggregate_execution_reports` reverses the prior production + reviewed-forward-evidence pass path: monthly alpha, Sharpe, drawdown, and forward-live diagnostics can pass, but the aggregate stays `not_evaluable`, `full_size_allowed = false`, and limitations state that capacity / concurrency-adjusted returns are not evaluable. `tests.schema.test_execution_aggregate_report_schema` validates v1.1.2 and the updated full-size permission description.
- Required next action: no active `SR-EXEC-007` evidence-overclaim action. If future work wants true capacity-adjusted execution evidence, implement concurrent holdings, cash locks across holding windows, and continuous portfolio equity tests before removing the not-evaluable gate.

### SR-CAP-001 - Capital ceiling is not validated at state load / sizing boundary

- Severity: P1
- Status: resolved
- Owner phase: capital policy / execution backtest / coordinator precondition
- Evidence: `runners/backtest_execution.py:calculate_shares` caps by cash, bucket capital, max position percent, and max positions, but there is no hard validation that the loaded `bucket_capital` respects the market / bucket capital ceiling from policy.
- Accepted calibration: this is a missing validation / clamp, not proof that current fixtures always over-allocate. If state already has `bucket_capital <= ceiling_pct * market_capital`, the current calculation may be fine; if state is hand-edited above ceiling, no code rejects it.
- Closure evidence: the reviewed change set updates `runners/backtest_execution.py` to validate `capital_context.bucket_capital <= capital_context.market_capital * capital_context.bucket_ceiling_pct` when building the capital context and again before empty / simulated execution uses the bucket capital. Above-ceiling cash-state inputs now raise instead of entering share calculation.
- Verification: `tests.execution.test_backtest_execution` covers a hand-edited A-short cash state with `short_bucket_capital = 200000.0` against market capital `350000.0` and ceiling `0.333333`, expecting a `bucket_capital exceeds bucket ceiling` rejection. `tests.schema.test_execution_backtest_report_schema` and `tests.schema.test_capital_context_schemas` still pass.
- Required next action: no active `SR-CAP-001` action. If a later coordinator intentionally supports manual liquidity transfers or ceiling overrides, add a reviewed state transition and tests before allowing above-ceiling bucket capital into sizing.

### SR-OPS-004 - Weekly xlsx overwrite guard checks a different default path than `egs_main.py`

- Severity: P3
- Status: resolved
- Owner phase: A-short weekly operation
- Evidence: `runners/weekly_screening.ps1` checks `A-EGS/Result/egs_tier1_<AsOf>.xlsx`, while `A-EGS/egs_main.py` defaults tier1 xlsx output to `A-EGS/egs_tier1_<AsOf>.xlsx` unless `CONF["xlsx_dir"]` is set.
- Accepted calibration: CSV and official result-directory guards still cover the main evidence outputs; this is a low-risk xlsx overwrite guard gap.
- Required next action: no active `SR-OPS-004` action. If `egs_main.py` later moves xlsx output again, update the weekly guard and regression test together.
- Closure evidence: `runners/weekly_screening.ps1` now checks the actual default xlsx path `A-EGS\egs_tier1_<AsOf>.xlsx` in addition to the legacy guarded `A-EGS\Result` xlsx path and existing CSV / official result-directory outputs.
- Verification: `tests.phase6.test_weekly_screening_guardrails` covers historical refusal when the default root-level xlsx output already exists.

### SR-OPS-005 - Forward tracker cache coverage uses calendar-day approximation

- Severity: P2
- Status: resolved
- Owner phase: A-short forward evidence / tracker reliability
- Evidence: `runners/forward_tracker.py:_check_cache_coverage` uses calendar-day shifting to approximate the required trading window.
- Accepted calibration: current producers over-pad enough for normal cases, so this is a weaker assertion rather than confirmed live contamination. Long holidays or unusual calendars can still break the assumption.
- Required next action: no active `SR-OPS-005` action. Future tracker cache coverage changes must keep coverage tied to cached trading-date rows, not only metadata calendar dates.
- Closure evidence: the reviewed change set updates `runners/forward_tracker.py:_check_cache_coverage` to read `stocks.trade_date` from the shared `forward_daily.pkl` payload, require every pending tracker `as_of` to exist in that cached trading-date sequence, and require `base_idx + max_window` to be present before backfill can reuse the cache. It no longer uses `as_of + calendar days` or metadata end-date alone to decide coverage.
- Verification: `tests.phase6.test_forward_tracker_cache_guard` covers close-only benchmark rejection, same-anchor acceptance, insufficient cached trading-date rejection, missing `as_of` rejection, and a sparse long-calendar case that passes because the required cached trading dates exist.

### SR-OPS-006 - Relisted-stock lookback boundary needs revalidation

- Severity: P3
- Status: resolved
- Owner phase: A-short screening maintenance
- Evidence: `A-EGS/egs_main.py:get_relisted_stocks` uses `trade_dates[CONF["suspend_lookback"]]` as the cutoff when enough trade dates exist; this may be an off-by-one or short-calendar semantic issue depending on the intended "lookback" definition.
- Accepted calibration: this is a plausible low-risk boundary defect, not confirmed active contamination.
- Required next action: no active `SR-OPS-006` action. Future relisted-stock lookback changes must preserve inclusive trading-date-window semantics and bump cache keys when cached set semantics change.
- Closure evidence: the reviewed change set adds `_lookback_cutoff_trade_date`, using `lookback - 1` as the descending `trade_dates` cutoff index so `suspend_lookback = 5` covers exactly the latest five trading dates (`trade_dates[0..4]`) instead of six. Short histories fall back to the oldest available date. `get_relisted_stocks` now uses `relisted_<as_of>_v2` so old off-by-one cached relisted sets are not reused.
- Verification: `tests.phase6.test_egs_main_relisted_guard` covers the inclusive five-date cutoff, short-history fallback, relisted membership, and v2 cache key. `python -m unittest discover -s tests\phase6 -v` passed 45 tests.

### SR-RANK-001 - Forward-return status can remain `ok` when conversion leaves NaN

- Severity: P3
- Status: resolved
- Owner phase: rank backtest / forward-tracker compatibility
- Evidence: `runners/backtest_rank.py:attach_forward_returns` catches conversion exceptions and later assigns status `"ok"` even when return values can remain NaN.
- Accepted calibration: current rank statistics drop NaN values, so numeric contamination is low; a status-only consumer such as tracker / reporting code could still overread `"ok"`.
- Required next action: no active `SR-RANK-001` action. Future forward-return status changes must keep `"ok"` reserved for rows whose required return fields converted to finite numeric values.
- Closure evidence: `runners/backtest_rank.py:attach_forward_returns` now sets `pending_return_conversion_failed` and skips the `"ok"` status whenever required close-to-close or T+1 open-to-exit-close return conversion fails, produces NaN, or produces a non-finite value. `ret_*d_status = "ok"` is assigned only after both required return paths have converted successfully.
- Verification: `tests.test_backtest_rank_phase3` adds `test_forward_return_conversion_failure_is_not_ok_status`, proving a non-numeric exit close leaves return fields NaN and marks `ret_5d_status = pending_return_conversion_failed` instead of `"ok"`. `tests.phase6.test_forward_tracker_cache_guard` still passes, covering the status-consuming forward-tracker path.

### SR-EXEC-002 - Execution backtest risk-control limitations need a tracked fix path

- Severity: P1
- Status: superseded
- Owner phase: Phase 5 / Phase 8 monitoring and ship-gate readiness
- Evidence: audit #1 reported execution-backtest drawdown underestimation, unimplemented cooldown / circuit-breaker / concurrency limits, and capital-ceiling enforcement gaps.
- Accepted calibration: line-level revalidation split the material execution findings into concrete entries rather than treating the summary as one vague blocker.
- Supersession evidence: replaced by `SR-EXEC-003`, `SR-EXEC-004`, `SR-EXEC-005`, `SR-EXEC-007`, and `SR-CAP-001`. Each child entry owns its current status; still-open child entries remain blockers until fixed and verified.

### SR-GOV-001 - A-short screening thresholds are not governed by preset schema

- Severity: P2
- Status: open
- Owner phase: A-short screening governance
- Evidence: `presets/a_short.yaml` is a capital / routing preset and still says detailed thresholds will be filled later; many live screening thresholds live in `A-EGS/egs_main.py` `CONF` and scoring code.
- Accepted calibration: `backtest_execution.py` does read `presets/a_short.yaml` for capital profile, so the issue is screening-threshold governance, not total preset non-use.
- Required next action: move production-relevant A-short thresholds into a governed preset contract or add tests that assert docs / preset / code parity.

### SR-SKILL-001 - US-short reference docs are copy-paste runtime prompt shaped

- Severity: P2
- Status: resolved
- Owner phase: US-short Skill / reference hygiene
- Evidence: `skills/us_short_analysis/reference/us_short_analysis_spec.md` and `us_short_screening_spec.md` start with imperative persona / execution instructions, while `skills/us_short_analysis/SKILL.md` is reserved for Phase 8.
- Accepted calibration: the reserved `SKILL.md` prevents normal Skill invocation, but it does not prevent a future LLM from pasting reference material directly into a chat.
- Required next action: no active `SR-SKILL-001` action. Future US-short reference imports must keep the non-runtime boundary visible before any persona / workflow text.
- Closure evidence: the reviewed change set adds top-of-file banners to both US-short reference docs, stating they are design reference only, not runtime prompts, and cannot support operation advice / sizing before schema-first runner / Skill implementation and reviewed ship-gate evidence.
- Verification: `rg -n "设计参考源|schema-first runner / Skill implementation|SR-SKILL-001" skills\us_short_analysis\reference\us_short_analysis_spec.md skills\us_short_analysis\reference\us_short_screening_spec.md docs\system_risk_register.md docs\CURRENT.md` confirms the banners and register status.

### SR-SKILL-002 - A-short frozen v14.2 reference can still be pasted as a runtime prompt

- Severity: P2
- Status: blocked
- Owner phase: A-short Skill / reference hygiene
- Evidence: `skills/a_short_analysis/reference/v14.2_spec.md` opens with imperative persona / full-framework execution / operation-advice language, but `CLAUDE.md` explicitly says `skills/a_short_analysis/reference/v14.2_spec.md` must not be edited because the design is frozen.
- Accepted calibration: this is partially mitigated by `skills/a_short_analysis/SKILL.md`, which is the active Skill entrypoint and now states that `v14.2_spec.md` is a frozen design spec, not a runtime prompt, and cannot authorize live operation advice / buy-sell actions / sizing outside the schema-validated runner and reviewed ship-gate evidence. Residual risk remains if someone copies the frozen reference file alone without the Skill boundary.
- Required next action: do not edit `skills/a_short_analysis/reference/v14.2_spec.md` unless the user explicitly lifts the freeze for a non-design banner only. Until then, treat direct-pasted v14.2 reference text as unsafe / non-authoritative for runtime advice and route through the Skill plus schema-validated runner boundary.
- Mitigation evidence: this repair strengthens `skills/a_short_analysis/SKILL.md` with a `Non-Runtime Reference Boundary` section and keeps the frozen reference file unchanged.
- Verification: `rg -n "Non-Runtime Reference Boundary|live operation advice|SR-SKILL-002|v14.2_spec.md" skills\a_short_analysis\SKILL.md docs\system_risk_register.md CLAUDE.md` confirms the boundary, residual-risk entry, and frozen-spec constraint.

### SR-LLM-001 - Web-news policy-risk prompt injection surface

- Severity: P2
- Status: resolved
- Owner phase: A-short Stage 3 LLM policy-risk check
- Evidence: `A-EGS/egs_main.py` builds a DeepSeek prompt by embedding raw Sina / Baidu news titles into user content.
- Accepted calibration: bounded impact; it can flip a policy-risk veto but does not directly create broker action or automatic buying.
- Required next action: no active `SR-LLM-001` action. Future Stage 3 LLM prompts that embed external text must preserve an explicit untrusted-text boundary and targeted tests.
- Closure evidence: the reviewed change set adds `_sanitize_untrusted_news_title`, `_sanitize_untrusted_news_titles`, and `_build_policy_risk_prompt` in `A-EGS/egs_main.py`; DeepSeek policy-risk checks now pass Sina / Baidu titles through a sanitized `[UNTRUSTED_NEWS_TITLE]` block with an explicit instruction boundary before LLM classification, and logs policy-risk trigger titles from the sanitized list.
- Verification: `tests.phase6.test_egs_main_llm_prompt_guard` covers hostile title delimiters, newline / code-fence neutralization, HTML entity decoding, explicit "do not execute title instructions" boundary text, inline boundary-token neutralization, and max-length truncation.

### SR-CANARY-001 - Data canary status is advisory but can be overread

- Severity: P2
- Status: resolved
- Owner phase: Phase 2.6 data lineage / weekly operation
- Evidence: `runners/data_canary.py` intentionally returns exit 0 for drift / missing / fetch errors; `runners/weekly_screening.ps1` treats canary as bypass and exits with the EGS code.
- Accepted calibration: bypass behavior is intentional; the risk is naming / documentation causing future LLMs to treat "pipeline green" as data validation pass.
- Required next action: no active `SR-CANARY-001` action. Keep future canary changes advisory-only unless a separate reviewed gate contract is created.
- Closure evidence: `runners/data_canary.py` now emits explicit `evidence_role = advisory_sidecar`, `gate_effect = never_blocks_screening_or_ship_gate`, `data_passed_claim = false`, and `ship_gate_evidence = false`; its summary line uses `[ADVISORY-*]` labels and says it is not a data-pass and not a ship-gate signal. `runners/weekly_screening.ps1` parses the canary log after the sidecar run and prints the same advisory boundary, while `runners/README.md` documents that exit 0 / warning cannot support alpha or production evidence.
- Verification: `tests.phase6.test_data_canary_advisory_boundary` covers the non-evidence payload fields and console wording; `tests.phase6.test_weekly_screening_guardrails` covers weekly-script advisory wording.

### SR-DET-001 - Deterministic report depends on wall-clock state for circuit breaker status

- Severity: P2
- Status: resolved
- Owner phase: Phase 4 deterministic report / state replay
- Evidence: `runners/run_analysis_report.py` calls `state_manager.is_circuit_breaker_active()` without an as-of replay time; state manager defaults to `datetime.now(timezone.utc)`.
- Accepted calibration: schema validation is real for report output; the issue is replay determinism, not schema validity.
- Required next action: no active `SR-DET-001` action. Future state-consuming report fields must record their replay/evaluation timestamp instead of relying on wall-clock state.
- Closure evidence: `runners/run_analysis_report.py` now derives a deterministic state replay timestamp from the report `as_of` date (A-share close, `15:00 +08:00`) and passes it to `state_manager.is_circuit_breaker_active(...)`; callers may override with `--state-now <ISO timestamp>` for explicit replay. `deterministic_report` / enrichment contracts are bumped to v1.2.0 and `data_lineage.state_evaluation_time` records the exact timestamp used.
- Verification: `tests.skill.test_run_analysis_report` covers default as-of replay activating a circuit breaker that wall-clock now would see as expired, explicit `state_now` override, v1.2.0 lineage output, enrichment target-version alignment, and schema-valid write.

### SR-OPS-001 - Audit #1 operational findings need line-level revalidation

- Severity: P2
- Status: superseded
- Owner phase: A-short operation / Phase 3-6 maintenance
- Evidence: audit #1 reported L3 today default risk, silent degradation paths, forward tracker atomic-write concern, missing tests, and possible delisted-universe handling issues.
- Accepted calibration: line-level review confirmed several operational defects and downgraded others to lower-priority or needs-revalidation entries.
- Supersession evidence: replaced by `SR-DATA-001`, `SR-OPS-002`, `SR-OPS-003`, `SR-DATA-002`, `SR-OPS-004`, `SR-OPS-005`, `SR-OPS-006`, and `SR-RANK-001`. Each child entry owns its current status; open / `needs_revalidation` child entries remain blockers until fixed or closed individually.
