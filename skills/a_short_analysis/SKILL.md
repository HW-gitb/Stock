---
name: a_short_analysis
description: Use for the A-share short-term weekly screening and M6.7 operation report, with older single-stock deterministic reports retained as research-only tools.
---

# A Short Analysis

This Skill is a usage guide. The standard Windows production launcher is `runners/weekly_screening.cmd`; it starts the implementation `runners/weekly_screening.ps1` with a process-scoped execution-policy bypass, then runs screening and publishes the receipt-gated M6.7 weekly bundle.

`runners/run_analysis_report.py` is research-only. It must not be presented as the current production-facing operation path.

## Non-Runtime Reference Boundary

`reference/v14.2_spec.md` is a frozen design specification, not a runtime prompt. Do not paste it into an LLM as operating instructions, do not treat its persona / workflow language as production execution guidance, and do not use it to authorize live operation advice, buy / sell actions, or sizing outside the schema-validated runner / report workflow and reviewed ship-gate evidence.

The current production-facing path is the weekly wrapper plus a matching `weekly_m67.receipt.json` whose `stage_status=complete`, identity fields, and `outputs_digest` bind the exact JSON and deterministic Markdown bytes. Formal consumers, including post-run sidecar health, must use the shared strict validation snapshot; launcher manifests cannot self-assert `complete` or override snapshot identity. Current invocation intent dominates directory history: `skipped` / `not_run` must ignore old weekly bundles and old pipeline manifests, while only `requested` may derive `complete` from the strict snapshot. A failed, mismatched, non-canonical, or content-drifted requested bundle is non-consumable and must remain visibly failed/unavailable rather than reuse an older complete health claim.

A default run that fails preflight before canonical resolution has no as-of identity, so it exits nonzero without emitting a dated failed receipt; any existing complete bundle remains only the previous completed run. With explicit `-AsOf`, or after canonical resolution, a failure invalidates the same-date bundle.

## Inputs

- `result/a_short/<as_of>/analysis_input.json`
- Optional private `state/a_short/account_bundle.json` (`a_short_account_bundle` generated from manual CSV tables)
- `schemas/deterministic_report.schema.json`
- Optional: user-provided current news, regulatory, industry, or cross-market context for LLM enrichment

## Quick Start

First convert the five manually maintained CSV tables into one private atomic bundle, then run the weekly screening and M6.7 operation report:

```powershell
.\runners\a_short_account_state_from_manual_tables.py --input-dir state\a_short\account_state_csv --as-of 20260522 --out state\a_short\account_bundle.json
.\runners\weekly_screening.cmd -AsOf 20260522 -L3Mode pit -Account state\a_short\account_bundle.json
```

Do not hand-author a bare account JSON for `-Account`; the converter's output is the required `a_short_account_bundle`. CSV columns and boundary details belong to `docs/a_short_account_state_manual_tables_4_3.md`. For the normal live cadence, omit `-AsOf` and `-L3Mode` so the wrapper resolves the canonical decision date. Use `runners/run_analysis_report.py` only for explicit research/replay work.

State replay is deterministic by default: circuit-breaker expiry is evaluated at the as-of A-share close timestamp. Pass `--state-now <ISO timestamp>` only when intentionally replaying a different state evaluation time.

Expected outputs:

- `result/a_short/<as_of>/reports/<ts_code>.json`
- `result/a_short/<as_of>/reports/<ts_code>.md`

Use the project Python with runtime validation dependencies installed for report generation:

```powershell
python -m pip install -r requirements.txt
```

`jsonschema` is a runtime validation dependency for `analysis_input` / report contract checks, not an optional dev-only package.

Generate with an enrichment patch:

```powershell
python runners\run_analysis_report.py --as-of 20260522 --ts-code 600415.SH --enrichment-path path\to\enrichment.json
```

## Deterministic Boundary

Do not edit deterministic fields by hand:

- `decision`
- `veto`
- `entry_plan`
- `exit_plan`
- `position_size`
- `risk_flags`
- `evidence`
- `data_lineage`
- `analyzer_invocations`

For Phase 4 v1, `decision.action` should remain `skip` or `watch`. Do not turn an LLM interpretation into `buy`.

If the report has a hard veto, treat it as a hard stop unless analyzer code changes in `engine/analyzer/` and tests pass.

## Reading The Report

Use JSON for machine decisions and Markdown for human review.

Priority reading order:

1. `decision`
2. `veto.reasons`
3. `risk_flags`
4. `unknowns`
5. `evidence`
6. `llm_notes`
7. Markdown M6.7 table

If a field is `unknown`, respect the paired reason in `unknowns`. Do not fill missing values from memory.

## Optional LLM Enrichment

LLM enrichment is optional and separate from deterministic output. If it is written back to JSON, it must use `schemas/deterministic_report_enrichment.schema.json` and runner `--enrichment-path`.

The enrichment patch may only update:

- `llm_notes.enabled`
- `llm_notes.sections[]`

It must not override analyzer decisions.

Use these prompt files only when the user asks for deeper analysis or when a downstream workflow explicitly needs LLM notes:

- `prompts/industry_trend.md`
- `prompts/regulatory_48h.md`
- `prompts/policy_news.md`
- `prompts/earnings_no_good_repair.md`
- `prompts/cross_market_linkage.md`
- `prompts/hidden_risk.md`

For each enrichment section, record:

- source/date checked, or state that no live source was checked
- status
- confidence
- concise evidence chain

If live/external data was not checked, output `unknown`, not `clear`.

## Reference Files

- `reference/v14.2_spec.md` is the frozen design specification, not a runtime prompt; the non-runtime boundary above applies before any reference-spec content is used.
- `schemas/deterministic_report_coverage.md` records what Phase 4 v1 covers and what remains unknown.

## Validation

Run unit tests after changing runner, schema, or this Skill workflow:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Run one real sample before claiming the workflow is usable:

```powershell
python runners\run_analysis_report.py --as-of 20260522 --ts-code 600415.SH
```
