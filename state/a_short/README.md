# A-short Local State

This folder holds user-maintained local state for A-short reports. JSON/CSV files here are ignored by git because they can contain account, position, or execution details.

For weekly M6.7, fill the five CSV templates under `state/a_short/account_state_csv/`, then use `runners/a_short_account_state_from_manual_tables.py` to publish one atomic `a_short_account_bundle` such as `state/a_short/account_bundle.json`. Pass that generated bundle to `weekly_screening.cmd -Account`; do not hand-author a bare account JSON.

The authoritative CSV columns, conversion command, and account-contract details are in `docs/a_short_account_state_manual_tables_4_3.md`. The system must not connect to a broker, fetch account holdings, or place orders.

`factor_comparison_private/` is the local, gitignored home for A-short D1/D3 factor-comparison results. It is settled only from the existing forward-price cache and may contain ticker lists, paired returns, and user decisions; do not put those files in tracked result or document folders.
