# Provider Evidence And Drift Monitor Contract

**Status**: Phase 7b-1 schema-first baseline plus Phase 7b-2 P1 public-source, market-data-candidate, authorization / cost / stability, benchmark / GICS, fundamentals observed-date, coverage / fallback / incident candidate evidence snapshots, P1 readiness review matrix, P1 access-decision / sample-validation plan, narrow access approval, AAPL / MSFT sample-validation result, FMP stable-endpoint mapping review, FMP stable retry result, post-retry remaining-blocker plan, fallback / incident / stability playbook, and incident-log contract. Broader provider access and implementation remain blocked.

**Owner role**: provider capability evidence population and data quality / provider drift monitoring contract after the Phase 7a provider-priority, feasibility, and evidence-report contracts. This document defines the evidence shape and routes reviewed evidence snapshots.

This document does not select providers, fetch data, create adapters, implement DataHub tables, change strategy rules, relax ship gates, or authorize broker / OS automation.

## 1. Purpose

Phase 7a established the lane verdicts, provider evidence queue, provisional benchmarks, feasibility controls, and evidence report shape. Phase 7b-1 converts the provider evidence queue into a machine-checkable provider evidence and drift-monitor artifact so later provider population, DataHub, or runner work cannot rely on guessed provider readiness. Phase 7b-2 uses that contract to populate actual provider capability evidence from reviewed provider documentation, fields, PIT, coverage, cost, fallback, and stability evidence.

The machine-checkable owner for provider evidence snapshots is `schemas/provider_evidence_drift_monitor.schema.json` v1.1.0. The example is `schemas/examples/provider_evidence_drift_monitor.example.json`. The current evidence-population artifacts are `docs/provider_evidence_p1_us_public_sources_20260528.json`, `docs/provider_evidence_p1_us_market_data_candidates_20260528.json`, `docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json`, `docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json`, `docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json`, and `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`. The machine-checkable owner for the P1 synthesis matrix is `schemas/provider_p1_readiness_review.schema.json`; the current matrix artifact is `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`. The machine-checkable owner for the P1 access-decision and sample-validation plan is `schemas/provider_p1_access_decision_plan.schema.json`; the current plan artifact is `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json`. The machine-checkable owner for the narrow user-approved sample-validation boundary is `schemas/provider_p1_sample_validation_access_approval.schema.json`; the current approval artifact is `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json`. The machine-checkable owner for the tracked no-secret sample-validation summary is `schemas/provider_p1_us_egs_sample_validation_summary.schema.json`; the current summary artifact is `docs/provider_evidence_p1_us_sample_validation_summary_20260602.json`, produced by `runners/us_egs_sample_validation.py`. The machine-checkable owner for the docs-only FMP current-endpoint mapping review is `schemas/provider_p1_fmp_endpoint_mapping_review.schema.json`; the current mapping artifact is `docs/provider_evidence_p1_us_fmp_current_endpoint_mapping_review_20260602.json`. The machine-checkable owner for the FMP stable retry summary is `schemas/provider_p1_fmp_stable_endpoint_retry_summary.schema.json`; the current retry artifact is `docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json`. The machine-checkable owner for the post-retry remaining blocker resolution plan is `schemas/provider_p1_remaining_blocker_resolution_plan.schema.json`; the current plan artifact is `docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json`. The machine-checkable owner for the fallback / incident / stability playbook is `schemas/provider_p1_fallback_incident_stability_playbook.schema.json`; the current playbook artifact is `docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json`. The machine-checkable owner for the incident-log contract is `schemas/provider_p1_incident_log_contract.schema.json`; the current contract artifact is `docs/provider_evidence_p1_us_incident_log_contract_20260602.json`.

## 2. Scope Locks

The schema scope fixes:

- `phase = 7b`,
- `purpose = provider_evidence_drift_monitor_contract`,
- `contract_status = schema_first_contract_only` or `provider_evidence_population_snapshot`,
- `provider_selection_allowed = false`,
- `data_fetch_allowed = false`,
- `provider_adapter_allowed = false`,
- `datahub_table_implementation_allowed = false`,
- `strategy_rule_change_allowed = false`,
- `broker_or_order_automation_allowed = false`,
- `manual_order_only = true`,
- `ship_gate_relaxed = false`,
- `production_ready_claim_allowed = false`.

