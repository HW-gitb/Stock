# Burst Lane Spec

**Status**: Phase 6c docs-only baseline with Phase 7a-4 evidence-feasibility controls. This document defines the A/US short-term `burst_lane` contract. It does not implement runners, providers, DataHub, or order execution.

**Owner role**: detailed spec owner for the short-term burst lane. `docs/strategy_design_synthesis.md` remains the strategy architecture entry; `docs/handoff/2026-05-26_phase6a_kickoff_spec_handoff.md` remains the Phase 6 boundary / evidence-routing owner.

## 1. Scope

`burst_lane` is an independent short-term alpha-source lane for A-share short and US short systems.

It exists because explosive short-term opportunities have different evidence than the steady risk-filter lane. It must not be implemented by weakening steady-lane filters, bypassing hard vetoes, or reusing A-short variant promotion evidence.

This spec covers:

- common signal families,
- minimum trigger semantics,
- A-share versus US market data-field differences,
- risk locks,
- sizing stages,
- independent ship gate,
- forward evidence and output expectations,
- data requirements to feed Phase 6e provider / data requirements audit.

Non-scope:

- No numeric factor weights or threshold constants are locked here.
- No schema version, runner, migration, or report format is introduced here.
- No provider is selected here.
- No full-size manual use is allowed from this document alone; ship gate still requires monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and >=12 months forward live evidence.
- No broker connection, OS automation, or automatic trading is allowed.

## 2. Lane Relationship

| Lane | Role | Evidence boundary |
|---|---|---|
| Steady short lane | Risk-filtered observation and decision support | Uses the existing short-system reports, hard vetoes, and bucket-aware capital context. |
| A-short bounded variants | Internal optimization of the steady A-short lane | Tracking-only comparison tracks until forward evidence supports a reviewed promotion decision. |
| `burst_lane` | Independent short-term alpha-source lane | Own signal family, risk lock, sizing gate, forward evidence, and ship gate. It does not inherit steady-lane pass/fail status. |

The burst lane may compare against steady-lane candidates and market benchmarks, but it cannot borrow a steady-lane ship gate result. A burst candidate must be explainable from burst-specific evidence.

## 2.5 Evidence Tiers

Burst lanes are split into two data tiers so implementation is not blocked by a monolithic provider gate, while pure EOD momentum is not mislabeled as full burst alpha.

| Tier | Required data | Allowed stage | Live eligibility |
|---|---|---|---|
| `minimal_data_burst` | OHLCV, volume / turnover, relative strength, benchmark context, liquidity, market mechanics, and existing candidate context | Research / paper only by default | Not live-eligible unless a later reviewed contract adds non-price confirmation and risk controls. |
| `full_data_burst` | Minimal tier plus reviewed event / catalyst / filing / guidance / capital-flow / options / borrow / short-interest or manual evidence | Paper and minimal live observation | Live-eligible only after provider/manual evidence path, bucket capital context, report path, and forward evidence capture are active. |

The first implementation may start with `minimal_data_burst` to start paper evidence. It must not describe this as production burst readiness. Minimal live observation requires `full_data_burst` or a reviewed exception that documents equivalent non-price confirmation.

Minimal-to-full promotion criteria are owned by the Phase 7a-4 contract in `docs/evidence_feasibility_controls.md` and `schemas/evidence_feasibility_controls.schema.json`. At minimum, promotion must prove benchmark-relative paper alpha, acceptable drawdown and false-positive behavior, more than pure price momentum, a credible non-price confirmation path, cost / liquidity / spread / borrow / limit-risk feasibility, retained rejected / failed candidates, and a paired comparison between minimal-only and minimal-plus-full-data evidence after full data is available.

## 2.6 Phase 7a-1 Audit Routing

The first formal audit (`docs/phase7a_alpha_plausibility_audit.json`) keeps burst lanes alive only inside their evidence maturity boundary:

| Lane | Audit verdict | Current allowed work |
|---|---|---|
| `a_share_burst_minimal_data` | `continue` | Paper / research only, using OHLCV, benchmark, liquidity, limit / halt, and existing A-short context. |
| `us_burst_minimal_data` | `continue` | Paper / research only; US OHLCV / benchmark provider readiness still needs later evidence before production claims. |
| `a_share_burst_full_data` | `defer_until_provider_ready` | Do not move to live eligibility until event / catalyst observed dates, capital-flow or manual evidence, and A-share execution constraints are reviewed. |
| `us_burst_full_data` | `defer_until_provider_ready` | Do not move to live eligibility until filings / events, options / short-interest / borrow or manual evidence, and US microstructure constraints are reviewed. |

Minimal and full tiers are maturity stages of the same parent lane. Portfolio contribution uses the active stage only; do not add minimal-tier paper contribution and full-tier hypothetical contribution together.

