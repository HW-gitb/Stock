# Strategy Design Synthesis

**Status**: user-approved design direction, revised 2026-05-28 with Phase 7a-4 evidence feasibility controls.
**Scope**: four-system strategy architecture after Phase 5 execution aggregation.
**Authority**: this document explains the design; `AGENTS.md` carries the binding summary for all LLM collaborators.

## 1. Final Framing

The stock system is not an "always maximize short-term hit rate" engine. The production system's first job is:

- disciplined risk control,
- reproducible evidence,
- manual decision support,
- prevention of silent full-size deployment before evidence exists.

Alpha improvement is still a real goal, but it is split by horizon:

- **Short-term systems**: keep steady lanes as risk filters / evidence loops, run variants for bad-ticket and drawdown reduction, and make controlled burst lanes the short-term alpha candidates.
- **Long-term systems**: become the main alpha-push layer only when each candidate has an expected-alpha thesis, benchmark-relative opportunity cost, and provider/PIT evidence.
- **Research layer**: explore faster ideas without contaminating production contracts.
- **Coordinator layer**: reconcile cash, drawdown, bucket usage, and extreme-risk locks across all four systems.

This preserves the user's constraints:

- A-share / US market allocation is `35% / 65%`.
- Within each market: `1/3 long + 1/3 short + 1/3 liquidity`.
- A-share cash and US cash are non-fungible by default.
- The system outputs analysis, screening, backtests, reviews, and recommendations only; the user manually places orders.
- Full-size manual use still requires multi-metric AND ship gate: monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and forward live data >= 12 months.

## 1.5 Alpha Validation Upgrade

The design now inserts a Phase 7a alpha-validation layer before broad DataHub / runner implementation.

Required owners:

- `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`: current Phase 7a+ highest action guide. It lists alpha-reality guardrails, accepted business gaps, and their roadmap placement. It supersedes older roadmap wording except for fixed governance in `AGENTS.md`.
- `docs/alpha_plausibility_audit.md`: system-level audit of lane objective, expected excess return, volatility, drawdown, data readiness, PIT/provider blockers, detectability horizon, and portfolio-level contribution.
- `docs/evidence_capital_policy.md`: evidence-level policy separating `paper` evidence from `live_normalized` evidence without changing fixed capital allocation.

The audit must be schema-first before it can drive implementation decisions. Each lane receives one verdict: continue, continue as risk filter, redesign required, defer until provider ready, or do not implement now.

The Phase 7a-1 audit schema must also capture alpha-reality guardrails: hypothesis registration, multiple-testing risk, statistical power, survivorship and security-master status, fraud/accounting red flags for long lanes, regime sensitivity, factor framework, gross versus net alpha, execution feasibility, risk-filter effectiveness, parent-lane aggregation, correlation basis, and capital-deployment effect.

The first formal audit artifact is `docs/phase7a_alpha_plausibility_audit.json` (`audit_run_id = alpha_audit_20260527_initial`). Its current verdicts are now the Phase 7a-2 routing baseline:

| Parent / lane | Current verdict | Practical effect |
|---|---|---|
| A-short steady | `continue_as_risk_filter` | Continue as risk-filter / evidence loop; do not treat as push-alpha lane. |
| A-short variants | `continue_as_risk_filter` | Continue bounded comparison tracks; no independent bucket or production promotion without forward evidence. |
| US-short steady | `continue_as_risk_filter` | Continue as risk-filtered support only after US microstructure and provider requirements are specified. |
| A / US minimal-data burst | `continue` | Continue paper / research only; no live sizing from minimal-data momentum alone. |
| A / US full-data burst | `defer_until_provider_ready` | Plausible alpha source, but live eligibility waits for event / flow / options / borrow / manual-evidence readiness. |
| A / US long lanes | `defer_until_provider_ready` | Plausible long-alpha lanes, but implementation waits for PIT fundamentals, survivorship / security-master, benchmark, and fraud red-flag evidence. |

This audit is not ship-gate evidence. It routes spec revisions and provider sequencing only.

This upgrade reverses the older next-step assumption that Phase 7 should first spend implementation attention on already-proven A-share EOD / benchmark surfaces. Those surfaces remain valuable as ready evidence, but provider and schema work should now be ordered by alpha leverage and data blockers. The Phase 7a-3 owner contract is `docs/provider_priority_benchmark_contract.md`.

