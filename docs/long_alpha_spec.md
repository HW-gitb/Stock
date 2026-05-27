# Long Alpha Common Spec

**Status**: Phase 6d docs-only baseline. This document defines the common long-alpha contract plus US-long and A-long annex skeletons. It does not implement schemas, runners, providers, DataHub, or order execution.

**Owner role**: detailed spec owner for A-long / US-long common long-alpha design. `docs/strategy_design_synthesis.md` remains the strategy architecture entry; `docs/datahub_design.md` remains the DataHub / provider guardrail owner.

## 1. Scope

Long-term systems are the primary push-alpha layer. They are not adaptations of the short-term v14.x frameworks.

Shared long systems use two lanes:

1. `core_quality_compounding`: durable quality, cash-flow strength, balance-sheet resilience, and reinvestment runway.
2. `re_rating_catalyst_long`: valuation dislocation plus evidence of earnings, cycle, policy, or company-specific re-rating.

The common spec covers factor semantics, point-in-time rules, industry normalization, portfolio-construction constraints, thesis-broken exits, review cadence, benchmark-relative validation, and data requirements. Market annexes specialize taxonomy, fields, benchmarks, and provider dependencies.

Non-scope:

- No numeric factor weights or threshold constants are locked here.
- No schema version, runner, migration, or report format is introduced here.
- No provider is selected here.
- No full-size manual use is allowed from this document alone; ship gate still requires monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and >=12 months forward live evidence.
- No broker connection, OS automation, or automatic trading is allowed.

## 2. Candidate Lifecycle

Each long candidate should move through the same conceptual lifecycle:

1. Universe and liquidity eligibility.
2. Data availability and point-in-time eligibility.
3. Industry-normalized factor evaluation.
4. Lane assignment: core quality, re-rating / catalyst, or reject.
5. Written thesis and explicit invalidation conditions.
6. Portfolio construction proposal within the relevant market long bucket.
7. Quarterly and event-driven review.
8. Exit, hold, or resize decision with evidence logged.

This is a specification contract only. Future implementation can split these stages across schemas, reports, skills, and runners.

## 3. Common Factor Catalog

| Domain | Common factors | Purpose | Point-in-time / data notes | Failure modes |
|---|---|---|---|---|
| Eligibility | Listing status, liquidity, investability, trading suspension / halt status, corporate-action availability | Remove names that cannot support a reliable manual process | Must be evaluated as of the decision date; future delisting or later liquidity is not valid evidence | Survivorship bias, stale classifications, hidden liquidity constraints |
| Profitability quality | ROIC, ROE, gross / operating margin stability, return spread over cost of capital | Identify durable economic quality | Compare to industry rolling history, not a global static threshold | Peak-cycle margins, accounting distortions, low asset-base artifacts |
| Cash-flow quality | Free-cash-flow margin, CFO / net income, FCF conversion, working-capital drag, capex intensity | Separate accounting earnings from cash economics | Use filings available by `as_of`; restatements need lineage flags | One-off working capital release, deferred capex, acquired cash flow |
| Balance-sheet resilience | Net debt / EBITDA, interest coverage, cash runway, refinancing wall, dilution risk | Keep long thesis from relying on fragile financing | Debt maturity and rate sensitivity need provider support before automation | Hidden leverage, off-balance obligations, variable-rate exposure |
| Growth durability | Revenue growth stability, unit economics, retention / backlog when available, reinvestment runway | Distinguish durable growth from one-off acceleration | Market annex defines available fields; missing semantic fields must be reported, not imputed | Pull-forward demand, channel stuffing, cyclic peak |
| Valuation context | EV / FCF, EV / EBIT, normalized P/E, FCF yield, price-to-sales for early cases, own-history percentile | Judge whether quality or catalyst is already priced | Use both industry-relative and own-history context when data allows | Multiple expansion already complete, accounting denominator noise |
| Catalyst / re-rating | Earnings inflection, guidance or estimate revision, cycle reversal, policy / regulation, buyback, capital return, product / market expansion | Define why valuation should change within a reasonable horizon | Event evidence must be time-stamped and separable from later outcomes; see §5 `event_date` / `catalyst_observed_date` | Narrative-only catalyst, unverified news, catalyst priced before entry |
| Capital allocation | Buyback efficiency, dividend discipline, M&A record, reinvestment ROI, dilution / SBC | Judge whether management converts cash flow into per-share value | Share-count and buyback fields must be point-in-time tracked | Value-destructive M&A, buybacks above intrinsic value, dilution offset |
| Risk / red flags | Accounting quality, customer concentration, regulatory pressure, governance, rate / FX sensitivity, commodity exposure | Make thesis risk explicit before sizing | Red flags can be manual evidence until structured fields exist | Silent deterioration, unbounded narrative exceptions |

