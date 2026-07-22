# A-short private holding regulatory-confirmation contract

## Scope

This is the optional **holding-domain** companion to the candidate confirmation contract. It is available only with a validated `--account` bundle and is used only after the M6.7 path has identified its holding semantics. It does not fetch official data, change EGS, Rule6, rank, thresholds, backtests, or sizing, and cannot automate an order.

No file means no new blocker: high official events remain `pending_confirmation`. A user-supplied file with a missing path, invalid schema, stale binding, or unmatched current event is a pre-publish FATAL.

## Binding

`schemas/a_short_regulatory_holding_confirmation.schema.json` binds one document to:

1. the weekly `as_of`;
2. the supplied account bundle's `snapshot_digest`;
3. the SHA-256 digest of the sorted complete account-position `ts_code` universe; and
4. each confirmed code plus its exact current official-event fingerprint.

The pipeline validates the binding before price fetch or publication. It separately attaches the records only while obtaining holding semantics, then rejects every unmatched record. A confirmation cannot cross accounts, survive a changed holding set, apply to an old event, or be reused as a candidate confirmation. A Top-N held candidate remains in the candidate domain; a holding-domain record for it is rejected as unmatched.

## Private operational use

Pass `--holding-regulatory-confirmations <private-file>` together with `--account`; the standard `weekly_screening.ps1` wrapper forwards it unchanged. The file is permitted only outside the repository or in a repository path that Git ignores. The private weekly holding output follows the existing `state/a_short/weekly_private/<as_of>/` route. Do not put raw official responses, request URLs, tokens, reviewer identity, or a live confirmation file in a tracked artifact.

## Effect boundary

Only a current `confirmed_material` high event with a non-empty official link may reach the existing non-production M6.7 `semantic_official_high_confirmed` holding advisory effect. The effect is `clear_review` for an existing holding; it is not an EGS or Rule6 verdict, a production veto, a sizing instruction, or an order.