1. US fundamentals, filing dates, corporate actions, and US benchmark/security-master readiness.
2. A-share fundamentals, announcement dates, SW industry history, and A-long benchmark/industry attribution readiness.
3. Burst event / flow / options / borrow fields, classified as structured, manual evidence, research-only, or deferred.
4. Already-proven A-share EOD / CSI benchmark surfaces recorded as ready evidence, not the default next implementation sink.

The same Phase 7a-3 contract defines provisional evidence benchmarks for A-short, A/US burst, US-short, A-long, and US-long. These benchmarks start evidence accumulation and sensitivity reporting only. They do not finalize ship-gate benchmarks or convert paper evidence into live-normalized evidence.

Phase 7a-4 evidence feasibility controls are defined in `docs/evidence_feasibility_controls.md` and `schemas/evidence_feasibility_controls.schema.json`. They lock burst minimal-to-full promotion evidence, concentration / liquidity / ADV sizing, slippage / borrow / limit-risk feasibility, and drawdown / circuit-breaker playbooks without provider selection, data fetch, runner changes, or ship-gate relaxation.

Phase 7a-5 evidence report schemas are defined in `docs/evidence_report_schema_contract.md` and `schemas/evidence_report.schema.json`. They lock immutable decision packets, cost-adjusted return details, cash drag, manual overrides, minimal reconciliation, thesis outcome logs, and research experiment logs without provider selection, data fetch, runner changes, or ship-gate relaxation.

## 2. Short-Term Architecture

Short-term is a two-lane system, not a single relaxed risk model.

### 2.1 Steady Short Lane

The steady short lane keeps the existing A-short direction but is treated as a permanent risk filter / evidence loop unless future forward evidence explicitly overturns that role:

- rank / filter / analyze candidates,
- prefer Tier1 evidence,
- reject or downgrade known bad signals,
- keep manual-order-only boundaries,
- evaluate with bucket-aware capital context,
- treat full-size as blocked until ship gate passes.

It is a risk-filtered observation and decision-support lane, not an automatic buy list and not the primary short-term push-alpha engine.

Phase 7a-1 audit status: A-short steady and US-short steady are both `continue_as_risk_filter`. Their evidence value is drawdown, bad-ticket, false-positive / false-negative, and execution-quality control. They do not receive live alpha sizing from this verdict.

### 2.2 A-Short Optimization Variants

Do not rewrite the production strategy after one 24-period finding. Run bounded variants in parallel and promote only with evidence.

Initial variant set is capped at six families:

1. `chasing_high_veto`: entry flag "追高风险，周一确认" as a veto candidate.
2. `overheat_veto`: OVERHEAT as a veto candidate.
3. `tier1_only_trading`: Tier2 remains observation-only and does not enter trading evidence.
4. `esp_cap_or_winsorize`: cap / winsorize extreme positive ESP and high base-effect growth; do not hard veto yet.
5. `rank_bucket_split`: Top 1-5 / 6-10 / 11-15 tracked separately.
6. `exit_policy_variants`: 10d time stop baseline vs 5d time stop vs 5d profit-take vs trailing-stop variants.

Promotion rules:

- Each variant needs at least 12 forward observations before promotion decisions.
- Compare against the current baseline, not just absolute return.
- Candidate promotion requires materially better risk-adjusted evidence, such as Sharpe improving by at least 0.5, alpha t-stat improving by at least 0.5, and drawdown not worsening.
- Promote at most one variant family per review round.
- Shut down or redesign-review a variant after four consecutive mature forward observations underperforming baseline unless there is a documented regime explanation.

Important non-decisions:

- The 5d positive signal is not enough to hard-code a 5d take-profit rule. A-share short returns are right-skewed; early profit-taking can cut off rare winners.
- ESP extreme positive values are not yet a hard veto. Use cap / winsorize / downgrade variants first.
- LOCK remains observation-only until sample size is meaningful.
- No current variant is deprecated solely from the existing 24-period evidence; insufficient sample directions remain tracking-only until forward evidence resolves them.

