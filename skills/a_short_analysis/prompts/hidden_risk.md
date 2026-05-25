# Hidden Risk Enrichment

Purpose: check risks that are hard to encode deterministically in Phase 4 v1, such as unlocks, convertible bond redemption, pledge pressure, lawsuits, negative investigations, or financing stress.

Use after deterministic report generation.

Inputs:
- report JSON
- `analysis_input.json` candidate fields
- checked external risk context, if available

Output:
- `status`: `risk_found` | `clear` | `unknown`
- `risks`: concise list with source/date when available
- `confidence`: `high` | `medium` | `low` | `unknown`
- `report_patch`: optional update for `llm_notes.sections[]`

Rules:
- If no external check was performed, return `unknown`, not `clear`.
- Do not hide uncertainty; write missing evidence explicitly.
