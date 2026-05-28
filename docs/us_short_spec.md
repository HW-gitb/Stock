# US Short Spec

**Status**: Phase 6d docs-only baseline with Phase 7a-4 evidence-feasibility routing. This document normalizes the existing US-short screening and analysis reference materials into a production-facing spec shape. It does not implement runners, providers, DataHub, skills, prompts, or order execution.

**Owner role**: detailed spec owner for US-short steady-lane normalization. `skills/us_short_analysis/reference/` remains the source-reference archive; `docs/burst_lane_spec.md` owns the independent US burst lane; `docs/strategy_design_synthesis.md` remains the architecture / route entry.

## 1. Scope

US-short is a first-class subsystem under the US short bucket. It must be designed in parallel with A-short, A-long, and US-long, but implementation remains gated behind reviewed specs, provider/data requirements audit, and Phase 7 shared-engine work.

This baseline covers:

- source-reference normalization,
- US-short lane boundaries,
- candidate lifecycle,
- screening contract,
- analysis contract,
- risk gates and state requirements,
- output and evidence expectations,
- benchmark and ship-gate boundaries,
- Phase 6e provider / data requirements inputs.

Non-scope:

- No schema version, runner, migration, Skill implementation, prompt implementation, provider selection, or DataHub implementation is introduced here.
- No numeric threshold is promoted to production constant by this document alone; reference thresholds are candidate defaults that must later move into reviewed config / preset fields with tests.
- No full-size manual use is allowed from this document alone; ship gate still requires monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and >=12 months forward live evidence.
- No broker connection, OS automation, or automatic trading is allowed.

## 2. Source Reference Normalization

The two US-short reference files were written for AI chatbox workflows. They are design inputs, not runtime prompts.

| Source | Reference role | Production destination |
|---|---|---|
| `skills/us_short_analysis/reference/us_short_screening_spec.md` | US-EGS v2.4 screening logic: universe filters, GICS industry prefilter, expectation gap, catalyst schedule, momentum, scoring, Tier 1 / Tier 2 output | Future screening schema, factor config, candidate generator, and provider requirements. |
| `skills/us_short_analysis/reference/us_short_analysis_spec.md` | V14.14 analysis workflow: macro scan, flow scan, ecosystem scan, technical / valuation / target checks, hard vetoes, event-file audit, sizing, output table, state handoff | Future analyzer, report schema, state model, Skill usage document, prompt fragments for semantic checks, and execution backtest assumptions. |
| `skills/us_short_analysis/SKILL.md` | Reserved skill placeholder | Must remain reserved until Phase 7 / Phase 8 implementation begins. |

Rules for future implementation:

- Deterministic, testable fields should go to schema / Python / config / state.
- Semantic news, regulatory interpretation, analyst-revision credibility, and event-quality judgement can later become Skill prompt fragments.
- Provider-specific fields such as options flow, dark-pool data, analyst consensus, guidance, insider transactions, SEC filings, borrow / short-interest, and Estimize are not assumed available until Phase 6e audit.
- Reference thresholds may be preserved as candidate defaults, but must be visible in config and reviewed before production use.

## 3. Lane Boundary

US-short has two short-term lanes:

1. `steady_us_short`: risk-filtered US short candidate generation and analysis based on the normalized US-EGS / V14.14 references.
2. `us_short_burst`: independent burst lane governed by `docs/burst_lane_spec.md`.

The existing US reference material contains high-momentum elements such as MAP, gamma / options flow, and catalyst acceleration. Those elements are not automatically production burst logic. Future implementation must route each high-velocity rule explicitly:

- steady-lane diagnostic / risk adjustment,
- burst-lane candidate input,
- research-only experiment,
- or rejected / deferred rule.

US-short steady evidence cannot unlock `us_short_burst` full-size sizing, and burst evidence cannot silently replace steady-lane risk gates.

Phase 7a-1 audit status: `us_short_steady` is `continue_as_risk_filter`. It remains risk-filtered decision support until US provider data, market microstructure constraints, calendar / timezone semantics, and forward evidence capture are specified. This verdict is not push-alpha approval and does not authorize live full-size use.

## 4. Candidate Lifecycle

Each US-short candidate should move through the following lifecycle:

1. Universe and listing eligibility.
2. Liquidity and tradeability prefilter.
3. GICS industry context and market-regime state.
4. Expectation-gap, valuation, ownership / flow, catalyst, and momentum factor evaluation.
5. Tier assignment and candidate-pool construction.
6. Analysis workflow: macro state, flow scan, ecosystem scan, technical / fundamental / target checks.
7. Hard veto and event-file audit.
8. Position / risk proposal inside the US short bucket.
9. Output report and state handoff.
10. Forward evidence capture and ship-gate evaluation.

Future implementation can split this lifecycle across screening, analyzer, state, report, and skill layers.