Phase 7a-1 audit status: A-short variants remain `continue_as_risk_filter` and belong under the A-short steady parent lane. They are optimization tracks, not parallel alpha lanes, and must not consume independent capital allocation.

### 2.3 Burst Lane

The burst lane exists because explosive short-term opportunities are different from steady rank selections. It targets catalyst + volume + relative-strength bursts, but it must not bypass evidence gates.

Burst lane entry is a separate signal family. It does not inherit the steady lane's ship-gate result.

Burst implementation is split into two evidence tiers:

- `minimal_data_burst`: uses OHLCV, volume / turnover, relative strength, benchmark context, limit / halt status, liquidity, and existing candidate context. This tier is paper / research only by default.
- `full_data_burst`: adds reviewed event, catalyst, filing, guidance, capital-flow, options, borrow / short-interest, or manual evidence. This tier is required before minimal live observation.

Pure EOD momentum must not be described as full burst alpha. Non-price confirmation is required before live observation.

Phase 7a-1 audit status: minimal-data A / US burst tiers may continue as paper / research only; full-data A / US burst tiers are `defer_until_provider_ready`. Minimal and full tiers are maturity stages of the same parent burst lane, not additive portfolio alpha contributions.

Candidate trigger design:

- volume expansion,
- concentrated capital inflow,
- breakout quality,
- concept / theme heat,
- fundamental or event catalyst,
- relative strength versus market and industry,
- liquidity sufficient for manual execution.

At least three independent conditions should be required before a burst candidate enters paper / research tracking. Exact data fields and thresholds belong in the later burst-lane spec.

Risk lock:

- harder time stop than steady lane,
- trailing or breakout-failure stop,
- no averaging down by default,
- lane-level pause after repeated losses,
- weekly trade count cap,
- independent ship gate.

Sizing gate uses per-market short bucket math:

| Stage | Allowed sizing |
|---|---|
| Research / paper | May simulate up to 30% of the relevant short bucket |
| Minimal live observation | Up to 10% of the relevant short bucket |
| 6-month preliminary pass | Up to 20% of the relevant short bucket |
| 12-month independent ship-gate pass | Up to 30% of the relevant short bucket |

The 6-month preliminary pass must be falsifiable and defined in the Phase 6c burst-lane spec. It cannot be a passive "six months elapsed" promotion. The detailed Phase 6c baseline now lives in `docs/burst_lane_spec.md`; exact preliminary threshold numbers are still deferred to the first reviewed implementation contract.

Per-market examples:

- A-share burst lane at 10% of A-short bucket = `35% * 1/3 * 10% ~= 1.17%` total portfolio.
- US burst lane at 10% of US-short bucket = `65% * 1/3 * 10% ~= 2.17%` total portfolio.
- Do not describe "10% short bucket" as `3.33% total AUM` unless explicitly referring to a combined global short bucket. The project policy is per-market buckets.

## 3. Long-Term Alpha System

Long-term systems are the primary alpha-push layer. They do not reuse short-term v14.x frameworks.

Long alpha now requires an `expected_alpha_thesis` for each candidate before it can leave research-only status. The thesis must explain benchmark-relative opportunity cost, quality edge, valuation gap or compounding path, catalyst / re-rating path, downside path, sizing rationale, and review / invalidation trigger.

Phase 7a-1 audit status: all A-long and US-long sub-lanes are currently `defer_until_provider_ready`. They remain the intended push-alpha design, but no long lane should move into implementation or live sizing until PIT fundamentals, security-master / survivorship coverage, observed-date catalyst evidence, benchmark data, and fraud / accounting red-flag coverage are reviewed.

Current active alpha-search route after the A-short 5d repair: only A-long is an active workstream, but it is blocked at data integrity, not ready for signals. `research/results/a_long_data_integrity_audit_20260603/audit_report.json` passed 6 planted-violation self-tests, then returned `blocked_missing_required_source` because raw PIT fundamentals, full PIT universe, dividend / total-return treatment, and terminal delisting return lineage are missing. `docs/a_long_tushare_data_route_repair_plan_20260603.json` now fixes the next repair attempt as existing-account Tushare route validation first, but it still authorizes no fetch, no audit rerun, and no signal search. A-short 5d stays forward-observation-only / no rescue; US stays active-only forward validation in the background.

### 3.1 Two Long-Term Lanes

