# Earnings No-Good Repair Enrichment

Purpose: judge whether an apparently strong earnings/growth signal has already been priced in, lacks follow-through, or shows "good data, bad reaction" repair.

Use after deterministic report generation and only when the candidate has relevant earnings/expectation evidence.

Inputs:
- `fundamental.expectation` fields from `analysis_input.json`
- recent price reaction context if available
- report `evidence` and `risk_flags`

Output:
- `status`: `repaired` | `not_repaired` | `not_applicable` | `unknown`
- `reasoning`: concise evidence chain
- `confidence`: `high` | `medium` | `low` | `unknown`
- `report_patch`: optional update for `llm_notes.sections[]`

Rules:
- If recent reaction data is unavailable, return `unknown`.
- Do not change `esp_non_positive` analyzer behavior from this prompt.