Future market annexes can add fields, but they should not redefine these domains without updating this common spec.

## 4. Industry Normalization

Long factors must be interpreted within industry context.

Common rule:

- Compare factor levels and stability against a 5-year rolling industry distribution where data exists.
- If an industry sample has fewer than 20 comparable names, use the parent industry group defined by the market annex.
- Prefer percentile / z-score style evidence over global threshold constants.
- Keep raw metric, normalized metric, industry taxonomy, sample count, window length, and fallback reason visible in future reports.
- Treat cyclic industries separately: cycle-normalized margins and returns are required before calling a name structurally cheap or structurally high quality.

Market defaults:

- A-long annex will define SW L2 as the default taxonomy, with SW L1 fallback when sample count is insufficient.
- US-long annex uses GICS industry as default taxonomy, with GICS industry group fallback when sample count is insufficient.

## 5. Point-In-Time Rules

Long alpha work is invalid if it leaks future fundamentals into past decisions. Future schemas and runners must preserve at least these dates:

- `as_of`: decision date.
- `fiscal_period_end`: economic period covered by the statement.
- `report_date` / `filing_date`: date when the information became publicly available.
- `fetch_date`: date when the local system retrieved the data.
- `classification_as_of`: industry classification date or provider version.
- `benchmark_as_of`: benchmark / index data date.
- `event_date` / `catalyst_observed_date`: date when catalyst evidence occurred, was scheduled, or became publicly observable.

Rules:

- A factor can be used only if the underlying data was public by `as_of`.
- Catalyst evidence follows the same public-by-`as_of` rule; when `event_date` and `catalyst_observed_date` differ, `catalyst_observed_date` controls eligibility.
- Revised or restated values must not silently overwrite historical evidence; future implementation needs a lineage flag when the provider cannot supply pre-restatement values.
- Missing data is a data-quality condition, not automatic negative evidence, unless a market annex explicitly defines a missing-field rule.
- Industry membership and benchmark membership should be point-in-time where providers support it; if not, reports must state the limitation.

## 6. Portfolio Construction Contract

Long systems propose manual actions within the relevant market long bucket. They do not size against the whole account and do not move cash across A / US markets without an explicit coordinator rule or user decision.

Common constraints:

- Respect the preset capital ceiling for the market long bucket.
- Future implementations should consume the P0a `portfolio_allocation` and `cash_buffer_state` schemas rather than reinventing capital ceiling or bucket-cash math.
- Separate paper / minimal-size evidence collection from full-size manual use.
- Keep position, industry, and lane concentration visible in future reports.
- Treat cash-buffer requests as explicit recommendations, not implicit cross-system transfers.
- Do not average down only because price is lower; averaging requires the thesis to remain intact and valuation / risk evidence to improve or remain favorable.
- All execution remains manual.

Exact position caps, industry caps, and rebalance bands are deferred to market annexes or later portfolio-coordinator specs.

## 7. Thesis, Exit, and Review

Every long candidate needs a written thesis with invalidation conditions before it can leave research-only status.

Required thesis fields:

- Lane: core quality, re-rating / catalyst, or both with primary lane marked.
- Business quality evidence.
- Cash-flow and balance-sheet evidence.
- Valuation evidence.
- Catalyst or compounding horizon.
- Major risks and what would disprove the thesis.
- Next review date and expected evidence update.

Exit or downgrade triggers:

- Thesis broken: original reason for ownership no longer holds.
- Fundamental deterioration: quality, cash-flow, leverage, or competitive position weakens beyond the written tolerance.
- Catalyst failure: expected re-rating driver expires, reverses, or becomes unobservable.
- Valuation saturation: risk-adjusted forward return no longer clears the benchmark-relative opportunity cost.
- Governance / accounting / regulatory risk becomes material and unresolved.
- Scheduled quarterly review cannot refresh the evidence because required data is missing or stale.

