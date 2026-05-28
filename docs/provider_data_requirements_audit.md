# Provider Data Requirements Audit

**Status**: Phase 6e docs-only baseline. This document consolidates the data requirements created by the Phase 6 spec pack before Phase 7 DataHub / engine implementation.

**Owner role**: detailed owner for provider capability, data-class, PIT, frequency, lineage, authorization / cost, and stability requirements. It does not select a final provider, implement DataHub, or start production data ingestion. Phase 7 has since derived the first schema contract in `schemas/provider_capability_catalog.schema.json`.

## 1. Scope

This audit consumes:

- `docs/long_alpha_spec.md` section 9, section 10.4, and section 11.8,
- `docs/burst_lane_spec.md` section 11,
- `docs/us_short_spec.md` section 9,
- `docs/datahub_design.md` as the DataHub guardrail.

It covers provider requirements for:

- A-long,
- US-long,
- A-share burst,
- US burst,
- US-short steady lane,
- existing A-short steady / evidence plumbing where it constrains shared DataHub design.

Non-scope:

- No provider is selected.
- No paid / free data split is decided.
- No schema version, runner, migration, cache format, provider adapter, or DataHub table is implemented.
- No numeric strategy threshold is promoted to production.
- No benchmark primary choice is finalized outside the already-decided A-short CSI1000 primary / CSI300 secondary policy.
- No broker, OS automation, or automatic trading path is introduced.
- No ship gate is relaxed.

## 2. Requirement Status Labels

Future implementation should classify each requested field with one of these statuses before it is used in production logic.

| Status | Meaning | Production rule |
|---|---|---|
| `structured_required` | Must be available from a reviewed provider before the rule can be automated. | Missing data blocks the automated rule or keeps the candidate research-only. |
| `structured_optional` | Useful if available, but not required for the first implementation. | May be omitted if the report states the limitation. |
| `manual_evidence` | Requires human or LLM-assisted review because provider structure is unreliable or not yet selected. | Must carry `observed_date`, source, and reviewer notes; cannot silently become a deterministic factor. |
| `research_only` | Can be explored, but not used by production reports or ship-gate evidence. | Requires experiment log before promotion. |
| `deferred` | Not in the first implementation contract. | Revisit only through a later reviewed spec. |

Missing data is not automatically negative evidence unless an owning spec explicitly says so. Missing data that is essential to a claimed trigger blocks that trigger.

## 3. Common Data-Class Matrix