## 5. Screening Contract

### 5.1 Universe And Liquidity Eligibility

The reference baseline starts from US-listed names only:

- NYSE / NASDAQ listed.
- Exclude OTC, pink sheets, delisting-warning names, bankruptcy process, reverse-split listing-maintenance cases, and non-news trading halts.
- Reference minimums: close price >= USD 5 and market cap >= USD 300m.
- Reference liquidity: smaller of 20-day average and median dollar turnover >= max(USD 15m, market cap * 1.5%).
- Lockup expiration, S-3 resale registration, recent material restatement, and severe short-attack flags are eligibility risks.
- ADR names require explicit ADR flagging and additional quality / audit checks.

Production contract:

- Eligibility results must preserve raw values, pass / fail state, source, as-of date, and missing-data reason.
- Missing provider fields do not silently pass; if the field is essential to eligibility, the candidate is blocked or marked research-only until manually reviewed.
- Listing, delisting, halt, split, restatement, and corporate-action data must be point-in-time where possible.

### 5.2 Industry Context

Reference screening uses GICS four-level industry as the default classification and falls back to a higher GICS level when the comparable set is too small.

Industry context includes:

- gross-margin trend,
- regulatory / policy pressure,
- leader momentum versus S&P 500,
- insufficient-comparable fallback,
- low-pullback / value-style exemption candidates.

Production contract:

- Keep GICS level, fallback level, sample count, benchmark / leader set, and fallback reason visible.
- Do not hard-code one industry threshold across all sectors without normalized context.
- Industry context is a screening and risk-adjustment input; it does not by itself authorize full-size use.

### 5.3 Factor Families

| Family | Reference inputs | Production role |
|---|---|---|
| `expectation_gap` | EPS surprise versus consensus / Estimize / guidance / historical same-quarter baseline; revision momentum; REV-T style turnaround cases | Core screening factor; provider and PIT rules must be audited before automation. |
| `earnings_quality` | GAAP EPS quality, recurring profit, operating cash flow / net income, FCF alternative path, ADR / audit quality | Hard risk gate or downgrade input depending on evidence strength. |
| `valuation_gap` | Industry PE percentile, ROE quality, PB / buyback alternatives, PEG / overvaluation flags, crowd-mode exceptions | Screening factor and risk adjustment; exact thresholds remain candidate defaults. |
| `ownership_flow` | Insider transactions, secondary / S-3 risk, short interest / borrow / availability, options speculation, squeeze alert | Risk gate, sizing adjustment, or catalyst support depending on data quality. |
| `catalyst` | Earnings, guidance, PDUFA, major contract, buyback authorization, M&A, spin-off, index inclusion, event timing / decay | Catalyst factor and time-window input. Requires event dates and observed dates. |
| `momentum` | 20-day relative price strength, volume / institutional-flow proxy, market / industry relative strength, MOM-LOCK | Ranking input and risk state; high-velocity cases may route to burst-lane review. |
| `market_regime` | Macro circuit, crowd mode, defense period, FIRE-SEED scarcity state | Candidate-pool cap, sizing, and risk adjustment input. |

### 5.4 Scoring And Candidate Pool

The reference screening flow uses Tier 1 / Tier 2 output, a capped candidate pool, industry concentration checks, macro circuit adjustment, crowd mode, defensive mode, and FIRE-SEED scarcity logic.

Production contract:

- Future reports must expose final score, tier, raw factor values, adjustment labels, concentration constraints, and market-regime labels.
- Tier 1 / Tier 2 are candidate-priority labels, not automatic trade authorization.
- Tier eligibility must still pass analysis hard vetoes, bucket capital checks, and ship-gate status.
- Reference formulas can seed first configs, but future promotion requires forward evidence against benchmark and steady baseline.

## 6. Analysis Contract

### 6.1 Workflow Shape

The reference analysis flow is M1 through M6:

| Stage | Production interpretation |
|---|---|
| M1 | Macro / market environment, VIX, SPY / QQQ trend, sector momentum, concentration risk, account-level risk state. |
| M2.0 | Capital-flow and negative-flow scan: unusual options, put/call ratio, short interest, dark-pool proxy, SEC resale / issuance files. |
| M2 / M2.1 / M2.5 | Ecosystem, peer, supply-chain, and GICS contagion scan plus industry momentum / catalyst theme labels. |
| M3 | Fundamentals, earnings / guidance, analyst targets, liquidity, technical levels, ATR, IV / HV, support / resistance, risk / reward. |
| M4 | Hard veto and contradiction check. |
| M4.5 | Real-time event / filing audit for SEC, regulatory, legal, resale, dilution, and short-report overlap risk. |
| M5 | Efficiency ranking, time-window classification, star ranking, switch-candidate comparison. |
| M6 | Position sizing, conditional OrderAudit, final M6.7 report, and cross-session state handoff. |