## 3. Candidate Lifecycle

Each burst candidate should move through this lifecycle:

1. Market, universe, and liquidity eligibility.
2. Data freshness and point-in-time eligibility.
3. Common signal-family evaluation.
4. Market-specific field interpretation.
5. Trigger sufficiency check.
6. Risk-lock check.
7. Research / paper output or minimal-size manual recommendation, depending on stage.
8. Forward evidence capture with rejected and failed candidates retained.
9. Gate review: continue, pause, downsize, promote stage, or shut down the lane.

This is a specification contract only. Future implementation can split these stages across schemas, reports, skills, runners, and state files.

## 4. Common Signal Family

Liquidity / executability and `risk_state` are hard preconditions. They do not count as positive trigger families.

| Family | Positive evidence | Failure / caution evidence |
|---|---|---|
| `volume_expansion` | Turnover or volume expands versus a rolling baseline; participation is broad enough to support manual execution. | Single illiquid spike, stale quote, extreme gap without tradable follow-through, or volume only caused by mechanical limit / halt effects. |
| `capital_inflow` | Net inflow, active-buy proxy, fund-flow proxy, breadth, or repeated accumulation evidence supports demand. | One-source flow without confirmation, mechanically high turnover from forced selling, or flow data unavailable without manual disclosure. |
| `breakout_quality` | Price clears a prior range, resistance, or consolidation with close quality and limited false-break risk. | Pure gap with no close confirmation, repeated failed breakout, chase entry after vertical exhaustion, or entry near a forced limit state. |
| `catalyst` | Policy, event, earnings, guidance, regulatory, product, industry-cycle, or company-specific evidence has a timestamp visible before the decision. | Narrative-only catalyst, later-outcome explanation, unverified rumor, catalyst already priced before entry, or no separable `event_date` / `catalyst_observed_date`. |
| `relative_strength` | Strength versus market, industry, and relevant peer set across more than one short window. | Strength is only market beta, single-day rebound, or driven by benchmark / sector move without name-level confirmation. |
| `theme_breadth` | Related theme, concept, sector, or peer group shows breadth that supports the move. | Theme is crowded, low-quality, short-lived, or only one stock without independent catalyst / flow confirmation. |
| `risk_state` | Absence of disqualifying overheat, liquidity, data, or event-risk failures. | Existing hard veto, missing critical data, overheat / chase exhaustion, abnormal halt / limit lock, or regulatory / headline risk that prevents reliable manual handling. |

Future implementations may add fields inside each family, but should not add a new family without updating this owner spec.

## 5. Trigger Contract

Before a candidate enters research / paper tracking:

1. Liquidity / executability must pass.
2. Data freshness must pass for all fields used in the trigger.
3. At least three independent positive signal families must be present.
4. At least one of `catalyst`, `capital_inflow`, or `relative_strength` should be present by default. If not, the report must explain why the trigger is still valid.
5. No hard risk lock may be active.

Independence rules:

- Multiple indicators from the same family count as one family.
- A catalyst and theme breadth count separately only when the theme has independent market breadth evidence beyond the single candidate.
- Liquidity, data quality, and `risk_state` are gates, not alpha signals.
- Missing data is not automatically negative, but missing data that is essential to the claimed trigger blocks paper entry until manually documented.

Exact numeric thresholds are deferred until provider fields, backtest surfaces, and forward evidence are available. The first implementation should expose raw and normalized values rather than hiding them behind a single opaque score.

Before a candidate enters minimal live observation, the report must also prove that the candidate is not only a minimal-data momentum case. At least one non-price confirmation source must be reviewed or manually evidenced, such as catalyst, filing/event, capital flow, options/borrow, or dated policy / company evidence.

## 6. A-Share Burst Annex

### 6.1 Data Fields

A-share `minimal_data_burst` evaluation may use:

- daily OHLCV, turnover, amount, and rolling volume / turnover baselines,
- limit-up / limit-down state, trading halt / suspension, ST status, and listing-age flags,
- industry / concept / L3 context where available,
- existing A-short candidate context from `analysis_input.json`,
- CSI1000 / CSI300 benchmark monthly returns for Phase 6 reporting until a burst-specific benchmark review changes the policy.

A-share `full_data_burst` evaluation may add:

- policy, regulatory, earnings, product, or industry-cycle catalyst evidence with observed date,
- capital-flow or northbound-flow fields if a reviewed provider makes them available,
- manual evidence with source, observed date, and reviewer/process tag.

The A-share burst lane may reuse the existing A-short benchmark return materializer as an input source for benchmark-aware reporting, but it must keep independent burst-lane evidence and ship-gate evaluation. Reusing a data source does not mean inheriting the steady A-short gate.