| Data class | A-short steady / evidence | A-share burst | A-long | US-short steady | US burst | US-long | Phase 7 implication |
|---|---|---|---|---|---|---|---|
| Instrument master and listing state | Existing A-share code / name / status inputs; must remain visible. | Need listing age, ST, suspension, and eligibility flags. | Need investability, ST / suspension, IPO / restructuring eligibility. | Need exchange, OTC / pink exclusion, delisting, bankruptcy, reverse split, ADR flags. | Same US listing / event eligibility as US-short plus event timing. | Need common equity / ADR / ETF / SPAC eligibility. | Build market-specific security master with listing status and exclusion reasons. |
| Trading calendar and market status | Existing Tushare `trade_cal` is used by A-short execution plumbing. | Need A-share T+1 and trading-day context. | Need A-share trading status and suspensions. | Need US trading calendar and halt status. | Need regular / pre-market / after-hours context if accepted. | Need US trading calendar and delisting / survivorship handling. | Standardize calendar, open dates, halt / suspension, and market-session metadata. |
| Adjusted EOD OHLCV and liquidity | Existing `daily` / `adj_factor` / `stk_limit` support A-short execution evidence. | Need OHLCV, amount, turnover, rolling volume / turnover baseline. | Need adjusted prices, dividends, splits, share count, market cap. | Need OHLCV, spread / liquidity, ADTV, ATR, IV / HV if retained. | Need OHLCV, gap, range summary, rolling volume baseline. | Need adjusted prices, dividends, splits, shares outstanding. | EOD price contract must include adjustment mode, units, frequency, and missing-row rules. |
| Limit / halt / suspension mechanics | Existing A-share limit and suspension gaps are material to A-short evidence. | Hard requirement for risk locks. | Required for investability and execution feasibility. | US does not have A-share price limits; halt status still required. | Halt / gap risk required. | Halt / delisting required for survivorship. | Keep market-specific mechanics as explicit fields, not inferred from missing prices. |
| Industry taxonomy | A-short currently uses SW / L1 / concept context where available. | Need industry / concept / L3 context. | SW L2 primary, SW L1 fallback when sample count is insufficient. | GICS hierarchy and point-in-time classification. | Sector / industry / peer relative strength. | GICS industry primary, GICS industry group fallback. | DWD industry membership must carry taxonomy, level, as-of, sample count, and fallback reason. |
| Benchmark returns and membership | A-short primary CSI1000, secondary CSI300; materializers exist. | May reuse CSI1000 / CSI300 return source for reporting, but not gate verdict. | Needs CSI300 / broad A-share / SW industry / CSI500-CSI1000 candidates. | Needs SPY / S&P 500, Russell 1000, QQQ / Nasdaq 100, sector ETF candidates. | Needs SPY / S&P 500, Russell 1000, Nasdaq 100 / QQQ, sector ETF candidates. | Needs S&P 500 and Russell 1000 candidates. | Benchmark returns and membership must be separate from strategy gate policy. |
| Financial statements and filings | A-short may use limited fundamentals from current screening inputs. | Earnings catalyst only if observed date is reliable. | Income, balance sheet, cash flow, announcement dates, revisions / restatement flags. | Financial statements, restatements, EPS, revenue, margin, guidance, filing dates. | Earnings / guidance / SEC filing events as catalyst data. | 10-K / 10-Q dates, statement line items, FCF, debt, cash, interest expense. | Fundamentals require PIT availability dates and restatement / latest-only limitation flags. |
| Cash flow, quality, and valuation | Not the A-short main alpha source. | Optional diagnostic unless explicitly used. | CFO / net income, FCF conversion, capex, working capital, valuation, EV inputs. | Earnings quality, CFO / FCF, valuation gap, target price context. | Usually supplemental, not core burst trigger. | FCF margin, ROIC, EV, buyback efficiency, dilution. | Factor layer must version formulas and record input statements and as-of eligibility. |
| Corporate actions and capital actions | Existing splits / adj factor and limit data are relevant. | Need listing / split / halt / event context. | Dividends, buybacks, share-count changes, pledge / guarantee risk where available. | Lockups, S-3 / resale, dilution, insider transactions. | Buyback / M&A / spin-off / index inclusion as catalyst candidates. | Buybacks, dividends, share count, SBC, dilution. | Corporate action layer must distinguish adjustment mechanics from alpha evidence. |
| Analyst, guidance, and consensus | Not first-class for A-short current path. | Manual evidence unless structured support is reviewed. | Manual evidence or structured field if available. | Consensus, targets, revisions, Estimize-like inputs if retained. | Guidance / revisions as catalyst data. | Guidance, consensus, and revision data or explicit manual fallback. | Provider audit must flag license / cost / PIT limits before automation. |
| SEC / exchange filings and events | Not applicable for A shares except local regulatory filings. | Policy / regulatory / earnings catalysts need observed dates. | Local announcements, regulatory inquiry, penalties, audit opinions. | S-1 / S-3 / 424B / 144, 10-K / 10-Q, 8-K, material updates. | SEC filing and event catalysts. | 10-K / 10-Q and material-event evidence. | Event store must record `event_date`, `observed_date`, source URL / ID, and as-of eligibility. |
| Ownership, borrow, short interest, options | A-share capital-flow fields only after reliability review. | Capital-flow / northbound-flow fields are optional until reviewed. | Usually not core long data except pledge / ownership risk. | Insider transactions, short interest, borrow fee, availability, options flow, PCR, IV percentile, gamma, dark-pool / off-exchange diagnostics. | Options, short interest, borrow, pre-market diagnostics are optional until reliability is reviewed. | SBC / dilution, ownership context where available. | These are high-risk fields: default to diagnostic / research until provider reliability is proven. |
| News, legal, regulatory, and short reports | Manual / LLM-assisted evidence for A-short semantic checks. | Catalyst evidence with observed date. | Policy / cycle / regulatory / governance evidence. | News, regulatory, legal, short-report evidence with public observed dates. | Event catalyst evidence. | Regulatory, antitrust, export-control, tax, litigation risks. | Manual-evidence path must be explicit; do not hide semantic interpretation inside factors. |
| Macro and regime | Existing A-short reports carry limited benchmark / market context. | Risk-state precondition and benchmark context. | Benchmark-relative opportunity cost and rate / FX sensitivity where relevant. | VIX, TNX, SPY / QQQ / Russell, sector state. | VIX / sector / peer relative strength. | Rate, demand, FX, credit, and broad benchmark context. | Macro inputs need frequency, source, and whether they are gating or context only. |

