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

Current routing note: the corrected-basis A-share burst preregistration failed a frozen-cohort preflight with `valid_signal_events = 0`; do not run outcome / benchmark-excess for that artifact. The ledger-gated full-universe redesigned preflight has now passed event-count with `valid_signal_events = 134`, but it computed no outcome / benchmark excess. `SR-DATA-003` must be resolved before any outcome / excess slice.

1. `SR-DATA-003` - Resolve benchmark-open input before any redesigned A-share burst outcome / excess calculation; the forward-tracker close-only cache guard is addressed in this change slice.
2. `SR-DATA-001` + `SR-OPS-002` + `SR-OPS-003` - Fix before the next new weekly official capture, forward-tracker official use, or direct historical `egs_main.py` cohort regeneration.
3. `SR-EXEC-003` + `SR-EXEC-004` + `SR-EXEC-005` + `SR-EXEC-007` + `SR-CAP-001` + `SR-CONTRACT-002` - Fix before execution-backtest evidence, ship-gate-like evidence, or manual sizing conclusions are used.
4. `SR-SEC-001` - Remove or narrow broad local Claude Bash allow rules before relying on Claude-side automation.
5. `SR-PIT-001` + `SR-CONTRACT-001` - Strengthen `analysis_input` PIT contract and make producer / consumer schema validation real.
6. `SR-DATA-002` + `SR-OPS-004` + `SR-OPS-005` + `SR-RANK-001` + `SR-OPS-006` - Maintenance queue before affected subsystem promotion.

## Entries

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
- Status: open
- Owner phase: Phase 7c DataHub / report contract precondition; long-lane blocker
- Evidence: `schemas/analysis_input.schema.json` has `trade_date` and L3 metadata but cannot express `ann_date <= trade_date` for fundamentals, cannot compare `source.l3_snapshot_date <= trade_date`, and does not require PIT snapshot presence when `source.l3_mode = pit`.
- Accepted calibration: `A-EGS/egs_main.py` currently filters `fina_indicator.ann_date <= TODAY_DT`; the risk is contract-level non-enforcement and future producer regression, not proof of current look-ahead.
- Required next action: introduce an `analysis_input` contract revision or adjunct validation that can express PIT dates for fundamentals / L3 and reject future-dated or missing PIT metadata where required.

### SR-CONTRACT-001 - Producer and consumer do not validate `analysis_input` against schema

- Severity: P1
- Status: open
- Owner phase: Phase 1 / Phase 4 contract hardening
- Evidence: `A-EGS/egs_main.py` writes `analysis_input.json` without jsonschema validation; `runners/run_analysis_report.py` loads `analysis_input` and validates only its own output report.
- Accepted calibration: `build_data_health` performs some bespoke checks, but it is not equivalent to schema validation at producer and consumer boundaries.
- Required next action: add shared schema validation for `analysis_input` on write and read, with tests covering malformed payload rejection.

### SR-CONTRACT-002 - Forward-live evidence artifact lacks a schema-first contract

- Severity: P2
- Status: open
- Owner phase: Phase 6 forward evidence / Phase 5 aggregate ship-gate contract
- Evidence: `runners/aggregate_execution_reports.py` v1.1.0 correctly requires `--forward-live-evidence-ref` before `full_size_allowed` can become true, but the referenced forward-live evidence artifact is currently validated only inline for `review_status == "reviewed"` and non-negative integer `forward_live_months`. No `schemas/forward_live_evidence.schema.json` contract yet defines provenance fields such as reviewer, source window, tracker artifact ref, captured-month basis, or review lineage.
- Accepted calibration: this is not an active blocker because no 12-month forward-live artifact exists yet and SR-EXEC-006's inline validation closes the current smoke / bare-CLI gate bug. It becomes material before any real Phase 6 forward-live evidence artifact is produced or used for aggregate full-size permission.
- Required next action: before the first reviewed forward-live evidence artifact is produced or consumed for ship-gate-like aggregation, add a schema-first contract covering `review_status`, `forward_live_months`, provenance / reviewer / source-window / tracker refs, and validation tests; then update `aggregate_execution_reports.py` to validate the evidence artifact against that schema.

### SR-SEC-001 - Broad local Claude Bash allow rules