These locks mean the artifact can record evidence status and monitoring requirements, but it cannot approve provider selection or implementation.

## 3. Required Evidence Queue

The artifact must carry all four priorities from `docs/provider_priority_benchmark_contract.md`:

| Priority | Family |
|---|---|
| `P1` | US fundamentals, filings, corporate actions, security master, GICS, and US benchmark readiness |
| `P2` | A-share fundamentals, announcements, restatements, SW history, and A-long benchmark / industry readiness |
| `P3` | Burst full-data event, flow, options, borrow / short-interest, pre-market / after-hours, and manual evidence workflow |
| `P4` | Already-proven A-share EOD, limit, calendar, CSI benchmark, and candidate-universe helper surfaces |

P4 ready helper evidence must be recorded, but it does not authorize broad A-share DataHub implementation ahead of P1-P3 review.

## 4. Provider Evidence Records

Each provider evidence record must state:

- priority and affected lanes,
- market and data class,
- field family,
- provider candidate or placeholder ID,
- source basis,
- capability status and production-use status,
- PIT and observed-date support,
- survivorship / security-master support,
- missing required evidence,
- lineage fields required before implementation can rely on the data,
- drift-monitoring requirement,
- explicit `silent_default_allowed = false`,
- explicit `latest_only_historical_evidence_allowed = false`,
- explicit `provider_selection_made = false`,
- explicit `data_fetch_performed = false`.

Records with `source_basis = reviewed_provider_evidence` must carry `evidence_source_refs` with reviewed source URL, source type, review date, and evidence note.

The schema intentionally keeps these dimensions separate. A field may be partially supported but still blocked for production use.

## 5. Drift Monitor

The drift monitor must cover at least:

- coverage count,
- freshness / latency,
- schema or field semantics,
- PIT / as-of integrity,
- survivorship / security master,
- corporate action and revision behavior,
- calendar / timezone alignment,
- authorization / cost / quota risk,
- provider incidents,
- outlier and revision rate.

The action set must include `warn`, `block_production_use`, `manual_review`, `fallback_path_review`, `rerun_provider_evidence`, `record_incident`, and `freeze_latest_only_claims`.

Missing benchmark sessions must not be zero-filled, latest-only historical backfill must remain forbidden, and silently changed provider semantics must be logged.

## 6. Validation Contract

The reviewed contract baseline is complete when:

1. `schemas/provider_evidence_drift_monitor.schema.json` validates as Draft 7.
2. `schemas/examples/provider_evidence_drift_monitor.example.json` validates against the schema.
3. Regression tests prove scope locks, P1-P4 queue coverage, provider evidence no-default locks, reviewed-evidence source refs, drift dimensions and actions, example validation, provider-selection rejection, latest-only / silent-default rejection, and P4 helper-surface containment.
4. Evidence-population snapshots validate against the schema and preserve the no-selection / no-fetch / no-implementation locks.

## 7. First P1 Public-Source Snapshot

`docs/provider_evidence_p1_us_public_sources_20260528.json` is the first Phase 7b-2 evidence-population artifact. It reviews official public documentation for:

- SEC EDGAR submissions and XBRL data APIs,
- SEC current CIK / ticker / exchange static files,
- Nasdaq Trader current-day symbol directory sources,
- MSCI / S&P GICS methodology.

Verdict: P1 moves from `unknown` to `partial`, but remains implementation-blocked. SEC EDGAR is useful for filing metadata and XBRL source review; SEC / Nasdaq ticker files are current-reference aids, not historical survivorship-safe security masters; GICS methodology is not issuer-level PIT membership history. The artifact does not cover US adjusted prices, delistings, full corporate actions, benchmark returns, paid-provider licensing, sandbox tokens, or DataHub implementation.

## 8. Second P1 Market-Data Candidate Snapshot

`docs/provider_evidence_p1_us_market_data_candidates_20260528.json` is the second Phase 7b-2 evidence-population artifact. It reviews official provider documentation for:

