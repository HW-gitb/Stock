# Policy And News Enrichment

Purpose: summarize policy, sector news, and company news that may affect the candidate's short-term setup.

Use after deterministic report generation. Keep this section evidence-focused and separate from deterministic fields.

Inputs:
- report JSON
- source candidate from `analysis_input.json`
- checked policy/news context, if available

Output:
- `status`: `positive` | `negative` | `mixed` | `neutral` | `unknown`
- `key_points`: concise bullets with source/date
- `confidence`: `high` | `medium` | `low` | `unknown`
- `report_patch`: optional update for `llm_notes.sections[]`

Rules:
- Do not infer fresh news from stale memory.
- Do not output a buy/sell instruction; update LLM notes only.
