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

Stop broad design looping. Phase 7a-1 through Phase 7a-5 are complete. Phase 7a-3 adds the provider priority and provisional benchmark contract in `docs/provider_priority_benchmark_contract.md`; Phase 7a-4 adds evidence feasibility controls in `docs/evidence_feasibility_controls.md` and `schemas/evidence_feasibility_controls.schema.json`; Phase 7a-5 adds evidence report schemas in `docs/evidence_report_schema_contract.md` and `schemas/evidence_report.schema.json`. Phase 7b-1 adds provider evidence / drift-monitor contracts in `docs/provider_evidence_drift_monitor.md` and `schemas/provider_evidence_drift_monitor.schema.json`. Phase 7b-2 provider capability evidence population has P1 public-source, market-data-candidate, authorization / cost / stability, benchmark / GICS, fundamentals observed-date, and coverage / fallback / incident candidate snapshots in `docs/provider_evidence_p1_us_public_sources_20260528.json`, `docs/provider_evidence_p1_us_market_data_candidates_20260528.json`, `docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json`, `docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json`, `docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json`, and `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`, plus the readiness review matrix in `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`, which makes P1 documentation evidence collection complete but still implementation-blocked. The P1 access-decision and sample-validation plan is `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` under `schemas/provider_p1_access_decision_plan.schema.json`; it is plan-only. The later 2026-06-02 approval artifact `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json` under `schemas/provider_p1_sample_validation_access_approval.schema.json` authorizes only a $0 AAPL / MSFT small-sample validation using the existing FMP key plus SEC EDGAR public APIs. It does not authorize provider contact, new token / trial / paid access, `yfinance`, full-market fetch, provider selection, Phase 7c, adapters, DataHub tables, runner changes, or production readiness claims.

The original A-share `minimal_data_burst` preregistration artifact in `research/preregistrations/a_share_minimal_data_burst_20260531.json` remains `BLOCKED_DO_NOT_RUN` because its benchmark entry basis is invalid for promotion-relevant evidence. The corrected-basis superseding preregistration is `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`, but its frozen-cohort preflight in `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json` found `valid_signal_events = 0`; do not run outcome / benchmark-excess calculation for that artifact. The next A-share burst alpha-validation action is ledger-gated redesign via `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json`. US-long SEC observed-date / parser feasibility remains provider-evidence work; it proves data construction feasibility, not long-alpha existence. Broad provider sample / trial / paid access remains blocked. The only current exception is the reviewed 2026-06-02 approval boundary for $0 AAPL / MSFT FMP existing-key + SEC public-API sample validation; everything broader still requires explicit user approval and a separate reviewed decision.

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

The current burst preregistration contract is `schemas/research_preregistration.schema.json`; the superseded blocked artifact is `research/preregistrations/a_share_minimal_data_burst_20260531.json`, and the corrected-basis superseding artifact is `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`. The corrected-basis artifact has a failed zero-event preflight and must not be run for outcome / excess calculation. It spent the single frozen event-count test; changing the A-share burst trigger thresholds, ranking cap, universe, benchmark, holding period, cost model, or pass/fail criteria now routes through the singleton program-level ledger `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json`.

The current A-short steady alpha re-audit contract is `schemas/a_short_steady_alpha_reaudit_preregistration.schema.json`; the preregistered artifact is `research/preregistrations/a_short_steady_alpha_reaudit_20260603.json`, with spent-test ledger `research/ledgers/a_short_steady_alpha_reaudit_program_test_budget_ledger_20260603.json`. The repaired outcome is `research/results/a_short_steady_alpha_reaudit_20260603/evidence_report.json`: true same-anchor 5d CSI1000 net excess is positive but failed the frozen statistical gate (`mean = 0.6158673222` pp, monthly t `1.7623850474`; old uncorrected t `2.8769227582`). Result: `risk_filter_only`, not alpha evidence. It does not authorize production, ship-gate evidence, full-size manual use, DataHub, provider work, runner changes, or parameter rescue.

A research experiment may skip a program-level test-budget ledger only when it is a single frozen test: one preregistered hypothesis, frozen parameters, frozen universe, frozen benchmark, frozen holding period, frozen entry / exit rule, and `test_budget = 1`. If the work introduces a second promotion-relevant hypothesis, parameter search, variant search, benchmark sweep, holding-period sweep, or other promotion-relevant degree of freedom, create a singleton program-level test-budget ledger before running that work.

Do not add ad hoc fields to `schemas/evidence_report.schema.json` to carry this budget. A later research-only evidence report should use the existing `research_experiment_log.hypothesis_registration_ref` to point back to the preregistration artifact. If a program-level ledger becomes necessary, keep it as a singleton audit / portfolio-level artifact or reference it from the audit synthesis; do not model it as one ledger per hypothesis.

### Measurement-Basis Lock

Promotion-relevant alpha, research-continuation evidence, and any future ship-gate evidence must declare stock entry basis, benchmark entry basis, exit basis, cost basis, and benchmark missing-data behavior before outcomes are computed.

Stock and benchmark legs must use the same entry anchor. For a tradable A-share stock leg that enters at T+1 open and exits at T+N close, the promotion-relevant benchmark leg must use benchmark T+1 open to the same T+N close. A stock T+1 open leg may not be mixed with a benchmark close basis for promotion-relevant alpha, research-continuation, or shipping evidence.

