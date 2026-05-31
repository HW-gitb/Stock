# Research

**Owner role**: isolated research-only artifacts, preregistrations, and future experiment logs. Research outputs cannot feed production runners directly; promotion requires schema review, Claude review, user approval, and an evidence report.

Current preregistration status:

- `research/preregistrations/a_share_minimal_data_burst_20260531.json` - superseded A-share `minimal_data_burst` single frozen test preregistration; remains `BLOCKED_DO_NOT_RUN` because its benchmark entry basis is invalid for promotion-relevant evidence.
- `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json` - current corrected-basis superseding preregistration; it changes only benchmark entry basis to same-anchor CSI1000 T+1 open -> T+5 close and freezes the original universe, thresholds, holding period, criteria, and `test_budget = 1`.

Contracts:

- `schemas/research_preregistration.schema.json` - single frozen research test preregistration schema.

This directory is not a provider-access, DataHub, runner, broker, or production signal directory.

Do not run a blocked preregistration. The next A-share burst research-only falsification may run only the corrected-basis superseding artifact above after its change set has passed review and commit.
