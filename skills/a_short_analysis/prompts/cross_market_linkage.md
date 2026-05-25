# Cross-Market Linkage Enrichment

Purpose: identify material commodity, FX, index, or overseas market moves that may affect an A-share short-term candidate.

Use only when the candidate's business or industry makes cross-market linkage plausible.

Inputs:
- candidate industry and business context
- report `evidence`
- checked cross-market data or user-provided context

Output:
- `status`: `risk` | `supportive` | `neutral` | `not_applicable` | `unknown`
- `linked_markets`: concise list
- `confidence`: `high` | `medium` | `low` | `unknown`
- `report_patch`: optional update for `llm_notes.sections[]`

Rules:
- If no cross-market data was checked, return `unknown`.
- Pure sector association is not enough; explain the linkage mechanism.