- Massive / Polygon all tickers, adjusted aggregate bars, dividends, splits, market status, exchanges, and market-data terms,
- Norgate Data pricing / overview, US data content tables, accessibility, and package FAQ.

Verdict: P1 remains `partial` and implementation-blocked. The reviewed docs establish candidate evidence for US adjusted OHLCV, corporate actions, current/listing-status surfaces, exchange / market-status metadata, survivorship-aware EOD package claims, and some index-membership/package claims. They still do not authorize provider selection or implementation. Remaining blockers include user-approved authorization / cost and license terms, direct trial/sandbox validation, exact coverage counts, benchmark return construction, issuer-level PIT GICS membership history, filing observed-date/fundamental field candidates, stability / quota evidence, and fallback behavior.

R1 repair note: the Massive.com source refs in this artifact include explicit `WebFetched on 2026-05-28 at ...` traces in their `evidence_note` fields. These traces record that the Massive docs pages were actually opened and reviewed for this artifact; they do not by themselves prove Polygon-to-Massive brand or legal continuity, and they do not authorize provider selection.

## 9. Third P1 Authorization / Cost / Stability Snapshot

`docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json` is the third Phase 7b-2 evidence-population artifact. It reviews official provider documentation for:

- Massive / Polygon pricing, REST API-key access, stock-plan tiers, regulatory / non-professional framing, and market-data terms,
- Norgate Data package pricing, subscription / free-trial limits, Windows / plugin access, EULA restrictions, and export / retention constraints,
- Norgate current-fundamentals latest-only limitations for US-long observed-date reconstruction.

Verdict: P1 remains `partial` and implementation-blocked. This slice narrows the authorization / cost / trial / access evidence gap, but it does not approve paid access or provider selection. Massive / Polygon remains blocked by user classification, local storage, non-display / derived-work use, quota, stability, and business-plan review. Norgate remains blocked by subscription, Windows/plugin access, export, personal-use license, retention-after-lapse, and stability review. Norgate current fundamentals are latest-only and should not be treated as PIT historical fundamentals.

## 10. Fourth P1 Benchmark / GICS Candidate Snapshot

`docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json` is the fourth Phase 7b-2 evidence-population artifact. It reviews official documentation for:

- S&P DJI S&P 500 benchmark methodology and return-type construction context,
- Nasdaq-100 methodology and official dissemination surfaces,
- FTSE Russell / LSEG Russell US Indexes methodology and Russell 1000 reconstitution context,
- MSCI / S&P Global GICS methodology and GICS History product candidate evidence.

Verdict: P1 remains `partial` and implementation-blocked. This slice narrows the direct benchmark and GICS-history candidate evidence gap, but official index pages / methodology docs are not licensed project-ready historical return feeds, and GICS taxonomy / product pages are not yet issuer-level PIT membership history with usable sample rows, data dictionary, license, coverage counts, and as-of semantics.

## 11. Fifth P1 Fundamentals Observed-Date Candidate Snapshot

`docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json` is the fifth Phase 7b-2 evidence-population artifact. It reviews official documentation for:

- SEC EDGAR submissions, complete-submission timestamp semantics, extracted XBRL companyfacts, and public-source reconstruction constraints,
- Intrinio filing-linked fundamentals with filing `accepted_date`, `filing_date`, `is_latest`, and `updated_date` candidate evidence,
- FMP SEC filings / as-reported statement endpoints and cycle-time documentation, with latest/current endpoint limitations,
- Nasdaq Data Link / Sharadar Core US Fundamentals product-listing and publisher candidate context, pending table-level date-key review.

Verdict: P1 remains `partial` and implementation-blocked. This slice narrows the fundamentals observed-date candidate gap, especially by separating SEC public reconstruction and Intrinio accepted-date support from latest-only sources. It still does not provide coverage counts, license approval, field-level PIT construction, sample-row validation, fallback behavior, or provider incident / stability evidence.

## 12. Sixth P1 Coverage / Fallback / Incident Candidate Snapshot

`docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json` is the sixth Phase 7b-2 evidence-population artifact. It reviews official documentation for:

- Intrinio fundamentals coverage, business-use licensing, status page, outage help, and ADR limitations,
- FMP broad coverage, developer directory / delisted endpoints, cycle times, and endpoint uptime status shell,
- Massive coverage counts, stocks REST coverage, active / delisted ticker surfaces, system status, and status-page help,
- Norgate US stock / delisted / historical constituent coverage and explicit incompleteness limitations,
- Nasdaq Data Link status page and table API error-code / call-limit handling.

Verdict: P1 remains `partial` and implementation-blocked. This slice narrows the remaining coverage, fallback, incident, and field-license evidence gap, but vendor-level coverage claims and public status pages are still not project coverage counts, sample-row validation, license approval, or provider selection.

## 13. P1 Readiness Review Matrix

`docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json` synthesizes the six P1 snapshots field-by-field under `schemas/provider_p1_readiness_review.schema.json`. It covers security master / survivorship, adjusted EOD / liquidity, corporate actions, fundamentals observed-date / PIT, benchmark returns, GICS PIT membership, coverage counts, authorization / license / cost, fallback / incident / stability, and sample-row validation / lineage.

Verdict: P1 documentation evidence collection is complete enough to define blockers, but P1 is not ready for Phase 7c, provider selection, data fetch, DataHub tables, or runner consumption. The strongest candidate evidence remains blocker-bound: Intrinio for filing fundamentals, Norgate for survivorship-aware EOD / membership, Massive / Polygon for market-data surfaces, SEC EDGAR for public reconstruction, and official benchmark / GICS sources for methodology / product context. None authorizes implementation.

## 14. P1 Access Decision And Sample Validation Plan

`docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` translates the readiness matrix blockers into explicit user decision boundaries for cost ceiling, access path, trial / token / paid access, license / local-storage / non-display / retention use, sample rows, coverage-count verification, and fallback / incident playbook.

Verdict: the plan is not an access approval. It locks approved spend to zero and forbids provider contact, token / trial / paid access, sample-row collection, data fetch, provider selection, adapters, DataHub tables, runner changes, Phase 7c authorization, and ship-gate claims. It defines the gates a later user-approved and reviewed access packet must resolve.

## 15. US EGS Data-Source Direction

As of 2026-06-01, the user accepted the following US EGS data-source direction for future reviewed provider work:

- FMP is the preferred primary US EGS data-source candidate for fundamentals, valuation / ratio inputs, EOD price / volume, and liquidity fields.
- SEC EDGAR `submissions` / `companyfacts` is the fundamentals authority / audit source. It is used to check filing-grounded financial statement fields and obvious anomalies in FMP-derived inputs.
- SEC EDGAR is not a price source and must not be treated as a reliable strict source for free float. Free float can receive sanity checks from filing-derived share fields, but not exact EDGAR reconciliation.
- EDGAR XBRL is as-reported source data. Full field-by-field PIT normalization remains a separate data-engineering task; the default audit should target EGS-sensitive fields and anomaly-triggered samples rather than recreating an entire normalized fundamentals vendor.
- `yfinance` is not a formal audit source and must not replace EDGAR for fundamentals validation. It may be used only as an optional, low-trust, ad hoc price smoke check after explicit approval for that check; it is not part of the official provider chain.
- Polygon / Massive is deferred for now because the current EGS requirement is daily / fundamental / valuation data, not low-latency or minute / tick data.

This direction narrows the candidate roles for the next access packet, but it is not by itself an access approval, sample-validation packet, provider-selection artifact, DataHub implementation authorization, or data-fetch authorization. The 2026-06-02 approval in §16 authorizes only a zero-dollar AAPL / MSFT FMP existing-key + SEC public-API small sample. New FMP token / trial / paid access, any `yfinance` check, broad US data fetch, provider selection, adapter work, DataHub work, or Phase 7c still requires separate explicit approval and reviewed decision.

## 16. P1 Small Sample Validation Access Approval

`docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json` records the user's 2026-06-02 approval for a narrow US EGS sample-validation boundary under `schemas/provider_p1_sample_validation_access_approval.schema.json`.

