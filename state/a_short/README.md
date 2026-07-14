# A-short Local State

This folder holds user-maintained local state for A-short reports. JSON/CSV files here are ignored by git because they can contain account, position, or execution details.

For weekly M6.7, create a local account-state file such as:

```text
state/a_short/account_state.json
```

Use `schemas/examples/a_short_account_state.example.json` as the template and validate against `schemas/a_short_account_state.schema.json`.

The file is manual input only. It records cash, current positions, Rule12 portfolio cooldown/recovery state, and Rule13 per-stock re-entry cooldowns. The system must not connect to a broker, fetch account holdings, or place orders.

`factor_comparison_private/` is the local, gitignored home for A-short D1/D3 factor-comparison results. It is settled only from the existing forward-price cache and may contain ticker lists, paired returns, and user decisions; do not put those files in tracked result or document folders.