Long-term should be built as two lanes:

1. **Core quality compounding**
   - durable ROIC / ROE relative to industry,
   - free cash flow quality,
   - balance-sheet resilience,
   - moat / pricing power,
   - management capital allocation,
   - long-term reinvestment runway.

2. **Re-rating / catalyst long**
   - quality asset temporarily mispriced,
   - valuation mean reversion,
   - earnings inflection,
   - industry-cycle reversal,
   - policy or company-specific catalyst,
   - guidance / analyst revision / buyback evidence.

### 3.2 A-Long Emphasis

A-share long-term rule pack should emphasize:

- financial statement reliability,
- operating cash flow versus net profit,
- policy and regulatory risk,
- industry cycle and pricing indicators,
- dividend / buyback capacity,
- balance-sheet stress,
- valuation versus own industry history,
- whether apparent cheapness is cyclical peak earnings.

### 3.3 US-Long Emphasis

US long-term rule pack should emphasize:

- ROIC and FCF margin,
- revenue durability,
- moat and pricing power,
- 10-K / 10-Q risk changes,
- guidance credibility,
- buyback efficiency,
- net debt / EBITDA,
- rate sensitivity,
- valuation versus growth durability.

### 3.4 Industry Normalization

Do not use one absolute threshold across all industries.

Initial normalization policy:

- A-share: SW L2 as default; fall back to SW L1 if sample size is below 20.
- US: GICS industry as default; fall back to GICS industry group if sample size is below 20.
- Rolling history window: five years by default.
- Cyclical industries require cycle-aware interpretation; low PE at cyclical peak is not automatically cheap.
- Financials, utilities, technology, healthcare, consumption, and cyclicals require separate rule-pack adjustments.

Example: "ROE is above the industry's five-year median and stable" is safer than "ROE >= 12%" as a universal rule.

### 3.5 Long-Term Exit Logic

Long-term exits are not short-term ATR stops.

Exit triggers should be based on:

- thesis broken,
- fundamental deterioration,
- valuation extreme versus growth / cash flow,
- capital allocation quality deterioration,
- industry cycle reversal,
- risk event invalidating the original premise,
- scheduled quarterly review.

A safety net drawdown rule may exist, but it should be a risk-control override, not the primary long-term sell rule.

## 4. Research Layer

Research exists to move faster than production without creating shadow production code.

Suggested structure:

```text
research/
├── experiments/
│   ├── short_variants/
│   ├── burst_lane/
│   ├── long_quality_value/
│   ├── regime_detection/
│   └── ml_factor_search/
├── notebooks/
└── promotion_log.md
```

Research rules:

- Experiments may iterate faster and do not require full multi-LLM review for every scratch change.
- Every experiment that may influence production must record data lineage, date range, parameters, random seed when applicable, and output path.
- Any experiment that may influence production must follow the preregistration and test-budget rules in `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`: a single frozen test may proceed from a preregistration artifact, but any promotion-relevant parameter / variant / benchmark / holding-period search requires a singleton program-level test-budget ledger first.
- Research outputs must not directly feed production runners.
- Promotion into production requires schema-first contract, tests, review, and documented evidence.

Promotion gate:

- sample-out or walk-forward evidence,
- forward evidence when applicable,
- no hidden lookahead,
- reproducible data lineage,
- comparison against baseline,
- review-approved production contract.

## 5. Cross-System Coordinator

The coordinator is required for four-system coexistence, but it should begin as a spec, not an immediate implementation.

Responsibilities:

- read the four system states,
- summarize market and bucket capital usage,
- track drawdowns per system and total portfolio,
- track cash requests and liquidity reserve pressure,
- detect extreme drawdown lock conditions,
- generate manual recommendation reports.

Non-goal:

- no automatic fund transfer,
- no broker integration,
- no OS automation,
- no silent cross-market cash mixing.

## 6. Revised Phase Route

Execution principle: **spec-parallel / implementation-gated**.

Spec work may proceed in multiple reviewable docs-only slices because it defines contracts, factor catalogs, data requirements, PIT rules, exit logic, benchmark policy, and promotion gates. Implementation work remains single-threaded through the normal multi-LLM `执行 -> 审查 -> 修复 -> 提交` loop. This route revision must not lower ship gates, skip A-short forward evidence, or treat DataHub engineering as alpha evidence.