Stop-loss style price moves can trigger a review, but price alone is not a thesis-broken exit for long systems.

Review cadence:

- Quarterly after material filings.
- Event-driven after guidance, earnings, major policy / regulatory events, M&A, credit events, or large unexplained drawdowns.
- Annual thesis reset for positions still held after a full operating cycle.

## 8. Validation and Promotion

Engineering completion and strategy signoff stay separate.

Minimum validation requirements before production promotion can be considered:

- Backtest / walk-forward methodology documented with benchmark-relative return.
- Monthly alpha t-stat and Sharpe measured at system level.
- Max drawdown measured at system level.
- Forward evidence log accumulated after the report process is stable, using the Phase 6a forward-evidence semantics in `docs/handoff/2026-05-26_phase6a_kickoff_spec_handoff.md` §3.2 so monthly cohorts, mature windows, and consecutive-month evidence remain comparable across systems.
- Failure cases and rejected candidates retained for comparison.
- Data limitations stated alongside metrics.

Full-size manual use still requires the project ship gate: monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and >=12 months forward live evidence. Until then, output is paper or minimal-size decision support.

## 9. Common Data Requirements

Provider selection is deferred to Phase 6e provider / fundamentals data contract audit. This spec only defines the required data classes:

- Adjusted daily prices and total-return-capable benchmark series.
- Corporate actions, dividends, splits, share count, and market capitalization.
- Income statement, balance sheet, and cash-flow statement line items.
- Filing / report availability dates.
- Industry taxonomy and historical classification where available.
- Enterprise value inputs: debt, cash, minority interest, preferred equity where available.
- Buyback, dividend, and dilution fields.
- Guidance, analyst revisions, or event evidence if available; otherwise manual evidence fields must be explicit.
- Index / benchmark returns and membership limitations.
- Data lineage: provider, API family, retrieval date, PIT limitation, adjustment mode, and known missing fields.

DataHub Phase 7 should implement storage and contracts only after market specs and provider audit clarify which fields are actually available.

## 10. US-Long Annex Skeleton

### 10.1 Scope and Status

US-long is a long-alpha market annex for the US long bucket. This skeleton lists intended factor emphasis and data needs, but it is not a complete market spec and does not select a provider.

### 10.2 Taxonomy and Universe

Default taxonomy:

- Primary: GICS industry.
- Fallback: GICS industry group when comparable sample count is below 20.

Initial universe assumptions to validate later:

- US-listed common equities with sufficient liquidity and provider coverage.
- ADRs, OTC names, closed-end funds, ETFs, preferreds, SPACs, and recent de-SPACs require explicit eligibility rules before inclusion.
- Mega-cap concentration must be visible in benchmark-relative analysis because broad US benchmarks can be dominated by a small number of names.

### 10.3 US Factor Emphasis

US-long keeps the common factor domains and adds US-specific emphasis:

- 10-K / 10-Q filing availability and lag handling.
- ROIC and return spread versus US industry peers.
- FCF margin, FCF conversion, and capex intensity.
- Buyback efficiency: buybacks relative to valuation, FCF, and dilution.
- Share-based compensation and share-count dilution.
- Guidance credibility and revision history where data is available.
- Gross / operating margin durability across rate and demand regimes.
- Net debt / EBITDA, interest coverage, refinancing risk, and rate sensitivity.
- Revenue durability, customer concentration, backlog / RPO where available.
- Valuation versus GICS peers and own 5-year history.
- Regulatory, antitrust, export-control, tax, and litigation risks.

### 10.4 US Data Requirements

US provider audit must determine whether the system can reliably obtain:

- Daily adjusted prices, dividends, splits, and shares outstanding.
- 10-K / 10-Q filing dates and financial statement line items.
- Cash-flow statement fields sufficient for FCF, FCF margin, and conversion.
- Debt, cash, interest expense, leases if available, and enterprise value inputs.
- Buyback amount, net share count change, and SBC / dilution fields.
- GICS industry history or provider-stable GICS classification.
- Market capitalization, enterprise value, and valuation multiples.
- Guidance, consensus, and revision data, or a clear manual-evidence fallback.
- Benchmark series for S&P 500 and Russell 1000 candidates; final primary benchmark is deferred.
- Delisting, corporate action, and survivorship-bias limitations.