## 4. A-Share Provider Requirements

Existing project plumbing already proves a narrow A-share EOD surface:

- Tushare `daily`, `adj_factor`, `stk_limit`, and `trade_cal` can materialize Phase 5 `execution_price_data`.
- Tushare `index_daily` can materialize CSI1000 / CSI300 monthly benchmark return inputs.
- Tushare `index_weight` can support candidate-universe overlap audits against CSI1000 / CSI300.

This audit does not make Tushare the final provider for all A-share needs. Phase 7 must still evaluate whether reviewed providers can support:

- SW L1 / SW L2 industry history with effective dates or documented latest-only limitations.
- A-share financial statements with announcement dates and enough line items for CFO / net income, FCF conversion, capex, working capital, debt, cash, receivables, inventory, contract assets, guarantees, and pledge-related risk.
- Audit opinion, restatement / correction, regulatory inquiry, and penalty fields.
- Dividends, buybacks, share-count changes, dilution, and capital actions.
- A-share policy / regulatory / industry-cycle evidence, either structured or explicitly manual.
- Concept / L3 / theme context with snapshot date and PIT limitation.
- Capital-flow / northbound-flow data only if provider reliability is reviewed; otherwise keep it manual / diagnostic.
- Benchmark and SW industry index returns with survivorship and PIT limitations stated.

Known A-share constraints:

- Tushare financial data may expose latest revised values rather than original disclosure versions; this must be recorded as a PIT limitation.
- L3 concept data is not PIT-safe unless project snapshots exist; serious historical use must use snapshots or neutralized mode.
- Intraday, dynamic stops, and some semantic research / policy fields are not solved by the current EOD provider surface.

## 5. US Provider Requirements

US implementation remains blocked until a reviewed provider capability baseline exists. Phase 7 must evaluate whether one or more providers can support:

- Security master: NYSE / NASDAQ listing, OTC / pink exclusion, ADR flag, ETF / fund / preferred / SPAC classification, delisting, bankruptcy, reverse split, lockup, and resale registration status.
- Daily adjusted OHLCV, dividends, splits, shares outstanding, market capitalization, spread / liquidity, and ADTV.
- Trading calendar, halt status, pre-market / after-hours fields if those are accepted by later implementation contracts.
- GICS hierarchy with enough as-of stability for industry normalization and fallback sample counts.
- 10-K / 10-Q / 8-K filing dates, statement line items, restatement flags, and filing availability dates.
- Cash-flow data sufficient for FCF, FCF margin, conversion, capex, working-capital diagnostics, debt, cash, interest expense, leases if available, and enterprise value.
- Buyback amount, net share-count change, SBC / dilution, dividends, and capital actions.
- Guidance, consensus, analyst target history, revision history, and Estimize-like inputs if retained.
- SEC event filings: S-1 / S-3 / 424B / 144, material 8-K events, and resale / dilution evidence.
- Insider transactions and 10b5-1 context.
- Short interest, borrow fee, days-to-cover, availability, options flow, put / call ratio, IV percentile, gamma / max-pain, and dark-pool / off-exchange activity.
- News, regulatory, legal, short-report, product, approval, and litigation evidence with public observed dates.
- SPY / S&P 500, Russell 1000, Nasdaq 100 / QQQ, sector ETF, VIX, TNX, and macro regime inputs.

