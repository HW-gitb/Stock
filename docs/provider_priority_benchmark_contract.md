# Provider Priority And Provisional Benchmark Contract

**Status**: Phase 7a-3 docs-only baseline.

**Owner role**: provider-evidence priority and provisional evidence-benchmark contract after the first alpha plausibility audit. This document converts audit implications into an ordered Phase 7b evidence queue and lane-level provisional benchmark policy.

**Non-scope**: this document does not select a provider, fetch data, create adapters, implement DataHub tables, change runners, change strategy rules, finalize ship-gate benchmarks, relax ship gates, or introduce broker / OS automation.

## 1. Inputs

This contract consumes:

- `docs/phase7a_alpha_plausibility_audit.json`
- `docs/phase7a_provider_status_snapshot.json`
- `docs/provider_data_requirements_audit.md`
- `docs/strategy_design_synthesis.md`
- `docs/burst_lane_spec.md`
- `docs/long_alpha_spec.md`
- `docs/us_short_spec.md`
- `docs/evidence_capital_policy.md`
- `schemas/provider_capability_catalog.schema.json`

The first audit is a routing artifact, not ship-gate evidence. It marks steady short lanes as risk filters, minimal-data burst lanes as paper / research only, and full-data burst plus long lanes as provider-blocked.

## 2. Scope Locks

Phase 7a-3 is still contract work.

| Lock | Required value |
|---|---|
| Final provider selection | Not selected |
| Data fetch | Not allowed |
| Provider adapter | Not allowed |
| DataHub table implementation | Not allowed |
| Runner or strategy-rule change | Not allowed |
| Final ship-gate benchmark | Not selected for any lane except the existing A-short evidence policy |
| Broker or OS automation | Not allowed |
| Manual order boundary | Preserved |

Already-proven A-share EOD and CSI benchmark helper surfaces remain useful ready evidence. They must not consume the default next implementation slice merely because they are convenient.

## 3. Provider Evidence Priority

Provider evidence priority follows alpha leverage and blocker severity, not current implementation convenience.

| Priority | Evidence family | Primary lanes unlocked | Required evidence before implementation can rely on it | Notes |
|---|---|---|---|---|
| P1 | US fundamentals, SEC filing dates, corporate actions, security master, delisting / survivorship, GICS history, and US benchmark readiness | `us_long_core_quality`, `us_long_re_rating_catalyst`, then `us_short_steady` and `us_burst` shared infrastructure | Provider capability catalog rows with PIT availability, filing observed dates, delisting coverage, corporate actions, benchmark series lineage, authorization / cost, history depth, and stability limitations | Highest leverage because US-long is the largest alpha-push bucket and is fully provider-blocked. |
| P2 | A-share fundamentals, announcement dates, restatement / correction flags, audit / inquiry / penalty evidence, SW L1 / L2 history, and A-long benchmark / industry attribution readiness | `a_long_core_quality`, `a_long_re_rating_catalyst` | Provider capability catalog rows with announcement-date eligibility, latest-only limitation flags, SW classification as-of handling, benchmark / SW index lineage, and manual-evidence fallback where structured fields are weak | This is separate from the existing A-short EOD surface. |
| P3 | Burst full-data event, flow, options, borrow / short-interest, pre-market / after-hours, capital-flow, and manual-evidence workflow | `a_share_burst_full_data`, `us_burst_full_data` | Field-by-field classification as structured required, structured optional, manual evidence, research-only, or deferred; observed-date rules; reliability notes; cost / liquidity / borrow / limit-risk constraints | Full-data burst remains provider-blocked. Minimal-data burst stays paper / research only. |
| P4 | Already-proven A-share EOD, limit, calendar, CSI benchmark returns, and candidate-universe overlap helper surfaces | `a_short_steady`, `a_short_variants`, `a_share_burst_minimal_data` reporting inputs | Record as ready evidence with lineage and drift monitoring; do not expand into broad DataHub implementation before P1-P3 blockers are reviewed | Ready evidence is still evidence, but it is not the default priority sink. |

## 4. Provider Evidence Packet Minimum

Before a field family can move from provider-blocked to implementation-ready, the evidence packet must record:

- field family and lane IDs affected,
- provider candidate ID or placeholder ID,
- API / table / source family,
- required fields and missing fields,
- PIT status and as-of eligibility rule,
- observed-date support for filings, announcements, and events,
- survivorship / delisting / corporate-action coverage where relevant,
- history depth and coverage counts,
- units, currency, adjustment mode, and frequency,
- authorization / license class and cost / quota risk,
- stability, outage, schema-drift, and retry behavior,
- fallback path when unavailable,
- production-use status and missing-data rule.

Do not average these dimensions into a single provider score. A single missing observed-date or delisting field can keep a lane provider-blocked.

## 5. Provisional Evidence Benchmarks