For the current A-share CSI1000 / CSI300 correction, benchmark open is available through Tushare `index_daily`. The same-anchor path is implemented by extending `runners/materialize_benchmark_monthly_returns_tushare.py` and the forward-daily benchmark fetch to request, persist, validate, and use benchmark T+1 open. Close-to-close is not an acceptable fallback for the current A-share / CSI1000 corrected revalidation.

The corrected-basis supersession is `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`, but the preflight result at `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json` found zero valid signal events. Do not run outcome / benchmark-excess calculation for that artifact; any redesigned A-share burst test must be ledger-gated and newly preregistered. Do not run the superseded blocked artifact.

If a future market or benchmark genuinely lacks benchmark open after reviewed provider evidence, close-to-close benchmark excess may be reported only as diagnostic evidence. It must not support research continuation, production promotion, or ship-gate claims unless a later reviewed contract explicitly accepts the limitation. This generic fallback does not apply to the current A-share CSI1000 / CSI300 case.

Corrected revalidation of the existing A-short 5d `excess_csi1000` clue is one frozen primary test: corrected 5d CSI1000. 10d and 20d may be reported as diagnostics only. Do not search thresholds, variants, benchmarks, holding periods, rank caps, or cost models during this corrected revalidation.

The current A-share burst preregistration may be superseded only to correct benchmark / entry-anchor basis. Trigger thresholds, universe, holding period, ranking cap, cost model, pass/fail criteria, and `test_budget = 1` must remain unchanged. Any broader change is fishing and requires a singleton program-level test-budget ledger before running.

The current `BLOCKED_DO_NOT_RUN` marker is a docs-only execution stop because no burst runner consumes this preregistration yet. Before any runner or automated research command consumes preregistration artifacts, it must either explicitly reject this marker or use a reviewed schema bump with a structured execution-status field such as `execution_status = blocked`; do not rely on a human-only note once automation exists.

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
| Phase 7b-2 | provider capability evidence population: P1 six snapshots, readiness matrix, and access-decision / sample-validation plan complete; 2026-06-02 approval allows only $0 AAPL / MSFT FMP existing-key + SEC public-API small-sample validation; provider selection, broad collection, and Phase 7c remain separate reviewed decisions |
| Phase 7b-2 follow-up | the corrected A-share minimal-data burst preregistration failed frozen-cohort preflight with `valid_signal_events = 0`; do not run its outcome / excess calculation, and route the next A-share burst alpha action through `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` plus a new reviewed preregistration; do not route US-long SEC parser feasibility as alpha validation |
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

The repaired A-short steady same-anchor re-audit has run and spent its one planned test. Plain result: the old 5d CSI1000 clue did not survive the corrected statistical gate; A-short steady remains risk-filter-only / research reference. Do not rescue it with regime slicing, parameter changes, reruns, or new validation cuts.

The current active alpha-search workstream is A-long only, but A-long signal search is currently blocked. The reviewed local-cache-only data-integrity audit in `research/results/a_long_data_integrity_audit_20260603/audit_report.json` passed all 6 planted-violation self-tests, then returned `blocked_missing_required_source`: local A-short derived `financial_*.pkl` caches omit `ann_date` / `end_date`, and the repo lacks raw PIT income / balancesheet / cashflow / fina_indicator lineage, full PIT universe proof, dividend / total-return treatment, and terminal delisting return lineage. The small Tushare route-validation execution at `docs/a_long_tushare_route_validation_execution_summary_20260604.json` touched existing Tushare data and was partial; the follow-up route-gap repair at `docs/a_long_tushare_route_gap_repair_execution_summary_20260604.json` passed tiny-sample field checks for SW membership mapping and older-delisted terminal price coverage. `docs/a_long_tushare_incremental_materialization_execution_summary_20260604.json` records the bounded 2022-2023 thin slice as `passed_thin_slice_materialization_shape`, `research/results/a_long_materialized_thin_slice_data_integrity_audit_20260604/audit_report.json` records `passed_thin_slice_data_integrity_not_alpha_ready`, and `docs/a_long_tushare_broader_materialization_execution_summary_20260604.json` records the 2018-2025 fixed-panel run as incomplete because all 9 `daily` price calls returned 0 rows. `docs/a_long_tushare_daily_price_route_diagnostic_packet_20260604.json` now locks the next diagnostic as two future fixed `daily` calls only: 2018-2025 isolated retest plus 2022 control, not executed in this slice. Simple result: the bigger data step failed the price leg, so A-long still cannot audit or search for alpha. After Claude Pass and a separate user `执行`, run the two-call diagnostic; only then decide whether the repair should be pacing/rate-limit or chunked-daily.

The original A-share `minimal_data_burst` preregistration remains `BLOCKED_DO_NOT_RUN`; the corrected-basis artifact has failed a frozen-cohort preflight with `valid_signal_events = 0`; the full-universe redesigned burst outcome failed its registered thresholds. Do not rerun, rescue, or reinterpret those burst artifacts as production evidence.

Do not start new provider work, production provider data fetches, DataHub tables, production runner changes, or Phase 7c implementation from this alpha re-audit. This repaired result does not prove alpha; full-size use still requires the fixed 12-month forward-live ship gate.