- Severity: P1
- Status: open
- Owner phase: local AI tooling security
- Evidence: root `.claude/settings.local.json` allows broad `Bash(python *)`; `A-EGS/.claude/settings.local.json` allows `Bash(python -c ' *)`. These files are local and currently untracked.
- Accepted calibration: this is local automation exposure, not repository business-code behavior.
- Required next action: narrow allow rules to concrete project scripts or remove them from local Claude settings; record the local change in `SESSION_LOG.md` if it affects review/execution behavior.

### SR-RESEARCH-001 - Corrected A-share burst preregistration has zero valid signal events

- Severity: P0
- Status: resolved
- Owner phase: A-share burst research / alpha-validation preflight
- Evidence: `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json` evaluated the frozen 20240131-20251231 generated cohorts against `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`. It found 360 total rows, 305 Tier1 rows, 301 rows after hard filters, 17 `pct_5d >= 6.0` rows, 38 amount-expansion rows, 7 breakout rows, and 0 rows satisfying all three preregistered burst signals. The preregistered `valid_signal_events >= 30` gate fails before any return / benchmark outcome can be informative.
- Accepted calibration: this is not proof that a future redesigned A-share burst universe has no alpha. It proves only that the current steady Tier1 watchlist universe cannot test the frozen all-pass burst trigger. The current corrected-basis preregistration is spent as `failed_preflight_zero_signal_events`; changing universe, entry flags, Tier2 inclusion, breakout definition, thresholds, or signal conjunction is a new promotion-relevant degree of freedom.
- Required next action: resolved for event-count routing. Do not run outcome / benchmark-excess calculation for the current corrected-basis preregistration. Any new redesigned hypothesis still requires a ledger append and reviewed preregistration before it runs.
- Closure evidence: `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json` and its ledger planned test were reviewed / committed, and `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json` records a pre-outcome preflight pass with `valid_signal_events = 134` and no outcome / benchmark-excess computation. The current blocker for any later outcome / excess run is `SR-DATA-003`.

### SR-DATA-003 - Corrected same-anchor burst test needs benchmark open input

- Severity: P1
- Status: open
- Owner phase: A-share burst research input / benchmark measurement / forward-tracker cache guard
- Evidence: `result/a_short/backtest/cache/forward_daily.pkl` predates the same-anchor fix and stores `benchmarks.csi300` / `benchmarks.csi1000` with only `trade_date,close`. `runners/backtest_rank.py` now requires benchmark `trade_date,open,close`; missing benchmark open makes `_benchmark_returns` return `None`, while naïve cache refresh would refetch the full stock / limit / benchmark forward surface.
- Additional forward-tracker evidence: before this slice, `runners/forward_tracker.py:_check_cache_coverage` read only `forward_daily.pkl` metadata date range and was blind to benchmark `open` / `close` fields. It could return `ok`, then `forward_tracker.py:backfill` called `fetch_forward_daily(..., refresh=False)`, which rejected close-only benchmark frames through `runners/backtest_rank.py:_benchmark_frame_has_same_anchor_fields` and refetched the shared forward surface. That bypassed the tracker comment that backfill must not trigger a universe-wide Tushare refetch on its own, and the user did not see the intended `[SKIP]` / hint path.
- Accepted calibration: this is now the active blocker before the full-universe redesigned A-share burst preregistration can compute outcome / excess returns. The redesigned preflight passed event-count with `valid_signal_events = 134`, but no return or benchmark-excess calculation is authorized until benchmark-open input is reviewed.
- Required next action: before the redesigned burst preregistration computes outcome / excess returns, create a reviewed benchmark-open input slice that refreshes only the necessary CSI1000 / CSI300 `index_daily` open/close lineage or otherwise provides reviewed benchmark open data without silently authorizing a full forward-daily provider refetch. The forward-tracker cache guard portion is addressed by `runners/forward_tracker.py:_check_cache_coverage`, which now rejects cached benchmark frames lacking same-anchor `trade_date/open/close` fields before `fetch_forward_daily` can refetch.
- Progress evidence: `tests/phase6/test_forward_tracker_cache_guard.py` covers both close-only benchmark cache rejection and same-anchor benchmark cache acceptance.

