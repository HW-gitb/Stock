# Alpha Plausibility Audit

**Status**: Phase 7a design route owner. This document defines the audit that must run before major implementation investment in any lane.

**Owner role**: system-level alpha plausibility and lane-objective owner. It complements `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`, `docs/provider_priority_benchmark_contract.md`, `docs/strategy_design_synthesis.md`, `docs/long_alpha_spec.md`, `docs/burst_lane_spec.md`, and `schemas/provider_capability_catalog.schema.json`.

## 1. Purpose

The project now treats alpha plausibility as a first-class gate before broad DataHub / runner implementation. A complete spec is not enough; each lane must show why it is likely to create useful risk-adjusted excess return, what data is needed to prove it, and how long evidence will take to become detectable.

This audit does not prove alpha. It decides whether a lane should continue, be redesigned, remain a risk filter, wait for provider readiness, or be deferred before implementation consumes months of work.

Non-goals:

- No ship gate is relaxed.
- No provider is selected.
- No strategy threshold is promoted to production.
- No broker, OS automation, or automatic trading is introduced.
- No cross-market or cross-bucket capital pooling is allowed.

## 2. Required Audit Contract

The first formal audit must be schema-first. Before a completed audit can be used for implementation decisions, add and validate:

- `schemas/alpha_plausibility_audit.schema.json`
- `schemas/examples/alpha_plausibility_audit.example.json`
- focused schema tests

The first formal Phase 7a-1 audit artifact is `docs/phase7a_alpha_plausibility_audit.json`. It uses `docs/phase7a_provider_status_snapshot.json` as the shared provider readiness baseline and remains an alpha-plausibility routing artifact, not ship-gate evidence.

Each lane record must include at least:

- `lane_id`: one of the lane IDs in section 3.
- `lane_role`: `risk_filter`, `alpha_source`, `capital_stabilizer`, `research_only`, or `deferred`.
- `alpha_source_hypothesis`: behavioral edge, structural risk premium, catalyst mispricing, flow / momentum burst, valuation re-rating, quality compounding, or explicit no-alpha risk-filter role.
- `expected_excess_return_band`: range, unit, time base, and rationale.
- `expected_volatility_band`: range, unit, time base, and rationale.
- `expected_max_drawdown_band`: range and rationale.
- `data_readiness`: structured provider, manual evidence, research-only, missing, or unknown.
- `pit_blockers`: historical as-of blockers, latest-only limitations, restatement risk, event observed-date gaps, or none.
- `provider_blockers`: coverage, authorization, cost, quota, stability, or fallback issues.
- `detectability_horizon_months`: minimum forward/live months likely needed before a useful signal can be distinguished from noise.
- `benchmark_plan`: provisional evidence benchmark and open final benchmark questions.
- `evidence_level_required`: `paper`, `live_normalized`, or both.
- `portfolio_correlation_assumption`: expected correlation to other lanes and major risk regimes.
- `portfolio_contribution`: expected contribution to total portfolio alpha, drawdown control, or diversification.
- `decision`: one of the decision labels in section 4.
- `decision_reason`: evidence-based reason; no pure narrative verdicts.

The audit may cite academic literature, existing project backtests, provider audits, market history, and current forward evidence, but it must label each source type. Literature-derived expectations are plausibility priors, not project evidence.

### 2.1 Phase 7a-1 Mandatory Schema Additions

Mandatory Phase 7a-1 field groups are defined in `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` §3-§10. This document owns audit purpose, lane coverage, verdict semantics, and execution route; the detailed mandatory field inventory must not be duplicated here.

Long-lane fraud / accounting red-flag coverage is owned by `docs/long_alpha_spec.md` §7 plus the A / US long annexes, and required by `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` §7. Do not duplicate the detailed red-flag inventory in this audit route document.

## 3. Lane Coverage

The audit must cover these lane IDs:

| Lane ID | Target role | Notes |
|---|---|---|
| `a_short_steady` | Risk filter / evidence loop | Existing A-short steady lane should not be treated as the main short-term alpha engine unless future evidence overturns the current finding. |
| `a_short_variants` | Risk-filter improvement | Variants are bounded comparison tracks for drawdown / bad-ticket reduction and execution-quality improvement. |
| `a_share_burst_minimal_data` | Research / paper alpha probe | Uses OHLCV, turnover, relative strength, benchmark context, limit / halt, and current A-short candidate context only. |
| `a_share_burst_full_data` | Short-term alpha source candidate | Adds reviewed capital flow, catalyst, event, and manual-evidence fields before minimal live observation. |
| `us_short_steady` | Risk-filtered short decision support | US-short steady lane may contain alpha signals but must not inherit burst-lane evidence. |
| `us_burst_minimal_data` | Research / paper alpha probe | Uses OHLCV, gap / range, relative strength, benchmark / sector context, and liquidity only. |
| `us_burst_full_data` | Short-term alpha source candidate | Adds reviewed filings, earnings / guidance, options, borrow / short-interest, and catalyst evidence before minimal live observation. |
| `a_long_core_quality` | Long alpha / stabilizer candidate | Quality compounding may have lower t-stat but useful drawdown / diversification value. |
| `a_long_re_rating_catalyst` | Long alpha source candidate | Active mispricing / catalyst capture, dependent on fundamentals and observed-date evidence. |
| `us_long_core_quality` | Long alpha / stabilizer candidate | Quality compounding and capital allocation edge, dependent on PIT fundamentals and corporate actions. |
| `us_long_re_rating_catalyst` | Long alpha source candidate | Active mispricing / catalyst capture, dependent on filings, guidance, revisions, buybacks, and event data. |

## 4. Decision Labels

Each lane receives exactly one decision:

| Decision | Meaning | Implementation consequence |
|---|---|---|
| `continue` | Plausibility, data readiness, and evidence horizon justify the next implementation or schema slice. | May proceed through normal review. |
| `continue_as_risk_filter` | Lane is useful for risk control or evidence quality, but should not be described as a push-alpha lane. | Preserve or implement only risk-filter/reporting scope. |
| `redesign_required` | Alpha source is weak, contradictory, or not aligned with available data. | Rewrite spec before implementation. |
| `defer_until_provider_ready` | Alpha source is plausible, but provider/PIT evidence is not sufficient. | Do provider evidence first. |
| `do_not_implement_now` | Expected edge, data readiness, or detectability horizon does not justify current implementation. | Keep as archived idea or research-only. |

Do not use a mechanical single-threshold kill rule. Long detectability horizon can still be acceptable if the lane has low correlation, low drawdown, or clear portfolio value. Conversely, a high standalone expected return can still be rejected if PIT, cost, liquidity, or provider risk makes evidence unreliable.

## 5. Portfolio-Level Synthesis

The audit must include a portfolio-level synthesis after lane records:

- expected lane correlation matrix or qualitative correlation table,
- expected contribution by market and bucket,
- total portfolio expected excess-return range,
- total portfolio drawdown and concentration implications,
- evidence-clock bottlenecks,
- lanes most likely to improve portfolio-level Sharpe,
- lanes most likely to reduce drawdown without being alpha engines.

The user's target is portfolio-level push alpha under capital and manual-execution constraints, not just isolated lane t-stat. A set of individually plausible lanes can still fail if they are too correlated, too slow to detect, or dependent on the same fragile provider fields.

## 6. Current Design Hypotheses To Test

These are not final audit verdicts:

- A-short steady should be treated as a permanent risk filter unless forward evidence creates an explicit escape-valve case.
- A-short variants should be evaluated mainly for bad-ticket reduction, drawdown reduction, execution quality, and evidence quality.
- Burst lanes are the short-term alpha candidates, but minimal-data burst tiers are paper/research only until non-price evidence is available.
- Long re-rating / catalyst lanes are the main long push-alpha candidates.
- Long core quality lanes may be lower-t-stat stabilizers; portfolio value must be assessed before labeling them failures.
- Provider priority should follow alpha leverage and data blockers, not convenience of already-proven A-share EOD surfaces.

## 7. Execution Route

Recommended route:

1. Phase 7a-1: add `alpha_plausibility_audit` schema, example, tests, lightweight provider status snapshot, and first audit using `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`.
2. Phase 7a-2: use the audit to update `docs/strategy_design_synthesis.md`, `docs/long_alpha_spec.md`, `docs/burst_lane_spec.md`, and `docs/CURRENT.md`.
3. Phase 7a-3: provider priority reorder and provisional evidence benchmarks are locked in `docs/provider_priority_benchmark_contract.md`.
4. Phase 7a-4: burst minimal-to-full promotion criteria and evidence capital controls are locked in `docs/evidence_feasibility_controls.md` and `schemas/evidence_feasibility_controls.schema.json`.
5. Phase 7a-5: add burst / long / research evidence report schemas, immutable decision packet, cost-adjusted return details, minimal reconciliation, manual override records, and thesis outcome log.
6. Phase 7b / 7c / 8 / 9: follow `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` for provider evidence, DataHub monitoring, lane implementation, and coordinator controls.

If the audit reverses an existing next-step assumption, record the reversal explicitly in `docs/SESSION_LOG.md` with reason.