Fields without reliable PIT support remain manual evidence, research-only, or deferred. They must not be silently imputed from current data.

## 6. PIT, Frequency, and History Requirements

Minimum cross-system rules:

- Every automated historical field needs `as_of` eligibility logic.
- Price and benchmark series need trade date, fetch date, adjustment mode, currency, and frequency.
- Financial statement fields need fiscal period end, filing / report date, provider retrieval date, and restatement / latest-only limitation.
- Industry classification needs taxonomy, level, classification as-of or provider version, sample count, and fallback reason.
- Event / catalyst evidence needs `event_date` and `observed_date`; when they differ, `observed_date` controls eligibility.
- Manual evidence needs source, observed date, reviewer identity or process tag, and scope of use.
- Latest-only data may be used for live reports if labeled, but cannot be used to claim historical PIT evidence.
- Benchmark monthly returns must not fill missing months with zero.

Suggested minimum history depth before production research:

| Need | Minimum history intent | Reason |
|---|---|---|
| Daily price / liquidity baselines | At least 5 years where available; shorter windows marked explicitly. | Supports rolling baselines, drawdown, and regime comparison. |
| Long fundamental normalization | 5-year rolling industry distribution where possible. | Required by long-alpha industry normalization. |
| Benchmark returns | Same window as the strategy evidence under review. | Required for alpha t-stat and sensitivity. |
| Corporate actions / delisting | Full available window for the test universe. | Avoids survivorship and adjustment bias. |
| Event / catalyst evidence | Public observed dates for every event used. | Prevents retrospective catalyst leakage. |

## 7. Minimum Lineage Contract

Before Phase 7 implementation uses a provider field in any schema, report, or factor, the data source should be able to record:

- `provider_id`,
- `provider_product_or_tier` when relevant,
- API family / endpoint / table name,
- provider symbol / identifier,
- request parameters,
- fetch timestamp,
- source date range,
- frequency,
- currency and unit,
- adjustment mode,
- PIT status: `pit_safe`, `latest_only`, `manual_evidence`, or `unknown`,
- as-of eligibility rule,
- row count / coverage count,
- missing required fields,
- known provider limitations,
- retry / stability status,
- authorization / license class,
- cost / quota risk class,
- fallback path if unavailable.

This list is a contract target, not a schema implementation in this slice.

## 8. Provider Evaluation Rubric

Provider evaluation should be evidence-first. A later provider-selection review should compare candidates on these dimensions:

| Dimension | Required question |
|---|---|
| Coverage | Which required fields are available for A-share, US, long, short, burst, and benchmark use? |
| PIT support | Does the provider expose the date the information became public, or only latest revised values? |
| History depth | Does the available history cover rolling baselines, 5-year industry distributions, and forward / backtest windows? |
| Corporate actions | Are splits, dividends, delistings, halts, suspensions, and survivorship handled explicitly? |
| Units and currency | Are field units stable and documented? Are currency conversions required? |
| Update latency | When is the data available relative to market close, filings, or events? |
| Stability | Are API limits, outages, schema changes, and retry behavior acceptable? |
| Authorization | Does license scope allow local storage, derived reports, and private analysis use? |
| Cost | Is cost acceptable for the field's expected alpha / risk value? |
| Fallback | What happens if the provider lacks the field or coverage is unreliable? |

Do not average these dimensions into a single provider score. Field-level blockers matter: one missing filing-date field can block an otherwise broad fundamentals provider from historical automation.

## 9. DataHub Phase 7 Implications

Phase 7 should use this audit as a requirement input, not as a provider verdict.