Verdict: this approval allows only the user's existing FMP API key, SEC EDGAR public APIs under fair-access limits, zero-dollar spend, local gitignored raw sample storage, and a two-symbol AAPL / MSFT small sample. It does not authorize `yfinance`, Polygon / Massive, Intrinio, Norgate, Nasdaq Data Link, benchmark feeds, GICS history, full-market downloads, paid upgrades, provider selection, adapters, DataHub tables, runner changes, Phase 7c, production readiness, or ship-gate claims.

## 17. P1 Small Sample Validation Result

`runners/us_egs_sample_validation.py` ran the approved AAPL / MSFT sample packet and wrote the tracked no-secret summary `docs/provider_evidence_p1_us_sample_validation_summary_20260602.json` under `schemas/provider_p1_us_egs_sample_validation_summary.schema.json`. Raw provider / public API payloads are stored only under ignored `provider_samples/us_egs_sample_validation_20260602/`.

Result: `validation_status = completed_with_endpoint_errors`, `actual_total_endpoint_calls = 17`, `within_budget = true`, and `secrets_logged = false`. SEC EDGAR company-ticker mapping, `submissions`, and `companyfacts` succeeded for AAPL and MSFT with CIKs found and core companyfacts tags present. The FMP v3 endpoint families used in this packet returned HTTP 403 legacy-endpoint errors for both symbols, so FMP is not sample-validated by this packet. Before treating FMP as viable for US EGS, the next reviewed slice must map current FMP endpoints or otherwise decide the FMP account/API boundary; it must not broaden symbols, use `yfinance`, download the full market, upgrade paid access, select a provider, implement DataHub, change runners, or authorize Phase 7c without separate approval and review.

## 18. FMP Current Endpoint Mapping Review

`docs/provider_evidence_p1_us_fmp_current_endpoint_mapping_review_20260602.json` maps the failed sampled FMP v3 endpoint families to current FMP stable endpoint candidates under `schemas/provider_p1_fmp_endpoint_mapping_review.schema.json`.

Verdict: the current official FMP docs identify stable endpoint candidates for profile, income statement, balance sheet statement, cash-flow statement, key metrics, and full historical EOD price / volume. This mapping artifact itself is docs-only: no FMP stable endpoint retry was performed in that slice, no data fetch happened in that slice, limit / timeseries parameter parity remained unvalidated, and the artifact did not authorize provider selection, paid access, `yfinance`, full-market fetch, adapters, DataHub, production runner consumption, Phase 7c, production readiness, or ship-gate claims. The later same-scope retry is recorded separately in §19.

## 19. FMP Stable Endpoint Retry Result

`runners/us_egs_sample_validation.py --fmp-endpoint-mode stable` ran the approved same-scope AAPL / MSFT FMP stable retry and wrote `docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json` under `schemas/provider_p1_fmp_stable_endpoint_retry_summary.schema.json`. Raw FMP payloads are stored only under ignored `provider_samples/us_egs_sample_validation_20260602/fmp_stable_retry/`.

Result: `validation_status = completed`, `actual_total_endpoint_calls = 12`, `within_budget = true`, and `secrets_logged = false`. Profile, income statement, balance sheet statement, cash-flow statement, key metrics, and full historical EOD price / volume returned HTTP 200 for AAPL and MSFT. Statement observed-date fields were present through `filingDate` / `acceptedDate`, and EOD price / volume fields were present. This result closes only the two-symbol current-stable-endpoint access / response-shape retry; it does not prove FMP coverage, PIT semantics, license sufficiency, fallback behavior, provider stability, local-storage rights beyond the approved sample, production readiness, provider selection, DataHub / runner consumption, Phase 7c authorization, or ship-gate evidence.

## 20. P1 Remaining Blocker Resolution Plan

`docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json` routes the remaining `SR-PROVIDER-001` blockers under `schemas/provider_p1_remaining_blocker_resolution_plan.schema.json` after the AAPL / MSFT FMP stable retry.

