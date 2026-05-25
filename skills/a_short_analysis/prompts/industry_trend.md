# Industry Trend Enrichment

Purpose: judge whether the candidate's industry backdrop is tailwind, neutral, or headwind for A-share short-term trading.

Use only when enriching a `deterministic_report` after `runners/run_analysis_report.py` has produced a schema-valid JSON report. Do not change analyzer veto results.

Inputs:
- report JSON: `as_of`, `ts_code`, `name`, `evidence`, `risk_flags`
- source candidate from `analysis_input.json`
- any user-provided current industry/news context

Output:
- `status`: `tailwind` | `neutral` | `headwind` | `unknown`
- `confidence`: `high` | `medium` | `low` | `unknown`
- `summary`: concise evidence-backed judgment
- `report_patch`: optional update for `llm_notes.sections[]`

Rules:
- If evidence is stale, missing, or not independently checked, return `unknown`.
- Do not convert this judgment into `decision.action=buy`; Phase 4 v1 runner owns deterministic actions.