If provider readiness is insufficient, US-long implementation must stop at data-requirements documentation and paper research. It must not invent missing fundamentals or silently reuse A-share fields.

### 10.5 US Output Expectations

Future US-long reports should expose:

- Primary lane and thesis.
- GICS-normalized quality, cash-flow, valuation, catalyst, and risk evidence.
- Data availability and PIT limitation notes.
- Benchmark context against the selected US primary benchmark and at least one broad secondary benchmark where useful.
- Portfolio concentration and market-long bucket sizing recommendation.
- Exit / review triggers tied to the written thesis.
- Ship-gate status: research, paper, minimal, preliminary, or full-size eligible.

### 10.6 Deferred US Decisions

These remain open until later Phase 6d / 6e work:

- Exact US universe and exclusion rules.
- Primary US-long benchmark.
- Provider choice and paid / free data split.
- Numeric factor weights, caps, and thresholds.
- Report schema and runner interfaces.
- Whether guidance / estimate revisions are structured data or manual evidence in the first implementation.

## 11. A-Long Annex Skeleton

### 11.1 Scope and Status

A-long is a long-alpha market annex for the A-share long bucket. This skeleton specializes the common long-alpha contract for A-share fundamentals, SW industry normalization, policy / cycle context, cash-flow quality, and A-share benchmark selection. It is docs-only and does not select a final fundamentals provider.

### 11.2 Taxonomy and Universe

Default taxonomy:

- Primary: SW L2 industry.
- Fallback: SW L1 when comparable SW L2 sample count is below 20 or when SW L2 history is not sufficiently stable.

Initial universe assumptions to validate later:

- A-share common stocks with sufficient listing history, liquidity, trading-status observability, and fundamentals coverage.
- ST / *ST names, long suspensions, materially illiquid names, and names with unresolved major regulatory or accounting flags require explicit eligibility rules before inclusion.
- IPOs and newly restructured names require a minimum post-listing and post-restructuring evidence window before normal long-alpha scoring.
- State-owned enterprise, private enterprise, and strategic-industry policy exposure should be visible as context fields, not hidden narrative assumptions.

### 11.3 A-Share Factor Emphasis

A-long keeps the common factor domains and adds A-share-specific emphasis:

- Financial-statement reliability: audit opinion, restatement / correction record, receivables quality, related-party transactions, pledged-share / guarantee exposure where available.
- Operating cash flow versus net profit: CFO / net income, FCF conversion, working-capital drag, receivables and inventory build, and capex quality.
- Profitability quality: ROIC / ROE relative to SW L2 peers and own 5-year history, with cycle-aware treatment for commodity, equipment, property-chain, and financial names.
- Balance-sheet resilience: net debt, interest coverage, refinancing pressure, short-term debt versus cash, contingent liabilities, and off-balance risk when data exists.
- Dividend and buyback discipline: payout sustainability, buyback price discipline, cancellation versus treasury treatment where observable, and whether capital return improves per-share value.
- Policy and regulatory exposure: policy tailwind / headwind, procurement / localization policy, price controls, anti-corruption or sector rectification risk, and subsidy dependence.
- Industry cycle and pricing indicators: capacity cycle, product price trend, inventory cycle, utilization, and upstream / downstream bargaining power.
- Governance and control risk: controlling-shareholder pledge, related-party tunneling risk, management turnover, and ownership incentives.
- Valuation context: PE / PB / EV-style measures where meaningful, dividend yield, FCF yield, SW L2 percentile, own-history percentile, and cycle-adjusted valuation.

### 11.4 A-Share Financial Reliability Rules

Financial statement quality must be a first-class gate before factor scoring is trusted.

Required reliability checks for future implementation:

- Report audit opinion and non-standard opinion history.
- Restatement, correction, or regulatory inquiry history where data is available.
- CFO / net income persistence, not just a single-period value.
- Receivables, inventory, and contract-asset growth versus revenue growth.
- Related-party transactions, guarantees, and pledged-share exposure where provider coverage exists.
- Subsidy and fair-value gain dependence for profit quality.
- Segment or business-model changes that make five-year history non-comparable.

Missing reliability fields must be reported as data limitations. They must not be silently treated as clean evidence.