Phase 7a-3 provisional benchmark routing for A-share burst is owned by `docs/provider_priority_benchmark_contract.md`. It keeps CSI1000 as provisional primary reporting benchmark, CSI300 as mandatory secondary context, and SW industry attribution as a full-data sensitivity path where provider coverage supports it.

### 6.2 Market Constraints

Future A-share burst implementation must handle:

- T+1 sell constraint,
- daily price limits,
- 100-share lot sizing,
- suspension / halt and limit-lock risk,
- crowded theme and policy reversal risk,
- manual execution feasibility under bucket capital ceilings.

### 6.3 A-Share Deferred Decisions

- Exact primary benchmark for A-share burst full ship-gate evaluation if CSI1000 / CSI300 proves insufficient.
- Numeric trigger thresholds for volume expansion, breakout quality, and relative strength.
- Whether capital-flow fields are reliable enough for structured automation or remain manual evidence.
- A-share burst report interface and schema shape.

## 7. US Burst Annex

### 7.1 Data Fields

US `minimal_data_burst` evaluation may use:

- daily OHLCV, gap, intraday range summary when available, and rolling volume baselines,
- sector / industry / peer relative strength,
- benchmark candidates such as S&P 500, Russell 1000, Nasdaq 100 / QQQ, and sector ETF proxies.

US `full_data_burst` evaluation may add:

- earnings date, guidance, analyst revision, SEC filing, product / regulatory / legal event, and company news evidence with observed date,
- pre-market / after-hours context when a reviewed provider supports it,
- options, short interest, borrow, or dark-pool style fields only after provider reliability is reviewed,
- manual evidence with source, observed date, and reviewer/process tag.

Benchmark choice for US burst is deferred. Candidate benchmark set should be logged early because it affects alpha t-stat interpretation and Phase 6e provider requirements. Phase 7a-3 provisional benchmark routing is owned by `docs/provider_priority_benchmark_contract.md`: Russell 1000 is the provisional primary reporting benchmark, with S&P 500 / SPY, Nasdaq 100 / QQQ, sector ETF sensitivity, and event-specific peer attribution where available.

### 7.2 Market Constraints

Future US burst implementation must handle:

- overnight gap risk,
- no A-share-style daily price limit protection,
- spread and slippage for lower-liquidity names,
- earnings / guidance / filing event timing,
- pre-market and after-hours data lineage if used,
- LULD halts and volatility pauses,
- short-side constraints when applicable: locate / borrow availability, Reg SHO threshold list, SSR / uptick restriction after a 10% decline, and hard-to-borrow fees,
- PDT / day-trade constraints if any workflow expects same-day entry and exit in a small account,
- odd-lot, sub-penny, and extended-hours liquidity caveats,
- manual execution feasibility under the US short bucket capital ceiling.

### 7.3 US Deferred Decisions

- Primary US burst benchmark.
- Minimum liquidity / spread requirement.
- Whether options / short-interest fields are core inputs or supplemental diagnostics.
- Whether pre-market / after-hours evidence is accepted in production or only in research.
- US burst report interface and schema shape.

### 7.4 Calendar And Timezone Semantics

Future burst reports must record decision timestamps with market-local calendar context and UTC where available:

- A-share burst uses China Standard Time, the SSE / SZSE trading calendar, T+1 sell constraints, and limit-state evidence as of the decision date.
- US burst uses US Eastern Time for regular, pre-market, and after-hours context, with explicit market session labels (`pre_market`, `regular`, `after_hours`, `closed`).
- Filing, earnings, guidance, policy, and manual evidence must record both `event_date` and `observed_at` / `catalyst_observed_date`; after-close events must not be treated as available before the next tradable decision point.
- Cross-market comparisons must state the calendar used for benchmark alignment. A/US holidays and half-days cannot be silently forward-filled into evidence windows.

## 8. Risk Lock

The burst lane must be stricter than the steady lane because it targets faster, higher-variance moves.

Required rules:

- No averaging down by default.
- Time stop must be harder than the steady lane; exact holding windows are deferred to implementation evidence.
- Breakout failure must trigger fast exit / reject logic.
- Position sizing must respect future concentration and liquidity / ADV limits before any live-normalized evidence claim.
- Market impact, spread, borrow, halt, and limit-lock feasibility must be part of promotion and sizing evidence.
- Trailing stop or equivalent give-back control must be defined before minimal-size manual recommendations.
- No immediate re-entry after a failed burst trigger without a new catalyst or new independent signal evidence.
- Per-name cooldown and weekly trade-count cap are required before any minimal-size live observation.
- Lane-level pause is required after repeated mature evidence underperforms baseline / benchmark without documented regime explanation.
- Halt, limit-lock, stale data, or missing liquidity evidence blocks new entry.

