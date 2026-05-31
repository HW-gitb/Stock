# Alpha Validation Action Guide

**Status**: current highest action guide for Phase 7a+ strategy, evidence, provider, DataHub, and implementation work.

**Authority**: `AGENTS.md` remains the root rule and fixed-governance owner. This document is the binding Phase 7a+ execution guide routed from `AGENTS.md`. If an older roadmap, handoff, or design note conflicts with this guide, follow `AGENTS.md` plus this guide unless the user explicitly approves a newer reversal.

## 1. Final Baseline

The system must optimize for real, reproducible, cost-adjusted, manually executable alpha, not attractive paper backtests.

Fixed target:

- A-share short-term: risk control plus A-share burst.
- US short-term: risk control plus US burst.
- A-share long-term: push alpha.
- US long-term: push alpha.

Fixed governance:

- A-share / US allocation remains `35% / 65%`.
- Each market remains `1/3 long + 1/3 short + 1/3 liquidity`.
- A-share cash and US cash are non-fungible by default.
- The system outputs analysis, screening, backtests, reviews, and reports only. The user places orders manually.
- Full-size manual use requires the four-metric AND ship gate: monthly alpha t-stat >= 2.0, Sharpe >= 1.0, max drawdown <= 15%, and forward live data >= 12 months.

## 2. Current Execution Rule

