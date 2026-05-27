# Handoff Index

This directory stores phase-level historical context and validation records. It is not the first-stop routing layer.

Use this file to decide which handoff to open. Do not read every handoff by default.

## Reading Policy

- Start from `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, the top 1-3 entries of `docs/SESSION_LOG.md`, and `docs/AI_REVIEW_PROTOCOL.md`.
- Open a handoff only when the current task touches that phase, schema, runner, benchmark policy, provider contract, or historical finding.
- Old handoffs are historical records. Do not merge, rewrite, or delete them for ordinary cleanup.
- Append to the current phase handoff by default. Create a new handoff only for the high-threshold cases listed in `AGENTS.md §交接记录`.

## Current Phase Handoff

- `2026-05-27_phase7_kickoff_spec_handoff.md` — Phase 7 provider capability / field catalog contract boundary, with later Phase 7a alpha-validation route and Phase 7a+ alpha reality action guide additions; schema-first, no provider selection, no data fetch, no adapter / DataHub table.

## Phase Index

- Phase 2:
  - `2026-05-24_phase2_v7.9_handoff.md`
  - `2026-05-24_phase2_tier1only_subset_handoff.md`
  - `2026-05-24_phase2_git_init_handoff.md`
  - `2026-05-24_phase2_validation_tooling_handoff.md`
  - `2026-05-24_phase2_6_datahub_guardrail_handoff.md`
  - `2026-05-24_phase2_24p_v710_results_handoff.md`
  - `2026-05-24_phase2_tier1_count_warning_handoff.md`
  - `2026-05-24_phase2_data_lineage_handoff.md`
- Phase 3:
  - `2026-05-24_phase3_kickoff_spec_handoff.md`
- Phase 4:
  - `2026-05-25_phase4_kickoff_spec_handoff.md`
- Phase 5:
  - `2026-05-25_phase5_kickoff_spec_handoff.md`
- Phase 6:
  - `2026-05-26_phase6a_kickoff_spec_handoff.md`
- Phase 7:
  - `2026-05-27_phase7_kickoff_spec_handoff.md` — includes Phase 7 provider capability, Phase 7a alpha-validation route, and Phase 7a+ alpha reality action guide additions.
  - Phase 7a additions live in the same file, not a separate handoff.