### 11.5 Operating Cash Flow Versus Net Profit

A-long should treat net profit as lower-confidence evidence when cash conversion is weak.

Default interpretation:

- Persistent CFO / net income below industry peers is a negative quality signal unless there is a documented business-model reason.
- One-year CFO spikes are not enough to override multi-year weak cash conversion.
- Receivables / inventory expansion can downgrade reported earnings quality even when headline growth is high.
- Capex-heavy businesses need maintenance-capex versus growth-capex reasoning before FCF weakness is judged negative.
- Dividend or buyback quality should be assessed against durable cash generation, not only reported net profit.

Exact thresholds and lookback windows are deferred to implementation specs after provider field availability is known.

### 11.6 Policy, Cycle, Dividend, And Buyback Context

A-share long thesis often depends on regime context. The annex requires this context to be explicit:

- Policy catalyst: source, announcement date, affected industry, expected mechanism, and whether the catalyst is recurring or one-off.
- Regulatory risk: sector rectification, price control, procurement rule changes, environmental / safety enforcement, and anti-corruption cycles.
- Industry cycle: capacity additions, inventory cycle, product price trend, demand cycle, and whether valuation is being measured at cycle peak or trough.
- Dividend thesis: payout history, cash coverage, balance-sheet support, policy incentive, and sustainability across downturns.
- Buyback thesis: buyback size, execution progress, price discipline, cancellation / share-count effect, and whether buybacks offset dilution or improve per-share value.

Narrative policy or cycle claims require dated evidence and follow §5 `event_date` / `catalyst_observed_date` rules.

### 11.7 A-Share Benchmark Candidates

Final primary benchmark is deferred. Candidate benchmark set for A-long validation:

- CSI300: large-cap core opportunity cost and institutional benchmark context.
- CSI All Share / broad A-share total-market proxy where provider coverage supports it.
- SW L2 industry index or equivalent industry benchmark for attribution and industry-relative alpha checks.
- CSI500 / CSI1000 may be secondary sensitivity candidates when the A-long universe materially tilts toward mid/small-cap quality names.

A-long benchmark choice must be reported separately from A-short's CSI1000 primary / CSI300 secondary policy. Do not inherit the A-short benchmark contract by default.

### 11.8 A-Share Data Requirements

A-share provider audit must determine whether the system can reliably obtain:

- Adjusted daily prices, trading status, suspensions, limit-up / limit-down status, dividends, splits, and share count.
- Financial statement line items with report dates / announcement dates sufficient for PIT filtering.
- Cash-flow statement fields sufficient for CFO / net income, FCF conversion, capex, and working-capital diagnostics.
- Balance-sheet fields for debt structure, cash, receivables, inventory, contract assets, guarantees, and pledge-related risk where available.
- Audit opinion, restatement / correction, regulatory inquiry, and penalty fields where available.
- SW L1 / SW L2 classification history or provider-stable industry classification.
- Dividend, buyback, share-count, and capital-action details.
- Policy / regulatory / industry-cycle evidence, either as structured fields or explicit manual evidence.
- Benchmark and SW industry index returns with known PIT and survivorship limitations.

If provider readiness is insufficient, A-long implementation must stop at data-requirements documentation and paper research. It must not substitute A-short technical fields for missing long fundamentals.

### 11.9 A-Long Output Expectations

Future A-long reports should expose:

- Primary lane and thesis.
- SW-normalized quality, cash-flow, valuation, catalyst, and risk evidence.
- Financial reliability status and missing-data limitations.
- Policy / cycle / dividend / buyback evidence with dates.
- Benchmark context against the selected A-long primary benchmark and relevant industry benchmark.
- Market-long bucket sizing recommendation and liquidity-buffer request, if any.
- Exit / review triggers tied to the written thesis.
- Ship-gate status: research, paper, minimal, preliminary, or full-size eligible.

### 11.10 Deferred A-Long Decisions

These remain open until later Phase 6d / 6e work:

- Exact A-long universe and exclusion rules.
- Primary A-long benchmark and secondary sensitivity set.
- Fundamentals provider choice and paid / free data split.
- Whether audit opinion, pledge, inquiry, penalty, and buyback details are structured fields or manual evidence in the first implementation.
- Numeric factor weights, caps, and thresholds.
- Report schema and runner interfaces.