### Phase 6a - Boundary Kickoff

Define:

- forward evidence source,
- benchmark monthly return source,
- forward tracker to aggregate-report flow,
- steady lane / variant / burst lane boundaries,
- long spec deliverables,
- what still counts only as backtest plumbing.

### Phase 6b - A-Short Maintenance / Evidence Line

Keep A-short alive as the current proven sample loop, but no longer let it consume all design attention.

Allowed work:

- weekly forward capture,
- comparison-track accumulator,
- forward evidence accumulation,
- minimal fixes required to keep the evidence clock running.

Do not expand new A-short helper tools unless they directly serve the evidence clock. A-short variants are steady-lane internal optimization, not the primary source of new short-term alpha. If forward evidence shows a promotable alpha signal, raise an explicit escape-valve review before reallocating implementation capacity back to A-short.

### Phase 6c - Burst Lane Spec

Write the A/US burst lane contract as the short-term alpha-source spec:

- signal inputs,
- trigger logic,
- market-specific data field differences,
- risk locks,
- sizing stage gates,
- independent ship gate,
- research / paper output format.

Detailed burst-lane ownership now lives in `docs/burst_lane_spec.md`. This synthesis document keeps the route and architecture only.

### Phase 6d - Long Alpha Spec Pack And US-Short Normalization

Write long-term specs as alpha-push systems and normalize US-short before DataHub implementation:

- long alpha common spec: factor catalog, PIT rules, industry normalization, quality / cash-flow / valuation / catalyst factors, portfolio construction, thesis-broken exits, quarterly review cadence, benchmark and walk-forward validation requirements,
- A-long annex: SW L2, A-share financial reliability, operating cash flow versus net profit, policy / cycle / dividend / buyback considerations, A-share benchmarks,
- US-long annex: GICS, 10-K / 10-Q, FCF margin, ROIC, buyback efficiency, guidance credibility, US benchmarks,
- US-short normalization: convert the existing US-short references into a spec shape parallel to A-short.

Detailed long-alpha ownership, including the A-long and US-long annex skeletons, now lives in `docs/long_alpha_spec.md`. Detailed US-short normalization ownership now lives in `docs/us_short_spec.md`. This synthesis document keeps the route and architecture only.

### Phase 6e - Provider / Data Requirements Audit

List the data requirements that the four-system spec pack creates:

- required fields,
- PIT and as-of semantics,
- frequency and history depth,
- provider/API lineage,
- authorization, cost, stability, and fallback constraints.

This audit defines what Phase 7 must support. It does not lock final provider choices by itself.

Detailed Phase 6e ownership now lives in `docs/provider_data_requirements_audit.md`. This synthesis document keeps the route and architecture only.

### Phase 7a-1 - Alpha Validation Schema And First Audit

Before broad DataHub implementation, write the alpha plausibility audit schema, example, tests, lightweight provider status snapshot, and first audit. Mandatory field groups are defined in `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`.

This is still implementation-gated. It does not relax ship gate, select providers, fetch data, or change production strategy rules.

### Phase 7a-2 Through 7a-5 - Evidence Contracts Before Implementation

Split the post-audit work into small reviewed slices:

- Phase 7a-2: revise long / short specs; add US microstructure, monitoring contract, calendar and timezone semantics.
- Phase 7a-3: provider priority reorder and provisional benchmark contract.
- Phase 7a-4: burst minimal-to-full promotion criteria, evidence capital schema, concentration limits, liquidity / ADV sizing, slippage constraints, and drawdown / circuit-breaker tiered action playbook in `docs/evidence_feasibility_controls.md`.
- Phase 7a-5: evidence report schemas, immutable decision packet, cost-adjusted return details, cash drag, manual override, minimal reconciliation, long thesis outcome log, and research experiment log in `docs/evidence_report_schema_contract.md` and `schemas/evidence_report.schema.json`.

### Phase 7b / 7c - Provider Evidence And DataHub

