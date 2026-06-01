---
name: a_short_analysis
description: Use for A-share short-term single-stock analysis after screening. Generates or reads Phase 4 deterministic reports via runners/run_analysis_report.py, then optionally enriches LLM-only sections without changing analyzer veto decisions.
---

# A Short Analysis

This Skill is a usage guide. It is not the deterministic executor.

The executor is `runners/run_analysis_report.py`. It reads `analysis_input.json`, calls the Phase 3 analyzer/state layer, validates `deterministic_report.schema.json`, and writes JSON + Markdown.

## Inputs

- `result/a_short/<as_of>/analysis_input.json`
- `state/a_short/*.json`
- `schemas/deterministic_report.schema.json`
- Optional: user-provided current news, regulatory, industry, or cross-market context for LLM enrichment

## Quick Start

Generate one deterministic report:

```powershell
python runners\run_analysis_report.py --as-of 20260522 --ts-code 600415.SH
```

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

- `reference/v14.2_spec.md` is the design specification, not a runtime prompt.
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