Verdict: the stable retry closed only two-symbol current-stable-endpoint access / response-shape evidence. Coverage counts, license / local-storage / retention rights, field-level PIT and observed-date semantics, price adjustment / corporate-action semantics, SEC EDGAR audit parser feasibility and scope limits, fallback / incident / stability playbooks, production readiness, provider selection, DataHub / runner consumption, and Phase 7c remain blocked. The plan is routing-only: it performs no web research, provider contact, new token / trial / paid access, `yfinance` check, endpoint call, full-market fetch, adapter work, DataHub work, runner change, or ship-gate claim.

The fallback / incident / stability design slice is recorded in §21, and the incident-log contract is recorded in §22. Safe remaining no-access work is docs-only license / storage / retention review. Any coverage-count, PIT-row, corporate-action, broader sample-validation, `yfinance`, new-token, trial, paid, full-market, provider-selection, adapter, DataHub, runner-consumption, provider-status polling, fallback execution, incident-log writer implementation, or Phase 7c step still requires separate explicit approval and review.

## 21. P1 Fallback / Incident / Stability Playbook

`docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json` defines the fallback / incident / stability playbook under `schemas/provider_p1_fallback_incident_stability_playbook.schema.json` after the post-retry remaining-blocker plan.

Verdict: the playbook is schema-first design only. It defines default-deny fallback order, incident triggers, drift-monitor bindings, incident-log field expectations, and block-production-use behavior for fundamentals, price / volume / liquidity, corporate actions, security master / coverage, SEC EDGAR audit, and benchmark / GICS families. It does not execute fallback paths, poll provider status pages, fetch data, use `yfinance`, request new tokens / trials / paid access, select providers, create adapters, implement DataHub tables, change runners, authorize Phase 7c, or make production-readiness / ship-gate claims.

The playbook narrows the `fallback_incident_stability` blocker but does not close `SR-PROVIDER-001`: license / storage / retention rights, coverage counts, PIT / observed-date semantics, price adjustment / corporate-action samples, SEC parser feasibility, incident-log writer implementation, fallback execution, provider stability evidence, provider selection, DataHub / runner consumption, and Phase 7c remain blocked until separate reviewed slices resolve or accept them. The incident-log contract is recorded in §22.

## 22. P1 Incident-Log Contract

`docs/provider_evidence_p1_us_incident_log_contract_20260602.json` defines the future incident-log record contract under `schemas/provider_p1_incident_log_contract.schema.json` after the fallback / incident / stability playbook.

Verdict: the incident-log contract is schema-first design only. It defines future record fields, incident-type mappings, storage / retention policy expectations, review / replay policy, and decision gates for provider incidents. It creates no logs or storage paths, implements no writer, performs no provider calls, polls no status pages, executes no fallback paths, uses no `yfinance`, selects no provider, creates no adapter, implements no DataHub table, changes no runner, authorizes no Phase 7c, and makes no production-readiness / ship-gate claim.

The contract narrows the incident-log-design blocker but does not close `SR-PROVIDER-001`: license / storage / retention rights, coverage counts, PIT / observed-date semantics, price adjustment / corporate-action samples, SEC parser feasibility, actual incident-log writer behavior, fallback execution, provider stability evidence, provider selection, DataHub / runner consumption, and Phase 7c remain blocked until separate reviewed slices resolve or accept them.

## 23. Next Use

Phase 7c may consume reviewed Phase 7b evidence only after the access/sample blockers are separately resolved, and must be a separate reviewed implementation-design slice. The original A-share alpha-validation artifact `research/preregistrations/a_share_minimal_data_burst_20260531.json` remains `BLOCKED_DO_NOT_RUN`; the corrected-basis supersession is `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`, but its frozen-cohort preflight found zero valid signal events. The next alpha action is ledger-gated A-share burst redesign, not running that corrected artifact for outcome / excess calculation. US-long SEC parser feasibility remains provider-evidence feasibility, not alpha validation.

Except for the reviewed 2026-06-02 AAPL / MSFT small-sample validation packet and the same-scope FMP stable retry, this Phase 7b baseline does not fetch provider data, implement adapters, create DataHub tables, or modify production runners. The remaining-blocker plan in §20, fallback / incident / stability playbook in §21, and incident-log contract in §22 do not broaden that boundary.