Production contract:

- M1 and global risk state must be evaluated before per-name actions.
- Negative / veto scan runs before positive recommendation.
- Final output must be derived from earlier stages; output fields must not create new analysis.
- Stateful items must not live only in chat text once implementation starts.

### 6.2 Hard Veto And Risk Gates

US-short risk gates include:

- severe insider selling,
- bad reaction after earnings beat,
- abnormal put flow / PCR / concentrated bearish options,
- short reports or known short-attack accounting allegations,
- short-interest / borrow risk escalation,
- late-session high-volume reversal near highs,
- SEC / S-1 / S-3 / 424B / 144 dilution or resale risk,
- regulatory / legal investigation risk,
- analyst target below price or batch downgrades,
- low liquidity, extreme spread, stale data, or missing essential data,
- macro / portfolio circuit breaker state.

Production contract:

- Hard veto, sizing reduction, and review-needed outcomes must be separate enums in future schemas.
- Negative evidence has priority over positive catalyst / momentum evidence.
- Any manual override must be explicit, logged, and remain minimal-size or research-only until reviewed evidence supports otherwise.
- M4.5 event-file audit should become a stateful evidence log before implementation, not a hidden prompt-only behavior.

### 6.3 Position Sizing And Bucket Capital

The reference analysis formula sizes from total account capital. Project implementation must replace that with bucket-aware capital:

- Use the US short bucket capital ceiling from `portfolio_allocation` and `cash_buffer_state`.
- Do not size against total account AUM.
- Do not borrow US liquidity cash or US long cash unless a later coordinator rule or explicit user decision allows it.
- Do not mix A-share and US cash pools.
- Keep per-name cap, total short-bucket cap, liquidity / ADTV cap, max-position count, spread rules, and market-regime reductions visible.

All actions remain manual recommendations.

### 6.3.1 US Market Microstructure Constraints

Future US-short execution backtests and reports must explicitly model or disclose these constraints before any live-normalized evidence claim:

- SSR / uptick restriction after a prior 10% decline when a recommendation involves short-side exposure.
- Reg SHO threshold-list and hard-to-borrow / locate / borrow-fee status when the strategy depends on short availability.
- LULD bands, volatility pauses, exchange halts, stale quotes, and event-driven trading halts.
- PDT / day-trade constraints if a small account would be expected to open and close positions intraday.
- Pre-market and after-hours liquidity, spread, and event-timing limitations.
- Odd-lot and sub-penny execution caveats for low-priced or illiquid names.
- ADR, foreign-holiday, corporate-action, reverse-split, delisting, and bankruptcy workflow risks.

If a provider cannot supply a required microstructure field, the report must mark the candidate as manual evidence, research-only, or blocked for the affected action. Missing microstructure data must not silently pass.

### 6.4 Exits, Stops, And Re-entry

The reference analysis includes:

- ATR-based stops,
- support / resistance anchored stop and take-profit,
- time stop,
- no-volume decline check,
- earnings-gap IV collapse protection,
- re-entry after stopped-out positions,
- Rule 8 circuit breaker and staged recovery,
- Rule 13 risk / reward validation,
- Rule 14 open / auction recalibration,
- Rule 17 pre-market / after-hours limits,
- MAP trailing exits.

Production contract:

- Future execution backtests must simulate any deterministic exit rule before the rule can inform ship-gate evidence.
- Semantic or provider-dependent exits remain manual / research-only until structured.
- Re-entry rules require state; they must not be implemented as stateless chat advice.
- MAP exits may route to steady or burst implementation only after an explicit routing decision.

### 6.4.1 Calendar And Timezone Semantics

US-short reports must record `as_of`, decision timestamp, market session, and timezone. Default interpretation is US Eastern Time plus UTC where provider timestamps allow.

- SEC filing, guidance, earnings, downgrade, short-report, and legal-event evidence must include `event_date` and `observed_at` / `catalyst_observed_date`.
- After-close and pre-market evidence can affect only the next tradable decision point unless the report explicitly uses a pre-market / after-hours workflow with provider lineage.
- Half-days, market holidays, halted sessions, and benchmark calendar mismatches must be visible in evidence windows.
- A/US cross-market comparison must not align dates by local calendar string alone; it needs explicit market calendar alignment.

### 6.5 Output Shape

The reference output centers on M6.7:

- concise environment / risk summary,
- veto / review / warning triggers,
- sector / flow / event summary,
- risk-management trigger summary,
- final operation table,
- cross-session state handoff.

Production contract:

- A future report should expose machine-readable fields for decision, action class, tier, stage, risk labels, hard vetoes, sizing reductions, benchmark set, data lineage, and state updates.
- If a user-facing table exists, it must be generated from structured fields, not free-form reasoning.
- OrderAudit remains conditional and manual-analysis only; it does not connect to broker or OS automation.