These benchmarks are for paper or live-normalized evidence accumulation and sensitivity reporting. They do not finalize ship-gate benchmark choices unless the lane already has an earlier reviewed benchmark policy.

| Lane or parent lane | Provisional primary | Mandatory secondary / attribution | Final benchmark status |
|---|---|---|---|
| `a_short_steady` and `a_short_variants` | CSI1000 | CSI300 | Existing A-short evidence policy remains active. Full-size still requires the full ship gate and live-normalized evidence. |
| `a_share_burst_minimal_data` | CSI1000 | CSI300 | Reporting only. Minimal-data burst remains paper / research. |
| `a_share_burst_full_data` | CSI1000 | CSI300 and SW industry attribution where provider coverage supports it | Final burst benchmark remains open if style or industry attribution shows CSI1000 / CSI300 are insufficient. |
| `us_short_steady` | Russell 1000 | S&P 500 / SPY, Nasdaq 100 / QQQ, and sector ETF sensitivity | Provisional reporting only. Final US-short benchmark remains deferred. |
| `us_burst_minimal_data` | Russell 1000 | S&P 500 / SPY and Nasdaq 100 / QQQ | Reporting only. Minimal-data burst remains paper / research. |
| `us_burst_full_data` | Russell 1000 | S&P 500 / SPY, Nasdaq 100 / QQQ, sector ETF sensitivity, and event-specific peer attribution where available | Final US-burst benchmark remains deferred. |
| `a_long_core_quality` and `a_long_re_rating_catalyst` | CSI300 | CSI All Share and SW L2 industry attribution; CSI500 / CSI1000 sensitivity when the universe tilts mid / small cap | Provisional evidence benchmark only. Final A-long benchmark remains deferred. |
| `us_long_core_quality` and `us_long_re_rating_catalyst` | Russell 1000 | S&P 500 and sector ETF attribution; later factor-model residual where provider readiness supports it | Provisional evidence benchmark only. Final US-long benchmark remains deferred. |

## 6. Benchmark Evidence Packet Minimum

Every benchmark used for evidence must record:

- benchmark ID and role: primary, secondary, or attribution,
- provider, API / table, request parameters, and fetch timestamp,
- source date range and coverage count,
- return frequency and return construction method,
- adjustment mode: price return, total return, or documented limitation,
- currency and unit,
- membership source and PIT limitation where membership is used,
- trading calendar and timezone alignment,
- missing months or missing sessions,
- no-zero-fill confirmation,
- reason the benchmark is suitable for the lane's current universe or hypothesis.

Missing benchmark months must not be filled with zero. A/US holidays, half-days, halted sessions, filing after-hours, and different market closes must not be silently forward-filled into evidence windows.

## 7. Benchmark Switch Rule

Changing a provisional primary benchmark or finalizing a ship-gate benchmark requires a reviewed evidence packet. The packet must include:

- candidate-universe overlap or style-exposure evidence,
- primary versus secondary sensitivity over the same evidence window,
- rationale for why the new benchmark better represents opportunity cost,
- impact on monthly alpha t-stat and benchmark-sensitive flags,
- confirmation that the switch does not lower the ship gate or reclassify paper evidence as live-normalized evidence,
- Claude review and user final approval before full-size implications.

Subjective claims such as "the universe looks large-cap" or "this benchmark feels closer" are not sufficient.

## 8. Next Use

Phase 7b-1 provider evidence / drift-monitor contracts now live in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`. They preserve the P1 to P4 order above unless a later reviewed audit reverses the queue.

Phase 7b-2 has started with two P1 snapshots: `docs/provider_evidence_p1_us_public_sources_20260528.json` for SEC EDGAR submissions/XBRL, SEC ticker files, Nasdaq symbol directory, and GICS methodology; and `docs/provider_evidence_p1_us_market_data_candidates_20260528.json` for Massive / Polygon and Norgate US market-data candidate documentation. These snapshots make P1 `partial`, not implementation-ready. Phase 7b-2 still needs to continue actual provider capability evidence in the P1 to P4 order above: authorization / cost, sandbox or trial feasibility, direct benchmark return sources, issuer-level PIT GICS membership, fundamentals / filing observed-date provider candidates, fallback, stability, and limitations before moving to P2-P4.

Phase 7a-4 evidence feasibility controls now live in `docs/evidence_feasibility_controls.md` and `schemas/evidence_feasibility_controls.schema.json`. That contract does not revisit provider priority.

Phase 7a-5 evidence report schemas now live in `docs/evidence_report_schema_contract.md` and `schemas/evidence_report.schema.json`; they consume both this benchmark / provider-priority contract and the Phase 7a-4 feasibility controls.

Phase 7c DataHub / report / reproducibility work should consume reviewed Phase 7b-2 evidence instead of reopening provider priority or treating P4 ready helper surfaces as the broad implementation default.