### SR-DATA-001 - Suspend inference can silently drop tradable stocks on partial daily response

- Severity: P1
- Status: open
- Owner phase: A-short weekly operation / Phase 6b maintenance
- Evidence: `A-EGS/egs_main.py:get_suspend_info` computes `suspended = all_codes - traded_codes` from single-day `pro.daily` responses and later `filter_l0` removes that set from candidates. There is no row-count / completeness sanity check before treating missing `daily` rows as suspended stocks.
- Accepted calibration: this is a real wrong-output path, but the trigger is a partial `pro.daily` bulk response. Frequency is not proven and is expected to be low; impact is silent and high when it fires. It does not block corrected 5d revalidation if that revalidation uses frozen historical generated cohorts and does not rerun `A-EGS/egs_main.py`.
- Required next action: replace the inference with a proper suspend / trade-status source where available, or hard-fail / quarantine the run when daily row-count completeness is below a reviewed threshold. Fix before the next new weekly official capture or any cohort regeneration used as evidence.

### SR-OPS-002 - Forward tracker writes are non-atomic

- Severity: P1
- Status: open
- Owner phase: A-short forward evidence / Phase 6b maintenance
- Evidence: `runners/forward_tracker.py:_write_tracker` sorts and writes the tracker with direct `to_csv(TRACKER_CSV, ...)`; an interruption can leave a partial file.
- Accepted calibration: this is an operational integrity issue, not a strategy-alpha finding. It does not affect corrected 5d revalidation if that run does not consume or update the forward tracker.
- Required next action: write to a temp file in the same directory, flush / close it, and atomically replace the tracker file. Add a test or focused review evidence for the write path.

### SR-OPS-003 - Direct historical `egs_main.py --as-of` still defaults to live L3 concepts

- Severity: P1
- Status: open
- Owner phase: A-short historical replay / Phase 6b maintenance
- Evidence: `A-EGS/egs_main.py` argparse still defaults `--l3-mode` to `today`; `SR-EXEC-001` fixed the weekly wrapper but not direct engine invocation.
- Accepted calibration: current `runners/weekly_screening.ps1` protects historical official-output runs, so this is now a direct-engine / ad hoc replay risk. It does not block corrected 5d revalidation if no cohort regeneration occurs.
- Required next action: add an engine-level guard or explicit historical replay contract so direct historical `--as-of` runs cannot silently use `today` L3 mode unless the caller explicitly declares a non-evidence / live-concept run.

### SR-DATA-002 - Severe daily-data insufficiency degrades to neutral stats that can pass filters

- Severity: P2
- Status: open
- Owner phase: A-short data quality / screening maintenance
- Evidence: `A-EGS/egs_main.py:precompute_stock_stats` returns `_neutral_stats_df` when `all_daily` is empty or too small; neutral rows include `has_crash_veto=False`, and `filter_l0` can skip amount filtering when liquidity fields are all NaN / zero.
- Accepted calibration: this is not evidence that normal runs are contaminated; it is a severe-data-insufficiency path that should not emit normal-looking candidate output.
- Required next action: hard-fail, quarantine, or mark the run non-evidence when daily payload completeness is below a reviewed threshold; do not silently produce neutral pass-through stats.

### SR-EXEC-003 - Execution drawdown misses open-position mark-to-market

- Severity: P1
- Status: open
- Owner phase: Phase 5 execution backtest / ship-gate readiness
- Evidence: `runners/backtest_execution.py:simulate_execution` initializes `daily_equity` with `market_value = 0`, appends equity points only around realized exit events, and computes `max_drawdown` from realized cash-only equity. Open-position mark-to-market drawdown is not represented.
- Accepted calibration: current ship-gate status remains default-deny / not-evaluable because other required metrics are missing; the risk is future execution or ship-gate evidence overreading a realized-only drawdown.
- Required next action: implement daily mark-to-market equity for open positions, or mark drawdown as `not_evaluable` until MTM is implemented. Do not use execution drawdown for safety conclusions before this is fixed.

### SR-EXEC-004 - Execution assumptions report cooldown / circuit breaker controls that are not simulated

