# Research

**Owner role**: isolated research-only artifacts, preregistrations, and future experiment logs. Research outputs cannot feed production runners directly; promotion requires schema review, Claude review, user approval, and an evidence report.

Current preregistration status:

- `research/preregistrations/a_share_minimal_data_burst_20260531.json` - superseded A-share `minimal_data_burst` single frozen test preregistration; remains `BLOCKED_DO_NOT_RUN` because its benchmark entry basis is invalid for promotion-relevant evidence.
- `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json` - corrected-basis superseding preregistration; it changes only benchmark entry basis to same-anchor CSI1000 T+1 open -> T+5 close and freezes the original universe, thresholds, holding period, criteria, and `test_budget = 1`. A frozen-cohort preflight found `valid_signal_events = 0`, so do not run outcome / excess calculation for this artifact.
- `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json` - ledger-gated redesigned preregistration for one research-only full EGS candidate-surface preflight / test. It has passed review and commit in `1a3e71e`; its pre-outcome event-count / input-integrity preflight has now run and passed the event-count gate.

Current preflight / ledger status:

- `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json` - research-only preflight result for the corrected-basis artifact. It fails the preregistered event-count / power gate before outcome returns are informative.
- `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json` - research-only preflight result for the full-universe redesign. It passes event-count with `valid_signal_events = 134` and computes no outcome / benchmark excess.
- `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` - singleton program-level test-budget ledger for any redesigned A-share burst test after the zero-event preflight. It records the full-universe redesigned preflight as spent / passed event-count with outcome pending; no new test is authorized.

Contracts:

- `schemas/research_preregistration.schema.json` - single frozen research test preregistration schema; v1.1.0 also supports preregistrations gated by the singleton program-level ledger.
- `schemas/research_preflight_result.schema.json` - pre-outcome research preflight result schema; locks no outcome / benchmark-excess / provider-fetch / production / ship-gate side effects.
- `schemas/program_test_budget_ledger.schema.json` - singleton program-level test-budget ledger schema; locks spent tests, planned tests, and no-silent-rescue review gates.

This directory is not a provider-access, DataHub, runner, broker, or production signal directory.

Do not run a blocked preregistration. Do not run the corrected-basis artifact for outcome / excess calculation after the zero-event preflight. The full-universe redesigned preflight passed event-count, but it did not compute outcome returns or benchmark excess. Resolve `SR-DATA-003` and create a separate reviewed outcome / excess slice before any such calculation.