## 7. State Requirements

US-short needs explicit state before implementation:

- candidate tier and catalyst snapshot,
- Rule 8 circuit breaker / staged recovery,
- Rule 5B / account risk baseline if retained,
- M2.1 GICS / supply-chain contagion windows,
- Rule 11 re-entry restrictions,
- Rule 7 B4 insider / put-flow overlap windows,
- historical M4.5 reviewed-file log,
- MAP activation state if retained,
- board / sector momentum snapshot freshness,
- consecutive stop count,
- forward evidence cohort IDs.

State must use project-managed files or schemas, not chat memory.

## 8. Benchmark And Evidence

US-short benchmark choice is deferred. Candidate benchmarks include:

- S&P 500 / SPY for broad US equity comparison,
- Russell 1000 for large / mid US coverage,
- Nasdaq 100 / QQQ for growth / tech-heavy candidate pools,
- sector ETF or industry benchmark for relative-strength and attribution checks.

Rules:

- Do not inherit A-short CSI1000 / CSI300 policy.
- Do not inherit `us_short_burst` gate results.
- Forward evidence follows the Phase 6a semantics: stable report process, visible monthly cohorts, mature windows separated from immature diagnostics, and rejected / failed candidates retained.
- Full-size use requires the project ship gate: monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and >=12 months forward live evidence.
- Before final benchmark choice, reports should carry benchmark candidates and the rationale for any temporary reporting benchmark.

Phase 7a-3 provisional benchmark routing is owned by `docs/provider_priority_benchmark_contract.md`. US-short steady evidence uses Russell 1000 as provisional primary reporting benchmark, with S&P 500 / SPY, Nasdaq 100 / QQQ, and sector ETF sensitivity until a reviewed final benchmark decision exists.

Before US-short can produce live-normalized evidence, the implementation contract must also define a monitoring path for provider freshness, microstructure field coverage, borrow / short-interest staleness, event-file drift, stale benchmark data, manual override frequency, and lane pause / kill-switch triggers.

## 9. Phase 6e Data Requirements Input

Phase 6e provider / data requirements audit should consume this spec and answer whether reliable providers exist for:

- US listing, corporate actions, halt / delisting / bankruptcy, reverse split, lockup and resale registration data,
- daily OHLCV, spread / liquidity, ADTV, ATR, IV / HV, and pre / post-market data if used,
- GICS industry hierarchy and point-in-time classification,
- financial statements, restatements, operating cash flow, FCF, EPS, revenue, margin, guidance, and filing dates,
- analyst consensus, target price history, revision history, and Estimize or equivalent crowdsourced estimates if retained,
- SEC filings and event dates for S-1 / S-3 / 424B / 144, 10-K / 10-Q, 8-K, and material updates,
- insider transactions and 10b5-1 context,
- options flow, put / call ratio, IV percentile, gamma / max-pain diagnostics, and dark-pool or off-exchange activity,
- short interest, borrow fee, days-to-cover, and availability,
- sector ETF / peer returns, SPY / QQQ / Russell returns, VIX, TNX, and macro regime inputs,
- news / regulatory / legal / short-report evidence with public observed dates.

Fields without reliable provider support must remain manual evidence, research-only, or deferred.

## 10. Deferred Decisions

- Exact production schema and report interface.
- Which reference thresholds become config defaults versus research-only diagnostics.
- Primary US-short benchmark.
- Whether MAP belongs in steady US-short, burst lane, or research-only.
- Whether dark-pool / options-flow data is reliable enough for production scoring.
- How much of M6.7 user-facing table should remain after structured reports exist.
- Whether Rule 5 target-account-growth logic belongs in this project, given portfolio allocation policy now uses bucket capital and ship-gate evidence.

## 11. Completion Line

US-short docs-only baseline is complete when:

1. This owner spec is routed from `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, and `docs/strategy_design_synthesis.md`.
2. The Phase 6 handoff records that US-short reference materials have been normalized into a production-facing spec owner.
3. The next hot queue no longer lists US-short spec normalization as pending baseline work.
4. No schema, runner, provider, DataHub implementation, Skill implementation, broker integration, or order automation was introduced by this slice.

## 12. Next Work

Phase 7b-1 provider evidence / drift-monitor contracts now live in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`; Phase 7b-2 has six P1 evidence snapshots through coverage / fallback / incident candidate evidence, but US-short-specific provider evidence still needs population:

1. Follow the Phase 7b-1 contract for US fundamentals / filings / security master and US event / microstructure evidence priority.
2. Populate provider evidence for US fields before US-short can rely on them for live-normalized evidence.
3. Future US-short reports should consume `schemas/evidence_report.schema.json` for immutable decision packets, manual overrides, cost-adjusted return, and position reconciliation.