- Severity: P1
- Status: open
- Owner phase: Phase 5 execution backtest / Phase 8 monitoring
- Evidence: `runners/backtest_execution.py:build_execution_assumptions` reports cooldown and portfolio circuit breaker controls as enabled, while the simulation loop does not enforce those controls.
- Accepted calibration: this is primarily an evidence overclaim / report-contract defect. It does not currently authorize full-size use, but it must be fixed before execution evidence is cited as if these controls were tested.
- Required next action: either implement the controls in the simulator with tests, or report them as `not_implemented` / `not_evaluable` and exclude them from any safety conclusion.

### SR-EXEC-005 - Zero-trade execution reports are aggregated as 0.0% monthly returns

- Severity: P1
- Status: open
- Owner phase: Phase 5 execution aggregation / ship-gate readiness
- Evidence: `runners/aggregate_execution_reports.py:report_total_return_for_aggregation` returns `0.0` for zero-trade reports when total return is absent, causing those months to enter monthly return, t-stat, and Sharpe calculations as flat observations.
- Accepted calibration: this does not currently pass the full ship gate because other metrics remain missing / not-evaluable; it can still inflate sample count or compress variance when execution evidence is later summarized.
- Required next action: treat zero-trade no-return reports as missing / not-evaluable for return statistics, or explicitly model cash return with a documented rule and separate no-trade diagnostics.

### SR-EXEC-006 - Execution aggregate can turn smoke / unbound forward-month inputs into full-size permission

- Severity: P1
- Status: resolved
- Owner phase: Phase 5 execution aggregation / ship-gate evidence integrity
- Evidence: `runners/aggregate_execution_reports.py:validate_compatible_reports` only checks that reports share the same `capital_context` summary and `mode`; it does not require `mode == production` for ship-gate permission. `--forward-live-months` is a plain CLI integer with no reviewed forward-tracking evidence artifact / ref binding. `build_ship_gate_evaluation` sets `full_size_allowed = status == "pass"`, and current tests include `tests/execution/test_aggregate_execution_reports.py:test_aggregate_with_benchmark_and_forward_months_can_pass_gate`, which can assert `full_size_allowed == true` from two default smoke reports plus a bare `--forward-live-months 12`.
- Accepted calibration: there is no broker or automatic order path, and current burst research is blocked before execution evidence is used. The risk is evidence / manual-sizing overclaim: the core `>= 12 months forward live` ship-gate requirement can be bypassed by an unbound CLI value, and smoke diagnostics can be presented as full-size manual-use permission.
- Closure evidence: the reviewed change set updates `runners/aggregate_execution_reports.py` so `execution_aggregate_report` v1.1.0 reads a reviewed `--forward-live-evidence-ref` JSON, validates `review_status='reviewed'`, derives / checks `forward_live_months` from that artifact, and keeps bare `--forward-live-months` diagnostic. `ship_gate_evaluation.full_size_allowed` can become true only when the aggregate mode is `production`, a reviewed forward-live evidence source is present, and all AND-gate metrics pass. Smoke aggregates remain `not_evaluable` for ship-gate permission even if their numeric diagnostics pass.
- Verification: `tests.execution.test_aggregate_execution_reports` now reverses the old smoke / bare-forward-month pass invariant, covers production reports without reviewed forward evidence staying `not_evaluable`, covers smoke reports with reviewed evidence staying `not_evaluable`, covers production + reviewed evidence pass, and rejects CLI / evidence month mismatches. `tests.schema.test_execution_aggregate_report_schema` validates the v1.1.0 schema and required `forward_live_evidence_source` field.

### SR-EXEC-007 - Execution simulator serializes overlapping candidates and reuses bucket cash

- Severity: P2
- Status: open
- Owner phase: Phase 5 execution simulator / capacity and concurrency modeling
- Evidence: `runners/backtest_execution.py:simulate_execution` loops candidates sequentially. For each candidate it enters, subtracts cash, computes the full exit inside the same iteration, and adds cash back before the next candidate is sized. `calculate_shares` therefore sees cash after the prior candidate has already been closed, even when real holding windows would overlap. The code discloses "does not yet model concurrent open positions" in `limitations`, but there is no durable register gate for the resulting capacity / return distortion.
- Accepted calibration: this is distinct from `SR-CAP-001` bucket-ceiling validation. The risk is concurrency and cash-lock modeling: overlapping trades can reuse the same bucket capital serially, overstating capacity-adjusted returns if execution results are later used as ship-gate-like evidence.
- Required next action: before execution returns are used for ship-gate-like conclusions, either model concurrent holdings and lock bucket cash through each holding window, or mark capacity / concurrency-adjusted return as not-evaluable and keep the aggregate out of full-size permission decisions.

