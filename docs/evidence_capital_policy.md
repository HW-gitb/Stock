# Evidence Capital Policy

**Status**: Phase 7a design route owner with Phase 7a-4 feasibility-control schema routed. This document defines how paper and live-normalized evidence are interpreted without changing the fixed capital allocation policy.

**Owner role**: evidence-level, normalized-return, and ship-gate evidence policy owner. It complements `docs/portfolio_allocation_policy.md`, `schemas/portfolio_allocation.schema.json`, and `schemas/execution_aggregate_report.schema.json`.

## 1. Purpose

The project needs enough evidence to evaluate four systems without violating the fixed capital policy:

- A / US market allocation remains `35% / 65%`.
- Each market remains `1/3 long + 1/3 short + 1/3 liquidity`.
- A-share and US cash remain non-fungible by default.
- Liquidity buckets remain protected reserves unless an explicit user-approved rule says otherwise.
- The system remains manual-order-only.

The solution is not a global temporary capital pool. The solution is explicit evidence levels and normalized model/live reporting.

## 2. Evidence Levels

Future aggregate and lane reports must distinguish:

| Evidence level | Meaning | Allowed use |
|---|---|---|
| `paper` | Simulated or model-portfolio evidence using a defined bucket-capital basis. | Design iteration, preliminary comparison, variant selection, provider dry-run, research promotion input. |
| `live_normalized` | Real minimal-size forward/manual observation normalized to a declared bucket-capital basis. | Ship-gate evidence only when the report process is stable and scaling assumptions are recorded. |

Ship-gate full-size eligibility must not use pure paper evidence. Full-size manual use requires `live_normalized` forward evidence and the existing four-metric AND gate.

## 3. Normalized Return Requirements

Every normalized evidence report must record:

- `evidence_level`: `paper` or `live_normalized`.
- `observed_capital_used`: actual or simulated capital used.
- `normalization_basis`: target market / bucket capital basis.
- `bucket_ceiling_context`: preset, market, bucket, currency, and ceiling.
- `cost_model`: commissions, taxes, slippage, spread, borrow, and other relevant assumptions.
- `capacity_assumption`: whether the observed return can scale to the target bucket.
- `scaling_mode`: `linear`, `capped`, `not_valid`, or `not_assessed`.
- `liquidity_constraints`: ADTV, lot, limit-up/down, halt, spread, borrow, or other constraints.
- `manual_execution_boundary`: always true; no broker or OS automation.
- `limitations`: reasons normalized evidence may overstate or understate full-bucket feasibility.

`live_normalized` must not blindly multiply small real trades to full-bucket returns. If liquidity, capacity, borrow, halt, or limit-lock behavior makes scaling unreliable, `scaling_mode` must be `capped` or `not_valid`, and ship-gate evaluation must treat the limitation explicitly.

Every alpha estimate must distinguish gross and net return. Long thesis reports, burst reports, and aggregate evidence reports must either provide cost-adjusted expected/realized alpha or explicitly mark why net alpha is not yet estimable. Cost scope must include the relevant commissions, taxes, stamp duty, slippage, spread, borrow, FX, dividends, withholding, ADR fees, cash drag, and missed-trade opportunity cost where applicable.

## 4. Paper Evidence

Paper evidence is useful but limited.

Allowed:

- compare bounded variants against a baseline,
- test burst trigger definitions,
- test long thesis schema and provider fields,
- inspect drawdown and monthly cohort behavior,
- decide whether a lane is worth live observation.

Not allowed:

- claim full-size manual ship-gate pass,
- bypass the >=12-month forward live requirement,
- treat latest-only data as PIT-safe history,
- ignore transaction costs or capacity limits,
- replace provider evidence.

## 5. Live-Normalized Evidence

Live-normalized evidence can contribute to ship-gate evaluation only when:

1. The report process was stable before the observation.
2. Candidate decisions were captured before outcomes.
3. Mature windows are separated from immature diagnostics.
4. Rejected and failed candidates are retained.
5. Costs and execution constraints are recorded.
6. Scaling assumptions are explicit and reviewable.
7. The evidence remains within market-local and bucket-local capital policy.
8. Actual position reconciliation is available for the observation, including manual overrides and differences between system recommendation and user action.

Minimal-size live observations are execution-feasibility and evidence-quality tools. They do not imply full-size authorization until the full ship gate passes.

Full position-reconciliation workflow belongs to the coordinator phase, but a minimal reconciliation record is required before any evidence can be labeled `live_normalized`. Without actual position and override records, the evidence remains paper-quality.

## 6. Capital Governance Boundary

This policy does not change `docs/portfolio_allocation_policy.md`.

Prohibited:

- no temporary global AUM pool,
- no automatic cross-market transfer,
- no automatic use of liquidity bucket,
- no cross-bucket borrowing,
- no full-size manual use before ship gate,
- no broker integration or OS automation.

If the user later approves a real-money evidence budget, it must be:

- market-local,
- bucket-local,
- explicitly approved by the user,
- recorded with audit reason,
- still subject to ship-gate failure mode if metrics fail.

## 7. Required Schema Follow-Up

Phase 7a-4 adds `schemas/evidence_feasibility_controls.schema.json` for burst promotion, capacity, liquidity, slippage, borrow / limit-risk, and circuit-breaker feasibility. It is a contract / example / test baseline, not a runner output schema.

Before aggregate reports consume this policy, Phase 7a-5 / later implementation-adjacent slices must update report schemas such as `schemas/execution_aggregate_report.schema.json` and runner output contracts to include:

- `evidence_level`,
- normalization basis,
- observed capital used,
- scaling mode,
- cost / slippage assumptions,
- capacity limitations,
- gross versus net alpha fields,
- cash drag / opportunity-cost fields when relevant,
- actual-position reconciliation reference for live-normalized evidence,
- manual override reason fields,
- ship-gate eligibility rules that reject paper-only full-size claims.

This schema update is a separate reviewed implementation-adjacent slice. It should happen before `burst_lane_report`, `long_alpha_thesis_report`, or research promotion reports rely on normalized returns.
