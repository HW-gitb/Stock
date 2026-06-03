# Research

**Owner role**: isolated research-only artifacts, preregistrations, and future experiment logs. Research outputs cannot feed production runners directly; promotion requires schema review, Claude review, user approval, and an evidence report.

Current preregistration status:

- `research/preregistrations/a_share_minimal_data_burst_20260531.json` - superseded A-share `minimal_data_burst` single frozen test preregistration; remains `BLOCKED_DO_NOT_RUN` because its benchmark entry basis is invalid for promotion-relevant evidence.
- `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json` - corrected-basis superseding preregistration; it changes only benchmark entry basis to same-anchor CSI1000 T+1 open -> T+5 close and freezes the original universe, thresholds, holding period, criteria, and `test_budget = 1`. A frozen-cohort preflight found `valid_signal_events = 0`, so do not run outcome / excess calculation for this artifact.
- `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json` - ledger-gated redesigned preregistration for one research-only full EGS candidate-surface test. It passed review and commit in `1a3e71e`; its preflight passed event-count, but its outcome / benchmark-excess slice failed the registered research-continuation thresholds.
- `research/preregistrations/a_short_steady_alpha_reaudit_20260603.json` - spent A-short steady-lane alpha re-audit preregistration. It froze the same-anchor 5d / 20d CSI1000 / CSI300 plan, multiple-testing / slice / factor / veto / PIT checks, and decision labels before the reviewed outcome run.

Current result / ledger status:

- `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json` - research-only preflight result for the corrected-basis artifact. It fails the preregistered event-count / power gate before outcome returns are informative.
- `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json` - research-only preflight result for the full-universe redesign. It passes event-count with `valid_signal_events = 134` and computes no outcome / benchmark excess.
- `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json` - research-only outcome report for the full-universe redesign. It records `decision = falsified_or_redesign_required`, mean net CSI1000 excess `-2.8696001309` percentage points, monthly clustered t-stat `-0.6312965283`, and max monthly signal-excess drawdown `26.5735343137` percentage points.
- `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/signal_events.csv` and `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/monthly_stats.csv` - reproducibility tables for the failed redesigned outcome slice.
- `research/results/a_short_steady_alpha_reaudit_20260603/evidence_report.json` - repaired research-only A-short steady re-audit outcome. It records `decision = risk_filter_only`: true same-anchor 5d CSI1000 net excess is positive but failed the frozen statistical gate (`mean = 0.6158673222` pp, monthly t `1.7623850474`; old uncorrected t `2.8769227582`). It is not alpha, production, ship-gate, or full-size evidence.
- `research/results/a_short_steady_alpha_reaudit_20260603/diagnostics.json`, `monthly_stats.csv`, `metric_summary.csv`, `stock_concentration.csv`, and `veto_filter_stats.csv` - reproducibility artifacts for the A-short steady re-audit.
- `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` - singleton program-level test-budget ledger for any redesigned A-share burst test after the zero-event preflight. It records the full-universe redesigned test as spent / failed outcome threshold; no new test is authorized.
- `research/ledgers/a_short_steady_alpha_reaudit_program_test_budget_ledger_20260603.json` - singleton test-budget ledger for the A-short steady re-audit. It records the one planned test as spent / research-continue-only; no rerun, rescue, production claim, ship-gate claim, or full-size use is authorized without a new reviewed preregistration and user approval.

Contracts:

- `schemas/research_preregistration.schema.json` - single frozen research test preregistration schema; v1.1.0 also supports preregistrations gated by the singleton program-level ledger.
- `schemas/a_short_steady_alpha_reaudit_preregistration.schema.json` - A-short steady alpha re-audit preregistration schema; locks same-anchor 5d / 20d metrics, required integrity checks, and no-production / no-ship-gate boundaries.
- `schemas/research_preflight_result.schema.json` - pre-outcome research preflight result schema; locks no outcome / benchmark-excess / provider-fetch / production / ship-gate side effects.
- `schemas/program_test_budget_ledger.schema.json` - singleton program-level test-budget ledger schema; locks spent tests, planned tests, and no-silent-rescue review gates.

This directory is not a provider-access, DataHub, runner, broker, or production signal directory.

Do not run a blocked preregistration. Do not run the corrected-basis artifact for outcome / excess calculation after the zero-event preflight. Do not rerun or rescue the full-universe redesigned test by changing parameters; any further redesigned A-share burst test needs a new ledger planned test plus reviewed preregistration before it runs. Do not rerun or rescue the spent A-short steady alpha re-audit by changing parameters, benchmarks, horizons, filters, or thresholds; any follow-up needs a new reviewed preregistration and user approval.