### SR-CAP-001 - Capital ceiling is not validated at state load / sizing boundary

- Severity: P1
- Status: open
- Owner phase: capital policy / execution backtest / coordinator precondition
- Evidence: `runners/backtest_execution.py:calculate_shares` caps by cash, bucket capital, max position percent, and max positions, but there is no hard validation that the loaded `bucket_capital` respects the market / bucket capital ceiling from policy.
- Accepted calibration: this is a missing validation / clamp, not proof that current fixtures always over-allocate. If state already has `bucket_capital <= ceiling_pct * market_capital`, the current calculation may be fine; if state is hand-edited above ceiling, no code rejects it.
- Required next action: validate and/or clamp capital context at state load and before sizing. Add a test that a bucket above its ceiling is rejected or reduced before share calculation.

### SR-OPS-004 - Weekly xlsx overwrite guard checks a different default path than `egs_main.py`

- Severity: P3
- Status: open
- Owner phase: A-short weekly operation
- Evidence: `runners/weekly_screening.ps1` checks `A-EGS/Result/egs_tier1_<AsOf>.xlsx`, while `A-EGS/egs_main.py` defaults tier1 xlsx output to `A-EGS/egs_tier1_<AsOf>.xlsx` unless `CONF["xlsx_dir"]` is set.
- Accepted calibration: CSV and official result-directory guards still cover the main evidence outputs; this is a low-risk xlsx overwrite guard gap.
- Required next action: align the guard with the actual xlsx output path or route xlsx output under the guarded result directory.

### SR-OPS-005 - Forward tracker cache coverage uses calendar-day approximation

- Severity: P2
- Status: open
- Owner phase: A-short forward evidence / tracker reliability
- Evidence: `runners/forward_tracker.py:_check_cache_coverage` uses calendar-day shifting to approximate the required trading window.
- Accepted calibration: current producers over-pad enough for normal cases, so this is a weaker assertion rather than confirmed live contamination. Long holidays or unusual calendars can still break the assumption.
- Required next action: use the trading calendar / cached trading dates for coverage checks, or document the approximation and hard-fail cases where the calendar-day buffer cannot prove coverage.

### SR-OPS-006 - Relisted-stock lookback boundary needs revalidation

- Severity: P3
- Status: needs_revalidation
- Owner phase: A-short screening maintenance
- Evidence: `A-EGS/egs_main.py:get_relisted_stocks` uses `trade_dates[CONF["suspend_lookback"]]` as the cutoff when enough trade dates exist; this may be an off-by-one or short-calendar semantic issue depending on the intended "lookback" definition.
- Accepted calibration: this is a plausible low-risk boundary defect, not confirmed active contamination.
- Required next action: re-read the intended lookback semantics, add a small date-list test, and either fix the index / cutoff or close this entry with evidence.

### SR-RANK-001 - Forward-return status can remain `ok` when conversion leaves NaN

- Severity: P3
- Status: open
- Owner phase: rank backtest / forward-tracker compatibility
- Evidence: `runners/backtest_rank.py:attach_forward_returns` catches conversion exceptions and later assigns status `"ok"` even when return values can remain NaN.
- Accepted calibration: current rank statistics drop NaN values, so numeric contamination is low; a status-only consumer such as tracker / reporting code could still overread `"ok"`.
- Required next action: set a non-ok status when any required forward return conversion fails or leaves NaN, and add a focused regression test if the field is consumed by status-only code.

### SR-EXEC-002 - Execution backtest risk-control limitations need a tracked fix path

- Severity: P1
- Status: superseded
- Owner phase: Phase 5 / Phase 8 monitoring and ship-gate readiness
- Evidence: audit #1 reported execution-backtest drawdown underestimation, unimplemented cooldown / circuit-breaker / concurrency limits, and capital-ceiling enforcement gaps.
- Accepted calibration: line-level revalidation split the material execution findings into concrete entries rather than treating the summary as one vague blocker.
- Supersession evidence: replaced by `SR-EXEC-003`, `SR-EXEC-004`, `SR-EXEC-005`, and `SR-CAP-001`. Those child entries remain open until fixed and verified.