Recommended Phase 7 / 7a slices:

1. Create a provider capability / field catalog contract before broad provider adapters. This is now established as `schemas/provider_capability_catalog.schema.json` v1.0.0. It records data class, required systems, PIT status, frequency, lineage, authorization, cost, stability, and fallback without selecting a provider.
2. Run the schema-first alpha plausibility audit defined in `docs/alpha_plausibility_audit.md` and `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` before spending major implementation capacity on any lane.
3. Reorder provider capability evidence by alpha leverage and data blockers. The Phase 7a-3 owner contract is now `docs/provider_priority_benchmark_contract.md`: US fundamentals / filings / corporate actions / security master first; A-share fundamentals / announcement dates / SW industry history second; burst event / flow / options / borrow fields third; already-proven A-share EOD / CSI helper surfaces recorded as ready evidence rather than the default implementation sink.
4. Record already-proven A-share EOD / CSI benchmark surfaces as ready evidence, but do not let convenience of those surfaces consume the default next implementation slice.
5. Define fundamentals and event-data contracts before long-system implementation.
6. Define US security-master / price / benchmark contracts before US-short or US-long implementation.
7. Keep manual evidence lanes explicit for semantic news, regulatory interpretation, and hard-to-license datasets.

Anti-patterns:

- Do not start DataHub by copying current A-short fields only; the Phase 7 shared layer must be shaped by all four systems.
- Do not treat DataHub completion as alpha evidence.
- Do not hide provider gaps behind default values.
- Do not let research outputs directly feed production runners without schema-first promotion.
- Do not implement parallel production pipelines for each subsystem.

## 10. Deferred Decisions

These decisions remain open after this audit:

- Final provider or provider set.
- Paid / free data split and user-approved cost ceiling.
- Exact schemas for security master, fundamentals, events, and benchmark series. The provider capability / field catalog contract now has v1.0.0, but a real provider registry artifact and provider selection remain deferred.
- Final ship-gate benchmarks for A-long, US-long, US-short steady, A-share burst, and US burst. Provisional evidence benchmarks are defined in `docs/provider_priority_benchmark_contract.md`.
- Numeric field thresholds, factor weights, and production configs.
- Whether options / dark-pool / off-exchange diagnostics become production inputs.
- Whether pre-market / after-hours fields are production inputs or research-only.
- Manual evidence workflow, reviewer identity field, and storage format.
- US provider implementation priority if provider readiness differs across long / short / burst needs.

## 11. Completion Line

Phase 6e docs-only baseline is complete when:

1. This audit doc exists and is routed from `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/strategy_design_synthesis.md`, and `docs/datahub_design.md`.
2. It lists required data classes across A-long, US-long, A/US burst, US-short steady, and existing A-short constraints.
3. It defines PIT, frequency, lineage, authorization / cost, stability, and fallback expectations.
4. It explicitly states that no provider, schema, runner, DataHub implementation, broker integration, or order automation was introduced.
5. `docs/CURRENT.md` no longer lists provider/data requirements audit as pending Phase 6 spec-pack work.

## 12. Next Work

After this baseline, the first Phase 7 schema-first slice derived `schemas/provider_capability_catalog.schema.json` from this audit. Phase 7a then added the alpha plausibility audit chain and the Phase 7a-3 provider priority / provisional benchmark contract in `docs/provider_priority_benchmark_contract.md`. Phase 7b-1 records provider evidence / drift-monitor shape in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`: P1-P4 evidence records, readiness rollup, coverage, freshness, schema drift, outliers, revision rate, provider incidents, and silent provider semantic changes. Phase 7b-2 has started with `docs/provider_evidence_p1_us_public_sources_20260528.json`, but P1 remains partial / blocked and must still record US price, corporate action, delisting/security-master, benchmark, authorization, cost, fallback, stability, and limitations evidence. Follow-up work should still not rewrite `A-EGS/egs_main.py`, add a US provider adapter, fetch new provider data, or build DataHub tables until the relevant implementation contract is reviewed.
