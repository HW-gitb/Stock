# Strategy Design Synthesis

**Status**: user-approved design direction, 2026-05-26.
**Scope**: four-system strategy architecture after Phase 5 execution aggregation.
**Authority**: this document explains the design; `AGENTS.md` carries the binding summary for all LLM collaborators.

## 1. Final Framing

The stock system is not an "always maximize short-term hit rate" engine. The production system's first job is:

- disciplined risk control,
- reproducible evidence,
- manual decision support,
- prevention of silent full-size deployment before evidence exists.

Alpha improvement is still a real goal, but it is split by horizon:

- **Short-term systems**: improve current rule-based filters, run variants, and add a controlled burst lane for explosive opportunities.
- **Long-term systems**: become the main alpha-push layer through quality, valuation, cash flow, cycle, and catalyst research.
- **Research layer**: explore faster ideas without contaminating production contracts.
- **Coordinator layer**: reconcile cash, drawdown, bucket usage, and extreme-risk locks across all four systems.

This preserves the user's constraints:

- A-share / US market allocation is `35% / 65%`.
- Within each market: `1/3 long + 1/3 short + 1/3 liquidity`.
- A-share cash and US cash are non-fungible by default.
- The system outputs analysis, screening, backtests, reviews, and recommendations only; the user manually places orders.
- Full-size manual use still requires multi-metric AND ship gate: monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and forward live data >= 12 months.

## 2. Short-Term Architecture

Short-term is a two-lane system, not a single relaxed risk model.

### 2.1 Steady Short Lane

The steady short lane keeps the existing A-short direction:

- rank / filter / analyze candidates,
- prefer Tier1 evidence,
- reject or downgrade known bad signals,
- keep manual-order-only boundaries,
- evaluate with bucket-aware capital context,
- treat full-size as blocked until ship gate passes.

It is a risk-filtered observation and decision-support lane, not an automatic buy list.

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
- Candidate promotion requires materially better risk-adjusted evidence, such as Sharpe improving by at least 0.3 and alpha t-stat improving without worse drawdown.
- Promote at most one variant family per review round.
- Shut down a variant after six consecutive forward observations underperforming baseline unless there is a documented regime explanation.

Important non-decisions:

- The 5d positive signal is not enough to hard-code a 5d take-profit rule. A-share short returns are right-skewed; early profit-taking can cut off rare winners.
- ESP extreme positive values are not yet a hard veto. Use cap / winsorize / downgrade variants first.
- LOCK remains observation-only until sample size is meaningful.

### 2.3 Burst Lane

The burst lane exists because explosive short-term opportunities are different from steady rank selections. It targets catalyst + volume + relative-strength bursts, but it must not bypass evidence gates.

Burst lane entry is a separate signal family. It does not inherit the steady lane's ship-gate result.

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

The 6-month preliminary pass must be falsifiable and defined in the Phase 6c burst-lane spec. It cannot be a passive "six months elapsed" promotion. The Phase 6c spec should define explicit preliminary criteria, such as weaker-than-full ship-gate thresholds for alpha, Sharpe, drawdown, and live-month coverage; exact numbers are not locked here.

Per-market examples:

- A-share burst lane at 10% of A-short bucket = `35% * 1/3 * 10% ~= 1.17%` total portfolio.
- US burst lane at 10% of US-short bucket = `65% * 1/3 * 10% ~= 2.17%` total portfolio.
- Do not describe "10% short bucket" as `3.33% total AUM` unless explicitly referring to a combined global short bucket. The project policy is per-market buckets.

## 3. Long-Term Alpha System

Long-term systems are the primary alpha-push layer. They do not reuse short-term v14.x frameworks.

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

### Phase 6d - Long Alpha Spec Pack And US-Short Normalization

Write long-term specs as alpha-push systems and normalize US-short before DataHub implementation:

- long alpha common spec: factor catalog, PIT rules, industry normalization, quality / cash-flow / valuation / catalyst factors, portfolio construction, thesis-broken exits, quarterly review cadence, benchmark and walk-forward validation requirements,
- A-long annex: SW L2, A-share financial reliability, operating cash flow versus net profit, policy / cycle / dividend / buyback considerations, A-share benchmarks,
- US-long annex: GICS, 10-K / 10-Q, FCF margin, ROIC, buyback efficiency, guidance credibility, US benchmarks,
- US-short normalization: convert the existing US-short references into a spec shape parallel to A-short.

Detailed long-alpha ownership now lives in `docs/long_alpha_spec.md`. This synthesis document keeps the route and architecture only.

### Phase 6e - Provider / Data Requirements Audit

List the data requirements that the four-system spec pack creates:

- required fields,
- PIT and as-of semantics,
- frequency and history depth,
- provider/API lineage,
- authorization, cost, stability, and fallback constraints.

This audit defines what Phase 7 must support. It does not lock final provider choices by itself.

### Phase 7 - DataHub / Engine Modularization

Use the four specs plus the provider/data requirements audit to split shared engine from independent rule packs:

- shared: data providers, validation, cache/retry, backtest skeletons, utility code,
- independent: factors, scoring, analyzers, risk model, position sizing, exits.

### Phase 7.5 - Research Infrastructure

Create `research/` structure, minimal experiment logging, and promotion policy.

### Phase 8+

Implement the four systems based on `capital weight × alpha leverage × data readiness`, not a hard-coded market order. Default tendency is US-long first because it has the largest single bucket and is a long-term alpha system; if US provider or fundamentals readiness is insufficient, A-long or US-short burst may move ahead. Do not let A-short implementation remain the only mature subsystem.

### Phase 9+

Write and then implement cross-system coordinator once the four systems have enough state shape to coordinate.

## 7. Invalidated Or Refined Prior Ideas

- "Short-term should be optimized into the main alpha engine" is rejected. Short-term stays risk-filtered and evidence-gated.
- "Burst lane can start at 30% of the short bucket in production" is rejected. It needs staged sizing and independent evidence.
- "5d alpha means hard-code 5d take-profit" is rejected. It becomes a variant.
- "ESP extreme positive should immediately become hard veto" is rejected. Start with cap / winsorize / downgrade variants.
- "Long-term uses absolute ROE / ROIC / PE thresholds" is rejected. Use industry-normalized thresholds.
- "Research does not need governance" is rejected. Research review cadence is lighter, but reproducibility and promotion gates are mandatory.

## 8. Next Execution Implication

The next `执行` after the first long-alpha slice should stay docs-only and continue the Phase 6 spec pack:

1. A-long annex in `docs/long_alpha_spec.md`.
2. A/US burst lane spec.
3. US-short normalization.
4. Provider / data requirements audit.

A-short continues as maintenance / evidence accumulation while those specs are written.