### SR-GOV-001 - A-short screening thresholds are not governed by preset schema

- Severity: P2
- Status: open
- Owner phase: A-short screening governance
- Evidence: `presets/a_short.yaml` is a capital / routing preset and still says detailed thresholds will be filled later; many live screening thresholds live in `A-EGS/egs_main.py` `CONF` and scoring code.
- Accepted calibration: `backtest_execution.py` does read `presets/a_short.yaml` for capital profile, so the issue is screening-threshold governance, not total preset non-use.
- Required next action: move production-relevant A-short thresholds into a governed preset contract or add tests that assert docs / preset / code parity.

### SR-SKILL-001 - US-short reference docs are copy-paste runtime prompt shaped

- Severity: P2
- Status: open
- Owner phase: US-short Skill / reference hygiene
- Evidence: `skills/us_short_analysis/reference/us_short_analysis_spec.md` and `us_short_screening_spec.md` start with imperative persona / execution instructions, while `skills/us_short_analysis/SKILL.md` is reserved for Phase 8.
- Accepted calibration: the reserved `SKILL.md` prevents normal Skill invocation, but it does not prevent a future LLM from pasting reference material directly into a chat.
- Required next action: add a clear banner to US-short reference docs: design reference only, not a runtime prompt, no operation advice / sizing without schema-first implementation and ship-gate evidence.

### SR-LLM-001 - Web-news policy-risk prompt injection surface

- Severity: P2
- Status: open
- Owner phase: A-short Stage 3 LLM policy-risk check
- Evidence: `A-EGS/egs_main.py` builds a DeepSeek prompt by embedding raw Sina / Baidu news titles into user content.
- Accepted calibration: bounded impact; it can flip a policy-risk veto but does not directly create broker action or automatic buying.
- Required next action: sanitize / delimit external titles and add an instruction boundary test, or replace the LLM call with deterministic keyword / source scoring for this veto.

### SR-CANARY-001 - Data canary status is advisory but can be overread

- Severity: P2
- Status: open
- Owner phase: Phase 2.6 data lineage / weekly operation
- Evidence: `runners/data_canary.py` intentionally returns exit 0 for drift / missing / fetch errors; `runners/weekly_screening.ps1` treats canary as bypass and exits with the EGS code.
- Accepted calibration: bypass behavior is intentional; the risk is naming / documentation causing future LLMs to treat "pipeline green" as data validation pass.
- Required next action: make weekly output and docs distinguish "canary ran / advisory warning" from "data passed"; do not let canary status support alpha or production evidence.

### SR-DET-001 - Deterministic report depends on wall-clock state for circuit breaker status

- Severity: P2
- Status: open
- Owner phase: Phase 4 deterministic report / state replay
- Evidence: `runners/run_analysis_report.py` calls `state_manager.is_circuit_breaker_active()` without an as-of replay time; state manager defaults to `datetime.now(timezone.utc)`.
- Accepted calibration: schema validation is real for report output; the issue is replay determinism, not schema validity.
- Required next action: allow report generation to pass a deterministic `now` / as-of timestamp when replaying historical reports, or document this as an explicit live-state limitation.

### SR-OPS-001 - Audit #1 operational findings need line-level revalidation

- Severity: P2
- Status: superseded
- Owner phase: A-short operation / Phase 3-6 maintenance
- Evidence: audit #1 reported L3 today default risk, silent degradation paths, forward tracker atomic-write concern, missing tests, and possible delisted-universe handling issues.
- Accepted calibration: line-level review confirmed several operational defects and downgraded others to lower-priority or needs-revalidation entries.
- Supersession evidence: replaced by `SR-DATA-001`, `SR-OPS-002`, `SR-OPS-003`, `SR-DATA-002`, `SR-OPS-004`, `SR-OPS-005`, `SR-OPS-006`, and `SR-RANK-001`. Those child entries remain open or `needs_revalidation` until fixed / closed individually.
