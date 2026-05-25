# 48h Regulatory Risk Enrichment

Purpose: identify whether the candidate has material regulatory, exchange inquiry, media investigation, or official warning events in the last 48 hours.

Use only after deterministic report generation. This prompt can add LLM notes and risk context, but it must not override `veto` or `analyzer_invocations`.

Inputs:
- `as_of`, `ts_code`, `name`
- `risk_flags` and `evidence`
- checked regulatory/news sources, if available

Output:
- `status`: `clear` | `risk_found` | `unknown`
- `events`: list of concise event summaries with source/date
- `confidence`: `high` | `medium` | `low` | `unknown`
- `report_patch`: optional update for `llm_notes.sections[]`

Rules:
- If no live search/source check was performed, return `unknown`, not `clear`.
- Any material 48h risk should be written as an LLM risk note; deterministic hard-veto policy changes require analyzer code, not prompt text.