The lane-level pause rule should be falsifiable. A default starting point is six consecutive mature monthly cohorts or review windows underperforming baseline / benchmark, but the exact measurement window belongs in the first reviewed implementation contract.

### 8.1 Monitoring Contract

Before any burst lane can produce live-normalized evidence, its implementation contract must define:

- data freshness and provider-drift checks for every trigger family used,
- stale / missing critical-field behavior,
- daily or weekly lane health output showing coverage, rejected candidates, failed breakouts, slippage assumptions, and limit / halt incidents,
- lane-level pause / kill-switch trigger, manual review requirement, reactivation rule, and cooldown,
- incident log requirements for provider outage, field semantic change, calendar mismatch, or execution infeasibility.

Monitoring is required for live-normalized evidence. It does not authorize automatic orders or broker integration.

## 9. Sizing And Promotion

Sizing is per relevant market short bucket, not global AUM.

| Stage | Maximum sizing | Required evidence |
|---|---:|---|
| Research / paper | May simulate up to 30% of the relevant short bucket | Trigger and risk-lock contract followed; no manual live sizing implied. |
| Minimal live observation | <=10% of the relevant short bucket | Reviewed report path, manual-only boundary, bucket capital context, and forward evidence capture are active. |
| 6-month preliminary pass | <=20% of the relevant short bucket | Falsifiable 6-month review: positive or acceptable benchmark-relative evidence, drawdown not worse than allowed preliminary limit, enough mature observations, and no unresolved risk-lock breach. |
| 12-month independent ship-gate pass | <=30% of the relevant short bucket | Monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and >=12 months forward live evidence. |

The 6-month preliminary pass is not "six months elapsed." It requires a reviewed evidence packet. Exact numeric preliminary thresholds are deferred, but the evidence packet must include alpha, Sharpe or risk-adjusted proxy, drawdown, coverage / mature observations, benchmark sensitivity, and capital-context status.

Full-size manual use remains blocked until the independent 12-month ship gate passes. A steady-lane or A-short variant pass does not unlock burst-lane full-size use.

## 10. Evidence And Output Expectations

Burst evidence uses the Phase 6a forward-evidence semantics: decisions must be logged after the report process is stable, mature windows must be separable from immature diagnostics, and monthly cohorts must be visible for ship-gate interpretation.

Future burst output should expose:

- market and lane (`a_short_burst` or `us_short_burst`),
- candidate universe and eligibility result,
- raw signal-family evidence and pass / fail state,
- trigger-family count and independence explanation,
- market-specific data fields used,
- catalyst `event_date` and `catalyst_observed_date` when applicable,
- risk-lock result,
- recommended stage (`research_paper`, `minimal_live_observation`, `preliminary_pass_candidate`, `ship_gate_candidate`, or `reject`),
- bucket capital ceiling and sizing cap,
- benchmark set used for reporting,
- rejected-candidate and failed-breakout reasons.

Rejected and failed candidates are part of the evidence set. Do not log only winners.

## 11. Phase 6e Data Requirements Input

Phase 6e provider / data requirements audit should consume this spec and answer:

- Which A-share provider fields can support volume, amount, turnover, limit state, suspension, concept / industry, and capital-flow evidence?
- Which US provider fields can support earnings / guidance / SEC filing events, volume / gap, sector / peer relative strength, and optional pre-market / options / short-interest diagnostics?
- Which fields have point-in-time availability and which are latest-only?
- Which fields require manual evidence rather than structured automation?
- What history depth is needed for rolling baselines and benchmark-relative validation?
- Which provider costs, authorization limits, stability risks, and fallback rules block implementation?

DataHub Phase 7 should not implement burst-lane production plumbing until this data-requirements audit has a reviewed baseline.

## 12. Completion Line

Phase 6c docs-only baseline is complete when:

1. This owner spec is routed from `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, and `docs/strategy_design_synthesis.md`.
2. The Phase 6 handoff records that burst lane scope is docs-only and independent from steady-lane gates.
3. The next hot queue no longer lists A/US burst spec as pending baseline work.
4. No schema, runner, provider, DataHub implementation, broker integration, or order automation was introduced by this slice.

## 13. Next Work

Phase 7b-1 provider evidence / drift-monitor contracts now live in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`; Phase 7b-2 still needs actual provider evidence population:

1. Follow the Phase 7b-1 contract for event / flow / options / borrow evidence priority and drift-monitor dimensions.
2. Populate provider evidence for event, flow, options, borrow, observed-date support, cost, fallback, and stability before any full-data burst implementation can rely on those fields.
3. Future burst reports should consume `schemas/evidence_report.schema.json` for immutable decision packet, cost-adjusted return, manual override, and minimal reconciliation fields.