Stop broad design looping. Phase 7a-1 through Phase 7a-5 are complete. Phase 7a-3 adds the provider priority and provisional benchmark contract in `docs/provider_priority_benchmark_contract.md`; Phase 7a-4 adds evidence feasibility controls in `docs/evidence_feasibility_controls.md` and `schemas/evidence_feasibility_controls.schema.json`; Phase 7a-5 adds evidence report schemas in `docs/evidence_report_schema_contract.md` and `schemas/evidence_report.schema.json`. Phase 7b-1 adds provider evidence / drift-monitor contracts in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`. Phase 7b-2 provider capability evidence population has P1 public-source, market-data-candidate, authorization / cost / stability, benchmark / GICS, fundamentals observed-date, and coverage / fallback / incident candidate snapshots in `docs/provider_evidence_p1_us_public_sources_20260528.json`, `docs/provider_evidence_p1_us_market_data_candidates_20260528.json`, `docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json`, `docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json`, `docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json`, and `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`, plus the readiness review matrix in `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`, which makes P1 documentation evidence collection complete but still implementation-blocked.

The next execution slice should produce a Phase 7b-2 P1 access-decision and sample-validation plan based on the readiness matrix. Do this without selecting a final provider, fetching data, requesting tokens / trials, or building adapters / DataHub tables.

After that reviewed slice is committed, the next alpha-validation slice is A-share `minimal_data_burst` research-only falsification. US-long SEC observed-date / parser feasibility remains provider-evidence work; it proves data construction feasibility, not long-alpha existence.

Phase 7a contract slices must not:

- select a final provider,
- fetch new provider data,
- add a provider adapter,
- create DataHub tables,
- change `A-EGS/egs_main.py`,
- change strategy runner behavior,
- describe paper evidence as ship-gate evidence.

## 3. Phase 7a-1 Mandatory Audit Coverage

The first audit must cover all current sub-lanes:

- `a_short_steady`,
- `a_short_variants`,
- `a_share_burst_minimal_data`,
- `a_share_burst_full_data`,
- `us_short_steady`,
- `us_burst_minimal_data`,
- `us_burst_full_data`,
- `a_long_core_quality`,
- `a_long_re_rating_catalyst`,
- `us_long_core_quality`,
- `us_long_re_rating_catalyst`.

Portfolio synthesis must aggregate these into six parent lanes:

- `a_short_steady`,
- `us_short_steady`,
- `a_burst`,
- `us_burst`,
- `a_long`,
- `us_long`.

The schema must include `parent_lane_id` and `parent_aggregation_rule`.

Allowed `parent_aggregation_rule` values:

- `active_stage_only`,
- `weighted_by_maturity`,
- `sum_with_overlap_penalty`,
- `take_dominant_role`.

Do not simply add minimal/full burst contribution together. They are maturity stages of the same parent lane. Do not treat steady baseline and variants as independent alpha lanes; variants are optimization tracks.

## 4. Provider Snapshot And Confidence

Audit needs provider readiness but provider evidence is incomplete. Solve this with a lightweight status snapshot, not by starting provider implementation early.

Audit schema must include:

- `provider_status_snapshot_ref`,
- `provider_readiness_confidence`: `high`, `medium`, or `low`,
- `provider_status_source`,
- `provider_status_limitations`.

The snapshot may inventory known fields, known PIT limitations, authorization/cost/stability unknowns, and ready evidence. It must not select providers, fetch data, create adapters, or build DataHub tables.

## 5. Hypothesis Registration And Multiple Testing

Every lane hypothesis used for audit decisions must be registered as a structured object, not just timestamped.

Required `hypothesis_registration` fields:

- `timestamp`,
- `hypothesis_text`,
- `registered_by_session_id`,
- `data_window_at_registration`,
- `evidence_available_at_registration`,
- `source_doc_refs`.

Required evidence-integrity fields:

- `evidence_window_type`: `in_sample`, `out_of_sample`, `forward`, or `live_normalized`,
- `tests_performed_count`,
- `multiple_testing_notes`,
- `adjustment_method`: `none`, `bonferroni`, `fdr`, `holdout`, `forward_confirmation`, or `not_applicable`,
- `minimum_effective_sample_required`,
- `current_effective_sample`,
- `power_status`: `insufficient`, `preliminary`, or `adequate`.

Do not derive expected alpha from a historical best slice without labeling it exploratory and registering a confirmation path.

Research preregistration is mandatory before any research experiment can influence future production decisions. The preregistration artifact should reuse the `hypothesis_registration` shape above and add freeze controls for universe, benchmark, holding period, entry / exit rule, success or falsification threshold, and `test_budget`.

A research experiment may skip a program-level test-budget ledger only when it is a single frozen test: one preregistered hypothesis, frozen parameters, frozen universe, frozen benchmark, frozen holding period, frozen entry / exit rule, and `test_budget = 1`. If the work introduces a second promotion-relevant hypothesis, parameter search, variant search, benchmark sweep, holding-period sweep, or other promotion-relevant degree of freedom, create a singleton program-level test-budget ledger before running that work.

Do not add ad hoc fields to `schemas/evidence_report.schema.json` to carry this budget. A later research-only evidence report should use the existing `research_experiment_log.hypothesis_registration_ref` to point back to the preregistration artifact. If a program-level ledger becomes necessary, keep it as a singleton audit / portfolio-level artifact or reference it from the audit synthesis; do not model it as one ledger per hypothesis.

## 6. PIT, Survivorship, And Security Master

Audit schema must force these risks into the open:

- `survivorship_handling_status`,
- `security_master_status`,
- `delisting_coverage_status`,
- `listing_status_coverage`,
- `halt_suspension_status_coverage`,
- `corporate_action_adjustment_status`,
- `industry_classification_pit_status`,
- `survivorship_bias_risk`.

Backtests that use today's live universe to infer historical alpha must be treated as low-confidence or invalid for ship-gate inference.

## 7. Fraud, Accounting, Regime, And Factor Exposure

For long lanes, fraud and accounting-quality red flags are mandatory. The schema must support:

- audit opinion / auditor change evidence,
- key audit matters when available,
- receivables growth versus revenue growth,
- CFO versus net income divergence,
- interest coverage deterioration,
- related-party transaction exposure,
- restatement or late-filing evidence.

Every lane must include:

- `regime_sensitivity_declaration`,
- `style_beta_or_factor_exposure_risk`,
- `factor_framework`.

Allowed `factor_framework` values:

- `capm`,
- `fama_french_3`,
- `fama_french_5`,
- `q_factor`,
- `barra_like`,
- `sector_size_value_momentum_proxy`,
- `benchmark_only_proxy`,
- `unknown`.

A-share and US lanes may use different frameworks. A proxy framework is acceptable in early audit; pretending it is full residual alpha attribution is not.

## 8. Risk-Filter Verdict Evidence

`continue_as_risk_filter` is not a free pass.

When a lane receives `continue_as_risk_filter`, the schema must require `risk_filter_effectiveness_evidence` with:

- with-filter versus without-filter drawdown comparison,
- win-rate comparison where relevant,
- false-positive comparison,
- false-negative risk,
- strong-candidate kill risk,
- regime sensitivity.

An already implemented filter can still fail the audit if it does not prove risk-control value.

## 9. Correlation Basis

Portfolio contribution must state the basis for correlation assumptions.

Audit schema must include:

- global `default_correlation_basis`,
- lane-level `correlation_basis`,
- lane-level override rationale when different from the global default.

Allowed `correlation_basis` values:

- `historical_benchmark_proxy`,
- `factor_model_proxy`,
- `hypothesized`,
- `unknown`.

## 10. Execution, Cost, And Capital Deployment

Every lane must distinguish gross and net expected alpha.

Required fields:

- `expected_alpha_return_gross_pct` where available,
- `expected_alpha_return_net_pct` or explicit reason it is not yet estimable,
- `cost_adjustment_required`,
- `cost_model_scope`,
- `execution_cost_feasibility_status`,
- `capacity_status`,
- `slippage_confidence`,
- `manual_execution_feasibility`.

Audit verdicts must define their capital-deployment effect without changing fixed allocation policy:

- `capital_deployment_effect`,
- `bucket_status`: `available_for_approved_lane`, `held_as_reserve`, `paper_only`, `minimal_observation_only`, or `blocked`,
- `deployment_scope`,
- `release_to_liquidity_reserve`,
- `requires_user_capital_decision`,
- `effect_rationale`.

Before Phase 8 implementation, each preset or lane contract must also define a `circuit_breaker_playbook` so drawdown events have deterministic manual actions instead of only a final ship-gate failure. The playbook must include tiered thresholds and actions such as:

- warn,
- size down,
- pause new entries,
- manual review,
- reactivation / cooldown rule.

## 11. Roadmap Placement For Accepted Gaps

| Phase | Mandatory coverage |
|---|---|
| Phase 7a-1 | alpha audit schema/example/tests, provider status snapshot, survivorship/security master, multiple testing, statistical power, regime sensitivity, factor framework, risk-filter effectiveness, parent aggregation, correlation basis, cost-adjusted alpha requirement, decision effect |
| Phase 7a-2 | spec revisions for long/short lanes; US market microstructure; monitoring contract; trading calendar/timezone semantics |
| Phase 7a-3 | provider priority reorder and provisional benchmark contract |
| Phase 7a-4 | burst minimal-to-full promotion criteria; evidence capital schema; concentration limits; liquidity/ADV sizing; market-impact/slippage constraints; drawdown / circuit-breaker tiered action playbook |
| Phase 7a-5 | evidence report schemas; immutable decision packet; cost-adjusted return details; cash drag/opportunity cost; manual override and minimal position reconciliation; long thesis outcome log; research experiment log |
| Phase 7b-1 | provider evidence / drift monitor schema-first contract only; no real provider data fetched and no provider selected |
| Phase 7b-2 | provider capability evidence population: P1 six snapshots and readiness matrix complete; next produce P1 access-decision / sample-validation plan; provider selection remains a separate reviewed decision |
| Phase 7b-2 follow-up | after the P1 access plan is reviewed/committed, start A-share minimal-data burst research-only falsification with preregistration; do not route US-long SEC parser feasibility as alpha validation |
| Phase 7c | DataHub shared layer / report contracts / reproducibility plumbing schema-first contract first; implementation only after reviewed contract scope |
| Phase 8 | lane implementation plus production monitoring, degradation detection, and kill switch |
| Phase 9 | coordinator, unified daily/weekly report, cross-lane conflict resolution, alert priority, full position reconciliation workflow |

## 12. Non-Optional Later Controls

These controls are allowed to land later, but they are not optional:

- data quality and provider drift monitoring,
- immutable decision packets for reproducibility,
- production monitoring and kill switches,
- drawdown / circuit-breaker tiered action playbook with warn, size-down, pause, manual-review, and reactivation rules,
- tax / FX / dividend / withholding / ADR fee treatment,
- trading calendar and timezone semantics,
- cash drag and missed-trade opportunity cost,
- manual override logging,
- position reconciliation before any `live_normalized` claim,
- cross-lane conflict resolution,
- unified report priority to avoid alert fatigue.

## 13. Current Next Step

After the Phase 7b-2 P1 public-source, market-data-candidate, authorization / cost / stability, benchmark / GICS, fundamentals observed-date, coverage / fallback / incident snapshots, and readiness review matrix, the next `执行` should produce the P1 access-decision and sample-validation plan from `docs/provider_priority_benchmark_contract.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`.

Do not start Phase 7c, provider adapters, production provider data fetches, DataHub tables, or runner changes before Phase 7b-2 evidence population is reviewed and accepted. Phase 7c itself must start as a schema-first DataHub / report / reproducibility contract before any implementation slice.

After the P1 access-decision and sample-validation plan is reviewed and committed, the next alpha-validation `执行` should be A-share `minimal_data_burst` research-only falsification. It must first create a preregistration artifact and must not change production runners, feed production decisions directly, or claim ship-gate evidence.