Phase 7b-1 provider evidence and drift-monitor contracts are defined in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`. Phase 7b-2 has six P1 snapshots through `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`, the readiness matrix in `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`, the access-decision / sample-validation plan in `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json`, and the narrow 2026-06-02 sample approval in `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json`; P1 remains partial / blocked until that small sample is executed, summarized, and reviewed. Phase 7c designs the DataHub shared layer, report contracts, reproducibility plumbing, and data quality monitor before broad implementation.

### Phase 7 - DataHub / Engine Modularization

Use the four specs plus the provider/data requirements audit to split shared engine from independent rule packs:

- shared: data providers, validation, cache/retry, backtest skeletons, utility code,
- independent: factors, scoring, analyzers, risk model, position sizing, exits.

The first Phase 7 schema-first baseline is `schemas/provider_capability_catalog.schema.json`, which records provider capability and field requirements without selecting a provider, fetching data, adding adapters, or creating DataHub tables.

### Phase 7.5 - Research Infrastructure

Create or expand `research/` structure, minimal experiment logging, and promotion policy after the Phase 7a scope is clear. Early research is allowed only through logged, isolated experiments with preregistration; it must not feed production runners directly. The original A-share `minimal_data_burst` preregistration in `research/preregistrations/a_share_minimal_data_burst_20260531.json` is `BLOCKED_DO_NOT_RUN`; the corrected-basis supersession in `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json` has a zero-event preflight result and must not be run for outcome / excess calculation. Any redesigned A-share burst test must route through `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` and a new reviewed preregistration.

### Phase 8+

Implement the four systems based on `capital weight × alpha leverage × data readiness`, not a hard-coded market order. Default tendency is US-long first because it has the largest single bucket and is a long-term alpha system; if US provider or fundamentals readiness is insufficient, A-long or US-short burst may move ahead. Do not let A-short implementation remain the only mature subsystem. Each lane implementation must include production monitoring, degradation detection, and a kill-switch / pause path before it can produce live-normalized evidence.

### Phase 9+

Write and then implement cross-system coordinator once the four systems have enough state shape to coordinate. Coordinator scope includes unified daily / weekly reports, cross-lane conflict resolution, alert priority, full position reconciliation, and manual override visibility.

## 7. Invalidated Or Refined Prior Ideas

- "Short-term should be optimized into the main alpha engine" is rejected. Short-term stays risk-filtered and evidence-gated.
- "Burst lane can start at 30% of the short bucket in production" is rejected. It needs staged sizing and independent evidence.
- "5d alpha means hard-code 5d take-profit" is rejected. It becomes a variant.
- "ESP extreme positive should immediately become hard veto" is rejected. Start with cap / winsorize / downgrade variants.
- "Long-term uses absolute ROE / ROIC / PE thresholds" is rejected. Use industry-normalized thresholds.
- "Research does not need governance" is rejected. Research review cadence is lighter, but reproducibility and promotion gates are mandatory.

## 8. Next Execution Implication

Phase 7a-1 is complete as a reviewed audit chain: schema contract, lightweight provider status snapshot, and first formal audit artifact. The current execution path is:

1. Phase 7a-2: owner-spec routing for long, steady short, US-short, and burst lanes is complete.
2. Phase 7a-3: provider priority and provisional benchmark contract is defined in `docs/provider_priority_benchmark_contract.md`.
3. Phase 7a-4: evidence feasibility controls are defined in `docs/evidence_feasibility_controls.md` and `schemas/evidence_feasibility_controls.schema.json`.
4. Phase 7a-5: evidence report schemas are defined in `docs/evidence_report_schema_contract.md` and `schemas/evidence_report.schema.json`.
5. Phase 7b-1: provider evidence / drift-monitor schema-first contract is defined in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`.
6. Phase 7b-2: continue provider capability evidence in the P1-P4 queue; do not treat the P1 public-source, market-data-candidate, authorization / cost / stability, benchmark / GICS, fundamentals observed-date, coverage / fallback / incident snapshots, or readiness review matrix as provider selection or implementation readiness.
7. Phase 7c: design the DataHub shared-layer / report / reproducibility contract that consumes reviewed Phase 7b-2 provider evidence and drift-monitor dimensions.

A-short continues as maintenance / evidence accumulation while Phase 7 contracts are written. Do not rewrite `A-EGS/egs_main.py`, add a US provider adapter, fetch provider data, or build DataHub tables before the relevant provider-evidence and DataHub implementation contracts are reviewed.
