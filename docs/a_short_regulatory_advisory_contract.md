# A-short official-regulatory advisory confirmation contract

## Scope

This is an advisory workflow for already-fetched `official_structured` CNINFO events. It does not fetch a source by itself and does not alter production EGS screening, Rule6, historical backtests, position sizing, broker access, or orders.

The official-source fetch remains explicitly authorized by the existing weekly-pipeline `--confirm-fetch-authorized` gate. A fetch failure remains `unknown`; it is never interpreted as a clean regulatory result.

## Workflow

1. The weekly pipeline obtains PIT-valid CNINFO official events for the current `as_of` and candidate pool. Each event has a deterministic SHA-256 fingerprint over its code and source/title/category/disclosure date/link/risk/severity fields.
2. Every official `high` event first remains `pending_confirmation`, including an event with a non-empty official link. The M6.7 report shows that state and its event fingerprint in the semantic trace.
3. A human checks the original official source and supplies a local JSON document matching `schemas/a_short_regulatory_advisory_confirmation.schema.json`. The document is bound to exactly one `as_of`, the EGS candidate digest, and one exact event fingerprint per decision. It contains no provider token, raw response, request URL, or reviewer identity.
4. `--regulatory-confirmations <path>` validates the schema, binding, timestamp, non-empty review note, uniqueness, and that every supplied confirmation matches a current CNINFO event. A stale, duplicate, cross-pool, or unmatched confirmation stops the run before report output.
5. Only `confirmed_material` for an official `high` event with a non-empty `url_or_pdf` may create the non-production M6.7 `semantic_official` advisory veto. `confirmed_not_material` and `needs_more_information` never relax another risk control; the latter remains pending. A blank official link remains pending even if it is marked material.

## Operation

Use the existing approved weekly command and append `--regulatory-confirmations <local-confirmation.json>` only when the run also has current official CNINFO semantic evidence. The confirmation file should be local operational input; the supplied schema example is illustrative only and must not be reused against a live event.

## Non-negotiable boundary

The advisory veto is a manual-review signal inside non-production M6.7 only. It is not a production hard veto, does not delete an EGS candidate, does not modify Rule6, and cannot automate a trade.
