# Evidence Feasibility Controls

**Status**: Phase 7a-4 schema-first baseline.

**Owner role**: burst minimal-to-full promotion, evidence-capital feasibility, concentration / liquidity / ADV sizing, slippage / borrow / limit-risk feasibility, and drawdown / circuit-breaker playbook owner.

**Contract artifact**: `schemas/evidence_feasibility_controls.schema.json` v1.0.0 with example `schemas/examples/evidence_feasibility_controls.example.json`.

**Non-scope**: this document does not select providers, fetch data, create adapters, implement DataHub tables, change strategy rules, relax ship gates, authorize broker / OS automation, or approve full-size manual use.

## 1. Inputs

This contract consumes:

- `docs/phase7a_alpha_plausibility_audit.json`
- `docs/provider_priority_benchmark_contract.md`
- `docs/evidence_capital_policy.md`
- `docs/burst_lane_spec.md`
- `docs/us_short_spec.md`
- `docs/portfolio_allocation_policy.md`
- `schemas/alpha_plausibility_audit.schema.json`
- `schemas/provider_capability_catalog.schema.json`

The first alpha audit keeps minimal-data burst alive only for paper / research and keeps full-data burst `defer_until_provider_ready`. Phase 7a-4 does not reverse that verdict. It defines what evidence and risk controls must exist before any later promotion review can happen.

## 2. Scope Locks

| Lock | Required value |
|---|---|
| Final provider selection | Not selected |
| Data fetch | Not allowed |
| Provider adapter | Not allowed |
| DataHub table implementation | Not allowed |
| Runner or strategy-rule change | Not allowed |
| Paper evidence as ship-gate evidence | Not allowed |
| Global or cross-market capital pool | Not allowed |
| Automatic order / broker / OS action | Not allowed |
| Manual order boundary | Preserved |

## 3. Covered Lanes

The schema must cover the four burst maturity lanes:

| Lane | Parent lane | Current evidence boundary |
|---|---|---|
| `a_share_burst_minimal_data` | `a_burst` | Paper / research only |
| `a_share_burst_full_data` | `a_burst` | Provider/manual evidence blocked before minimal live observation |
| `us_burst_minimal_data` | `us_burst` | Paper / research only |
| `us_burst_full_data` | `us_burst` | Provider/manual evidence blocked before minimal live observation |

Minimal and full tiers are maturity stages of the same parent lane. Portfolio contribution must use the active reviewed stage only; do not add minimal-paper contribution and full-data hypothetical contribution together.

## 4. Minimal-To-Full Promotion Gate

Promotion from `minimal_data_burst` to a full-data review path requires all of these to be present in a reviewed evidence packet:

1. Benchmark-relative paper alpha or a documented reason the paper signal is still worth a full-data test.
2. Drawdown review on mature cohorts, not only immature diagnostics.
3. False-positive behavior, including failed breakouts and rejected candidates.
4. A non-price confirmation path: dated catalyst, filing / event, capital flow, options / borrow, or manual evidence.
5. Cost, liquidity, spread, borrow, halt, and limit-risk feasibility.
6. Retention of rejected and failed candidates from the same stable report path.
7. Paired comparison between minimal-only and minimal-plus-full-data decisions after full data is available.

Minimal-data burst remains paper / research by default. It is not live-eligible merely because price momentum looks strong.

## 5. Evidence Capital And Concentration

Sizing remains inside the relevant market short bucket. The schema baseline keeps these caps explicit:

| Stage | Lane cap | Notes |
|---|---:|---|
| Research / paper | <=30% of relevant short bucket | Simulation only; no live sizing implied. |
| Minimal live observation | <=10% of relevant short bucket | Full-data path only, after reviewed report path and bucket context exist. |
| 6-month preliminary pass | <=20% of relevant short bucket | Requires a reviewed evidence packet, not just six elapsed months. |
| 12-month ship-gate pass | <=30% of relevant short bucket | Still requires monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and >=12 months live-normalized forward evidence. |

Baseline per-name and cluster caps are conservative starting points for later implementation contracts, not final production sizing:

- Minimal-data tiers: no live exposure; paper diagnostics must still record capacity assumptions.
- Full-data tiers: example baseline uses <=2.5% of short bucket per name and <=7.5% per theme / event cluster before stronger evidence.
- No global AUM pooling, cross-market pooling, or automatic liquidity-bucket borrowing is allowed.

## 6. Liquidity / ADV Sizing

Every burst evidence packet must record:

- ADV / amount / dollar-volume window and metric.
- Maximum order as percent of ADV.
- Maximum participation rate.
- Spread or spread proxy before any `live_normalized` label.
- Halt / suspension / LULD / limit-state fields as market-specific hard blocks.
- Scaling mode: `linear`, `capped`, `not_valid`, or `not_assessed`.

If liquidity or execution capacity is not reviewable, evidence stays paper-only or the scaling claim is capped / not valid.

## 7. Cost, Slippage, Borrow, And Limit Risk

Gross and net return must be separated. Zero-cost defaults are forbidden.

Required cost scope includes the market-relevant subset of:

- commissions,
- stamp duty / taxes,
- spread,
- slippage,
- market impact,
- borrow fee,
- FX,
- ADR fee,
- dividends / withholding,
- cash drag,
- missed-trade opportunity cost.

A-share burst must explicitly handle T+1, lot size, limit-up/down, halt / suspension, and limit-lock execution risk.

US burst must explicitly handle dollar ADV, spread, extended-hours session labels, LULD, Reg SHO / SSR where short-side logic is used, locate / borrow availability, borrow fee, short interest, and days to cover.

## 8. Circuit-Breaker Playbook

Every burst lane control must include these actions:

| Action | Meaning |
|---|---|
| `warn` | Evidence anomaly is visible but not yet a lane breach. |
| `size_down` | Capacity, slippage, drawdown, or false-positive evidence requires lower sizing / capped scaling. |
| `pause_new_entries` | New candidates stop until root-cause review clears the breach. |
| `manual_review` | Reviewer decides continue, redesign, or do-not-implement. |
| `reactivation_cooldown` | Restart only after documented fix and cooldown evidence; failed windows stay in history. |

The playbook never triggers automatic orders. It only changes report state, evidence interpretation, and manual recommendation eligibility.

## 9. Validation Contract

The reviewed baseline is complete when:

1. `schemas/evidence_feasibility_controls.schema.json` validates.
2. `schemas/examples/evidence_feasibility_controls.example.json` validates against the schema.
3. Regression tests prove scope locks, four-lane coverage, paper-only minimal tiers, no capital pooling, and required circuit-breaker actions.
4. Routing docs point Phase 7a-4 work here.
5. `docs/CURRENT.md` records Phase 7a-4 as complete and points the evidence-report contract to Phase 7a-5.

## 10. Next Use

Phase 7a-5 evidence report schemas now live in `docs/evidence_report_schema_contract.md` and `schemas/evidence_report.schema.json`. They consume this contract through `evidence_feasibility_context`.

Phase 7b-1 provider evidence / drift-monitor contracts now live in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`; Phase 7b-2 has six P1 snapshots through `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`, but P1 remains partial / blocked and needs a readiness review matrix. Phase 7a-4 does not reorder provider priority.
