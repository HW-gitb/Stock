# Phase 7 Kickoff Spec Handoff

## 2026-08-11 append: desk us_testrun0810 Problem 3 active analyst source same-source consumption (OPEN-NOT_VERIFIED)

This is appended to the existing Phase 7 provider/universe owner handoff; no fragment handoff was created.

**Scope / implementation**

- This slice closes only the yfinance/FMP active analyst source -> scoring -> result-linkage coverage -> final action/data-quality chain. Problem 6's eight-key provider health and receipt -> emit -> report/private-write chain is explicitly out of scope and unchanged.
- `runners/us_short_batch5_data_context_source_packet.py` now resolves and validates `active_analyst_payload`, `active_analyst_provider`, and `active_analyst_path_field` once at the packet boundary. Scoring and `build_result_source_facts()` consume the same payload; `engine/us_short_result_source_linkage.py` remains a pure consumer.
- `runners/us_short_batch5_full_candidate_live_source_packet.py` uses one `analyst_source` to control FMP calls, `FMP_API_KEY` reads, and summary fields. yfinance needs no FMP key and reports `yfinance_consumption_performed=true`, `fmp_grades_calls=0`, `not_required_yfinance_grades`, and `not_called_replaced_by_yfinance`; FMP fallback remains key-gated before provider calls.
- No health key, health digest, per-ticker SHA, second resolver, provider/live path, or real-key execution was added. Summary schema changes are limited to the truthful booleans and optional exclusion field.

**Verification / handoff boundary**

- Fixed-Python focused acceptance: `161 OK`, `receipt:307d601e59bba2aa3ebf94fb`; after reverse probes, affected source-packet module: `31 OK`, `receipt:7cb656ba871a5f2cb2896215`. Reverse probes genuinely failed when coverage was mapped back to the empty FMP shell and when yfinance was injected into global `provider_health`; both were restored.
- The one us_short full lane recorded `discovered=5744 ran=5744 equal=True PASS`, `399.1s/860s`, fingerprint `d0feedf7e23627a07a18b1e46567bfdb705e8b28a5edff5f737f1344bbda3f35`; `py_compile=4` and `git diff --check` passed.
- Current status is `OPEN-NOT_VERIFIED`, not provider/live acceptance, production, ship-gate, or full-size trading evidence. Claude Code must independently review and then decide whether to commit; Codex does not commit. `CURRENT.md` was intentionally not changed for pending review/commit state.


## 2026-06-20 append: A-long value-yield forward-paper round-3 re-review PASS

**Changed**:
- Codex re-reviewed only the A-long value-yield forward-paper round-3 data-layer/capture repair.
- Review verdict was recorded in `docs/SESSION_LOG.md`.
- Full closure evidence was recorded under `R-ALONG-VY-FP-DATALAYER-INDUSTRY-CLASSIFICATION-CONTRACT-GAP` and `R-ALONG-VY-FP-FORWARD-CAPTURE-EVIDENCE-INTEGRITY-GAP` in `docs/system_risk_register.md`.

**Plain result**:
- Verdict is PASS in working tree.
- D-origin blank delist, D-origin scored-item leakage, empty live universe, noncanonical `data_through`, and `research/../RESULT` path bypass are now guarded.
- The two Required entries remain open only because the fix is not committed yet.
- No live provider call, real capture, ledger spend, production route, ship-gate evidence, broker/order behavior, or A-short review is authorized by this entry.

**Verification**:
- A-long targeted + doc-route tests: 129 OK.
- Full `unittest discover`: 2747 OK.
- `py_compile` for the 4 A-long forward-paper files: OK.
- Independent probes used fake providers only.

**Next**:
- User may commit only the A-long forward-paper 4 files plus review docs.
- Keep A-short/EGS/phase6 working-tree changes out of this A-long commit path.

---

## 2026-06-19 append: A-long value-yield forward-paper round-2 re-review FAIL

**Changed**:
- Codex re-reviewed only the A-long value-yield forward-paper round-2 repair.
- Review verdict was recorded in `docs/SESSION_LOG.md`.
- Full Required detail was recorded under `R-ALONG-VY-FP-DATALAYER-INDUSTRY-CLASSIFICATION-CONTRACT-GAP` and `R-ALONG-VY-FP-FORWARD-CAPTURE-EVIDENCE-INTEGRITY-GAP` in `docs/system_risk_register.md`.

**Plain result**:
- Verdict is FAIL.
- The calendar guard now rejects before broad fetch, but provider/data evidence guards still have material holes.
- `list_status` is threaded into context, but D-origin blank-`delist_date` rows can still reach scoring / return lineage.
- No live provider call, real capture, ledger spend, production route, ship-gate evidence, broker/order behavior, or A-short review is authorized by this entry.

**Verification**:
- A-long forward-paper + doc/route targeted tests: 122 OK.
- `py_compile` for the 4 A-long forward-paper files: OK.
- Independent probes reproduced the remaining bad shapes; all probes used fake providers only.

**Next**:
- Repair only the remaining A-long data-layer/capture Required gaps.
- Do not include A-short/EGS/phase6 working-tree changes in this A-long review/repair/commit path.

---

## 2026-06-19 append: A-long value-yield forward-paper re-review FAIL

**Changed**:
- Codex re-reviewed only the A-long value-yield forward-paper capture/data-layer repair.
- Review verdict was recorded in `docs/SESSION_LOG.md`.
- Full Required detail was recorded under `R-ALONG-VY-FP-DATALAYER-INDUSTRY-CLASSIFICATION-CONTRACT-GAP` and `R-ALONG-VY-FP-FORWARD-CAPTURE-EVIDENCE-INTEGRITY-GAP` in `docs/system_risk_register.md`.

**Plain result**:
- Verdict is FAIL.
- The missing-SW exclusion and diagnostic matured-count forgery paths are repaired, but two material gaps remain: security-master origin/list_status is still not preserved, and calendar/entry-anchor guards still run after broad provider fetch.
- No live provider call, capture execution, ledger spend, production route, ship-gate evidence, broker/order behavior, or A-short review is authorized by this entry.

**Verification**:
- A-long forward-paper + doc/route targeted tests: 118 OK.
- `py_compile` for the 4 A-long forward-paper files: OK.
- Doc governance + route-doc tests after review-record edits: 30 OK.

**Next**:
- Repair only the two A-long Required gaps above.
- Do not include A-short/EGS/phase6 working-tree changes in this A-long review/repair/commit path.

---

## 2026-06-07 append: A-long large-cap signal-search package ready for review

**Changed**:
- Committed the reviewed `000043.SZ` bridge repair and repaired market-cap audit PASS in `b7f4cb4`.
- Prepared the next review-only large-cap pure-quality signal-search package without executing it.
- New package files: `schemas/a_long_large_cap_pure_quality_signal_search_execution_packet.schema.json`, `docs/a_long_large_cap_pure_quality_signal_search_execution_packet_20260607.json`, `runners/a_long_large_cap_pure_quality_signal_search.py`, `schemas/a_long_large_cap_pure_quality_signal_search_execution_summary.schema.json`, `tests/schema/test_a_long_large_cap_pure_quality_signal_search_schema.py`, and `tests/test_a_long_large_cap_pure_quality_signal_search.py`.
- The future runner reuses the reviewed full-main-board PIT fundamentals / returns / benchmark route, consumes the repaired large-cap market-cap audit PASS, applies the reviewed `000043.SZ` / `20191129` drop-plus-backfill policy, and evaluates one frozen primary cell: 504d CSI300 industry-size-neutral three-factor percentile composite.

**Plain result**:
- This is a review-only package build.
- It did not run signal search, read raw payloads during build, spend the large-cap singleton ledger, compute alpha, or authorize production / ship-gate / full-size use.
- CSI1000, 252d, non-neutral, cap-weighted, single-factor, and `earnings_stability` cells are diagnostics only and cannot rescue the single primary cell.

**Next**:
- Independent review of the signal-search package.
- After review PASS + commit, a separate user `执行` may run only `runners/a_long_large_cap_pure_quality_signal_search.py` with both confirmation flags. That future run would write the research-only summary and spend the large-cap singleton ledger exactly once.

---

## 2026-06-07 append: A-long large-cap 000043 bridge repair and local audit PASS

**Changed**:
- Registered the user-approved bounded data-quality exclusion for `000043.SZ` on `20191129`.
- Added `schemas/a_long_large_cap_data_quality_exclusion_decision.schema.json` and `docs/a_long_large_cap_data_quality_exclusion_decision_20260607.json`.
- Updated the large-cap preregistration, audit packet/schema, audit runner, and tests so the materialized raw top-500 re-derivation stays unchanged, but the future signal universe drops the documented observation and backfills the next main-board name by `circ_mv`.
- Reran only the local market-cap audit and regenerated `research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json` plus `monthly_coverage.csv`.

**Plain result**:
- The repaired local audit now passes: raw top-500 outside-prior observations `1`, documented exclusions `1`, unresolved outside observations `0`, and signal-universe backfill observations `1`.
- This is data-readiness only. It does not run signal search, spend the large-cap singleton ledger, compute alpha, or authorize production / ship-gate / full-size use.

**Next**:
- Independent review of this repair and the repaired audit result.
- After review PASS + commit, the next separate step may build a signal-search package. The audit report itself still does not authorize running signal search.

---

## 2026-06-07 append: A-long large-cap market-cap audit package ready for review

**Changed**:
- Committed the reviewed 96/96 large-cap market-cap materialization PASS summary in `7d5356c`.
- Prepared the next local-only audit package without executing it.
- New package files: `schemas/a_long_large_cap_market_cap_audit_packet.schema.json`, `docs/a_long_large_cap_market_cap_audit_packet_20260607.json`, `runners/a_long_large_cap_market_cap_audit.py`, `schemas/a_long_large_cap_market_cap_audit_report.schema.json`, `tests/schema/test_a_long_large_cap_market_cap_audit_schema.py`, and `tests/test_a_long_large_cap_market_cap_audit.py`.
- The future audit re-derives each monthly top-500 by `circ_mv`, checks the same 96 as-ofs, shared main-board filter, size-quintile coverage, and bridge to the prior audited full-main-board raw universe.

**Plain result**:
- This is a review-only package build.
- It does not run audit, signal search, alpha, production, ship-gate, DataHub, broker/order automation, or full-size logic.

**Next**:
- Independent review of the audit package.
- After review PASS + commit, the next separate `执行` may run only the local market-cap audit.
- Signal search remains locked until the audit result itself passes review and is committed.

---

## 2026-06-06 append: A-long pre-run signal-search repair ready for review

**Changed**:
- Repaired the pre-run A-long signal-search package without running signal search.
- `profitability_quality` now annualizes `fina_indicator.roe` by report-period suffix before cross-sectional ranking.
- `cash_conversion` excludes near-zero net-income denominators below the registered 10,000,000 threshold.
- PIT `namechange` selection-time veto now catches `...退` suffix delisting names.
- Non-terminal missing scheduled exits now use the next available tradable close or become missing; last-available backfill is reserved for verified terminal delisting/no-trade.
- Preregistration, execution-summary schema, runner, tests, `CURRENT.md`, `SESSION_LOG.md`, and `system_risk_register.md` were updated to lock the repair.

**Plain result**:
- This is a pre-run code/design repair only.
- It does not execute signal search and is not alpha evidence.
- No production, ship-gate, DataHub, broker/order automation, or full-size use is authorized.

**Next**:
- Independent review of the pre-run repair.
- After review PASS + commit, the next separate gate may run the first valid frozen A-long signal search with both confirmation flags.
- Result-review watch items remain early-window industry-neutral denominator coverage and Tushare delisted-universe completeness.

---

## 2026-06-06 append: A-long amended full audit PASS

**Changed**:
- Committed the materialization PASS-shape summary as `bf16a7d Record A-long materialization shape pass`.
- Ran `runners/a_long_full_main_board_data_integrity_audit.py` as Step 2 local raw audit.
- `research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json` now records `passed_full_main_board_data_integrity_for_signal_search`.
- Audit execution used zero provider/network calls, 12/12 self-tests passed, and six check results are pass/characterized.

**Plain result**:
- This clears only the amended full data-integrity gate pending review.
- It is not a signal-search result and not alpha evidence.
- No production, ship-gate, DataHub, broker/order automation, or full-size use is authorized.

**Next**:
- Independent review of `research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json`.
- After review PASS + commit, the next separate gate may run the frozen A-long signal search.
- Do not change families, thresholds, horizons, universe, cost model, or industry policy to rescue the search.

---

## 2026-06-06 append: A-long amended full materialization PASS shape

**Changed**:
- Committed the `fina_indicator` ann_date-only PIT contract repair as `e6aa705 Fix A-long fina_indicator PIT contract`.
- Ran the reviewed Step 1 materialization retry with `runners/a_long_full_main_board_materialization_packet.py --confirm-independent-review-pass --confirm-post-review-execute`.
- `docs/a_long_full_main_board_materialization_execution_summary_20260605.json` now records `passed_full_main_board_materialization_shape`: 23,718 endpoint results, 3 new Tushare network calls, 23,715 reused raw payloads, budget not exceeded.
- Candidate universe matches the reviewed packet: 3,200 active main-board + 187 delisted main-board = 3,387.
- All 14 table rollups passed, including PIT `namechange_2018_2025`, H-code TR-close `benchmark_index_daily`, statement-table `f_ann_date`, and `fina_indicator` ann_date-only fields.

**Plain result**:
- This clears only the materialization-shape gate.
- It is not a data-integrity PASS and not alpha evidence.
- No audit, signal search, alpha, production, ship-gate, DataHub, broker/order automation, or full-size use is authorized by this summary.

**Next**:
- Independent review of `docs/a_long_full_main_board_materialization_execution_summary_20260605.json`.
- After review, the next separate gate is the amended full data-integrity audit.
- Signal search remains locked until amended full audit PASS + review + separate user `执行`.

---

## 2026-06-06 append: A-long fina_indicator PIT contract repair

**Changed**:
- Disposed the materialization preflight blocker where Tushare returned `fina_indicator` rows but no `f_ann_date`.
- `income`, `balancesheet`, and `cashflow` remain statement tables that hard-require `f_ann_date`.
- `fina_indicator` is now explicitly ann_date-only in the current route: materialization requests `ts_code,ann_date,end_date,roe,profit_dedt`.
- Future signal selection for `fina_indicator` uses `ann_date <= as_of`, still excludes every matching `restatement_ambiguous_exclusions.csv` group, and still forbids latest-fill.
- The execution packet/schema, data-integrity preregistration/schema, signal preregistration/schema, materialization runner, audit runner, signal runner, and tests lock this table-specific PIT contract.

**Plain result**:
- This repair does not run provider calls, materialization, audit, signal search, alpha, production, ship-gate, or full-size use.
- A-long still has no valid alpha result.
- Superseded by the materialization PASS-shape append above: the next separate gate is now materialization-summary review, then amended full audit.

**Boundaries**:
- Do not clear reused `fina_indicator` checkpoints merely because they lack `f_ann_date`; the current reviewed request shape is ann_date-only and checkpoint shape validation should decide reuse.
- Do not weaken `f_ann_date` for `income`, `balancesheet`, or `cashflow`.
- Full audit still must pass before signal search; signal search still needs explicit later `执行`.

---

## 2026-06-04 append: A-long main-board fixed-panel audit pass and signal-search preregistration

**Changed**:
- Committed the prior reviewed delisted missing-industry boundary as `70900ff Implement A-long delisted industry exception`.
- Executed the main-board-only A-long broader materialization packet after the boundary: `600887.SH` replaces old ChiNext `300750.SZ`; active symbols are main-board only; raw payloads stay under gitignored `data/a_long/raw/tushare/materialization_full_period_panel_20260604/`.
- `docs/a_long_tushare_broader_materialization_execution_summary_20260604.json` now records `passed_full_period_panel_materialization_shape`, 7 new network calls, 64 reused raw payloads, 8 daily empty-raw refetches, and no secret / request URL in the tracked summary.
- Ran `runners/a_long_materialized_full_period_data_integrity_audit.py` locally only; `research/results/a_long_materialized_full_period_data_integrity_audit_20260604/audit_report.json` records `passed_fixed_panel_data_integrity_for_signal_preregistration`, hard checks pass, 11/11 self-tests, and usable start year 2018.
- Added `schemas/a_long_signal_search_preregistration.schema.json`, `research/preregistrations/a_long_signal_search_preregistration_20260604.json`, `research/ledgers/a_long_signal_search_program_test_budget_ledger_20260604.json`, and schema tests.

**Plain result**:
- A-long data route is now good enough to write the first signal-search preregistration.
- It still has not found alpha.
- The fixed 9-symbol panel is only route proof, not full-universe proof.

**Guardrails**:
- The preregistration runs no signal, fetches no data, and authorizes no alpha, production, ship-gate evidence, full-size use, DataHub, provider expansion, or broker/order automation.
- `000666.SZ` remains in returns/risk/coverage and is excluded only from industry-normalization denominators under the reviewed bounded exception.
- Active-symbol missing industry still fails.

**Next**:
- Claude should review this whole big package.
- After clean review and explicit user execute, the next package may combine main-board candidate-universe expansion, signal-search runner implementation, full-period signal run, summary, tests, and docs. Do not use the 9-symbol fixed panel as alpha proof.

## 2026-06-04 append: A-long delisted missing-industry boundary

**Changed**:
- Implemented the user-approved design boundary for reviewed already-delisted names with no recoverable SW membership / coarse industry in the current Tushare route.
- `runners/a_long_materialized_full_period_data_integrity_audit.py` now validates `docs/a_long_000666_sw_membership_supplement_execution_summary_20260604.json` before allowing the `000666.SZ` exception.
- The exception is bounded: max 1 symbol and max 12.5% of the fixed panel.
- The symbol stays in PIT universe, terminal delisting return, returns, risk, drawdown, and coverage reporting.
- The symbol is excluded only from industry-neutralization / industry-normalized scoring denominators.

**Why**:
- The corrected 4-call supplement proved the current Tushare route has no usable `000666.SZ` SW membership source.
- Continuing to search the same source path would not fix the data route, and dropping the delisted stock would create survivorship bias.

**Guardrails**:
- Active-symbol missing industry still fails.
- Silent industry fill, default industry, zero industry, or dropping a delisted symbol from returns/risk is forbidden.
- This does not authorize signal search, alpha, production, ship-gate, full-size use, DataHub, or broker/order automation.

**Next**:
- After review, prepare a main-board-only A-long fixed-panel replacement (`300750.SZ` out, `600887.SH` in) and rerun the data-integrity path under review.

## 2026-06-04 append: A-long corrected 000666 supplement execution

**Changed**:
- After commit `a248ec1`, ran `runners/a_long_000666_sw_membership_supplement_packet.py` with both confirmation flags.
- Updated `docs/a_long_000666_sw_membership_supplement_execution_summary_20260604.json` to the corrected 4-call execution result.
- Updated routing/status docs to record that the corrected Tushare route still did not find a usable `000666.SZ` SW membership source.

**Plain result**:
- The corrected probe ran.
- It still did not find a usable SW membership source for `000666.SZ`.
- `stock_basic` found the target row, but `industry` and `area` are both absent for that target.
- `index_classify` L2 returned rows.
- `index_member_all` found no `000666.SZ` row, both in targeted and unfiltered checks.
- A-long still cannot search for alpha.

**Boundaries**:
- Raw rows are only under gitignored `data/a_long/raw/tushare/000666_sw_membership_supplement_20260604/`.
- The tracked summary contains no raw rows, request URL, or secret.
- This execution authorizes no audit repair, audit rerun, signal search, alpha backtest, DataHub, production claim, ship-gate claim, full-size use, or broker/order automation.

**Next**:
- Reviewed decision on the `000666.SZ` delisted-name industry gap: explicit design boundary or another historical-industry source route.
- Then rebuild the main-board-only A-long fixed panel and rerun data integrity under review.

---

## 2026-06-04 append: A-long 000666 corrected supplement packet

**Changed**:
- `runners/a_long_000666_sw_membership_supplement_packet.py` now uses a corrected 4-call packet.
- `stock_basic_000666_delisted_context` requests `industry` and `area`, and the tracked summary records only whether those values exist.
- The invalid `index_member` leg was removed from the current packet and replaced with `index_classify_sw_l2_context`, `index_member_all_000666_ts_code_filter`, and `index_member_all_current_universe_crosscheck`.
- Packet/schema/docs/tests now classify the first 000666 supplement execution as historical/inconclusive, not a reliable no-source finding.

**Plain result**:
- No data call ran in this repair.
- The old 000666 result cannot be used to decide "Tushare has no source".
- A-long still cannot search for alpha.
- The corrected supplement probe still needs Claude review and a separate user `执行`.

**Boundaries**:
- No Tushare call, raw read, audit rerun, signal search, alpha backtest, DataHub, production claim, ship-gate claim, full-size use, or broker/order automation was authorized in this repair.
- If later executed, the corrected probe is limited to `000666.SZ`, four calls, zero retry, gitignored raw, and tracked no-secret summary.

---

## 2026-06-04 append: A-long paced fixed-panel rerun

**Changed**:
- `runners/a_long_tushare_broader_materialization_packet.py` now validates the daily-route diagnostic summary before treating old empty `daily` raw refs as repair candidates.
- Successful existing raw payloads are still checkpoint-reused.
- Only old empty `daily` raw refs are re-fetched with pacing and written to versioned `_paced_refetch` raw files under gitignored `data/a_long/raw/tushare/materialization_full_period_panel_20260604/`; old raw files are not overwritten.
- `docs/a_long_tushare_broader_materialization_execution_summary_20260604.json` now records 9 paced `daily` refetches, 62 reused raw payloads, 11/11 table rollups passed, and `passed_full_period_panel_materialization_shape`.

**Plain result**:
- The fixed 2018-2025 sample panel is downloaded.
- It is still not alpha-ready.
- The next step is a full-period panel data-integrity audit, not signal search.

**Boundaries**:
- Raw rows are only under gitignored `data/a_long/raw/tushare/materialization_full_period_panel_20260604/`.
- The tracked summary contains no raw rows, request URL, or secret.
- This execution authorizes no signal search, alpha backtest, DataHub, production claim, ship-gate claim, full-size use, or broker/order automation.

---

## 2026-06-04 append: A-long daily price route diagnostic execution

**Changed**:
- Added `docs/a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604.json`.
- Updated routing/status docs to record the diagnostic result and next pacing repair route.

**Plain result**:
- The two-call diagnostic ran.
- Both fixed `daily` probes returned rows.
- The 2018-2025 isolated probe returned 1,942 rows; the 2022 control returned 242 rows.
- The old 71-call broader failure is therefore likely a burst-rate / pacing problem, not an 8-year window problem.
- A-long data is still not usable for audit or alpha search.

**Boundaries**:
- Raw rows are only under gitignored `data/a_long/raw/tushare/daily_price_route_diagnostic_20260604/`.
- The tracked summary contains no raw rows, request URL, or secret.
- This execution authorizes no daily repair, broader materialization rerun, full audit, signal search, alpha backtest, DataHub, production claim, ship-gate claim, full-size use, or broker/order automation.

**Next**:
- Per user preference, combine the next work into one reviewed package: pacing / rate-limit price-route repair + fixed 2018-2025 panel rerun + summary + tests + docs.
- Do not route the next repair to chunking unless new evidence contradicts this diagnostic.

---

## 2026-06-04 append: A-long daily price route diagnostic packet

**Changed**:
- Added `schemas/a_long_tushare_daily_price_route_diagnostic_packet.schema.json`.
- Added `docs/a_long_tushare_daily_price_route_diagnostic_packet_20260604.json`.
- Added `runners/a_long_tushare_daily_price_route_diagnostic_packet.py`.
- Added `schemas/a_long_tushare_daily_price_route_diagnostic_execution_summary.schema.json`.

**Plain result**:
- The next A-long price-data diagnostic is now fixed for review.
- No Tushare call ran in this slice.
- A-long data is still not usable for audit or alpha search.
- The later run, if Claude passes and the user executes again, is exactly two `daily` calls for `000001.SZ`: `20180101..20251231` isolated retest plus `20220101..20221231` control, max 2 calls, retry 0.

**Boundaries**:
- Raw rows for the later run must stay under gitignored `data/a_long/raw/tushare/daily_price_route_diagnostic_20260604/`.
- The tracked summary must contain no raw rows, request URL, or secret.
- No daily repair, broader materialization rerun, full audit, signal search, alpha backtest, DataHub, production claim, ship-gate claim, full-size use, or broker/order automation is authorized.

**Verification**:
- `python -m unittest tests.test_a_long_tushare_daily_price_route_diagnostic_packet tests.schema.test_a_long_tushare_daily_price_route_diagnostic_packet_schema -v` passed 21/21 after the two-call repair.
- `python -m unittest discover -v` passed 676/676.

**Next**:
- Independent review of this packet and runner.
- If review passes, user may issue `执行` to run only the fixed two-call diagnostic with confirmation flags.
- If the 8-year isolated probe returns rows, design a separate reviewed pacing / rate-limit repair packet. If the 8-year probe is empty but the 2022 control returns rows, design a separate reviewed chunked-daily repair packet. If both are empty or either errors, fix endpoint parameters / account route / error handling first.

---

## 2026-06-04 append: A-long broader materialization execution

**Changed**:
- Added `docs/a_long_tushare_broader_materialization_execution_summary_20260604.json`.
- Updated routing/status docs to record the failed price-data leg.

**Plain result**:
- 更大的 A 股长线固定样本池已经跑了。
- 数据没有落完整。
- 现在仍不能审计、不能找 alpha。
- 失败点很窄：71/71 planned Tushare calls executed；财报、股票池、行业、基准 shape 通过；9 个 `daily` 价格调用全部 0 行。

**Boundaries**:
- Raw rows stayed under gitignored `data/a_long/raw/tushare/materialization_full_period_panel_20260604/`.
- The tracked summary contains no raw rows, request URL, or secret.
- No full-market / full-universe materialization, audit rerun, signal search, alpha backtest, DataHub, production claim, ship-gate claim, full-size use, or broker/order automation is authorized.

**Next**:
- Independent review of the execution summary.
- After review, repair the `daily` price route / parameters before any full-period panel data-integrity audit.
- Do not start signal search from this execution summary.

---

## 2026-06-04 append: A-long broader materialization packet

**Changed**:
- Added `schemas/a_long_tushare_broader_materialization_packet.schema.json`.
- Added `docs/a_long_tushare_broader_materialization_packet_20260604.json`.
- Added `runners/a_long_tushare_broader_materialization_packet.py`.
- Added `schemas/a_long_tushare_broader_materialization_execution_summary.schema.json`.

**Plain result**:
- 更大的 A 股长线数据落地 packet 已写好。
- 还没有跑数据。
- 现在仍不能找 alpha。
- 它只允许在 Claude 审查通过 + 用户再次 `执行` 后，跑固定 2018-2025 九股票样本池：8 只活跃股 + `000666.SZ` 退市样本，CSI300 / CSI1000，71 planned calls / max 80。

**Boundaries**:
- Not full-market and not full-universe.
- Raw rows for the later run must stay under gitignored `data/a_long/raw/tushare/materialization_full_period_panel_20260604/`.
- The tracked summary must contain no raw rows, request URL, or secret.
- No provider call is executed by this packet artifact.
- No audit rerun, signal search, alpha backtest, DataHub, production claim, ship-gate claim, full-size use, or broker/order automation is authorized.

**Verification**:
- `python -m unittest tests.test_a_long_tushare_broader_materialization_packet tests.schema.test_a_long_tushare_broader_materialization_packet_schema -v` passed 17/17.

**Next**:
- Independent review of this packet and runner.
- If review passes, user may issue `执行` to run only the fixed panel packet with confirmation flags.
- After execution, create a separate reviewed full-period panel data-integrity audit. Do not start signal search from the packet or execution summary.

---

## 2026-06-04 append: A-long materialized thin-slice data-integrity audit

**Changed**:
- Added `schemas/a_long_materialized_thin_slice_data_integrity_audit_report.schema.json`.
- Added `runners/a_long_materialized_thin_slice_data_integrity_audit.py`.
- Added `research/results/a_long_materialized_thin_slice_data_integrity_audit_20260604/audit_report.json`, plus `check_summary.csv` and `coverage_by_year.csv`.

**Plain result**:
- 小切片审计通过。
- 这还不能用来找 alpha。
- 它只证明 2022-2023 三股票小切片上的 PIT / 退市样本 / 收益输入 / 基准输入 / 覆盖率刻画机制能跑通。
- Claude 提出的两个 full-audit 前必修项已处理：PIT 指标不再声称死的 look-ahead counter；self-tests 增至 11/11，其中 5 个直接打当前 runner 自己的 check 函数。

**Boundaries**:
- The audit reads only existing gitignored raw payloads under `data/a_long/raw/tushare/materialization_thin_slice_20260604/`.
- No provider call, no data fetch, no raw rows in tracked report, no signal search, no alpha backtest, no DataHub, no production claim, no ship-gate claim, no full-size use.

**Verification**:
- `python -m unittest tests.test_a_long_data_integrity_audit_runner tests.test_a_long_materialized_thin_slice_data_integrity_audit tests.schema.test_a_long_data_integrity_audit_preregistration_schema tests.schema.test_a_long_materialized_thin_slice_data_integrity_audit_schema -v` passed 23/23.
- The actual report validates against `schemas/a_long_materialized_thin_slice_data_integrity_audit_report.schema.json`.

**Next**:
- Independent review of this slice.
- If review passes, commit.
- Next `执行`: create a reviewed broader A-long materialization packet. Do not start signal search from the thin slice.

---

## 2026-06-04 append: A-long thin-slice materialization execution

**Changed**:
- Added tracked summary `docs/a_long_tushare_incremental_materialization_execution_summary_20260604.json`.
- Executed only the reviewed 2022-2023 three-symbol thin-slice packet through `runners/a_long_tushare_incremental_materialization_packet.py`: `000001.SZ`, `600519.SH`, `000666.SZ`, CSI300 / CSI1000, 29 planned calls / max 32, zero retry.
- Raw rows are only under gitignored `data/a_long/raw/tushare/materialization_thin_slice_20260604/`; tracked summary contains no raw rows, request URL, or secret.

**Plain result**:
- 小切片数据已经成功落地。
- 这还不能用来找 alpha。
- 它只证明 materialization 机制、字段形状和 raw lineage 可以落地。

**Next**:
- Review this execution summary.
- Then create a separate reviewed data-integrity audit authorization.
- Do not full-materialize 2018-2025, rerun the spent audit, start signal search, DataHub, production, ship-gate, or full-size from this summary.

---

## 2026-06-04 append: A-long thin-slice materialization packet

**Changed**:
- Added `schemas/a_long_tushare_incremental_materialization_packet.schema.json`, `docs/a_long_tushare_incremental_materialization_packet_20260604.json`, `runners/a_long_tushare_incremental_materialization_packet.py`, `schemas/a_long_tushare_incremental_materialization_execution_summary.schema.json`, and tests.
- The packet fixes a 2022-2023 three-symbol thin slice (`000001.SZ`, `600519.SH`, `000666.SZ`), CSI300 / CSI1000, 29 planned calls / max 32, gitignored raw storage, tracked no-secret summary, and checkpoint resume.

**Plain result**:
- The packet is ready for independent review, but it has not executed.
- A-long data is still not ready for alpha.
- The runner requires Claude Pass + a later user `执行` confirmation before live Tushare calls.

**Validation**:
- Targeted packet/schema tests passed 17/17 on Python313.

**Next**:
- Claude should review the packet and runner before any live materialization.
- After a clean review and user `执行`, run only this thin slice; then create a new reviewed data-integrity audit authorization.
- Do not full-materialize 2018-2025, rerun the spent audit, start signal search, DataHub, production, ship-gate, or full-size from this packet.

---

## 2026-06-04 append: A-long Tushare route-gap repair execution

**Changed**:
- Added `runners/a_long_tushare_route_gap_repair_packet.py`, `schemas/a_long_tushare_route_gap_repair_execution_summary.schema.json`, and `docs/a_long_tushare_route_gap_repair_execution_summary_20260604.json`.
- Executed a fixed 5-call existing-account Tushare route-gap repair packet. Raw rows are only under gitignored `data/a_long/raw/tushare/route_gap_repair_20260604/`; the tracked summary contains no raw rows, request URL, or secret.

**Plain result**:
- The two prior route gaps passed tiny-sample field checks.
- SW membership mapping now uses current `index_member_all` fields: `ts_code` / `l2_code` / `l2_name` / `in_date` / `out_date`.
- Older delisted sample `000666.SZ` returned terminal-window daily open/close rows and adj_factor rows.
- This still does not make A-long data usable for alpha.

**Next**:
- Next step is a reviewed incremental materialization packet, then a new data-integrity audit.
- Do not full-materialize, rerun the spent audit, start signal search, DataHub, production, ship-gate, or full-size from this route-gap repair result.

---

## 2026-06-04 append: A-long Tushare route validation execution

**Changed**:
- Added `runners/a_long_tushare_route_validation_packet.py`, `schemas/a_long_tushare_route_validation_execution_summary.schema.json`, and `docs/a_long_tushare_route_validation_execution_summary_20260604.json`.
- Executed a fixed 23-call existing-account Tushare route-validation packet. Raw rows are only under gitignored `data/a_long/raw/tushare/route_validation_20260604/`; the tracked summary contains no raw rows, request URL, or secret.

**Plain result**:
- Partial, not usable for alpha.
- Calendar, PIT universe shape, raw PIT fundamentals fields, restatement-lineage fields, price / adj_factor / dividend, and CSI300 benchmark fields passed the small field-presence check.
- Remaining blockers: SW industry membership fields (`index_member_all` returned rows but not required `index_code` / `con_code`) and terminal delisting return coverage (selected recent delisted sample had empty terminal daily price rows).

**Next**:
- A-long still cannot search for alpha.
- Next step is a narrow repair packet for those two route gaps, not full materialization, audit rerun, signal search, DataHub, production, ship-gate, or full-size.

---

## 2026-06-03 append: A-long Tushare data-route repair plan

**Changed**:
- Added `schemas/a_long_tushare_data_route_repair_plan.schema.json` and `docs/a_long_tushare_data_route_repair_plan_20260603.json`.
- The route plan fixes the next A-long repair attempt as existing-account Tushare raw PIT route validation: schedule, PIT universe, raw fundamentals, restatement lineage, SW history, total return / same-anchor benchmark, and terminal delisting return.
- Added `.gitignore` coverage for future raw A-long provider data under `data/a_long/raw/` and `data/a_long/audit_cache/`.

**Plain result**:
- A-long data still cannot be used for alpha.
- The next concrete step is not signal search; it is a reviewed small Tushare route-validation packet.

**Non-authorization**:
- No Tushare call, no data fetch, no raw parse, no audit rerun, no signal search, no DataHub work, no production / ship-gate / full-size claim, and no broker or order automation.

---

## 2026-06-01 append: SR-DATA-001 suspend daily completeness guard

**Changed**:
- Updated `A-EGS/egs_main.py:get_suspend_info` so a non-empty `pro.daily` payload must meet `suspend_daily_min_coverage = 0.95` against the as-of stock universe before missing rows are treated as suspended stocks.
- Bumped the suspend cache key to `suspend_<date>_v2` so old unvalidated suspend-inference caches are not reused.
- Added `tests/phase6/test_egs_main_suspend_guard.py` to cover partial daily rejection, high-coverage suspend inference, v2 cache save behavior, and the existing all-empty daily fallback.
- Marked `SR-DATA-001` resolved in `docs/system_risk_register.md`; the hot queue now moves to the execution-evidence risk group before any execution-backtest evidence or manual sizing conclusion is used.

**Why**:
- The old `all_codes - traded_codes` inference was safe only when the single-day `daily` response was complete enough. A partial provider response could silently remove tradable stocks during L0.
- The smallest safe fix is fail-fast / quarantine for suspicious non-empty daily payloads. Fully empty daily responses still keep the existing startup / non-trading fallback behavior and skip suspend filtering rather than marking the whole market suspended.
- This slice does not run EGS, regenerate cohorts, fetch provider data, change research artifacts, or change alpha conclusions.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_egs_main_suspend_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_egs_main_l3_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests\phase6 -v
git diff --check
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; print(len(Path('docs/CURRENT.md').read_text(encoding='utf-8').splitlines()))"
```

**Validation result**:
- `tests.phase6.test_egs_main_suspend_guard`: 3 tests passed.
- `tests.phase6.test_egs_main_l3_guard`: 4 tests passed.
- `python -m unittest discover -s tests\phase6 -v`: 32 tests passed.
- `git diff --check`: passed with only expected Windows LF-to-CRLF warnings.
- `docs/CURRENT.md` line count: 149 via Python `splitlines()`, below the 150-line snapshot target.

**Invalidated / blocked old conclusion**:
- "`SR-DATA-001` still blocks the next weekly official capture or direct cohort regeneration" is invalid after this reviewed slice.
- "Missing rows in a non-empty `daily` response can be treated as suspended without a completeness gate" is invalid after this reviewed slice.

**Next-step notes**:
- If this slice passes review and is committed, the default next `执行` returns to the risk-register execution-evidence group (`SR-EXEC-003/004/005/007` + `SR-CAP-001` + `SR-CONTRACT-002`) unless the user explicitly approves a narrower override.
- Do not use this fix as authorization to run weekly capture, rerun EGS, fetch provider data, or open a new A-share burst research test.

## 2026-06-01 append: SR-OPS-003 historical L3 engine guard

**Changed**:
- Added an engine-level guard in `A-EGS/egs_main.py`: non-current `--as-of` runs cannot use default `--l3-mode=today` unless the caller explicitly passes `--allow-historical-live-l3`.
- Added the explicit `--allow-historical-live-l3` declaration to `runners/backtest_rank.py` only for smoke-mode historical `today` L3 candidate generation.
- Added focused tests for the direct engine guard and the backtest command contract.
- Marked `SR-OPS-003` resolved in `docs/system_risk_register.md`; hot queue item #1 now leaves `SR-DATA-001` as the remaining blocker before new weekly official capture / direct cohort regeneration.

**Why**:
- `SR-EXEC-001` had already fixed the weekly wrapper, but direct `egs_main.py --as-of <historical>` still defaulted to live concept data through `--l3-mode=today`.
- The fix keeps the default safe while preserving an explicit non-evidence smoke path for local diagnostics.
- This does not run EGS, fetch provider data, regenerate cohorts, change research artifacts, or alter L3 scoring semantics for allowed `pit` / `neutralize` runs.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_egs_main_l3_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_backtest_rank_phase3 -v
```

**Validation result**:
- `tests.phase6.test_egs_main_l3_guard`: 4 tests passed.
- `tests.test_backtest_rank_phase3`: 6 tests passed.

**Invalidated / blocked old conclusion**:
- "`SR-OPS-003` still leaves direct historical `egs_main.py --as-of` silently defaulting to live L3 concepts" is invalid after this reviewed slice.
- "All hot queue #1 blockers are done" is still false: `SR-DATA-001` remains open and must be fixed before new weekly official capture or cohort regeneration used as evidence.

**Next-step notes**:
- If this slice passes review and is committed, the default next `执行` is `SR-DATA-001`.
- Do not use this guard as authorization to run weekly capture, rerun EGS, fetch provider data, or start any new A-share burst research test.

## 2026-06-01 append: SR-OPS-002 forward tracker atomic write

**Changed**:
- Updated `runners/forward_tracker.py:_write_tracker` so tracker persistence writes to a same-directory temp CSV, flushes and `fsync`s the handle, closes it, then atomically replaces `forward_tracker.csv` with `os.replace`.
- Added focused tests in `tests/phase6/test_forward_tracker_cache_guard.py` for same-directory temp naming, atomic replace, sorted schema-column output, successful temp cleanup, and failure-path preservation of an existing tracker file.
- Marked `SR-OPS-002` resolved in `docs/system_risk_register.md` and removed it from the hot queue; `SR-DATA-001` and `SR-OPS-003` remain open blockers before new weekly official capture / direct historical cohort regeneration.
- Updated `docs/CURRENT.md` and `docs/SESSION_LOG.md` with the current routing.

**Why**:
- Direct CSV writes can leave a partial `forward_tracker.csv` if the process is interrupted during forward-evidence capture or backfill.
- The fix is intentionally limited to the tracker writer. It does not change research results, EGS generation, provider access, cache refresh behavior, or any strategy threshold.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_forward_tracker_cache_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests\phase6 -v
git diff --check
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; print(len(Path('docs/CURRENT.md').read_text(encoding='utf-8').splitlines()))"
```

**Validation result**:
- `tests.phase6.test_forward_tracker_cache_guard`: 5 tests passed.
- `python -m unittest discover -s tests\phase6 -v`: 25 tests passed.
- `git diff --check`: passed with only expected Windows LF-to-CRLF warnings.
- `docs/CURRENT.md` line count after R1 trim: 149 via Python `splitlines()`, below the 150-line snapshot target.

**Invalidated / blocked old conclusion**:
- "`SR-OPS-002` still blocks forward-tracker official use because writes are non-atomic" is invalid after this reviewed slice.
- "The whole hot queue #1 is done" is still false: `SR-DATA-001` and `SR-OPS-003` remain open and must be handled before new weekly official capture / direct historical `egs_main.py` cohort regeneration.

**Next-step notes**:
- If this slice passes review and is committed, the default next `执行` returns to hot queue item #1: `SR-DATA-001` or `SR-OPS-003`, unless the user explicitly approves a narrower override.
- Do not use this fix as authorization to run weekly capture, rerun EGS, fetch provider data, or open US provider access.

## 2026-06-01 append: US EGS data-source direction

**Changed**:
- Recorded the user-approved US EGS data-source direction in `docs/provider_evidence_drift_monitor.md`: FMP as preferred primary US EGS data-source candidate, SEC EDGAR as fundamentals authority / audit source, and `yfinance` only as an optional low-trust price smoke check after explicit approval.
- Updated active routing in `AGENTS.md`, `docs/README.md`, and `docs/CURRENT.md`.
- Added `SR-PROVIDER-001` in `docs/system_risk_register.md` to make the access / fetch boundary durable.

**Why**:
- The source-role decision affects future provider access, license, storage, sample validation, and data quality gates. Keeping it only in chat would let a later LLM reopen the same provider debate or misread `yfinance` as a fundamentals audit source.
- The decision narrows future candidate roles, but the user has not approved any US data source access, token, trial, paid plan, sample fetch, adapter, DataHub table, or Phase 7c work.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema tests.schema.test_provider_evidence_drift_monitor_schema -v
git diff --check
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
```

**Validation result**:
- Provider access-plan and provider evidence / drift-monitor schema tests passed: 27 tests.
- `git diff --check` passed with only expected Windows LF-to-CRLF warnings.
- `docs/CURRENT.md` remains at 149 lines.

**Invalidated / blocked old conclusion**:
- "P1 US provider evidence has no preferred EGS source direction" is invalid; future reviewed access packets should start from FMP primary candidate + SEC EDGAR fundamentals audit.
- "Use `yfinance` as a fundamentals audit source" is blocked; it may only be a separately approved, low-trust price smoke check.
- This append does not authorize provider selection, FMP token / trial / paid access, SEC parser sample work, `yfinance` scraping, US data fetch, adapter / DataHub implementation, runner changes, production use, or ship-gate claims.

---

## 2026-06-01 append: A-share minimal-data burst audit/spec downgrade

**Changed**:
- Updated `docs/phase7a_alpha_plausibility_audit.json` as a `forward_evidence_changed` rerun superseding `alpha_audit_20260527_initial`; `a_share_burst_minimal_data` is now `redesign_required`, with evidence integrity, cost/return, capital, portfolio contribution, and source refs pointing to the failed full-universe redesigned outcome.
- Updated `docs/burst_lane_spec.md` and `docs/alpha_plausibility_audit.md` so A-share minimal-data burst is no longer described as an active `continue` path.
- Updated schema tests to lock the downgraded verdict and evidence refs.

**Why**:
- The reviewed outcome artifact failed the registered research-continuation thresholds after enough events were available. Leaving the owner audit/spec at `continue` would invite another unreviewed minimal-data A-share burst fishing loop.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_alpha_plausibility_audit_schema -v
```

**Validation result**:
- Focused alpha plausibility audit schema suite passed: 15 tests.
- The actual audit artifact still validates against `schemas/alpha_plausibility_audit.schema.json`, and a new test asserts `a_share_burst_minimal_data = redesign_required`.

**Invalidated / blocked old conclusion**:
- The prior audit/spec statement "`a_share_burst_minimal_data` = `continue`" is invalid.
- This does not change `a_share_burst_full_data = defer_until_provider_ready`; full-data burst remains blocked on reviewed provider/manual evidence and is not authorized by this docs-only downgrade.
- No new research run, provider fetch, US data access, runner change, production claim, live observation, or ship-gate claim is authorized.

---

## 2026-06-01 append: A-share burst full-universe redesigned outcome failed

**Changed**:
- Added the reviewed research-only outcome artifacts for the full-universe redesigned A-share burst test: `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json`, `signal_events.csv`, and `monthly_stats.csv`.
- Updated `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` so the redesigned test now points to the evidence report and is spent as `spent_failed_outcome_threshold`.
- Updated active routing docs and schema tests so the result is no longer treated as outcome-pending.

**Why**:
- The reviewed preflight had passed event-count with `valid_signal_events = 134`, and `SR-DATA-003` benchmark-open input was patched, so the next authorized smallest slice was the unchanged preregistered outcome / benchmark-excess calculation.
- The calculation used frozen local A-share cohorts and the patched local cache only. It did not rerun EGS, change preregistered parameters, full-refresh `forward_daily.pkl`, fetch provider data, or make any production / ship-gate claim.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema tests.schema.test_evidence_report_schema -v
git diff --check
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
```

**Validation result**:
- Outcome metrics: raw signal events `134`, selected signal events `123`, available return events `116`, mean net CSI1000 5d excess `-2.8696001309` pp, monthly clustered t-stat `-0.6312965283`, max monthly signal-excess drawdown `26.5735343137` pp, entry-unbuyable rate `0.0487804878`, decision `falsified_or_redesign_required`.
- Focused schema / artifact tests: 38 tests passed. `CURRENT.md` remains at 149 lines.
- `git diff --check` reported no whitespace errors; Git only printed expected CRLF normalization warnings on this Windows checkout.

**Invalidated / blocked old conclusion**:
- “The full-universe redesign outcome / excess is pending” is invalid. The registered redesigned test is now spent and failed under its own outcome thresholds.
- This does not prove every future A-share burst design has no alpha, but no further redesigned A-share burst test is authorized without a new ledger planned test, user approval, and reviewed preregistration.
- No production use, live observation, minimal-live sizing, full-size sizing, ship-gate evidence, or research-continue verdict is authorized by these artifacts.

---

## 2026-06-01 append: SR-DATA-003 benchmark-only cache patch run

**Changed**:
- Ran the reviewed benchmark-only helper against the ignored local shared cache: `runners/refresh_forward_daily_benchmark_open_tushare.py --dry-run`, then the same command without `--dry-run`.
- Patched `result/a_short/backtest/cache/forward_daily.pkl` so `benchmarks.csi300` and `benchmarks.csi1000` now contain `trade_date/open/close` frames for the existing `20240131..20260228` cache window.
- Updated active routing docs so `SR-DATA-003` is closed for benchmark-open input while the redesigned outcome / excess calculation remains a separate reviewed slice.

**Why**:
- The redesigned A-share burst preflight had enough signal events, but outcome / benchmark-excess calculation needed same-anchor benchmark entry-open input.
- A full forward-daily refresh would refetch stock / limit data unnecessarily; this run consumed only CSI300 / CSI1000 `index_daily` open/close for the existing cache range.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\refresh_forward_daily_benchmark_open_tushare.py --dry-run
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\refresh_forward_daily_benchmark_open_tushare.py
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_refresh_forward_daily_benchmark_open_tushare tests.phase6.test_forward_tracker_cache_guard tests.test_backtest_rank_phase3 tests.execution.test_materialize_benchmark_monthly_returns_tushare -v
```

**Validation result**:
- Dry-run and actual patch both reported `dry_run` as expected, `update_method = benchmark_only_index_daily_open_close_patch`, stock rows preserved at `2681523`, limit rows preserved at `3513895`, and two benchmark frames of 498 rows each.
- Readback of `forward_daily.pkl` shows both benchmarks have columns `trade_date/open/close`, zero open/close nulls, and `meta.benchmark_open_patch` provenance.
- Mocked-provider verification proved `backtest_rank.fetch_forward_daily(['20240131'], 5, refresh=False)` reuses the patched cache without calling the provider.
- Focused regression suite: 18 tests passed.

**Invalidated / blocked old conclusion**:
- "`SR-DATA-003` still needs the benchmark-only cache patch before any outcome / excess" is now invalid for this local workspace; the benchmark-open input is patched and verified.
- This run does not compute redesigned outcome returns, benchmark excess, drawdown, concentration, or ship-gate evidence. The next outcome / excess calculation still requires a separate reviewed slice using the unchanged reviewed preregistration and patched cache input.

---

## 2026-06-01 append: SR-DATA-003 benchmark-only cache refresh helper

**Changed**:
- Added `runners/refresh_forward_daily_benchmark_open_tushare.py`, a narrow helper that reads the existing shared `forward_daily.pkl` date range and fetches only CSI300 / CSI1000 `index_daily` `trade_date/open/close` frames before atomically patching the cache benchmark section.
- Added `tests/phase6/test_refresh_forward_daily_benchmark_open_tushare.py` to prove the helper preserves stock / limit payloads, supports dry-run, and makes the patched cache reusable by `backtest_rank.fetch_forward_daily(..., refresh=False)` without a provider refetch.
- Updated `runners/README.md`, `docs/CURRENT.md`, and `docs/system_risk_register.md` to route the remaining `SR-DATA-003` work through benchmark-only cache patching before any outcome / excess slice.

**Why**:
- The local shared `forward_daily.pkl` already contains stock and limit payloads for the research window but its benchmark frames are close-only. A full `--refresh-forward-daily` would refetch the entire stock / limit / benchmark surface, which is wider than the accepted `SR-DATA-003` input slice.
- The helper creates a reviewable path for the necessary benchmark open input without running outcome / excess or changing the existing return calculation path.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_refresh_forward_daily_benchmark_open_tushare -v
```

**Validation result**:
- `tests.phase6.test_refresh_forward_daily_benchmark_open_tushare`: 3 tests passed.

**Invalidated / blocked old conclusion**:
- "The only way to fix the close-only forward_daily benchmark cache is a full forward-daily refresh" is invalid. The benchmark frames can be patched via a benchmark-only `index_daily` slice.
- This change does not itself fetch provider data, patch the local cache, compute outcome returns, or compute benchmark excess. `SR-DATA-003` remains open until the cache input is actually patched and reviewed; redesigned outcome / excess still requires a later separate reviewed slice.

---

## 2026-06-01 append: SR-DATA-003 forward-tracker cache guard

**Changed**:
- Updated `runners/forward_tracker.py:_check_cache_coverage` to inspect cached CSI1000 / CSI300 benchmark frames before backfill and reject caches that lack same-anchor `trade_date/open/close` fields.
- Added `tests/phase6/test_forward_tracker_cache_guard.py` to lock both close-only benchmark cache rejection and same-anchor benchmark cache acceptance.
- Updated `docs/CURRENT.md` and `docs/system_risk_register.md` so `SR-DATA-003` remains open for benchmark-open outcome input while recording that the tracker refetch guard is handled.

**Why**:
- The tracker is a sidebar and must not trigger a universe-wide Tushare refetch through `fetch_forward_daily(..., refresh=False)` when the shared cache has close-only benchmark frames.
- This is not the redesigned burst outcome / excess slice. It only prevents official `forward_tracker.py backfill` from silently bypassing the `[SKIP]` / remediation-hint path.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_forward_tracker_cache_guard -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_backtest_rank_phase3 -v
```

**Validation result**:
- `tests.phase6.test_forward_tracker_cache_guard`: 2 tests passed.
- `tests.test_backtest_rank_phase3`: 4 tests passed.

**Invalidated / blocked old conclusion**:
- "Tracker cache coverage only needs date metadata" is invalid. It must also verify same-anchor benchmark `trade_date/open/close` fields.
- This does not resolve the remaining `SR-DATA-003` outcome precondition: a reviewed benchmark-open input slice is still required before any redesigned A-share burst return / excess calculation.

---

## 2026-05-31 append: A-share burst full-universe preflight pass

**Changed**:
- Added `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json`, a research-only pre-outcome preflight over 24 frozen full EGS intermediate cohorts.
- Updated `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json`: the reviewed planned test is now spent by preflight, `valid_signal_events = 134`, and no new test is authorized.
- Updated research routing docs, risk register, and schema tests so the next A-share burst blocker is `SR-DATA-003` benchmark-open input before any outcome / excess calculation.
- Extended `schemas/program_test_budget_ledger.schema.json` with `spent_passed_preflight_outcome_pending` to represent a spent event-count pass with outcome still blocked.

**Why**:
- The reviewed full-universe redesign's only authorized executable step was event-count / input-integrity preflight.
- The frozen Tier1+Tier2 full EGS surface produced enough preregistered events to pass the power gate, but this does not authorize outcome returns, benchmark excess, production use, or ship-gate claims.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**Validation result**:
- `tests.schema.test_research_preregistration_schema`: 23 tests passed.
- `tests/schema` discovery: 132 tests passed.
- `git diff --check`: passed; only Git LF-to-CRLF working-copy warnings.
- `docs/CURRENT.md` line count: 149.

**Invalidated / blocked old conclusion**:
- “The next A-share burst action is only the full-universe preflight” is now spent; the next action is `SR-DATA-003` benchmark-open input plus a separate reviewed outcome / excess slice.
- The preflight pass is not alpha evidence. It records only event-count / input integrity and does not compute outcome, excess, drawdown, concentration, or ship-gate evidence.

---

## 2026-05-31 append: A-share burst ledger-gated redesign preregistration

**Changed**:
- Extended `schemas/research_preregistration.schema.json` to v1.1.0 so a preregistration can be explicitly gated by the singleton program-level test-budget ledger while preserving the original research-only scope locks.
- Appended one planned test to `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` for `a_share_minimal_data_burst_full_universe_redesign_20260531`.
- Added `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json`, a research-only preregistration that moves the A-share minimal-data burst test from the steady Tier1 watchlist to frozen full EGS intermediate candidate surfaces.
- Updated research routing docs and schema tests so the new artifact is visible to future LLMs. After review / commit and the follow-up ledger status sync, only pre-outcome event-count / input-integrity preflight is authorized.

**Why**:
- The corrected-basis A-share burst preregistration spent its single test on a pre-outcome preflight and found `valid_signal_events = 0`. That made direct outcome / benchmark-excess calculation uninformative.
- A useful next burst test changes universe / eligibility and therefore is not a basis-only supersession. It must consume the singleton ledger discipline before it can run.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -v
git diff --check
```

**Validation result**:
- `tests.schema.test_research_preregistration_schema`: 22 tests passed.
- `tests/schema` discovery: 131 tests passed.
- Full unittest discovery: 244 tests passed.
- `git diff --check`: passed; only Git LF-to-CRLF working-copy warnings.

**Invalidated / blocked old conclusion**:
- Do not treat the corrected-basis 5d rerun as the next executable alpha test. That preregistration is spent by zero signal events.
- Do not run outcome / excess for the redesigned preregistration yet. After review / commit and the follow-up ledger status sync, the first executable step is only pre-outcome event-count / input-integrity preflight. Outcome / excess still requires `SR-DATA-003` benchmark-open resolution if the preflight has enough events.

---

**Status**: provider capability / field catalog contract baseline established.

**Scope**: Phase 7 schema-first kickoff. This handoff starts the DataHub / provider capability phase without selecting providers, fetching data, adding provider adapters, creating DataHub tables, rewriting `A-EGS/egs_main.py`, changing strategy logic, or relaxing ship gates.

---

## 2026-05-28 修复追加：Phase 7b label repair

- 上一轮 Phase 7b handoff 中“Phase 7b schema-first baseline 已建立，下一条进入 Phase 7c”表述过宽；本轮修复后应读作：Phase 7b-1 provider evidence / drift monitor schema-first contract 已建立，Phase 7b-2 provider capability evidence population 仍未开始。
- 当前下一条 `执行` 应推荐 Phase 7b-2：按 P1-P4 queue 填充 provider docs / fields / PIT / coverage / cost / fallback / stability evidence；不得把 Phase 7b-1 contract 当成真实 provider evidence population。
- Phase 7c 仍应先做 DataHub shared-layer / report / reproducibility schema-first contract，但只有在 Phase 7b-2 evidence population reviewed 后才进入自然队列；不得先建 adapter / DataHub table / runner integration。

---

## 2026-05-27 Repair: O1 status-axis clarification

**Optional disposition**: O1 accepted with path (a), not merged fields.

**Changed**:
- Added schema descriptions distinguishing `fieldDefinition.automation_status` from `productionUsePolicy.use_status`.
- Added schema descriptions distinguishing `productionUsePolicy.missing_data_rule` from `providerRequirements.fallback_path`.
- Added example field `a_industry.sw_l2_membership` to demonstrate a technically automatable field that remains production-blocked until provider evidence review.
- Added regression coverage proving the descriptions exist and the example can decouple the two status axes.

**Why**:
- `automation_status` is a technical/provider capability axis.
- `production_use_policy.use_status` is the governance axis and can veto production use even when automation looks technically feasible.
- `missing_data_rule` is runtime behavior when a field is missing after policy exists.
- `fallback_path` is design-time routing when provider capability is unsupported, unreliable, or not reviewed.

**Validation result**:
- `tests.schema.test_provider_capability_catalog_schema`: 11 tests passed.
- Full `tests/schema` discovery: 37 tests passed.
- `git diff --check`: passed (CRLF warnings only).
- Changed-file trailing whitespace check: passed.

---

## 1. 改了什么

- 新增 `schemas/provider_capability_catalog.schema.json` v1.0.0，作为 Phase 7 provider capability / field catalog contract。
- 新增 `schemas/examples/provider_capability_catalog.example.json`，用于验证 contract shape；不是 production provider registry。
- 新增 `tests/schema/test_provider_capability_catalog_schema.py`，覆盖 schema meta、example validation、scope lock、status/data-class/system coverage、provider evaluation no-overall-score guard、silent-default rejection、provider-selection rejection。
- 同步 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/provider_data_requirements_audit.md` 的 Phase 7 路由与下一步状态。

---

## 2. 为什么

Phase 6e audit 已经把四套系统的数据需求整理成字段、PIT、频率、lineage、授权 / 成本、稳定性和 fallback 要求。Phase 7 第一刀需要先把这些要求落成机器可校验的 schema contract，后续 provider capability evidence、field catalog population、DataHub table schema、provider adapter 或 implementation 才有统一边界。

该 contract 特意先做 schema-first，而不是直接实现 provider / DataHub：

- 避免 Phase 7 按 A-short 现有 convenience fields 重构。
- 防止 provider gap 被默认值、latest-only 数据或单一 provider score 掩盖。
- 让 A-share、US、long、short、burst、benchmark 和 manual-evidence requirements 在同一个 artifact 里可审查。

---

## 3. Contract 边界

`provider_capability_catalog` v1.0.0 必须记录：

- data class：覆盖 Phase 6e audit 的 14 个 data classes。
- required systems：`a_short_steady`、`a_short_evidence`、`a_share_burst`、`a_long`、`us_short_steady`、`us_burst`、`us_long`、`phase7_shared`。
- requirement status：`structured_required`、`structured_optional`、`manual_evidence`、`research_only`、`deferred`。
- PIT / frequency / history requirement。
- minimum lineage requirements：provider、API / table、request params、fetch timestamp、source date range、frequency、unit、adjustment、PIT status、coverage、missing fields、limitations、authorization、cost、fallback 等。
- provider evaluation dimensions：coverage、PIT、history、corporate actions、units/currency、latency、stability、authorization、cost、fallback。
- production use policy：missing-data rule、silent default lock、latest-only historical evidence lock。

Scope locks:

- `provider_selection_status = not_selected`。
- `data_fetch_allowed = false`。
- `provider_adapter_allowed = false`。
- `datahub_table_implementation_allowed = false`。
- `production_strategy_rule_change_allowed = false`。
- `broker_or_order_automation_allowed = false`。
- `manual_order_only = true`。

---

## 4. 示例边界

`schemas/examples/provider_capability_catalog.example.json` 只用于 schema validation，记录：

- 已证明的 `tushare_current_a_eod` A-share EOD / benchmark helper surface，但不把 Tushare 选为最终 provider。
- `us_fundamentals_provider_tbd` placeholder，用来显式表示 US fundamentals / filings 仍未选择 provider。
- A-share adjusted EOD、A-share CSI monthly returns、US filing / cash-flow fundamentals、manual event evidence 四类 representative fields。

示例不是 production registry，不触发 provider selection、data fetch、adapter、DataHub table 或 production scoring。

---

## 5. 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_capability_catalog_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_capability_catalog_schema tests.schema.test_a_short_variant_tracking_schema tests.schema.test_candidate_universe_overlap_audit_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

```powershell
$files = @(
  'AGENTS.md',
  'docs/CURRENT.md',
  'docs/README.md',
  'docs/datahub_design.md',
  'docs/strategy_design_synthesis.md',
  'docs/provider_data_requirements_audit.md',
  'docs/handoff/2026-05-27_phase7_kickoff_spec_handoff.md',
  'docs/SESSION_LOG.md',
  'schemas/provider_capability_catalog.schema.json',
  'schemas/examples/provider_capability_catalog.example.json',
  'tests/schema/test_provider_capability_catalog_schema.py'
)
foreach ($file in $files) {
  $lines = Get-Content -Encoding utf8 $file
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '\s+$') { "${file}:$($i + 1)" }
  }
}
```

---

## 6. 验证结果

- `tests.schema.test_provider_capability_catalog_schema`：10 tests passed。
- Provider capability catalog + adjacent Phase 6 schema regression (`test_a_short_variant_tracking_schema`, `test_candidate_universe_overlap_audit_schema`)：21 tests passed。
- Full `tests/schema` discovery：36 tests passed。
- `git diff --check`：passed（CRLF warnings only）。
- Changed-file trailing whitespace check：passed。
- Active stale next-step wording scan：passed。

---

## 7. 失效旧结论

- “Phase 7 可以先写 provider adapter 或 DataHub table”失效；先有 capability / field catalog contract。
- “Provider capability 可以用单一 overall score 表示”失效；schema 禁止 `overall_score`，必须保留 dimension-level blockers。
- “缺 provider 字段时可以 silent default / latest-only 回填历史证据”失效；schema 通过 const lock 禁止。
- “US fundamentals provider 可在 implementation 时再顺手决定”失效；US fields 必须先在 provider capability evidence 中显示支持 / 缺失 / manual / research / deferred 状态。
- “Manual evidence 可以直接变成 deterministic factor”失效；schema 要求 observed date / source / reviewer or process tag，且 promotion 前不能成为 deterministic factor。

---

## 8. 下一步注意事项

1. 本节原推荐“下一条 `执行` 从已证明的 A-share EOD / benchmark surfaces 填充 provider evidence 入手”已由下方 2026-05-27 追加的 Phase 7a alpha-validation route 失效；现下一步先做 schema-first alpha plausibility audit。
2. 不要在下一刀重写 `A-EGS/egs_main.py`、新增 US provider adapter、抓新 provider 数据、建立 DataHub table，或改变任何 strategy runner 行为。
3. 若后续 provider readiness 不足，字段必须保持 `blocked_until_provider_review`、`manual_evidence_only`、`research_only` 或 `deferred`；不得发明 fundamentals 或把 latest-only 数据当 PIT evidence。

## 2026-05-27 追加：Phase 7a alpha-validation route

**改了什么**:

- 新增 `docs/alpha_plausibility_audit.md`，作为 lane objective、alpha plausibility、portfolio-level synthesis、continue / risk-filter / redesign / defer / do-not-implement verdict 的 owner doc。
- 新增 `docs/evidence_capital_policy.md`，作为 `paper` vs `live_normalized` evidence、normalized return、capacity / slippage / scaling validity 和 ship-gate evidence 边界的 owner doc。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/strategy_design_synthesis.md`、`docs/long_alpha_spec.md`、`docs/burst_lane_spec.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md` 的路由与执行顺序。

**为什么改**:

- 原 Phase 7 下一步默认从已证明的 A-share EOD / benchmark surfaces 填充 provider evidence 入手。这是工程上容易的路线，但不是 alpha-leverage-first 的路线。
- 用户目标是 A/US 短线风控 + 爆发赛道、A/US 长线 push alpha。后续 implementation 前必须先判断每条 lane 的 alpha source、data/PIT/provider blockers、detectability horizon 和 portfolio-level contribution。
- 资金治理不变，不能用 temporary global AUM pool 解决 evidence accumulation；必须用 paper / live-normalized evidence level 区分，并禁止 paper-only ship-gate claim。

**验证命令**:

```powershell
git diff --check
```

以及 changed-doc trailing whitespace scan。

**验证结果**:

- 本轮为 docs-only 设计路由修改；最终校验结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一刀默认从 A-share EOD / benchmark provider capability evidence 入手”失效；改为先做 schema-first alpha plausibility audit，再按 alpha leverage / data blocker 排序 provider evidence。
- “Burst lane implementation 必须等 full provider set ready 才能开始”失效；改为 minimal-data paper tier 与 full-data live-eligible tier 分层。
- “Minimal live evidence 可以靠临时总 AUM pool 加速”失效；资金政策不变，ship-gate evidence 走 live-normalized 并记录 capacity / scaling validity。

**下一步注意事项**:

1. 下一条 `执行` 推荐新增 `schemas/alpha_plausibility_audit.schema.json`、example、tests，并产出第一版 audit。
2. Audit 结论再驱动 `long_alpha_spec.md` expected-alpha thesis 完整落地、A-short steady / variants 进一步收紧、provider priority、provisional benchmarks、burst tiering、evidence capital schema updates。
3. 不要在 alpha audit 前新增 provider adapter、抓 provider 数据、建立 DataHub table、或改 strategy runner 行为。

## 2026-05-27 追加：Alpha reality action guide

**改了什么**:

- 新增 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`，作为 Phase 7a+ 当前最高行动指南；`AGENTS.md` 已将其纳入必读路由和固化决策。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/strategy_design_synthesis.md`、`docs/alpha_plausibility_audit.md`、`docs/evidence_capital_policy.md`、`docs/burst_lane_spec.md`、`docs/long_alpha_spec.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`。
- 将最新三轮漏洞分析全部挂到既有 phase：Phase 7a-1 处理 alpha 真实性护栏；Phase 7a-2/7a-4/Phase 8 处理实战可用性；Phase 7a-5/Phase 9 处理工作流闭环；Phase 7b/7c/8 处理 DataHub operation / monitoring。

**为什么改**:

- 用户确认采纳最终设计，要求把设计变成所有后续 LLM 的最高行动指南。
- 原 Phase 7a 路由已经解决 alpha audit 前置，但还需要把 survivorship、multiple testing、statistical power、regime、factor exposure、execution cost、risk-filter effectiveness、decision packet、position reconciliation、data quality drift、kill switch 等业务真实性护栏写入 repo-visible owner docs。
- 这些不是新 design loop，而是防止 ship gate 纸面通过、实战失败的必要边界。

**验证命令**:

```powershell
git diff --check
```

以及 changed-doc trailing whitespace scan、active stale wording scan。

**验证结果**:

- 本轮 docs-only 变更的最终校验结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “Phase 7a audit 只需要 lane objective / provider blocker / verdict 字段”失效；Phase 7a-1 schema 还必须覆盖 alpha 真实性护栏。
- “cost-adjusted return、position reconciliation、decision packet、data quality drift 可以作为后期 polish”失效；这些已分配到 Phase 7a-5、Phase 7b/7c 或首次 live-normalized evidence 前的必修边界。
- “旧 24p t-stat finding 可直接作为显著结论”需加 multiple-testing / power / evidence-window 限定；未修正前只能作为探索性证据。

**下一步注意事项**:

1. 下一条 `执行` 仍然是 Phase 7a-1：写 `schemas/alpha_plausibility_audit.schema.json`、example、tests、lightweight provider status snapshot 和第一版 audit。
2. Phase 7a-1 必须使用 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` 的 mandatory field groups；不要缩水成主观 markdown audit。
3. 在 Phase 7a-1 review 通过前，不要新增 provider adapter、抓 provider 数据、建立 DataHub table、或改 strategy runner 行为。

### Optional O1 disposition

- Claude review O1 accepted. `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` now explicitly assigns drawdown / circuit-breaker tiered action playbook to Phase 7a-4 and to the non-optional later controls list. `AGENTS.md` and `docs/strategy_design_synthesis.md` route summaries now include the same Phase 7a-4 requirement.
- Required future shape: preset or lane contracts must define `circuit_breaker_playbook` tiers such as warn, size down, pause new entries, manual review, and reactivation / cooldown rule before Phase 8 implementation can rely on those lanes.

## 2026-05-27 追加：Phase 7a-1 provider status snapshot

**改了什么**:

- 新增 `docs/phase7a_provider_status_snapshot.json`，作为第一版 alpha plausibility audit 的 lightweight provider readiness input。
- 更新 `docs/README.md` 和 `docs/CURRENT.md` 路由：Phase 7a-1 schema contract 已完成，当前下一刀变为第一版 6 parent / 11 sub-lane audit。
- 更新 `tests/schema/test_alpha_plausibility_audit_schema.py`，验证该 snapshot 可嵌入 `alpha_plausibility_audit` example 并通过 schema 校验，同时确认它仍是 lightweight inventory，不是 provider selection。

**为什么改**:

- `docs/ALPHA_VALIDATION_ACTION_GUIDE.md §4` 要求 audit 在 provider evidence 不完整时使用 lightweight status snapshot，而不是提前启动 provider implementation。
- 第一版 audit 需要统一引用一个 provider readiness baseline，否则每条 lane 会各自猜测 A/US fundamentals、burst full-data、US microstructure 和 A-share EOD helper 的 readiness。
- 该 snapshot 明确区分：A-share EOD / CSI helper surfaces 是 narrow ready evidence；A/US long fundamentals、PIT industry history、US security master、burst full-data event / flow / options / borrow 仍 unknown 或 blocked。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_alpha_plausibility_audit_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan。

**验证结果**:

- `tests.schema.test_alpha_plausibility_audit_schema`：12 tests passed。
- Full `tests/schema` discovery：49 tests passed。
- `git diff --check` 和 trailing whitespace scan 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “第一版 audit 可以直接从 docs 推断 provider readiness”失效；必须引用 `docs/phase7a_provider_status_snapshot.json` 作为当前 readiness baseline。
- “A-share EOD / benchmark helper readiness 可代表 A-share provider readiness”失效；snapshot 仅标记 narrow helper surfaces ready，A-share fundamentals、SW PIT history 和 governance / audit red flags 仍 unknown。
- “US fundamentals / filings provider readiness 可等 implementation 时再判断”继续失效；snapshot 明确其为 unknown，是第一版 audit 的 blocker input。

**下一步注意事项**:

1. 下一条 `执行` 是第一版 alpha plausibility audit artifact，必须覆盖 11 sub-lanes 和 6 parent lanes。
2. Audit 的 `provider_status_snapshot_ref` 应引用 `provider_status_snapshot_20260527_phase7a1`。
3. 不要在 audit 前或 audit 中选择 provider、抓数据、建 adapter / DataHub table、改 runner，或把 paper evidence 写成 ship-gate evidence。

## 2026-05-27 追加：Phase 7a-1 first alpha plausibility audit

**改了什么**:

- 新增 `docs/phase7a_alpha_plausibility_audit.json`，作为第一版正式 schema-first alpha plausibility audit artifact。
- 更新 `tests/schema/test_alpha_plausibility_audit_schema.py`，验证正式 audit 通过 schema、不是 example artifact、引用 `provider_status_snapshot_20260527_phase7a1`，并覆盖 11 sub-lanes / 6 parent lanes。
- 更新 `docs/README.md`、`docs/CURRENT.md`、`docs/alpha_plausibility_audit.md` 路由与当前状态。

**为什么改**:

- Phase 7a-1 已有 schema contract 和 provider status snapshot；下一步必须产出真正的 audit artifact，而不是继续停在 contract / example 层。
- Audit 需要把用户目标拆成可执行 verdict：短线 steady 是否只做 risk filter、burst minimal/full 如何分层、长线是否 provider-blocked、哪些 provider evidence 先做。
- 该 artifact 明确不是 ship-gate evidence；它只决定下一阶段 spec revisions / provider sequencing / evidence horizon。

**当前 audit 结论摘要**:

- `continue_as_risk_filter`：`a_short_steady`、`a_short_variants`、`us_short_steady`。
- `continue`：`a_share_burst_minimal_data`、`us_burst_minimal_data`，均为 paper/research tier，不支持 live sizing。
- `defer_until_provider_ready`：`a_share_burst_full_data`、`us_burst_full_data`、`a_long_core_quality`、`a_long_re_rating_catalyst`、`us_long_core_quality`、`us_long_re_rating_catalyst`。
- 0 条 lane 获得 full-size / ship-gate 资格；固定 ship gate 与 capital policy 不变。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_alpha_plausibility_audit_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan。

**验证结果**:

- `tests.schema.test_alpha_plausibility_audit_schema`：14 tests passed。
- Full `tests/schema` discovery 最终结果记录在同日 Codex SESSION_LOG entry。
- `git diff --check` 和 trailing whitespace scan 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “Phase 7a-1 仍缺 first audit artifact”失效；第一版正式 audit 已存在。
- “下一刀继续产出 first audit”失效；下一刀进入 Phase 7a-2 spec revisions。
- “Minimal burst continue 可解释为 live eligibility”失效；audit 明确 minimal burst 只是 paper/research 继续。

**下一步注意事项**:

1. 下一条 `执行` 应进入 Phase 7a-2：用 audit 更新 `docs/strategy_design_synthesis.md`、`docs/long_alpha_spec.md`、`docs/burst_lane_spec.md` 和必要 routing。
2. 不要把 `continue` 当 ship-gate pass；不要把 `defer_until_provider_ready` 当失败，先转入 provider/PIT evidence sequencing。
3. 不要选 provider、抓数据、建 adapter / DataHub table、改 runner，除非后续 phase 明确进入对应 implementation slice。

## 2026-05-27 追加：Phase 7a-2 owner-spec routing

**改了什么**:

- 更新 `docs/strategy_design_synthesis.md`，把第一版 audit verdict 写成 Phase 7a-2 routing baseline，并把下一步从 Phase 7a-1 改为 Phase 7a-3 / 7a-4 / 7a-5 sequence。
- 更新 `docs/burst_lane_spec.md`，明确 minimal-data burst 只可继续 paper / research，full-data burst 仍 `defer_until_provider_ready`；补 US microstructure、calendar / timezone 和 monitoring contract。
- 更新 `docs/long_alpha_spec.md`，明确 A / US long 四条 sub-lane 全部 `defer_until_provider_ready`；补 calendar / timezone 与 live-normalized 前 monitoring contract。
- 更新 `docs/us_short_spec.md`，明确 `us_short_steady` 仍是 `continue_as_risk_filter`；补 SSR / Reg SHO / LULD / PDT / extended-hours 等 US market microstructure 约束、calendar / timezone 和 monitoring contract。
- 更新 `docs/CURRENT.md`，把当前 P0 推进到 Phase 7a-3 provider priority / provisional benchmark contract。

**为什么改**:

- Phase 7a-1 已产出正式 audit artifact；如果 owner specs 不吸收 verdict，后续 LLM 仍可能按旧 Phase 6 baseline 误读 lane 状态。
- Audit 的 `continue` 只允许 minimal-data burst paper / research，不能被解释成 live sizing 或 ship-gate pass。
- Long alpha 仍是 push-alpha 目标，但当前被 PIT fundamentals、survivorship / security master、observed-date catalyst 和 fraud red-flag evidence 阻塞。
- US-short / US-burst 必须先把市场微结构和日历时区约束写入 spec，否则 paper evidence 到 live-normalized evidence 会失真。

**验证命令**:

```powershell
git diff --check
rg -n "[ \t]+$" docs\strategy_design_synthesis.md docs\burst_lane_spec.md docs\long_alpha_spec.md docs\us_short_spec.md docs\CURRENT.md
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
rg -n "next .*Phase 7a-1|下一条.*Phase 7a-1|Phase 7a-2 spec revisions after first audit|provider capability catalog contract should start Phase 7a|P0a bucket-aware|P0a `portfolio" docs\strategy_design_synthesis.md docs\burst_lane_spec.md docs\long_alpha_spec.md docs\us_short_spec.md docs\CURRENT.md
```

**验证结果**:

- `git diff --check`：passed（CRLF warnings only）。
- Changed-file trailing whitespace scan：passed（no matches）。
- `docs/CURRENT.md` physical line count：144，低于 150 行 snapshot target。
- Stale wording scan：passed（no active stale Phase 7a-1 / P0a bucket wording in touched owner docs）。

**失效旧结论**:

- “下一条 `执行` 继续做 Phase 7a-1 first audit”失效；Phase 7a-1 已完成，下一刀进入 Phase 7a-3 provider priority / provisional benchmark contract。
- “Minimal-data burst continue 可支持 live observation”失效；minimal-data burst 只能 paper / research。
- “Long alpha spec 可进入 implementation wave”失效；四条 long sub-lane 均需先解决 provider/PIT/fraud/survivorship blocker。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7a-3：provider priority reorder + provisional benchmark contract，继续 docs/schema-first。
2. 不要在 Phase 7a-3 选最终 provider、抓数据、建 adapter / DataHub table 或改 runner。
3. Phase 7a-4 再处理 burst minimal-to-full promotion、concentration / ADV sizing、slippage 和 circuit-breaker playbook。

## 2026-05-28 追加：Phase 7a-3 provider priority / provisional benchmark contract

**改了什么**:

- 新增 `docs/provider_priority_benchmark_contract.md`，作为 Phase 7a-3 provider evidence priority 与 provisional evidence benchmark owner。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/strategy_design_synthesis.md`、`docs/provider_data_requirements_audit.md`、`docs/alpha_plausibility_audit.md` 的 routing / current-state wording。
- 更新 `docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/long_alpha_spec.md`，把 provisional benchmark routing 指向 Phase 7a-3 owner contract，并把下一步推进到 Phase 7a-4 / 7a-5。

**为什么改**:

- Phase 7a-1 audit 与 Phase 7a-2 owner specs 已经给出 lane verdict，但 provider evidence priority 和 provisional evidence benchmark 仍分散在 strategy、provider audit、burst / long / US-short specs 中。
- Phase 7a-3 需要把 provider evidence queue 固化为可交接 contract：P1 US fundamentals / filings / security master，P2 A-share fundamentals / announcements / SW history，P3 burst event / flow / options / borrow，P4 already-proven A-share EOD / CSI helpers。
- Provisional benchmark 只用于 evidence accumulation 与 sensitivity reporting；除既有 A-short CSI1000 / CSI300 policy 外，不锁最终 ship-gate benchmark。

**验证命令**:

```powershell
git diff --check
rg -n "[ \t]+$" AGENTS.md docs\ALPHA_VALIDATION_ACTION_GUIDE.md docs\CURRENT.md docs\README.md docs\alpha_plausibility_audit.md docs\burst_lane_spec.md docs\long_alpha_spec.md docs\provider_data_requirements_audit.md docs\strategy_design_synthesis.md docs\us_short_spec.md docs\provider_priority_benchmark_contract.md docs\handoff\2026-05-27_phase7_kickoff_spec_handoff.md docs\SESSION_LOG.md
rg -n "next `执行` should implement Phase 7a-1|next execution slice is Phase 7a-1|下一条 `执行` 推荐 Phase 7a-3|Phase 7a-3 provider priority / provisional benchmark routing for burst data fields|Phase 7a-3 provider priority and provisional benchmark routing" AGENTS.md docs\ALPHA_VALIDATION_ACTION_GUIDE.md docs\CURRENT.md docs\README.md docs\alpha_plausibility_audit.md docs\burst_lane_spec.md docs\long_alpha_spec.md docs\provider_data_requirements_audit.md docs\strategy_design_synthesis.md docs\us_short_spec.md docs\provider_priority_benchmark_contract.md
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `git diff --check`：passed（CRLF warnings only）。
- Changed-file trailing whitespace scan：passed（no matches）。
- Active stale next-step wording scan：passed（no matches）。
- `docs/CURRENT.md` physical line count：146，低于 150 行 snapshot target。

**失效旧结论**:

- “Phase 7a-3 provider / benchmark routing 仍散落在 owner specs 中”失效；现在有 `docs/provider_priority_benchmark_contract.md` 作为单一 owner。
- “下一条 `执行` 仍是 Phase 7a-3”失效；下一条进入 Phase 7a-4 evidence feasibility controls。
- “Already-proven A-share EOD / CSI helper surfaces 是默认下一 implementation sink”继续失效；这些 surface 只作为 P4 ready evidence 记录。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7a-4：burst minimal-to-full promotion criteria、concentration / liquidity / ADV sizing、slippage / borrow / limit-risk feasibility、drawdown / circuit-breaker tiered action playbook。
2. 不要在 Phase 7a-4 选最终 provider、抓数据、建 adapter / DataHub table 或改 runner。
3. Phase 7b provider capability evidence 应按 Phase 7a-3 contract 的 P1-P4 queue 填充，除非后续 reviewed audit 明确反转。

## 2026-05-28 追加：Phase 7a-4 evidence feasibility controls

**改了什么**:

- 新增 `docs/evidence_feasibility_controls.md`，作为 Phase 7a-4 burst minimal-to-full promotion、evidence capital、concentration / liquidity / ADV、slippage / borrow / limit-risk、drawdown / circuit-breaker playbook owner。
- 新增 `schemas/evidence_feasibility_controls.schema.json` v1.0.0、`schemas/examples/evidence_feasibility_controls.example.json` 和 `tests/schema/test_evidence_feasibility_controls_schema.py`。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/strategy_design_synthesis.md`、`docs/alpha_plausibility_audit.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_capital_policy.md`、`docs/provider_priority_benchmark_contract.md` 的 routing / current-state wording。

**为什么改**:

- Phase 7a-3 已经锁定 provider priority 和 provisional benchmarks；下一步不能继续讨论 provider 排序，而要把 burst 赛道进入 full-data / live-normalized evidence 前的 feasibility controls 写成可校验 contract。
- Minimal-data burst 仍只能 paper / research；schema 明确 `paper_only`，并要求 promotion 前有 benchmark-relative evidence、drawdown / false-positive review、非价格确认、成本 / liquidity / spread / borrow / limit feasibility、rejected / failed candidate retention、minimal-vs-full paired comparison。
- Evidence capital 不改变固定资金政策；schema 通过 const lock 禁止 global AUM pool、cross-market pooling、liquidity bucket auto-borrowing 和 paper ship-gate claim。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_evidence_feasibility_controls_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_evidence_feasibility_controls_schema`：10 tests passed。
- Full `tests/schema` discovery、`git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一条 `执行` 推荐 Phase 7a-4”失效；Phase 7a-4 baseline 已建立，下一条进入 Phase 7a-5 evidence report schemas。
- “Minimal-data burst 可因 paper signal 强而进入 live observation”继续失效；minimal tier 默认 `paper_only`，live-normalized evidence 只能走 reviewed full-data path。
- “Circuit breaker 可留到 Phase 8 implementation 再定义”失效；Phase 7a-4 schema 已要求 warn、size_down、pause_new_entries、manual_review、reactivation_cooldown 五类动作。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7a-5：evidence report schemas，覆盖 immutable decision packet、cost-adjusted return、cash drag、manual override、minimal reconciliation、thesis outcome log、research experiment log。
2. Phase 7a-5 应消费 `docs/provider_priority_benchmark_contract.md` 和 `docs/evidence_feasibility_controls.md`，不要重新打开 provider priority 或 burst feasibility design。
3. 不要在 Phase 7a-5 选 provider、抓数据、建 adapter / DataHub table 或改 runner。

## 2026-05-28 追加：Phase 7a-5 evidence report schema contract

**改了什么**:

- 新增 `docs/evidence_report_schema_contract.md`，作为 Phase 7a-5 evidence report schema owner。
- 新增 `schemas/evidence_report.schema.json` v1.0.0、`schemas/examples/evidence_report.example.json` 和 `tests/schema/test_evidence_report_schema.py`。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/strategy_design_synthesis.md`、`docs/alpha_plausibility_audit.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/long_alpha_spec.md`、`docs/evidence_capital_policy.md`、`docs/provider_priority_benchmark_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- Phase 7a-4 已经锁定 burst feasibility controls；下一步需要让未来 evidence reports 不能丢失决策时间、参数、成本、现金拖累、人工 override、最小 reconciliation、thesis outcome 和 research lineage。
- `schemas/evidence_report.schema.json` 明确消费 `docs/provider_priority_benchmark_contract.md` 与 `docs/evidence_feasibility_controls.md`，避免 Phase 7a-5 重新打开 provider priority 或 burst feasibility design。
- Research experiment 仍保持隔离；schema 锁定 `no_direct_production_feed = true`，promotion 仍需 schema review、Claude review 和用户批准。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_evidence_report_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_evidence_report_schema`：12 tests passed。
- Full `tests/schema` discovery：73 tests passed。
- `git diff --check`：passed（CRLF warnings only）。
- Changed-file trailing whitespace scan：passed（no matches）。
- `docs/CURRENT.md` physical line count：141，低于 150 行 snapshot target。

**失效旧结论**:

- “下一条 `执行` 推荐 Phase 7a-5”失效；Phase 7a-5 schema-first baseline 已建立，下一条进入 Phase 7b provider evidence / drift monitor。
- “Evidence reports 可以稍后再补 decision packet / override / reconciliation / research lineage”失效；Phase 7a-5 schema 已要求七个核心 section 即使不适用也必须显式记录。
- “Research experiment result 可以直接喂 production runner”继续失效；schema 通过 const lock 禁止 direct production feed。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7b：按 `docs/provider_priority_benchmark_contract.md` 的 P1-P4 queue 填充 provider capability evidence，并建立 data quality / provider drift monitor。
2. 不要在 Phase 7b silent default、latest-only 回填历史证据，或把 provider status guess 写成 production-ready evidence。
3. 不要在下一刀改 runner、建 adapter / DataHub table、接 broker / OS automation，除非后续 reviewed slice 明确进入对应 implementation scope。
## 2026-05-28 追加：Phase 7b provider evidence / drift monitor contract

**改了什么**:

- 新增 `docs/provider_evidence_drift_monitor.md`，作为 Phase 7b provider evidence / drift monitor owner。
- 新增 `schemas/provider_evidence_drift_monitor.schema.json` v1.0.0、`schemas/examples/provider_evidence_drift_monitor.example.json` 和 `tests/schema/test_provider_evidence_drift_monitor_schema.py`。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/datahub_design.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- Phase 7a-3 已经锁定 provider evidence P1-P4 queue；Phase 7a-5 已经锁定 evidence report shape。Phase 7b 需要把 P1-P4 provider evidence records、provider readiness rollup、data quality / provider drift dimensions 与 action set 写成可校验 contract，避免后续 Phase 7c DataHub / runner work 依赖 provider readiness guess。
- P4 A-share EOD / CSI helper surface 已有 ready evidence，但只能作为 narrow helper evidence 记录；不能因为它方便就绕过 P1-P3 blocker 或成为 broad DataHub implementation 默认起点。
- Drift monitor 必须显式覆盖 coverage、freshness、schema/field semantics、PIT/as-of、survivorship/security master、corporate actions/revisions、calendar/timezone、authorization/cost/quota、provider incidents、outlier/revision rate；否则后续 provider-backed evidence 会缺稳定性边界。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`：11 tests passed。
- Full `tests/schema` discovery、`git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一条 `执行` 推荐 Phase 7b”失效；Phase 7b schema-first baseline 已建立，下一条进入 Phase 7c DataHub shared layer / report contracts / reproducibility plumbing。
- “Phase 7b 可以靠文字约定 provider readiness / drift monitor”失效；现在必须通过 `schemas/provider_evidence_drift_monitor.schema.json` 记录 P1-P4 queue、provider evidence records、readiness rollup 和 drift dimensions/action set。
- “P4 ready A-share helper surface 可以作为 broad DataHub implementation 起点”继续失效；schema example 明确 P4 只记录 ready helper surface，不授权 implementation、provider selection 或 ship-gate claim。

**下一步注意事项**:

1. 下一条 `执行` 推荐 Phase 7c：设计 DataHub shared-layer / report / reproducibility contract，消费 Phase 7b provider evidence / drift monitor，不要重开 provider priority。
2. 不要在 Phase 7c 第一刀抓 provider 数据、选 provider、建 adapter / DataHub table 或改 runner；先写 contract。
3. 后续 implementation 若需要使用任何 provider-backed field，必须能引用 Phase 7b 的 evidence record 与 drift-monitor dimension/action。

## 2026-05-28 追加：Phase 7b-2 P1 US public-source provider evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_public_sources_20260528.json`，作为 Phase 7b-2 第一份 P1 US public-source evidence population artifact。
- `schemas/provider_evidence_drift_monitor.schema.json` 升至 v1.1.0：保留 no-selection / no-fetch / no-implementation locks，允许 `provider_evidence_population_snapshot`，并要求 `reviewed_provider_evidence` 记录 `evidence_source_refs`。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一轮 R1 修复明确 Phase 7b-2 才是真实 provider evidence population；本刀开始填 P1，而不是继续停留在 contract 层。
- 仅靠 v1.0.0 的 `schema_first_contract_only` 无法准确表达 evidence snapshot，所以 v1.1.0 增加 snapshot status 和 source refs，避免把来源证据写成不可审查的备注。
- 官方 SEC / Nasdaq / MSCI 文档足以把 P1 从 `unknown` 推进到 `partial`，但不足以解除 implementation blocker：US price、corporate action、delisting/security master、benchmark、paid-provider authorization/cost/stability 仍未完成。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`: 14 tests passed。
- Full `tests/schema` discovery、`git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “Phase 7b-2 provider capability evidence population 尚未开始”失效；现在已有第一份 P1 public-source snapshot。
- “P1 US provider evidence 仍完全 unknown”失效；现在是 `partial`，但仍 blocked。
- “`schemas/provider_evidence_drift_monitor.schema.json` 当前 `1.0.0`”失效；当前为 `1.1.0`。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2，而不是进入 Phase 7c；优先补 P1 US adjusted price、corporate action、delisting/security master、benchmark、authorization/cost/fallback/stability evidence。
2. 不要把 SEC EDGAR / SEC ticker files / Nasdaq symbol directory / GICS methodology 误读为完整 provider selection 或 implementation readiness。
3. 继续不抓 provider data、不选 provider、不建 adapter / DataHub table、不改 runner。

## 2026-05-28 追加：Phase 7b-2 P1 US market-data candidate evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_market_data_candidates_20260528.json`，作为 Phase 7b-2 第二份 P1 evidence-population artifact。
- 该 artifact 基于 Massive / Polygon 与 Norgate 官方文档，记录 US adjusted OHLCV、ticker / security-master surfaces、corporate actions、market status / exchange metadata、survivorship EOD package claims、index membership package claims 等 candidate evidence。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证两份 P1 evidence artifacts，并断言 market-data snapshot 仍为 partial / non-authorizing。

**为什么改**:

- 上一份 public-source snapshot 只覆盖 SEC / Nasdaq / MSCI 文档，尚未触及 P1 里 price / corporate action / delisting/security-master / benchmark candidate 方向。
- Massive / Polygon 与 Norgate 文档可把 P1 market-data candidate evidence 从完全未审查推进到 source-backed `partial`，但不能解除 implementation blocker。
- 本刀仍严守 Phase 7b-2 边界：不抓 provider data、不选 provider、不建 adapter / DataHub table、不改 runner、不放松 ship gate。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`: 15 tests passed。
- Full `tests/schema` discovery: 89 tests passed。
- Final `git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “Phase 7b-2 只有第一份 P1 public-source snapshot”失效；现在有 public-source + market-data-candidate 两份 P1 snapshots。
- “P1 仍完全未覆盖 US price / corporate action / security-master provider candidates”失效；现在已有 source-backed candidate evidence，但仍 partial / blocked。
- “下一刀应补 US adjusted price / corporate action / delisting security master”需收窄；下一刀应继续补 authorization / cost、sandbox / trial、coverage counts、direct benchmark return sources、issuer-level PIT GICS membership、fundamentals / filing observed-date candidates、fallback / stability。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2 P1，而不是进入 Phase 7c。
2. 不要把 Massive / Polygon 或 Norgate 文档误读为 provider selection、paid-access approval、PIT security-master proof、direct benchmark proof 或 production readiness。
3. 如需 trial / sandbox token、paid access、成本上限或 provider selection，必须另走 reviewed decision；不得在 evidence artifact 中隐式批准。

## 2026-05-28 修复追加：Phase 7b-2 market-data candidate R1 verification trace

**改了什么**:

- 修复 Claude R1：`docs/provider_evidence_p1_us_market_data_candidates_20260528.json` 中 4 条 Massive/Polygon records 的 Massive source refs 已在 `evidence_note` 明确写入 `WebFetched on 2026-05-28 at ...` verification trace。
- Polygon market-data terms refs 也写入 `WebFetched on 2026-05-28 at https://polygon.io/terms/market_data_terms.pdf`。
- Massive source refs 额外声明：这些 trace 只证明 Massive docs page 实际可访问并被审阅，不独立证明 Polygon-to-Massive rebrand / legal continuity，也不授权 provider selection。
- `tests/schema/test_provider_evidence_drift_monitor_schema.py` 新增断言，防止 Massive source refs 再次缺失 WebFetched trace 或 rebrand 非证明声明。
- `docs/provider_evidence_drift_monitor.md` 同步记录 R1 repair note。

**为什么改**:

- 最新 Claude review 指出 Massive/Polygon 双品牌 evidence chain 需要区分“实际打开过 massive.com 文档”与“依赖训练数据 / 假设 rebrand 成立”。
- 用户批准 R1 并指定修复路径 `(c)`，即保留 Massive/Polygon evidence，但把 verification path 写进 evidence_note。
- 修复后 downstream Phase 7b-2 / 7c 可追溯每条 Massive docs evidence 的实际 URL 审阅路径，同时不会把该 trace 误读成 provider selection 或品牌法律连续性的证明。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- 最终验证结果记录在同日 Codex `修复` SESSION_LOG entry。

**失效旧结论**:

- “Massive/Polygon source_url 可能是未验证 / 训练数据来源”这条 R1 风险已修复为可追溯 WebFetched trace。
- “Massive docs trace 可证明 Polygon-to-Massive rebrand / legal continuity”仍不成立；artifact 明确不做该证明。

**下一步注意事项**:

1. Claude re-review 时应重点确认 4 条 Massive records 的 source refs 是否都有 verification trace。
2. 后续若要证明 Polygon-to-Massive rebrand 或做 provider selection，必须另开 reviewed evidence / decision，不得把本次 trace 当作 selection。
3. P1 仍 partial / blocked；下一条 `执行` 仍继续 authorization / cost、sandbox / trial、coverage count、benchmark、PIT GICS、fundamentals observed-date、fallback / stability evidence。

## 2026-05-28 追加：Phase 7b-2 P1 US authorization / cost / stability evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json`，作为 Phase 7b-2 第三份 P1 evidence-population artifact。
- 该 artifact 基于 Massive / Polygon 与 Norgate 官方文档，记录 pricing、API-key / subscription / trial access、license / EULA、export / retention、stability constraints，以及 Norgate current-fundamentals latest-only limitation。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证三份 P1 evidence artifacts，并断言 authorization / cost / stability snapshot 仍为 partial / non-authorizing。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一刀已经补了 market-data candidate evidence，但 P1 仍缺 authorization / cost / trial / access / stability 的 reviewed source basis。
- 官方 terms 显示 Massive / Polygon 与 Norgate 都存在必须单独 review 的使用边界：personal / non-commercial、non-display、local storage、redistribution、subscription lapse、export scope、Windows/plugin access、no-warranty / data-change constraints。
- Norgate current fundamentals 明确为 latest-only，不能被下游误读成 US-long PIT historical fundamentals provider。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`: 16 tests passed。
- Full `tests/schema` discovery: 90 tests passed。
- `git diff --check`、trailing whitespace scan、stale wording scan 和 `docs/CURRENT.md` line count 的最终结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “P1 evidence snapshots 只有 public-source + market-data-candidate 两份”失效；现在有 public-source、market-data-candidate、authorization / cost / stability 三份 P1 snapshots。
- “下一刀应继续补 authorization / cost、sandbox / trial”需收窄；下一刀应继续补 coverage counts、direct benchmark return sources、issuer-level PIT GICS membership、fundamentals / filing observed-date candidates beyond latest-only sources、fallback behavior、incident / stability evidence。
- “Norgate current fundamentals 可以作为 US-long historical fundamentals candidate”不成立；本 artifact 明确 latest-only，不得当作 PIT historical fundamentals。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2 P1，而不是进入 Phase 7c。
2. 不要把 Massive / Polygon 或 Norgate 的 pricing / terms / trial evidence 误读为 provider selection、paid-access approval、local-storage approval、non-display approval 或 production readiness。
3. 如需 trial token、paid access、cost ceiling、provider selection、non-display / local-storage permission，必须另走 reviewed decision。

## 2026-05-28 追加：Phase 7b-2 P1 US benchmark / GICS candidate evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json`，作为 Phase 7b-2 第四份 P1 evidence-population artifact。
- 该 artifact 基于 S&P DJI、Nasdaq、FTSE Russell / LSEG、MSCI、S&P Global 官方文档，记录 S&P 500 / Nasdaq-100 / Russell 1000 direct benchmark source candidate evidence 与 GICS taxonomy / GICS History candidate evidence。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证四份 P1 evidence artifacts，并断言 benchmark / GICS snapshot 仍为 partial / non-authorizing。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一刀补了 authorization / cost / stability，但 P1 仍缺 direct benchmark return source 与 issuer-level PIT GICS candidate review。
- 官方 index methodology / index pages 可作为 direct benchmark-source candidate evidence，但不能当成已授权、可本地存储、可回测消费的历史 total-return feed。
- GICS methodology 只能证明 taxonomy context；S&P Global GICS History product docs 只是 issuer-level history candidate，仍需 license、sample rows、data dictionary、coverage counts、identifier mapping 与 as-of semantics 审查。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- `tests.schema.test_provider_evidence_drift_monitor_schema`: 17 tests passed。
- Full `tests/schema` discovery: 91 tests passed。
- `git diff --check`: passed；仅报告既有 LF/CRLF working-copy warnings。
- Changed-file trailing whitespace scan: no matches。
- `docs/CURRENT.md` line count: 144，低于 150-line snapshot target。

**失效旧结论**:

- “P1 evidence snapshots 只有 public-source + market-data-candidate + authorization / cost / stability 三份”失效；现在有四份 P1 snapshots。
- “下一刀应继续补 direct benchmark return sources、issuer-level PIT GICS membership”需收窄；该方向已有 candidate evidence，但仍非 implementation-ready。下一刀应继续补 coverage counts、fundamentals / filing observed-date candidates beyond latest-only sources、fallback behavior、incident / stability evidence。
- “S&P / Nasdaq / Russell methodology page 可以直接当历史 benchmark return feed”不成立；本 artifact 明确只记录 candidate evidence，不批准数据抓取、授权、存储或 provider selection。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2 P1，而不是进入 Phase 7c。
2. 不要把 official index pages / methodology docs 误读为 licensed historical benchmark return feed。
3. 不要把 GICS methodology / product docs 误读为已可用 issuer-level PIT GICS membership；仍需 license、sample、coverage、identifier 和 as-of 证据。

## 2026-05-28 追加：Phase 7b-2 P1 US fundamentals observed-date candidate evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json`，作为 Phase 7b-2 第五份 P1 evidence-population artifact。
- 该 artifact 基于 SEC、Intrinio、FMP、Nasdaq Data Link / Sharadar 官方文档，记录 SEC EDGAR public reconstruction、Intrinio filing fundamentals accepted-date candidate、FMP SEC filings / as-reported statement candidate、Nasdaq Data Link / Sharadar SF1 candidate context。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证五份 P1 evidence artifacts，并断言 fundamentals observed-date snapshot 仍为 partial / non-authorizing。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一刀补了 benchmark / GICS candidate evidence，但 P1 仍缺 fundamentals / filing observed-date provider candidates beyond latest-only sources。
- SEC EDGAR 能支持 public-source filing/XBRL reconstruction，但需要 accession-level observed-date、taxonomy、amendment、coverage、security-master linking 和 fair-access policy 才能进入 implementation。
- Intrinio 文档明确给出 filing-linked fundamentals 的 `accepted_date` / `filing_date` / `is_latest` / `updated_date` candidate evidence；FMP 和 Nasdaq Data Link / Sharadar 仍只是 candidate context，不能当作 PIT-ready historical fundamentals。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` line count check。

**验证结果**:

- 最终验证结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “P1 evidence snapshots 只有四份”失效；现在有 public-source、market-data-candidate、authorization / cost / stability、benchmark / GICS、fundamentals observed-date 五份 P1 snapshots。
- “下一刀应补 fundamentals / filing observed-date candidates beyond latest-only sources”需收窄；该方向已有 candidate evidence，但仍非 implementation-ready。
- “latest/current financial statement endpoints 可以直接作为 historical PIT fundamentals”不成立；artifact 明确禁止 latest-only backfill。

**下一步注意事项**:

1. 下一条 `执行` 仍应继续 Phase 7b-2 P1，而不是进入 Phase 7c。
2. P1 剩余主要 blocker 收窄为 coverage counts、fallback behavior、incident / stability evidence、unresolved fundamentals field-level license / sample-row validation。
3. 不要把 SEC / Intrinio / FMP / Nasdaq Data Link / Sharadar 文档误读为 provider selection、paid-access approval、PIT-safe production factors、local-storage approval 或 DataHub implementation readiness。

## 2026-05-28 追加：Phase 7b-2 P1 US coverage / fallback / incident candidate evidence snapshot

**改了什么**:

- 新增 `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`，作为 Phase 7b-2 第六份 P1 evidence-population artifact。
- 该 artifact 基于 Intrinio、FMP、Massive、Norgate、Nasdaq Data Link 官方文档，记录 coverage、status / incident、fallback / error-code、license / sample-row validation evidence。
- 扩展 `tests/schema/test_provider_evidence_drift_monitor_schema.py`，让 schema 回归同时验证六份 P1 evidence artifacts，并断言 coverage / fallback / incident snapshot 仍为 partial / non-authorizing。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一刀补了 fundamentals observed-date candidate evidence，但 P1 仍缺 coverage、fallback、incident-stability、field-level license / sample-row validation 的 reviewed source basis。
- 该切片把 vendor-level coverage claims、public status pages、error-code / call-limit docs、license caveats 和 explicit coverage limitations 写入 machine-checkable artifact，防止后续 DataHub 误把 provider docs 当作 implementation readiness。
- 本刀仍严守 Phase 7b-2 边界：不抓 provider data、不选 provider、不建 adapter / DataHub table、不改 runner、不放松 ship gate。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_evidence_drift_monitor_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 JSON parse、changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` authoritative line count check。

**验证结果**:

- 最终验证结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “P1 evidence snapshots 只有五份”失效；现在有六份 P1 snapshots。
- “下一刀应补 coverage / fallback / incident / license-sample evidence”需收窄；该方向已有 documentation-review evidence，但仍非 implementation-ready。
- “vendor-level coverage counts 或 status pages 可以替代 project coverage / sample-row validation”不成立；artifact 明确保持 P1 blocked。

**下一步注意事项**:

1. 下一条 `执行` 应做 P1 readiness review matrix，而不是进入 Phase 7c 或 provider implementation。
2. Readiness review 应 field-by-field 对比 6 份 P1 snapshots，并明确哪些字段仍需 paid license、sample-row validation、coverage-count check 或 provider decision。
3. 不要把任何 provider docs、status page 或 coverage claim 误读为 provider selection、paid-access approval、PIT-safe production factors、local-storage approval 或 DataHub implementation readiness。

## 2026-05-29 追加：Phase 7b-2 P1 readiness review matrix

**改了什么**:

- 新增 `schemas/provider_p1_readiness_review.schema.json`，作为 P1 readiness review matrix 的 schema-first contract。
- 新增 `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json`，field-by-field 综合六份 P1 snapshots：security master / survivorship、adjusted EOD / liquidity、corporate actions、fundamentals observed-date / PIT、benchmark returns、GICS PIT membership、coverage counts、authorization / license / cost、fallback / incident / stability、sample-row validation / lineage。
- 新增 `tests/schema/test_provider_p1_readiness_review_schema.py`，验证 matrix schema、artifact、source snapshot / record refs、non-authorizing scope locks、关键 provider blocker 结论和下一步建议。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- Claude 上轮 review 明确 Phase 7b-2 P1 evidence collection 已事实结束，下一刀应从 collect 转向 synthesize / decide。
- 六份 snapshots 已覆盖 P1 docs evidence，但仍不能被 Phase 7c 或 DataHub 当成 provider readiness；matrix 把 blocker disposition 机器化，避免后续把 candidate docs 误读为 selection / implementation。
- 本刀仍严守 Phase 7b-2 边界：不抓 provider data、不选 provider、不建 adapter / DataHub table、不改 runner、不放松 ship gate。

**验证命令**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_readiness_review_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests/schema -v
git diff --check
```

以及 JSON parse、changed-file trailing whitespace scan、active stale next-step scan、`docs/CURRENT.md` authoritative line count check。

**验证结果**:

- 最终验证结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一刀应做 P1 readiness review matrix”已完成；下一刀应做 P1 access-decision and sample-validation plan。
- “六份 P1 snapshots 可直接进入 Phase 7c consumption”不成立；matrix 明确 `p1_ready_for_phase7c = false`。
- “强 candidate evidence 可当 provider selection”不成立；Intrinio / Norgate / Massive / SEC / benchmark / GICS candidates 仍需 access、license、sample-row、coverage-count 和 fallback / incident review。

**下一步注意事项**:

1. 下一条 `执行` 应准备 P1 access-decision and sample-validation plan，而不是进入 Phase 7c 或 provider implementation。
2. 任何 token、trial、paid subscription、provider data fetch、sample-row collection、provider selection 或 DataHub table 仍需单独 reviewed decision。
3. Matrix 中的 `strong_candidate_but_blocked` 只表示值得后续 access/sample review，不表示 production provider readiness。

## 2026-05-31 追加：P1 access-plan 后 research prereg execution lock

**改了什么**:

- 更新 `docs/CURRENT.md`，把 P0 保持为 Phase 7b-2 P1 access-decision and sample-validation plan，并锁定 P0 reviewed/committed 后的下一条 alpha-validation 刀为 A-share `minimal_data_burst` research-only falsification。
- 更新 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`，新增 research preregistration、single frozen test、program-level test-budget ledger 触发规则，并明确 US-long SEC observed-date / parser feasibility 属于 provider-evidence track，不是 alpha-validation track。
- 更新 `docs/strategy_design_synthesis.md`，只保留短路由说明，把 research preregistration / test-budget 细则交给 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`。
- 未新建大设计文档，未改 schema / runner / provider / DataHub / order execution。

**为什么改**:

- 用户确认采用收敛后的执行方案：先收口 P1 access-decision / sample-validation plan，再启动 A-share minimal-data burst research-only falsification。
- 需要把该方案写进启动必读链路，防止后续 LLM 把 access-decision 继续滚成 provider docs 循环，或把 burst research 做成未预注册的参数 / variant fishing。
- 该修改保持 Phase 7b-2 串行执行边界：P1 access plan 仍是下一刀；research 只在该 reviewed slice 之后启动，且不进入 production、不改 runner、不声称 ship-gate evidence。

**验证命令**:

```powershell
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
git diff --stat
```

**验证结果**:

- `git diff --check` 通过；仅出现 touched docs 的 LF/CRLF working-copy warning。
- `docs/CURRENT.md` authoritative line count = 149，低于 150-line snapshot target。
- 最终 diff / status 记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “P1 access-decision plan 之后下一步未锁定”失效；现在明确锁定为 A-share `minimal_data_burst` research-only falsification。
- “US-long SEC observed-date / parser feasibility 可以作为 alpha-validation 首刀”不成立；该方向归 provider-evidence track。
- “单个 research experiment 可自由扫参数 / benchmark / holding period 而不触发 program-level ledger”不成立；只有 preregistered single frozen test 可豁免 ledger。

**下一步注意事项**:

1. 下一条 `执行` 仍是 P1 access-decision and sample-validation plan；不要跳到 research、Phase 7c、provider selection 或 data fetch。
2. P1 access plan reviewed/committed 后，下一条 alpha-validation `执行` 应先建立 A-share minimal-data burst preregistration artifact，再做 research-only falsification。
3. 如果 burst research 引入第二个 promotion-relevant hypothesis、参数搜索、variant 搜索、benchmark sweep 或 holding-period sweep，必须先建 singleton program-level test-budget ledger。

## 2026-05-31 追加：Phase 7b-2 P1 access-decision / sample-validation plan

**改了什么**:

- 新增 `schemas/provider_p1_access_decision_plan.schema.json`，作为 P1 access-decision / sample-validation plan 的 schema-first contract。
- 新增 `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json`，把 P1 readiness matrix blockers 转成 cost ceiling、access path、license / storage、sample rows、coverage counts、fallback / incident playbook 和 decision gates。
- 新增 `tests/schema/test_provider_p1_access_decision_plan_schema.py`，验证 plan schema、artifact、candidate queue / matrix alignment、10 个 sample workstreams、non-authorizing scope locks、decision gates 和 post-plan alpha-validation route。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/datahub_design.md`、`docs/strategy_design_synthesis.md`、`docs/evidence_report_schema_contract.md`、`docs/evidence_feasibility_controls.md` 的 routing / current-state wording。

**为什么改**:

- 上一轮已锁定当前最小任务是 P1 access-decision and sample-validation plan；本轮把它变成机器校验 artifact，而不是继续停留在自然语言 next-step。
- 需要防止后续 LLM 把 access plan 误读成 provider selection、trial / token request、paid access、sample fetch、data fetch 或 Phase 7c 授权。
- 计划完成后，下一条 alpha-validation 刀按已批准方案转向 A-share `minimal_data_burst` research-only preregistration / falsification；US-long SEC parser feasibility 仍归 provider-evidence track。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_provider_p1_access_decision_plan_schema`: 8 tests passed.
- `python -m unittest discover -s tests/schema -v`: 109 tests passed.
- `git diff --check`: passed；只出现 tracked docs 的 LF/CRLF working-copy warning。
- `docs/CURRENT.md` authoritative line count = 144，低于 150-line snapshot target。

**失效旧结论**:

- “下一条 `执行` 仍是 P1 access-decision and sample-validation plan”已完成；下一条 alpha-validation `执行` 应转向 A-share `minimal_data_burst` preregistration / research-only falsification。
- “P1 access plan 可授权 token / trial / paid access / sample fetch”不成立；artifact 锁定 approved spend = 0，所有 provider access 均需用户显式批准和后续 reviewed decision。
- “P1 access plan 可启动 Phase 7c / DataHub / runner work”不成立；Phase 7c 仍需单独 schema-first implementation-design slice。

**下一步注意事项**:

1. Claude 应审查本轮 uncommitted schema / JSON / test / routing 变更；重点看 scope locks 是否足以防 provider access 和 Phase 7c 误读。
2. 如果审查 Pass 并提交，下一条 `执行` 应先建立 A-share `minimal_data_burst` preregistration artifact，再做 research-only falsification。
3. 如用户想推进 provider sample / trial / paid access，必须先给出 cost ceiling、access path、license / storage / retention 边界，并仍走单独 reviewed decision。

## 2026-05-31 追加：A-share minimal-data burst preregistration artifact

**改了什么**:

- 新增 `schemas/research_preregistration.schema.json`，作为 single frozen research test preregistration contract。
- 新增 `research/README.md` 与 `research/preregistrations/a_share_minimal_data_burst_20260531.json`，把 A-share `minimal_data_burst` 的首刀 alpha-validation 固定为一个 research-only test：20240131-20251231 月度 A-short generated cohorts、CSI1000 primary benchmark、5 trading days、T+1 open 到 T+5 close、固定 EOD trigger、固定 pass/fail criteria、`test_budget = 1`。
- 新增 `tests/schema/test_research_preregistration_schema.py`，验证 schema / artifact、alpha audit hypothesisRegistration 形状复用、production / provider / Phase 7c scope locks、single frozen test budget、evidence_report ref linkage、singleton ledger trigger 和 fishing mutation reject。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/provider_evidence_drift_monitor.md` 的 routing / current-state wording。

**为什么改**:

- 上一轮已确认 P1 access-decision / sample-validation plan 收口后，下一条 alpha-validation 刀应转向 A-share `minimal_data_burst`，且必须先 preregister。
- 该 artifact 是执行锁，不是研究结果：它防止后续 LLM 在第一次 burst research 中扫参数、扫 benchmark、扫 holding period 或把 CSI300 diagnostic 当成 rescue。
- 本轮保持边界：不跑 research、不改 runner、不抓 provider data、不进 production、不声称 ship-gate evidence。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- 最终验证结果记录在同日 Codex SESSION_LOG entry。

**失效旧结论**:

- “下一条 `执行` 应先建立 A-share `minimal_data_burst` preregistration artifact”已完成；下一条 `执行` 才能运行该 frozen research-only falsification。
- “单一 research experiment 可以在首刀内扫 threshold / rank cap / benchmark / holding period 而不建 ledger”不成立；当前 schema / artifact 锁定 `test_budget = 1`。
- “Preregistration 需要修改 `evidence_report.schema.json` 才能被引用”不成立；后续 evidence report 使用现有 `research_experiment_log.hypothesis_registration_ref` 指回该 artifact。

**下一步注意事项**:

1. Claude 应审查本轮 uncommitted schema / artifact / test / routing 变更；重点看 frozen test 是否过窄或仍留 fishing 自由度。
2. 如果审查 Pass 并提交，下一条 `执行` 应只运行 `research/preregistrations/a_share_minimal_data_burst_20260531.json` 中的 frozen falsification，不得调参。
3. 如运行中发现需要改阈值、rank cap、universe、benchmark、holding period、cost model 或 pass/fail criterion，先停下并创建 singleton program-level test-budget ledger。

## 2026-05-31 追加：alpha measurement-basis lock and burst prereg pause

**改了什么**:

- 更新 `docs/CURRENT.md` 和 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`，把下一刀从“运行 A-share minimal-data burst frozen falsification”反转为“先做 alpha measurement integrity / same-anchor benchmark excess correction”。
- 将 `research/preregistrations/a_share_minimal_data_burst_20260531.json` 标记为 `BLOCKED_DO_NOT_RUN`，并在 `research/README.md`、`docs/burst_lane_spec.md`、`docs/provider_evidence_drift_monitor.md`、`docs/strategy_design_synthesis.md`、`AGENTS.md` 和 P1 access plan next_steps 中同步路由。
- 增加 schema regression：当前 prereg 必须含 `BLOCKED_DO_NOT_RUN`、`measurement-basis issue`、`corrected-basis supersession`；P1 access plan 必须把 next alpha slice 指向 measurement integrity，而不是直接运行旧 prereg。
- 修复轮接受 O1：给 4 份 `result/a_short/backtest/Phase2_rank_backtest_findings_*.md` 加 caveat 头，明确所有 benchmark excess surface 在 corrected-basis revalidation 前均为 contaminated / uncorrected。
- 修复轮 O2 accept with modification：不在本轮 bump schema，但在行动指南中锁定未来 runner / automated research command 不能只依赖人读文字 marker，必须显式 reject `BLOCKED_DO_NOT_RUN` 或采用结构化 execution-status schema bump。
- 修复轮 R1：明确当前 A-share CSI1000 / CSI300 benchmark open 可经 Tushare `index_daily` 取得；下一刀必须扩展 benchmark materializer / forward-daily benchmark fetch 取 open，close-to-close 对当前 A-share corrected revalidation 不是可接受 fallback。

**为什么改**:

- 全系统漏洞审查指出旧 5d `excess_csi1000` 线索和当前 burst prereg 存在入场锚点不对称风险：个股使用 T+1 open 语义，而 benchmark 使用 close basis。该混合口径不得支持 promotion-relevant alpha / research-continuation / ship-gate evidence。
- 旧 5d clue 不能直接判定为假，但必须按 measurement-contaminated / uncorrected 处理，直到 same-anchor corrected revalidation 证明不是 artifact。
- 修正只允许改变 benchmark / entry-anchor basis；阈值、universe、holding period、ranking cap、cost model、criteria、`test_budget=1` 不得借机变化，否则必须先建 singleton program-level ledger。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_research_preregistration_schema`: 11 tests passed.
- `tests.schema.test_provider_p1_access_decision_plan_schema`: 8 tests passed.
- `python -m unittest discover -s tests/schema -v`: 120 tests passed.
- `git diff --check`: passed; only normal LF/CRLF working-copy warnings.
- `docs/CURRENT.md` authoritative line count = 146, still under the 150-line snapshot target.
- `rg -n "Measurement caveat \(2026-05-31\)" result\a_short\backtest`: 4 findings files matched.

**失效旧结论**:

- “提交后下一刀 = 运行 `research/preregistrations/a_share_minimal_data_burst_20260531.json`”失效；该 artifact 现在是 `BLOCKED_DO_NOT_RUN`。
- “5d `excess_csi1000 t=+2.88` 是当前唯一显著正 alpha 线索”降级为未校正、疑似 measurement-basis artifact 的线索；corrected basis 重跑前不得当作 validated alpha。
- “benchmark close basis 可与 stock T+1 open entry 混用来支持 research continuation”失效；promotion-relevant evidence 必须同 entry anchor。
- “旧 Phase2 findings 文档中的任一 benchmark excess 表格可继续独立引用”失效；全部 excess surface 需等 corrected basis 重跑后再恢复引用。

**下一步注意事项**:

1. Claude 审查应重点核对所有 current route 是否禁止运行旧 prereg，并确认没有趁 measurement fix 改阈值、universe、holding period、criteria 或 `test_budget`。
2. 如果审查 Pass 并提交，下一条 `执行` 应修复 / 引入 same-anchor benchmark excess：stock T+1 open 与 benchmark T+1 open 到同一 exit close；当前 A-share CSI1000 / CSI300 应扩展 Tushare `index_daily` benchmark materializer / forward-daily benchmark fetch 取 open，不能用 close-to-close fallback。
3. corrected revalidation 只能是 corrected 5d CSI1000 primary；10d / 20d 只能 diagnostic，不得做参数、variant、benchmark、holding-period search。

## 2026-05-31 追加：system risk register and enforcement lock

**改了什么**:

- 新增 `docs/system_risk_register.md`，作为 data / PIT / schema / execution / security / cross-LLM process risks 的 durable queue。
- 更新 `AGENTS.md` 启动必读和 AI 协作守则，要求 material audit finding 必须同轮修复或进入 risk register，open P0 不得被普通 roadmap work 绕过。
- 更新 `docs/AI_REVIEW_PROTOCOL.md`，把 risk register 加入 Codex / Claude required reading、`执行` / `审查` / `修复` steps、review clean-Pass 条件和 documentation rules。
- 更新 `docs/README.md` routing table 与 `docs/CURRENT.md` 当前 P0，把下一步从单一 measurement-basis code fix 调整为 risk-register hot queue：先 `SR-EXEC-001` weekly historical `-AsOf` PIT interlock，再 `SR-MEASURE-001` same-anchor benchmark excess。
- 将两轮系统审查的 open items 进入 register：measurement basis、weekly PIT interlock、PIT contract、schema validation、Claude local permissions、execution-backtest risk-control limitations、threshold governance、US-short reference prompt hygiene、web-news prompt injection、data canary overread、deterministic report wall-clock state、audit#1 revalidation queue。

**为什么改**:

- 用户接受了“先建 tracked vulnerability / risk ledger”的判断。此前审查发现只存在于 chat 或 SESSION_LOG 过程文本里，后续 LLM 读取 CURRENT / README 无法看到完整 open-risk queue。
- Measurement-basis lock 只捕获了 benchmark-entry-basis 问题，不足以约束后续 LLM 对 PIT、schema、weekly operation、security 和 execution evidence 风险的执行优先级。
- 本轮不直接修业务代码，是为了先建立强制路由和 review gate，防止后续继续发现蒸发或绕开 open P0。

**验证命令**:

```powershell
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
rg -n "system_risk_register|SR-EXEC-001|SR-MEASURE-001" AGENTS.md docs\README.md docs\CURRENT.md docs\AI_REVIEW_PROTOCOL.md docs\system_risk_register.md
```

**验证结果**:

- 待本轮 Codex SESSION_LOG entry 记录最终验证结果。

**失效旧结论**:

- “下一条 `执行` 只需直接做 same-anchor benchmark excess code fix”被收紧：same-anchor 仍是 P0，但在 risk register hot queue 中排在 `SR-EXEC-001` weekly historical `-AsOf` PIT interlock 之后，除非用户显式 override。
- “全系统审查发现可只放在 chat / review prose / SESSION_LOG”失效；material finding 必须修复或进入 `docs/system_risk_register.md`。

**下一步注意事项**:

1. Claude 审查本轮时必须确认 risk register 是否覆盖已接受的 audit#1 / audit#2 open findings，并检查 protocol 是否足以让未来 `执行` / `审查` 强制读取该 register。
2. 如果审查 Pass 并提交，下一条 `执行` 默认按 `docs/system_risk_register.md` hot queue 修 `SR-EXEC-001`：weekly screening historical `-AsOf` PIT interlock / official-output overwrite guard。
3. `SR-MEASURE-001` same-anchor benchmark excess 仍然阻断 A-share burst prereg；旧 prereg 继续 `BLOCKED_DO_NOT_RUN`，不得因本 register slice 被解锁。

## 2026-05-31 追加：SR-MEASURE-001 same-anchor benchmark excess

**改了什么**:

- 更新 `runners/backtest_rank.py`：forward-daily benchmark fetch 请求 / 缓存 / 校验 CSI1000 与 CSI300 的 `trade_date,open,close`；close-only benchmark cache 不再复用；benchmark excess 改为 benchmark T+1 entry-date open 到同一 exit-date close。
- 更新 `runners/materialize_benchmark_monthly_returns_tushare.py`：`index_daily` 请求 `open,close`，月度兼容 benchmark return 改为 first open 到 last close，并在 metadata limitations 中说明 per-candidate corrected revalidation 使用 `backtest_rank.py` 的同锚点口径。
- 新增 `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`，作为 blocked 原 prereg 的 corrected-basis supersession；只改 benchmark / entry-anchor basis，阈值、universe、holding period、criteria、`test_budget = 1` 均冻结。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/burst_lane_spec.md`、`docs/provider_evidence_drift_monitor.md`、`docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json`、`docs/strategy_design_synthesis.md`、`docs/system_risk_register.md`、`research/README.md` 的 routing / current-state wording。
- 更新 tests：`tests/test_backtest_rank_phase3.py` 锁定同锚点 excess 与 close-only fallback reject；`tests/execution/test_materialize_benchmark_monthly_returns_tushare.py` 锁定 index open 字段与 first-open / last-close；`tests/schema/test_research_preregistration_schema.py` 锁定 corrected supersession 只改 measurement basis；`tests/schema/test_provider_p1_access_decision_plan_schema.py` 同步 next alpha route。

**为什么改**:

- 旧 5d `excess_csi1000` clue 与 blocked prereg 的 benchmark leg 使用 close basis，不能和 stock T+1 open entry 混合作为 promotion-relevant alpha / research-continuation evidence。
- 当前 A-share CSI1000 / CSI300 open 可由 Tushare `index_daily` 获取；因此正确修法是同锚点 benchmark T+1 open 到同一 exit close，而不是 close-to-close fallback。
- corrected supersession 必须只修测量 basis；任何顺手改阈值、宇宙、持有期、criteria 或 budget 都会变成 fishing 并触发 singleton program-level ledger。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_backtest_rank_phase3 tests.execution.test_materialize_benchmark_monthly_returns_tushare -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.test_backtest_rank_phase3` + `tests.execution.test_materialize_benchmark_monthly_returns_tushare`: 12 tests passed.
- `tests.schema.test_research_preregistration_schema`: 13 tests passed.
- `tests.schema.test_provider_p1_access_decision_plan_schema`: 8 tests passed.
- `python -m unittest discover -s tests/schema -v`: 122 tests passed.
- `git diff --check`: passed; only normal LF/CRLF working-copy warnings.
- `docs/CURRENT.md` authoritative line count = 148, still under the 150-line snapshot target.

**失效旧结论**:

- “SR-MEASURE-001 仍 open / hot queue 第一项”失效；本 reviewed change set 关闭后，risk register 下一项是 `SR-SEC-001` P1。
- “必须先创建 corrected-basis supersession 才能运行 burst falsification”已完成；下一条 alpha-validation `执行` 可在 review + commit 后运行 corrected artifact。
- “旧 prereg 可直接运行”仍失效；`research/preregistrations/a_share_minimal_data_burst_20260531.json` 继续 `BLOCKED_DO_NOT_RUN`。

**下一步注意事项**:

1. Claude 审查应重点核对 `backtest_rank.py` 是否真正用 benchmark entry open 到 exit close，且 close-only cached benchmark 不会被复用。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 应只运行 `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json`，并输出 research-only evidence report；不进 production、不声称 ship-gate evidence。
3. 10d / 20d 只允许 diagnostic；不得做 threshold / variant / benchmark / holding-period / rank-cap / cost search。

## 2026-05-31 追加：SR-EXEC-001 weekly historical PIT interlock

**改了什么**:

- 更新 `runners/weekly_screening.ps1`：新增 `-L3Mode pit|today|neutralize` 和 `-AllowHistoricalOverwrite`；当 `-AsOf` 不等于当前运行日期时，必须显式选择 `pit` 或 `neutralize`，禁止 `today`。
- `-L3Mode pit` 由 wrapper 自动传 `--l3-pit-strict` 给 `A-EGS/egs_main.py`，避免 PIT 缺快照时静默 fallback。
- 历史 `-AsOf` 若会覆盖 `result/a_short/<AsOf>/` 或 `A-EGS/Result/egs_{tier1,full}_<AsOf>` / xlsx 既有官方输出，默认拒绝；只有显式 `-AllowHistoricalOverwrite` 才继续。
- 新增 `tests/phase6/test_weekly_screening_guardrails.py`，覆盖缺失 L3 mode、历史 `today` 模式拒绝、既有官方输出 overwrite guard 和 PIT strict 参数。
- 更新 `docs/system_risk_register.md` / `docs/CURRENT.md` / `runners/README.md` 路由：`SR-EXEC-001` 关闭，下一 open P0 转为 `SR-MEASURE-001`。

**为什么改**:

- `SR-EXEC-001` 的风险不是 `egs_main.py` 的 PIT lookup 本身，而是 weekly wrapper 在 historical `-AsOf` 官方输出路径上默认使用 `--l3-mode=today`，并可能覆盖正式结果目录。
- 修在 wrapper 层最小：不动 `A-EGS/egs_main.py` 筛选逻辑、不改 provider / DataHub、不运行旧 burst prereg，也不改变 canary / tracker 的旁路退出码语义。
- 对 historical replay，用户必须在“严格 PIT 快照”与“L3 neutralize”之间显式选择，不能再由默认 today mode 混入当前概念数据。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.phase6.test_weekly_screening_guardrails -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/phase6 -v
$script = Get-Content -Raw runners\weekly_screening.ps1; $null = [scriptblock]::Create($script); Write-Output 'weekly_screening scriptblock ok'
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.phase6.test_weekly_screening_guardrails`: 4 tests passed.
- `python -m unittest discover -s tests/phase6 -v`: 17 tests passed.
- PowerShell scriptblock parse: `weekly_screening scriptblock ok`.
- `git diff --check`: passed；仅出现 touched files 的 LF/CRLF working-copy warning。
- `docs/CURRENT.md` authoritative line count = 147，低于 150-line snapshot target。

**失效旧结论**:

- “`weekly_screening.ps1 -AsOf <historical>` 可不指定 L3 mode”失效；historical official-output run 必须显式 `-L3Mode pit` 或 `-L3Mode neutralize`。
- “historical weekly run 可以默认覆盖 `result/a_short/<AsOf>/` 或 `A-EGS/Result/egs_*_<AsOf>`”失效；既有官方输出默认拒绝 overwrite。
- “risk register hot queue 第一项仍是 `SR-EXEC-001`”失效；本 reviewed change set 关闭后，下一 open P0 是 `SR-MEASURE-001` same-anchor benchmark excess。

**下一步注意事项**:

1. Claude 审查应重点确认 historical guard 是否在调用 `egs_main.py` 前触发，且没有引入 provider / DataHub / burst research scope。
2. 如果审查 Pass 并提交，下一条 `执行` 默认进入 `SR-MEASURE-001`：same-anchor benchmark excess（CSI1000 / CSI300 benchmark T+1 open 到同一 exit close）。
3. 旧 A-share burst prereg 仍然 `BLOCKED_DO_NOT_RUN`，不得因 weekly wrapper guard 关闭而运行。

## 2026-05-31 追加：confirmed bug audit register split

**改了什么**:

- 更新 `docs/system_risk_register.md` hot queue：corrected-basis 5d revalidation 只有在使用冻结 historical generated cohorts 且不重新跑 `A-EGS/egs_main.py` 时，才不受本轮新增 bug 条目阻塞。
- 将确认后的 bug audit 拆成具体条目：`SR-DATA-001`、`SR-OPS-002`、`SR-OPS-003`、`SR-DATA-002`、`SR-EXEC-003`、`SR-EXEC-004`、`SR-EXEC-005`、`SR-CAP-001`、`SR-OPS-004`、`SR-OPS-005`、`SR-OPS-006`、`SR-RANK-001`。
- 将原汇总项 `SR-EXEC-002` 和 `SR-OPS-001` 标为 `superseded`，避免后续 LLM 误读为已修复，也避免继续面对 vague needs-revalidation bucket。
- 更新 `docs/CURRENT.md`，明确本轮是 docs-only register split，不包含代码修复；corrected 5d 重验不得重新生成 cohort。

**为什么改**:

- 用户接受了对 bug 审查的收敛判断：大部分 finding 成立，但 B3 应写成 missing ceiling validation / clamp，N3 应写成 low / needs-revalidation，B6 应标注 partial daily fetch 低频触发而非持续污染。
- 本项目要求 material audit finding 不能只留在 chat；先进入 durable risk register，后续再按路径和优先级改代码。
- 这批 bug 不阻塞 corrected 5d 的唯一前提是使用已冻结 cohorts；若重新跑筛选器，B6 / B5 会重新进入污染路径。

**验证命令**:

```powershell
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
rg -n "SR-DATA-001|SR-OPS-002|SR-OPS-003|SR-DATA-002|SR-EXEC-003|SR-EXEC-004|SR-EXEC-005|SR-CAP-001|SR-OPS-004|SR-OPS-005|SR-OPS-006|SR-RANK-001|frozen historical generated cohorts|confirmed bug audit" docs\system_risk_register.md docs\CURRENT.md
```

**验证结果**:

- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` authoritative line count = 147，低于 150-line snapshot target。
- `rg` matched all intended new risk IDs and corrected 5d frozen-cohort routing.

**失效旧结论**:

- “`SR-EXEC-002` / `SR-OPS-001` 仍只是待复核汇总项”失效；本轮已拆成具体风险条目，原汇总项仅为 `superseded`，不是已修复。
- “新增 bug 会整体阻塞 corrected 5d 重验”失效；只有重新跑 `A-EGS/egs_main.py` / 生成新 cohort 时才会触发 B6 / B5 污染路径。
- “B6 可写成正在每周污染”失效；登记口径为 real wrong-output path with partial `pro.daily` trigger，频率未证、预计低频。

**下一步注意事项**:

1. Claude 审查应重点核对新增 risk IDs、severity、trigger condition 和 blocking path 是否忠实反映 bug audit 收敛结论。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 可运行 corrected-basis 5d revalidation，但必须使用冻结 historical generated cohorts，不得重新跑 `A-EGS/egs_main.py`。
3. 如果在 corrected 5d 之前必须跑新的 weekly official capture / forward tracker official use，则需先修 `SR-DATA-001` / `SR-OPS-002` / `SR-OPS-003` 或显式暂停该路径。

## 2026-05-31 追加：A-share burst zero-event preflight and ledger gate

**改了什么**:

- 新增 `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json`，记录 corrected-basis preregistration 在冻结 2024-2025 cohorts 上预检失败：`valid_signal_events = 0`。
- 新增 `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json`，把该 preflight 计为第一条 spent test，并锁定后续 redesigned A-share burst 测试必须先进入 singleton ledger + 新 reviewed preregistration。
- 更新 `docs/system_risk_register.md`：新增 `SR-RESEARCH-001`（当前 corrected prereg zero valid events）和 `SR-DATA-003`（未来非零事件 outcome / excess run 仍需要 benchmark open input）。
- 更新 active 路由文档和 preregistration artifacts：不再允许跑当前 corrected outcome / benchmark-excess；下一条 A-share burst alpha action 改为 ledger-gated redesign。
- 更新 schema tests，锁定 preflight counts、ledger spend、access-plan next-step routing 和 corrected prereg 的 zero-event 状态。

**为什么改**:

- 用户提供的二次阻塞审查成立：当前 corrected prereg 的 unchanged steady Tier1 universe + frozen trigger 在 24 个 cohort、305 个 Tier1 rows 中没有任何有效事件，直接运行 outcome / excess 只会得到 underpowered 空结果。
- 这不是 same-anchor measurement basis 问题，而是 burst trigger 被套在 steady watchlist universe 上的结构性测试设计问题；因此不能用“只改 basis”的 supersession 继续推进。
- 重新定义 burst universe / trigger 属于新的 promotion-relevant degree of freedom，必须消耗 program-level test-budget ledger，而不是静默改 prereg 后继续跑。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_research_preregistration_schema`: 15 tests passed.
- `tests.schema.test_provider_p1_access_decision_plan_schema`: 8 tests passed.
- `python -m unittest discover -s tests/schema -v`: 124 tests passed.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` authoritative line count = 148，低于 150-line snapshot target。

**失效旧结论**:

- “提交后下一刀可运行 corrected-basis 5d revalidation”失效；当前 corrected prereg 在 preflight 已经 `valid_signal_events = 0`，不得运行 outcome / excess。
- “corrected 5d 的唯一阻塞是 benchmark open 缺失”失效；benchmark open 仍是未来非零事件 outcome run 的 P1 前置，但在 zero-event 阻塞解决前只是 secondary。
- “现有 steady Tier1 frozen cohorts 可承载 minimal-data burst falsification”失效；它们 L3-clean，但不能检验 burst trigger。

**下一步注意事项**:

1. Claude 审查应重点核对 preflight counts 是否来自冻结 cohorts、是否没有 outcome / benchmark-excess / provider fetch，以及 ledger 是否正确把该 preflight 记为 spent test。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 不是跑 corrected artifact，而是创建 ledger-gated redesigned A-share burst preregistration。
3. 任何未来 redesigned test 必须先明确 universe / trigger / benchmark-open handling，并写入 ledger planned test；不得用 Tier2 rows、relaxed entry flags、changed `is_breakout` logic 或 diagnostic benchmark rescue 当前 artifact。

## 2026-05-31 追加：preflight / ledger schema-first repair

**改了什么**:

- 新增 `schemas/research_preflight_result.schema.json`，锁定 preflight result 的 required fields、no outcome / benchmark-excess / provider-fetch / production / ship-gate 边界、summary counts 和 evaluation result 结构。
- 新增 `schemas/program_test_budget_ledger.schema.json`，锁定 singleton program-level ledger、spent tests、future planned_tests 结构、review / user-approval gate 和 no-silent-rescue 边界。
- 更新 `tests/schema/test_research_preregistration_schema.py`：验证两个新 schema 与现有 artifacts，并新增 scope-creep / cardinality / review-gate relaxation 的 reject 测试。
- 更新 `docs/README.md`、`docs/CURRENT.md`、`research/README.md` 路由，把两个新 schema 纳入 research owner 文件。

**为什么改**:

- Claude O1 指出 `research_preflight_result` 与 `program_test_budget_ledger` 已声明 `schema_name` / `schema_version`，但没有 schema 文件；这与项目 schema-first 纪律不一致。
- ledger 后续会被 append planned tests / spend log，不能只靠当前实例逐值测试，否则下一次 redesign 时结构约束会漂移。
- 同时给 preflight result 建 schema，避免留下另一个正式 artifact 类型无 schema 的缺口。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_research_preregistration_schema`: 19 tests passed.
- `python -m unittest discover -s tests/schema -v`: 128 tests passed.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` authoritative line count = 148，低于 150-line snapshot target。

**失效旧结论**:

- “preflight / ledger 只有实例级测试、没有 schema contract”失效；两个 artifact 类型现在均有 v1.0.0 schema。

**下一步注意事项**:

1. Claude 复审应重点核对两个 schema 是否既锁住当前 no-silent-rescue / no-provider / no-production 边界，又允许未来 reviewed planned_tests append。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 仍是 ledger-gated redesigned A-share burst preregistration，不是运行当前 corrected artifact。

## 2026-05-31 追加：preflight pct max schema domain correction

**改了什么**:

- 更新 `schemas/research_preflight_result.schema.json`：`summary_counts.max_pct_5d_all_rows` 与 `max_pct_5d_tier1` 从 `nonNegativeNumber` 改为普通 `number`。
- 更新 `tests/schema/test_research_preregistration_schema.py`：新增测试证明 negative `max_pct_5d_*` 可通过，同时 `max_amount_ratio_*` 仍保持非负约束。

**为什么改**:

- Claude O1 指出 5 日收益的最大值在全员下跌窗口中可能为负；把 `max_pct_5d_*` 设为非负会在未来 redesigned burst preflight 中产生 false validation failure。
- 金额比值仍应保持非负，因此只放宽 pct return 字段，不放宽 amount ratio 字段。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests/schema -v
git diff --check
[System.IO.File]::ReadAllLines((Resolve-Path 'docs\CURRENT.md')).Length
```

**验证结果**:

- `tests.schema.test_research_preregistration_schema`: 20 tests passed.
- `python -m unittest discover -s tests/schema -v`: 129 tests passed.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` authoritative line count = 148，低于 150-line snapshot target。

**失效旧结论**:

- “`max_pct_5d_*` 可按非负数建模”失效；pct return 字段必须允许负值。

**下一步注意事项**:

1. Claude 复审应确认只放宽了 pct return max 字段，未放宽 amount ratio / execution boundary / ledger review gate。
2. 如果审查 Pass 并提交，下一条 alpha-validation `执行` 仍是 ledger-gated redesigned A-share burst preregistration。

## 2026-06-02 追加：US EGS small sample validation approval boundary

**改了什么**:

- 新增 `schemas/provider_p1_sample_validation_access_approval.schema.json`，把用户批准的 US EGS 小样本验证边界固化为 schema-first artifact：$0、现有 FMP key、SEC EDGAR public API、AAPL / MSFT only、no `yfinance`、no full-market、no paid upgrade、no provider selection、no adapter / DataHub / runner / Phase 7c。
- 新增 `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json`，记录 2026-06-02 用户批准内容与后续 sample-validation packet 的 storage / secret 边界。
- `.gitignore` 新增 `provider_samples/`，确保后续 raw vendor / public API sample rows 只能作为本地样本保存，不进入 git；tracked summary 仍可单独提交。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`AGENTS.md`、`docs/ALPHA_VALIDATION_ACTION_GUIDE.md`、`docs/CURRENT.md`、`docs/README.md`、`docs/datahub_design.md`、`docs/provider_priority_benchmark_contract.md`、`docs/provider_data_requirements_audit.md`、`docs/evidence_feasibility_controls.md`、`docs/evidence_report_schema_contract.md`、`docs/strategy_design_synthesis.md`，把旧的“sample/data fetch 完全未授权”改成“只授权后续 reviewed AAPL / MSFT 小样本验证，其余仍阻断”。
- 新增 `tests/schema/test_provider_p1_sample_validation_access_approval_schema.py`，验证 approval artifact、原 access plan 仍非授权、schema const locks、next-step 不授权 provider selection / Phase 7c。

**为什么改**:

- 用户明确批准：FMP 使用当前账号 / API key，预算上限 $0；允许 SEC EDGAR 公共 API；允许本地保存少量样本和校验结果；只允许抓少数股票小样本；不允许全市场下载、不允许付费升级。
- 需要把 chat approval 转成 durable repo artifact，避免后续 LLM 继续认为 sample validation 完全未授权，或反向误读成可做 provider selection / broad data fetch / Phase 7c。
- 旧 access plan 保持 plan-only；新的 approval artifact 只解决其中最窄的一条 access boundary，不改变 P1 readiness matrix 的 partial / blocked 结论。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_sample_validation_access_approval_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_access_decision_plan_schema tests.schema.test_provider_p1_sample_validation_access_approval_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests\schema -v
git diff --check
git check-ignore -v provider_samples/us_egs_sample_validation_20260602/raw.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=[...]; [Path(f).read_text(encoding='utf-8') for f in files]; print('utf8 ok'); print('CURRENT lines', len(Path('docs/CURRENT.md').read_text(encoding='utf-8').splitlines()))"
```

**验证结果**:

- `tests.schema.test_provider_p1_sample_validation_access_approval_schema`: 7 tests ran, 4 passed, 3 skipped because this bundled interpreter lacks `jsonschema`.
- `tests.schema.test_provider_p1_access_decision_plan_schema tests.schema.test_provider_p1_sample_validation_access_approval_schema`: 15 tests ran, 9 passed, 6 skipped because this bundled interpreter lacks `jsonschema`.
- `python -m unittest discover -s tests\schema -v`: failed for environment dependency, not this slice; 5 existing `tests/schema/test_analysis_input_contract.py` tests error because `engine/data/analysis_input_contract.py` requires `jsonschema`, and the available Python runtime does not have it installed. Many schema-validation tests also skip for the same missing dependency.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- UTF-8 read check passed；`docs/CURRENT.md` authoritative line count = 149，低于 150-line snapshot target。
- `git check-ignore -v provider_samples/us_egs_sample_validation_20260602/raw.json`: matched `.gitignore:50:provider_samples/`，raw provider sample path is ignored.

**失效旧结论**:

- “US EGS sample validation 完全没有用户授权”失效；现在只对 AAPL / MSFT、现有 FMP key、SEC EDGAR public API、$0 小样本验证授权。
- “P1 access plan 本身可授权 sample fetch / provider access”仍不成立；计划文件仍是 plan-only，授权只存在于新的 2026-06-02 approval artifact。
- “小样本批准可进入 provider selection / full-market / DataHub / Phase 7c”不成立；这些仍需单独 explicit approval + reviewed decision。

**下一步注意事项**:

1. Claude 复审应重点核对 approval schema / artifact 是否只解锁 AAPL / MSFT 小样本验证，且没有把 `yfinance`、paid access、full-market、provider selection、adapter、DataHub、runner 或 Phase 7c 打开。
2. 如果审查 Pass 并提交，下一条 `执行` 可以实现 narrow sample-validation packet：只检查 `FMP_API_KEY` / `SEC_USER_AGENT` 存在且不打印 secrets，只抓 AAPL / MSFT 的 FMP + SEC EDGAR small samples，raw rows 写到 gitignored `provider_samples/us_egs_sample_validation_20260602/`，tracked summary 不含 secrets 或完整 raw rows。
3. 由于当前可用 Python runtime 缺 `jsonschema`，若复审需要完整 Draft-07 validation，应先在合规环境安装项目 `requirements.txt` 依赖或用已有含 `jsonschema` 的解释器重跑 schema tests。

## 2026-06-02 追加：US EGS AAPL/MSFT sample-validation result

**改了什么**:

- 新增 `runners/us_egs_sample_validation.py`，实现已批准的窄 sample-validation packet：运行时校验 approval artifact、检查 `FMP_API_KEY` / `SEC_USER_AGENT` 存在但不打印值、只抓 AAPL / MSFT、raw payload 只写入 gitignored `provider_samples/us_egs_sample_validation_20260602/`、tracked summary 不含 raw rows 或 secrets。
- 新增 `schemas/provider_p1_us_egs_sample_validation_summary.schema.json`，锁定 summary 的 scope：no provider selection、no full-market、no `yfinance`、no paid access、no DataHub、no production runner consumption、no Phase 7c、no ship-gate claim。
- 真实执行 approved small sample，新增 `docs/provider_evidence_p1_us_sample_validation_summary_20260602.json`。结果为 `completed_with_endpoint_errors`：17 calls within budget；SEC EDGAR company tickers / submissions / companyfacts 对 AAPL 和 MSFT 成功；FMP v3 endpoint families 对两只股票均返回 HTTP 403 legacy-endpoint errors。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`docs/CURRENT.md`、`docs/README.md`，把状态从“待执行小样本”改为“SEC 样本通过，FMP v3 样本未验证通过；下一步需审查 current FMP endpoint mapping 或 FMP account/API boundary”。
- 新增 `tests/provider/test_us_egs_sample_validation.py` 与 `tests/schema/test_provider_p1_us_egs_sample_validation_summary_schema.py`，覆盖 fake-client 小样本、secret 不落 summary、raw root 必须在 ignored `provider_samples/`、SEC 不请求压缩 payload、schema scope locks。

**为什么改**:

- 上一轮 approval artifact 已经 reviewed / committed，只解锁 AAPL / MSFT 小样本验证；本轮把批准边界落实为可复跑 runner + schema + tracked no-secret summary。
- 真实小样本验证发现 FMP v3 legacy endpoint 问题，必须 durable 记录，避免后续 LLM 误把“已有 FMP key”当成“FMP 已验证可用”。
- SEC EDGAR 样本成功只证明公共 filing audit source 的小样本可访问；不证明 FMP、coverage、license、PIT、fallback、DataHub 或 production readiness。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe runners\us_egs_sample_validation.py
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.provider.test_us_egs_sample_validation -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema tests.schema.test_provider_p1_sample_validation_access_approval_schema -v
git diff --check
(Get-Content -Path docs\CURRENT.md -Encoding UTF8).Count
git check-ignore -v provider_samples\us_egs_sample_validation_20260602\raw\financial_modeling_prep\AAPL\income_statement.json
```

**验证结果**:

- `runners/us_egs_sample_validation.py`: wrote `docs/provider_evidence_p1_us_sample_validation_summary_20260602.json`; `validation_status = completed_with_endpoint_errors`; `actual_total_endpoint_calls = 17`; `secrets_logged = false`。
- `tests.provider.test_us_egs_sample_validation`: 5 tests passed.
- Combined summary / approval schema targeted tests: 12 tests ran, 5 passed, 7 skipped because this bundled interpreter lacks `jsonschema`; non-jsonschema scope-lock tests passed.
- `git diff --check`: passed；仅有正常 LF/CRLF working-copy warnings。
- `docs/CURRENT.md` line count = 149。
- `git check-ignore`: raw sample path matched `.gitignore:50:provider_samples/`。

**失效旧结论**:

- “AAPL / MSFT sample-validation packet 尚未执行”失效；packet 已执行并生成 tracked no-secret summary。
- “FMP existing API key 已可直接作为 US EGS 主源”不能成立；本轮 sampled FMP v3 endpoint families 均 403，FMP 未被此 packet 验证通过。
- “SEC EDGAR 小样本可访问意味着 provider / DataHub / Phase 7c 可推进”不成立；SEC 成功只支持 fundamentals audit source 的小样本可访问。

**下一步注意事项**:

1. Claude 复审应重点核对 summary 是否没有 raw rows / secrets、raw payload 是否保持 ignored、FMP 403 是否被正确降级为 blocker 而不是失败后 silent retry 或 provider selection。
2. 如果审查 Pass 并提交，下一条 `执行` 的自然候选是 current FMP endpoint mapping / account boundary review；不应直接扩大到 `yfinance`、full-market fetch、paid upgrade、DataHub、production runner consumption 或 Phase 7c。
3. 若要完整 Draft-07 validation，应在含 `jsonschema` 的环境中重跑 summary schema test；当前 bundled Python 仍缺该依赖。

## 2026-06-02 追加：US EGS FMP current endpoint mapping review

**改了什么**:

- 新增 `schemas/provider_p1_fmp_endpoint_mapping_review.schema.json`，锁定 FMP current-endpoint mapping review 的 docs-only 边界：不 live retry、不抓数据、不选 provider、不用 `yfinance`、不 full-market、不 paid upgrade、不建 adapter / DataHub、不改 production runner、不授权 Phase 7c / ship-gate。
- 新增 `docs/provider_evidence_p1_us_fmp_current_endpoint_mapping_review_20260602.json`，基于 FMP 官方 docs 把上一轮失败的 sampled v3 endpoint families 映射到 stable endpoint candidates：profile、income statement、balance sheet、cash flow、key metrics、historical EOD full。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`docs/CURRENT.md`、`docs/README.md`，把状态从“需要 mapping review”改为“stable endpoint candidates 已 docs-only 映射；下一步可做同范围 stable retry，但仍需 review / no broad deployment”。
- 新增 `tests/schema/test_provider_p1_fmp_endpoint_mapping_review_schema.py`，验证 scope locks、六个 endpoint family 覆盖、stable URL 前缀、no retry / no provider selection / no yfinance / no Phase 7c。

**为什么改**:

- 上一轮真实 AAPL / MSFT sample 证明 SEC EDGAR 可访问，但 FMP v3 endpoint families 全部 403。Claude review 指出这是真实 endpoint/account 边界，不是 runner bug。
- 直接改 runner 并 live retry 会把“mapping review”和“数据抓取”混成一刀；本轮只先固化 current stable endpoint candidates 和 retry gate，避免 silent retry / scope creep。
- FMP 官方 docs 当前使用 `https://financialmodelingprep.com/stable/` base URL；旧 `/api/v3/...` 样本不能再被当作当前 endpoint mapping。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema -v
git diff --check
(Get-Content -Path docs\CURRENT.md -Encoding UTF8).Count
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema` ran 6 tests: 3 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope-lock and mapping-coverage tests passed.
- Python313 with `jsonschema`: combined sample-summary + FMP-mapping schema tests ran 11 tests, all passed; the real sample summary and new mapping artifact both validate against their schemas, and scope-creep mutations are rejected.
- `docs/CURRENT.md` line count = 149。
- Full `git diff --check` should be rerun after SESSION_LOG is prepended in the same work round.

**失效旧结论**:

- “FMP endpoint mapping 尚未完成”失效；stable endpoint candidates 已 docs-only mapped。
- “stable endpoint candidates 已 live validated”不成立；本轮没有 FMP live retry，也没有新 data fetch。
- “mapping review 可授权 provider selection / DataHub / Phase 7c”不成立；schema 和 artifact 都显式阻断。

**下一步注意事项**:

1. Claude 复审应核对 mapping artifact 是否只引用官方 docs + tracked sample summary，并没有把 stable candidate 写成 validated provider readiness。
2. 如果审查 Pass 并提交，下一条 `执行` 的自然候选是更新 / parameterize standalone sample-validation runner，用 same-scope AAPL / MSFT stable endpoints 做一次 no-secret retry；不应扩大到 `yfinance`、full-market、paid access、provider selection、DataHub、production runner consumption 或 Phase 7c。
3. 若需要完整 Draft-07 validation，应在含 `jsonschema` 的解释器中重跑新增 schema test。

## 2026-06-02 追加：US EGS FMP stable endpoint retry result

**改了什么**:

- 更新 `runners/us_egs_sample_validation.py`，新增 `--fmp-endpoint-mode stable`，只用已批准的 AAPL / MSFT、现有 FMP key、$0、小样本边界，调用 mapped FMP stable endpoint families；legacy v3 + SEC sample 路径保留。
- 新增 `schemas/provider_p1_fmp_stable_endpoint_retry_summary.schema.json`，锁定 stable retry summary 的 no provider selection、no paid、no `yfinance`、no full-market、no adapter / DataHub、no production runner consumption、no Phase 7c、no ship-gate claim 边界。
- 真实执行 stable retry，新增 `docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json`。结果为 `completed`：12 FMP stable calls within budget；AAPL / MSFT 的 profile、income statement、balance sheet statement、cash-flow statement、key metrics、historical EOD price / volume 均 HTTP 200；summary 不含 secrets 或 request URLs。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`docs/CURRENT.md`、`docs/README.md`，把状态从“stable candidates mapped only”改为“two-symbol stable retry succeeded, but remaining provider blockers stay open”。
- 新增 / 更新测试：`tests/provider/test_us_egs_sample_validation.py` 覆盖 stable fake-client 路径、12-call / no SEC / no yfinance / no secrets / stable field presence；`tests/schema/test_provider_p1_fmp_stable_endpoint_retry_summary_schema.py` 覆盖 schema locks 与真实 summary validation。

**为什么改**:

- 上一轮 mapping review 已经证明旧 `/api/v3` endpoint 不是当前 retry 目标；本轮按 review 后的最小下一刀，把 stable candidate 真正跑一次，验证当前账号 / key 对两只样本股票的 endpoint access 和基本 response shape。
- 这能防止两个错误方向：一是继续误读 v3 403 为 FMP 不可用；二是把 stable docs path 误读成已验证可用。
- 仍然只解决小样本 access / shape；coverage、license / retention、PIT semantics、fallback / incident、provider stability、production readiness 仍不是本轮结论。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.provider.test_us_egs_sample_validation -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fmp_stable_endpoint_retry_summary_schema tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_stable_endpoint_retry_summary_schema tests.schema.test_provider_p1_fmp_endpoint_mapping_review_schema tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe runners\us_egs_sample_validation.py --fmp-endpoint-mode stable
git diff --check
git check-ignore -v provider_samples\us_egs_sample_validation_20260602\fmp_stable_retry\raw\financial_modeling_prep\AAPL\income_statement.json
Select-String -Path docs\provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json -Pattern 'apikey=','Bearer ','SEC_USER_AGENT=' -SimpleMatch
```

**验证结果**:

- Real stable retry wrote `docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json`; `validation_status = completed`; `actual_total_endpoint_calls = 12`; `secrets_logged = false`。
- `tests.provider.test_us_egs_sample_validation`: 7 tests passed.
- Bundled Python targeted schema tests: 16 tests ran, 5 passed, 11 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope-lock tests passed.
- Python313 with `jsonschema`: 16 tests passed, including the real stable retry summary validation and scope-creep rejection.
- `git diff --check`: passed before SESSION_LOG entry; rerun after SESSION_LOG is expected.
- `git check-ignore`: stable raw sample path matched `.gitignore:50:provider_samples/`。
- Secret-pattern check for key-bearing URL / bearer / SEC env syntax returned no matches.

**失效旧结论**:

- “FMP stable endpoint candidates 尚未 live retried”失效；AAPL / MSFT same-scope stable retry 已执行并成功。
- “旧 FMP v3 403 足以判断 FMP 当前账号不可用”不成立；当前 stable endpoint families 对 AAPL / MSFT 返回 HTTP 200。
- “FMP stable retry 成功 = provider selected / production ready / Phase 7c 可开工”不成立；本轮只提供两只股票的小样本 access / response-shape evidence。

**下一步注意事项**:

1. Claude 复审应重点核对 summary 是否没有 raw rows / request URLs / secrets，raw payload 是否保持 ignored，stable runner 是否没有调用 SEC / `yfinance` / TSLA / full-market。
2. `SR-PROVIDER-001` 仍 open；后续若要推进 provider work，必须另行处理 coverage、license / storage、PIT semantics、fallback / incident、stability 和 production-readiness evidence。
3. 不要把 sample runner 接入 production runner，也不要进入 DataHub / adapter / Phase 7c，除非用户另有 explicit approval + reviewed decision。

## 2026-06-02 追加：US EGS post-stable-retry remaining blocker plan

**改了什么**:

- 新增 `schemas/provider_p1_remaining_blocker_resolution_plan.schema.json`，把 AAPL / MSFT FMP stable retry 之后仍未解决的 P1 blocker 固化为 schema-first plan：coverage counts、license / storage / retention、PIT / observed-date semantics、price adjustment / corporate actions、SEC EDGAR audit parser feasibility、fallback / incident / stability、production-readiness / Phase 7c gate。
- 新增 `docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json`，记录 stable retry 只关闭 two-symbol access / response-shape sub-blocker；其余 blocker 仍不得 silent default、不得转成 provider selection / DataHub / runner consumption。
- 新增 `tests/schema/test_provider_p1_remaining_blocker_resolution_plan_schema.py`，验证 schema、真实 artifact、scope locks、blocker-track completeness、source refs 和 scope-creep rejection。
- 更新 `docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`、`docs/CURRENT.md`、`docs/README.md`，把 active provider routing 从“stable retry result”推进到“remaining blocker plan”，但保持 `SR-PROVIDER-001` open。

**为什么改**:

- Stable retry 成功后，最容易出现的误读是把 12/12 HTTP 200 当作 FMP 可选定或 Phase 7c 可开工。这个 artifact 把剩余 blocker 逐项拆开，明确下一步只能先解决 blocker，而不是扩大抓数或实现。
- 这轮刻意不调用 FMP / SEC / `yfinance`，不扩大 symbol，不接 adapter / DataHub / production runner，不放松 ship gate。
- 安全的后续 docs-only 切片是 license / storage / retention review；安全的 schema-first 切片是 fallback / incident / stability playbook。任何 coverage-count、PIT-row、corporate-action 或 broader sample validation 都必须重新获得 user approval。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
```

**验证结果**:

- Bundled Python: 6 tests ran; 3 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope-lock / blocker / routing tests passed.
- Python313 with `jsonschema`: 6 tests passed, including real artifact validation and scope-creep rejection.

**失效旧结论**:

- “stable retry 之后下一步可以直接 provider selection / DataHub / runner consumption / Phase 7c”不成立。
- “remaining blockers 只需要在 chat 里提醒”失效；现在由 schema-first artifact 路由，Claude review 应直接检查该 artifact 的 blockers 和 scope locks。

**下一步注意事项**:

1. Claude 复审应重点核对 artifact 是否只做 blocker routing，且没有授权新 access / data fetch / `yfinance` / provider selection / DataHub / runner / Phase 7c。
2. 如果审查 Pass 并提交，下一条 provider 方向的 `执行` 默认不抓数据；应先做 FMP / SEC license-storage-retention review，或 fallback / incident / stability playbook schema-first design。

## 2026-06-02 追加：US EGS fallback / incident / stability playbook

**改了什么**:

- 新增 `schemas/provider_p1_fallback_incident_stability_playbook.schema.json`，把 `fallback_incident_stability` blocker 拆成 schema-first playbook contract：field-family fallback order、incident response matrix、drift-monitor bindings、decision gates、prohibited actions。
- 新增 `docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json`，定义 fundamentals、price / volume / liquidity、corporate actions、security master / coverage、SEC EDGAR audit、benchmark / GICS 的默认阻断规则；定义 quota / outage / auth-scope / schema drift / stale rows / PIT ambiguity / corporate-action conflict / SEC audit conflict 的 incident actions。
- 新增 `tests/schema/test_provider_p1_fallback_incident_stability_playbook_schema.py`，验证 schema/artifact、scope locks、field-family completeness、incident completeness、design-only limitations、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 provider routing 从 remaining-blocker plan 推进到 fallback playbook design，但保持 `SR-PROVIDER-001` open。

**为什么改**:

- 上一轮 remaining-blocker plan 明确 safe schema-first next slice 是 fallback / incident / stability playbook。这个 slice 不需要新 provider access，也不需要联网查 license terms。
- Stable retry 的 12/12 HTTP 200 只证明 AAPL / MSFT access / shape；如果没有 default-deny fallback / incident contract，后续 DataHub / runner 容易 silent default 或把 status-page existence 误读成 stability evidence。
- 本轮刻意不执行 provider status polling、不抓新数据、不用 `yfinance`、不实现 fallback execution、不建 adapter / DataHub、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fallback_incident_stability_playbook_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fallback_incident_stability_playbook_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema tests.schema.test_provider_p1_fmp_stable_endpoint_retry_summary_schema tests.schema.test_provider_p1_us_egs_sample_validation_summary_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_fallback_incident_stability_playbook.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_fallback_incident_stability_playbook_schema` ran 7 tests: 4 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope / completeness / no-access tests passed.
- Python313 with `jsonschema`: fallback playbook + remaining-blocker plan + FMP stable retry summary + US EGS sample summary tests ran 23 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 149。
- `git diff --check` passed after the SESSION_LOG entry was prepended; only normal LF/CRLF working-copy warnings.

**失效旧结论**:

- “fallback / incident / stability playbook 尚未定义”失效；default-deny playbook 已 schema-first recorded。
- “playbook design = fallback execution / provider stability evidence”不成立；本轮 artifact 明确不执行 fallback、不轮询 status page、不抓数据、不证明稳定性。
- “有 playbook 就可进 DataHub / runner / Phase 7c”不成立；这些仍被 scope locks 和 `SR-PROVIDER-001` 阻断。

**下一步注意事项**:

1. Claude 复审应重点核对 playbook 是否只定义默认阻断行为，且没有授权 provider status polling、fallback execution、new access、`yfinance`、provider selection、DataHub、runner 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可以是 license / storage / retention review；如果继续 incident 方向，只能先做 incident-log schema contract，仍不得 provider calls。

## 2026-06-02 追加：US EGS incident-log contract

**改了什么**:

- 新增 `schemas/provider_p1_incident_log_contract.schema.json`，把 fallback playbook 里要求的 incident log 进一步固化为未来记录契约：required record fields、incident-type mappings、storage / retention policy、review / replay policy、decision gates、prohibited actions。
- 新增 `docs/provider_evidence_p1_us_incident_log_contract_20260602.json`，记录 planned log root / raw payload root / tracked summary pattern 只是 contract design，不创建日志路径、不写 incident rows、不实现 writer、不授权 storage / retention。
- 新增 `tests/schema/test_provider_p1_incident_log_contract_schema.py`，验证 schema/artifact、scope locks、24 个 required record fields、8 个 playbook incident mappings、storage/review no-authorization locks、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 provider routing 从 fallback playbook 推进到 incident-log contract，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- 上一轮 playbook 已经要求 incident log，但如果只停在字段期望，后续实现容易把 log writer、status polling、fallback execution、storage rights 混在同一刀里。
- 本轮先把记录形状和 review / replay boundary 固化为 schema-first contract，避免 future LLM 把 "record_incident" 误读成已经能写日志或能自动轮询 provider status。
- 本轮刻意不运行 provider status polling、不抓新数据、不用 `yfinance`、不创建日志路径、不实现 writer、不执行 fallback、不建 adapter / DataHub、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_incident_log_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_incident_log_contract_schema tests.schema.test_provider_p1_fallback_incident_stability_playbook_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_incident_log_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_incident_log_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_incident_log_contract_schema` ran 7 tests: 4 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope / completeness / no-access tests passed.
- Python313 with `jsonschema`: incident-log contract + fallback playbook + remaining-blocker plan targeted schema tests ran 20 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count remained 149.
- `git diff --check` passed before SESSION_LOG; the final after-SESSION_LOG check is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**失效旧结论**:

- “incident-log schema contract 尚未定义”失效；future record contract 已 schema-first recorded。
- “incident-log contract = log writer / storage authorization / provider status polling / fallback execution”不成立；本轮 artifact 明确不创建日志、不实现 writer、不授权 storage / retention、不轮询 status page、不抓数据、不执行 fallback。
- “有 incident-log contract 就可进 DataHub / runner / Phase 7c”不成立；这些仍被 scope locks 和 `SR-PROVIDER-001` 阻断。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否只定义未来 record shape，且没有授权 log writer、provider status polling、provider calls、fallback execution、provider selection、DataHub、runner 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 默认应转向 FMP / SEC license / storage / retention review；任何 log-writer implementation、status polling、fallback execution 或 provider call 都需要 separate explicit approval + reviewed decision。

## 2026-06-02 追加：DataHub local resource budget contract

**改了什么**:

- 新增 `schemas/datahub_local_resource_budget.schema.json`，把 Phase 7c 前的本机资源预算边界固化为 schema-first contract：默认 `single_slice_incremental`，单市场 / 单 lane / bounded window、lazy load、incremental cache reuse、heavy job checkpoint / resume、heavy run 必须显式用户批准 + reviewed job spec。
- 新增 `docs/datahub_local_resource_budget_contract_20260602.json`，记录两个 budget profile：`local_interactive_default` 与 `reviewed_heavy_run_optional`；两者都不授权 provider calls、DataHub implementation、runner change、Phase 7c implementation 或 all-system default run。
- 新增 `tests/schema/test_datahub_local_resource_budget_schema.py`，验证 schema/artifact、默认分片增量行为、budget profile、implementation gates、scope-creep rejection。
- 更新 `docs/datahub_design.md`、`docs/README.md`、`docs/CURRENT.md`、`AGENTS.md`，把该 contract 路由为 Phase 7c 前置边界。
- 更新 `docs/system_risk_register.md`，新增 `SR-RESOURCE-001` P2 open：contract 已定义，但未来 DataHub / runner 代码级 enforcement 尚未实现。

**为什么改**:

- 用户明确担心四套系统全设计完后本机带不动；当前设计并不要求一次性跑四套系统，但旧 DataHub guardrail 没有明确禁止“默认全系统 full refresh”。
- 直接写资源管理代码会过早进入 Phase 7c implementation。本轮只先固化 contract，约束后续实现必须分片、增量、可恢复、可审查。
- 该 contract 不解决 `SR-PROVIDER-001`，也不替代 provider license / storage / retention review；它只防止 DataHub / runner 以后把重任务变成默认行为。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_datahub_local_resource_budget_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_local_resource_budget_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\datahub_local_resource_budget.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\datahub_local_resource_budget_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_datahub_local_resource_budget_schema` ran 6 tests: 3 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema default-boundary / budget-profile / gate tests passed.
- Python313 with `jsonschema`: 6 tests passed, including real artifact validation and scope-creep rejection.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145 after slimming old completed-item detail back into risk-register references.
- `git diff --check` passed after the SESSION_LOG entry was prepended; only normal LF/CRLF working-copy warnings.

**失效旧结论**:

- “四套系统设计完成后必须一次性全量运行”不成立；默认运行边界已固化为 single-slice / incremental。
- “有 resource-budget contract 就已经可以进 Phase 7c implementation”不成立；artifact 明确不授权 DataHub table、adapter、runner change、provider call 或 Phase 7c。
- “SR-RESOURCE-001 已关闭”不成立；代码级 enforcement 和 job-spec tests 尚未实现。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否没有授权 provider calls、DataHub implementation、runner change、Phase 7c、ship-gate claim 或全系统默认运行。
2. Provider 方向的自然下一刀仍可回到 FMP / SEC license / storage / retention docs-only review；DataHub implementation 仍需单独 explicit approval + reviewed decision。

## 2026-06-02 追加：US EGS license / storage / retention review

**改了什么**:

- 新增 `schemas/provider_p1_license_storage_retention_review.schema.json`，把 FMP / SEC EDGAR 的 local raw sample、tracked no-secret summary、production raw storage、normalized DataHub storage、derived outputs、non-display use、export / redistribution、retention、professional / business use、broader sample / full-market use 分类为 schema-first review contract。
- 新增 `docs/provider_evidence_p1_us_license_storage_retention_review_20260602.json`，只基于既有 reviewed repo artifacts 做 blocker classification；不做 current provider terms web refresh、不联系 provider、不提供法律建议、不抓数据。
- 新增 `tests/schema/test_provider_p1_license_storage_retention_review_schema.py`，验证 schema/artifact、no-access locks、rights matrix、remaining gates、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 license-storage-retention review 路由进 Phase 7b-2，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- stable retry 只证明 AAPL / MSFT 两只股票 endpoint access / response-shape；它没有回答 FMP current terms、local storage、normalized DataHub storage、derived outputs、retention、non-display use 或 SEC broader reconstruction 的生产边界。
- 本轮先用既有 repo 证据把 “已批准小样本” 与 “生产 / broader use 仍 blocked” 分开，避免后续 LLM 把 sample raw storage 或 tracked summary 误读成 DataHub / runner 存储授权。
- 本轮刻意不刷新当前 provider terms、不做 legal conclusion、不抓新数据、不用 `yfinance`、不建 adapter / DataHub、不改 runner、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_license_storage_retention_review_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_license_storage_retention_review_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema tests.schema.test_provider_p1_incident_log_contract_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_license_storage_retention_review.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_license_storage_retention_review_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_license_storage_retention_review_schema` ran 7 tests: 4 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema scope / rights / blocker tests passed.
- Python313 with `jsonschema`: license-storage-retention review + remaining-blocker plan + incident-log contract tests ran 20 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145.
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**失效旧结论**:

- “FMP stable retry 成功即可进入 production storage / DataHub / runner consumption”不成立；license-storage-retention review 明确只允许已批准两 symbol sample 范围和 tracked no-secret summary。
- “SEC EDGAR public API 可直接扩成 broader reconstruction / production normalized storage”不成立；仍需 parser / fair-access / artifact-retention contract。
- “本轮 artifact 等于 current terms / legal signoff”不成立；artifact 明确没有 current terms web refresh、provider contact 或 legal advice。

**下一步注意事项**:

1. Claude 复审应重点核对 rights matrix 是否没有把 sample storage、tracked summary、SEC public API、FMP stable retry误读成 production storage / derived output / DataHub / runner 授权。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可转向 SEC EDGAR audit parser feasibility / scope contract 或 FMP PIT / observed-date semantics design；current terms legal review、broader sample、provider call、status polling、DataHub 或 runner consumption 仍需 separate explicit approval + reviewed decision。

## 2026-06-02 追加：SEC EDGAR audit parser scope contract

**改了什么**:

- 新增 `schemas/provider_p1_sec_edgar_audit_parser_scope_contract.schema.json`，把未来 SEC EDGAR audit parser 的 audit-only role、lineage requirements、fair-access expectations、artifact policy、decision gates 和 prohibited actions 固化为 schema-first scope contract。
- 新增 `docs/provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json`，只基于既有 reviewed repo artifacts 和 tracked no-secret sample summary 做 scope contract；不做 SEC API call、不读取或解析 raw payload、不实现 parser、不抓数据。
- 新增 `tests/schema/test_provider_p1_sec_edgar_audit_parser_scope_contract_schema.py`，验证 schema/artifact、no-access locks、audit role boundaries、13 个 lineage requirements、fair-access / artifact policy、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 SEC parser scope contract 路由进 Phase 7b-2，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- 上一轮 license-storage-retention review 已把 SEC broader reconstruction 阻断在 parser / fair-access / artifact-retention contract 之前；本轮先定义 parser 能做什么、不能做什么。
- SEC EDGAR 只保留为 fundamentals anomaly audit / FMP cross-check support；本轮明确它不是 price source、strict free-float authority、production fundamentals provider、security master、alpha-validation artifact 或 DataHub source。
- 本轮刻意不调用 SEC、不解析本地 raw payload、不实现 parser、不建 adapter / DataHub、不改 runner、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema tests.schema.test_provider_p1_license_storage_retention_review_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_sec_edgar_audit_parser_scope_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema no-access / boundary / lineage / policy tests passed.
- Python313 with `jsonschema`: SEC parser scope contract + license-storage review + remaining-blocker plan tests ran 22 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145.
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**失效旧结论**:

- “SEC EDGAR public API sample 成功即可 broader reconstruction / parser implementation”不成立；本轮 contract 明确 broader SEC endpoint call、raw parse、parser implementation 均 blocked。
- “SEC parser scope = price source / strict free-float authority / alpha validation / DataHub source”不成立；这些都被 audit role boundaries 排除或阻断。
- “本轮 artifact 证明 parser feasibility at scale”不成立；它只定义 scope 和 gates，不证明 coverage、PIT normalization、free-float reconciliation 或 production readiness。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否没有授权 SEC endpoint calls、raw-payload parsing、parser implementation、DataHub / runner consumption、provider selection 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可转向 FMP PIT / observed-date semantics design，或继续做 SEC parser field-family mapping contract；任何 actual parser implementation 或 SEC call 仍需 separate explicit approval + reviewed decision。

## 2026-06-02 追加：FMP PIT / observed-date semantics contract

**改了什么**:

- 新增 `schemas/provider_p1_fmp_pit_observed_date_semantics_contract.schema.json`，把 FMP stable retry 之后的 PIT / observed-date 语义边界固化为 schema-first contract：field-family historical-use gates、15 个 PIT lineage requirements、no-silent-default policy、decision gates、prohibited actions。
- 新增 `docs/provider_evidence_p1_us_fmp_pit_observed_date_semantics_contract_20260602.json`，只基于既有 reviewed repo artifacts 做 semantics contract；不做 FMP endpoint call、不读取或解析 raw payload、不实现 field mapping、不抓数据。
- 新增 `tests/schema/test_provider_p1_fmp_pit_observed_date_semantics_contract_schema.py`，验证 schema/artifact、no-access locks、two-symbol evidence calibration、6 个 field-family gates、15 个 lineage requirements、latest-only / missing-date blocking、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 FMP PIT / observed-date semantics contract 路由进 Phase 7b-2，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- FMP stable retry 的 `filingDate` / `acceptedDate` 字段存在只证明 AAPL / MSFT 两只活跃样本的 response shape；它不能证明历史 PIT、amendment / restatement、latest/current endpoint as-of semantics、coverage、price adjustment 或 DataHub eligibility。
- 本轮先把 statement / key metrics / profile / EOD price-volume 的历史使用门槛写成可审查契约，避免后续 LLM 把 stable retry 字段存在误读成 provider selection 或 Phase 7c 可用性。
- 本轮刻意不调用 FMP、不解析 ignored raw payload、不实现 field mapping、不建 adapter / DataHub、不改 runner、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_fmp_pit_observed_date_semantics_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_fmp_pit_observed_date_semantics_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema no-access / field-family / lineage / policy tests passed.
- Python313 with `jsonschema`: FMP PIT semantics contract + SEC parser scope contract + remaining-blocker plan targeted schema tests ran 24 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145.
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**失效旧结论**:

- “FMP stable retry 看到 `filingDate` / `acceptedDate` 就可历史 PIT 使用”不成立；本轮 contract 明确 field-level PIT validation、revision / restatement、as-of eligibility 和 latest endpoint exclusion 仍 blocked。
- “FMP profile / key metrics / EOD 字段存在就可进 DataHub / runner”不成立；profile 不具备 filing-observed semantics，key metrics 需证明派生规则，EOD 需另做 adjustment / corporate-action review。
- “本轮 artifact 证明 FMP production readiness”不成立；它只定义 semantics gates，不证明 coverage、license、price adjustment、fallback、stability 或 production readiness。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否没有授权 FMP endpoint calls、raw-payload parsing、field mapping implementation、provider selection、DataHub / runner consumption 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可转向 FMP price-adjustment / corporate-action semantics contract，或 SEC parser field-family mapping contract；任何 actual FMP PIT row validation、FMP call、SEC call、raw parse 或 field-mapping / parser implementation 仍需 separate explicit approval + reviewed decision。

## 2026-06-02 追加：FMP price-adjustment / corporate-action semantics contract

**改了什么**:

- 新增 `schemas/provider_p1_fmp_price_adjustment_corporate_action_semantics_contract.schema.json`，把 FMP stable historical EOD 之后的 price adjustment / corporate-action 语义边界固化为 schema-first contract：8 个 market-data gate families、18 个 price lineage requirements、no-silent-default policy、decision gates、prohibited actions。
- 新增 `docs/provider_evidence_p1_us_fmp_price_adjustment_corporate_action_semantics_contract_20260602.json`，只基于既有 reviewed repo artifacts 做 semantics contract；不做 FMP endpoint call、不读取或解析 raw payload、不计算 returns、不 reconciliation corporate actions、不实现 field mapping、不抓数据。
- 新增 `tests/schema/test_provider_p1_fmp_price_adjustment_corporate_action_semantics_contract_schema.py`，验证 schema/artifact、no-access locks、two-symbol EOD response-shape calibration、8 个 market-data gates、18 个 lineage requirements、adjustment / split / dividend / delisting / missing-session blocking、scope-creep rejection。
- 更新 `AGENTS.md`、`docs/README.md`、`docs/CURRENT.md`、`docs/provider_evidence_drift_monitor.md`、`docs/system_risk_register.md`，把 FMP price / corporate-action semantics contract 路由进 Phase 7b-2，同时保持 `SR-PROVIDER-001` open。

**为什么改**:

- FMP stable retry 的 historical EOD rows 只在 AAPL / MSFT 两只活跃样本上证明 OHLCV / change / changePercent / VWAP response shape；它不能证明 adjusted-return semantics、split / dividend handling、delisting / inactive coverage、zero-volume / halt behavior、missing-session policy、liquidity validity 或 DataHub eligibility。
- 上一轮 FMP PIT contract 已明确 EOD price-volume 需另做 adjustment / corporate-action review；本轮先把 return / liquidity 使用门槛写成可审查契约，避免后续 LLM 把 EOD 字段存在误读成 provider selection 或 Phase 7c 可用性。
- 本轮刻意不调用 FMP、不解析 ignored raw payload、不计算 returns、不 reconciliation corporate actions、不实现 field mapping、不建 adapter / DataHub、不改 runner、不授权 Phase 7c。

**验证命令**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_fmp_price_adjustment_corporate_action_semantics_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_price_adjustment_corporate_action_semantics_contract_schema tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_fmp_price_adjustment_corporate_action_semantics_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_fmp_price_adjustment_corporate_action_semantics_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**验证结果**:

- Bundled Python: `tests.schema.test_provider_p1_fmp_price_adjustment_corporate_action_semantics_contract_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`; non-jsonschema no-access / market-data gate / lineage / no-silent-default tests passed。
- Python313 with `jsonschema`: FMP price/corporate-action semantics contract + FMP PIT semantics contract + remaining-blocker plan targeted schema tests ran 24 tests, all passed。
- `json.tool` parsed the new schema and artifact successfully。
- `docs/CURRENT.md` line count = 145。
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round。

**失效旧结论**:

- “FMP stable retry 看到 OHLCV / VWAP 字段就可算 historical returns / liquidity”不成立；本轮 contract 明确 adjustment mode、corporate actions、delisting / inactive status、zero-volume / missing-session policy、calendar / timezone 和 liquidity rules 仍 blocked。
- “FMP price/corporate-action contract = actual adjusted-return validation / corporate-action reconciliation”不成立；它只定义 gates，不调用 FMP、不读 raw payload、不算 returns、不 reconciliation corporate actions。
- “本轮 artifact 证明 FMP production readiness”不成立；它不证明 coverage、license、PIT、price adjustment、fallback、stability 或 production readiness，也不关闭 `SR-PROVIDER-001`。

**下一步注意事项**:

1. Claude 复审应重点核对 contract 是否没有授权 FMP endpoint calls、raw-payload parsing、return calculation、corporate-action reconciliation、field mapping implementation、provider selection、DataHub / runner consumption 或 Phase 7c。
2. 如果审查 Pass 并提交，下一条 no-access provider slice 可转向 SEC parser field-family mapping contract 或 coverage-count access-packet planning；任何 actual FMP adjustment validation、corporate-action sample、coverage-count execution、FMP call、SEC call、raw parse 或 field-mapping / parser implementation 仍需 separate explicit approval + reviewed decision。

## 2026-06-02 append: SEC EDGAR field-family mapping contract

**What changed**:

- Added `schemas/provider_p1_sec_edgar_field_family_mapping_contract.schema.json`, a no-access schema-first contract for future SEC EDGAR audit field-family mapping after the SEC audit parser scope contract.
- Added `docs/provider_evidence_p1_us_sec_edgar_field_family_mapping_contract_20260602.json`, based only on existing reviewed repo artifacts. It defines 10 audit field-family gates, 16 parser lineage requirements, FMP cross-check policy, decision gates, and prohibited actions.
- Added `tests/schema/test_provider_p1_sec_edgar_field_family_mapping_contract_schema.py`, covering schema/artifact validation, no-access locks, complete field-family gates, complete lineage gates, cross-check no-silent-default policy, source refs / limitations, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md` to route this contract while keeping `SR-PROVIDER-001` open.

**Why**:

- The SEC parser scope contract already blocked broader SEC reconstruction pending later lineage / parser / fair-access / artifact work. This slice defines the field-family mapping gates without crossing into parser implementation.
- SEC EDGAR remains fundamentals anomaly audit / FMP cross-check support only. The contract explicitly excludes price-source use, strict free-float authority, production fundamentals provider use, security-master use, alpha-validation claims, DataHub source authority, and Phase 7c authorization.
- This round intentionally performs no SEC API call, no raw-payload parse, no fixture generation, no parser implementation, no field-mapping implementation, no provider call, no adapter / DataHub work, no runner change, and no Phase 7c authorization.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_sec_edgar_field_family_mapping_contract_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_sec_edgar_field_family_mapping_contract_schema tests.schema.test_provider_p1_sec_edgar_audit_parser_scope_contract_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_sec_edgar_field_family_mapping_contract.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_sec_edgar_field_family_mapping_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Bundled Python: `tests.schema.test_provider_p1_sec_edgar_field_family_mapping_contract_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`.
- Python313 with `jsonschema`: SEC field-family mapping contract + SEC parser scope contract + remaining-blocker plan targeted schema tests ran 24 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully.
- `docs/CURRENT.md` line count = 145.
- `git diff --check` final result is recorded in the top `docs/SESSION_LOG.md` Codex entry for this work round.

**Invalid conclusions**:

- "SEC sample success means SEC parser / mapping can now be implemented" is false. This contract authorizes no SEC call, raw parse, parser implementation, field mapping, fixture generation, or DataHub consumption.
- "SEC EDGAR can replace FMP as production fundamentals provider" is false. SEC remains audit / cross-check support only.
- "This closes `SR-PROVIDER-001`" is false. Actual SEC access, raw-payload retention, minimized fixtures, parser implementation, field mapping, coverage, license / production storage, PIT, price adjustment, fallback execution, stability evidence, provider selection, DataHub, runner consumption, and Phase 7c remain blocked.

**Next-step notes**:

1. Claude review should focus on whether the new contract accidentally authorizes SEC endpoint calls, raw-payload parsing, fixture generation, parser implementation, field-mapping implementation, provider selection, DataHub / runner consumption, alpha-validation claims, ship-gate claims, or Phase 7c.
2. If review passes and the change is committed, the next safe no-access provider slice is coverage-count access-packet planning. Any actual coverage-count execution, FMP call, SEC call, raw parse, fixture generation, field-mapping / parser implementation, provider status polling, adapter, DataHub, runner, or Phase 7c step still requires separate explicit approval + reviewed decision.

## 2026-06-02 append: Coverage-count access-packet plan

**What changed**:

- Added `schemas/provider_p1_coverage_count_access_packet_plan.schema.json`, a no-access schema-first plan for the future US EGS coverage-count access packet.
- Added `docs/provider_evidence_p1_us_coverage_count_access_packet_plan_20260602.json`, based only on existing reviewed repo artifacts. It defines four planned coverage request profiles, fourteen access-packet requirements, eight count metrics, no-silent-default policy, decision gates, and prohibited actions.
- Added `tests/schema/test_provider_p1_coverage_count_access_packet_plan_schema.py`, covering schema/artifact validation, no-execution locks, profile completeness, access-packet requirements, metric / no-silent-default behavior, source refs / limitations, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md` to route the plan while keeping `SR-PROVIDER-001` open.

**Why**:

- The AAPL / MSFT FMP stable retry proves only two-symbol endpoint access / response shape. It does not prove target-universe coverage, missing-field rates, inactive / delisted behavior, or class coverage.
- This slice defines what a later user-approved coverage-count access packet must contain before any provider call or count execution: bounded symbol universe, endpoint families, call budget, time window, rate / retry policy, SEC fair-access if relevant, storage / retention, no-secret summary, raw-payload gitignore proof, metric definitions, pass / fail thresholds, fallback / incident behavior, and explicit manual approval.
- This round intentionally performs no coverage-count execution, no FMP or SEC endpoint calls, no status polling, no data fetch, no raw-payload parsing, no fixture generation, no fallback execution, no incident-log writer implementation, no provider selection, no adapter / DataHub work, no runner change, and no Phase 7c authorization.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_coverage_count_access_packet_plan_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_coverage_count_access_packet_plan_schema tests.schema.test_provider_p1_sec_edgar_field_family_mapping_contract_schema tests.schema.test_provider_p1_remaining_blocker_resolution_plan_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_coverage_count_access_packet_plan.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_coverage_count_access_packet_plan_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Bundled Python: `tests.schema.test_provider_p1_coverage_count_access_packet_plan_schema` ran 9 tests: 6 passed, 3 skipped because this interpreter lacks `jsonschema`.
- Python313 with `jsonschema`: coverage-count access-packet plan + SEC field-family mapping contract + remaining-blocker plan targeted schema tests ran 24 tests, all passed.
- `json.tool` parsed the new schema and artifact successfully before docs routing updates.

**Invalid conclusions**:

- "FMP stable retry success means coverage is proven" is false. The plan explicitly says two-symbol response shape cannot imply target-universe coverage.
- "This plan authorizes the coverage-count run" is false. It defines the later access packet required before execution; it performs and authorizes no provider call.
- "This closes `SR-PROVIDER-001`" is false. Actual coverage counts, current terms / production storage rights, PIT row validation, price / corporate-action validation, SEC parser implementation, field mapping, fallback execution, stability evidence, provider selection, DataHub, runner consumption, and Phase 7c remain blocked.

**Next-step notes**:

1. Claude review should focus on whether the new plan accidentally authorizes coverage execution, FMP / SEC calls, raw parsing, fixture generation, provider selection, status polling, fallback execution, DataHub / runner consumption, ship-gate claims, or Phase 7c.
2. If review passes and the change is committed, any actual coverage-count packet must be a separate user-approved and reviewed access request with exact symbols, endpoints, call budget, storage, no-secret summary, and pass / fail thresholds.

## 2026-06-02 append: Approved coverage-count execution packet

**What changed**:

- Added `schemas/provider_p1_coverage_count_access_packet_approval.schema.json` and `docs/provider_evidence_p1_us_coverage_count_access_packet_approval_20260602.json`, recording the user's exact approval for a bounded 5-symbol / 30-call FMP stable coverage-count packet.
- Added `runners/us_egs_coverage_count_packet.py`, a narrow runner that validates the approval artifact, reads only the existing `FMP_API_KEY`, calls only FMP stable endpoint families, writes raw payloads under gitignored `provider_samples/us_egs_coverage_count_20260602/fmp_stable/`, and writes a tracked no-secret summary.
- Added `schemas/provider_p1_coverage_count_execution_summary.schema.json` and generated `docs/provider_evidence_p1_us_coverage_count_execution_summary_20260602.json`.
- Added `tests/provider/test_us_egs_coverage_count_packet.py`, `tests/schema/test_provider_p1_coverage_count_access_packet_approval_schema.py`, and `tests/schema/test_provider_p1_coverage_count_execution_summary_schema.py`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md` to route the executed coverage smoke while keeping `SR-PROVIDER-001` open.

**Execution result**:

- Actual packet used 5 active symbols: `AAPL`, `MSFT`, `NVDA`, `JPM`, `XOM`.
- Actual endpoint budget used: 30 / 30 FMP stable calls.
- Result summary: `validation_status = completed`, `endpoint_success_count = 30`, `endpoint_error_count = 0`, `symbol_all_endpoint_success_count = 5`, `statement_observed_date_endpoint_count = 15`, `price_ohlcv_presence_count = 5`.
- Missing-field result: `missing_required_field_count = 15`, from `peRatio`, `revenuePerShare`, and `netIncomePerShare` missing in FMP stable key-metrics responses across the five symbols; no silent default is used.
- Raw payloads are ignored by `.gitignore:50 provider_samples/`; tracked summary contains no API key, request URL, bearer token, or raw rows.

**Why**:

- The no-access coverage-count plan required exact symbols, endpoint families, call budget, storage, no-secret summary, thresholds, and explicit manual approval before execution.
- The user explicitly said `批准并执行`, so this slice records the approval boundary and executes only that bounded packet.
- The result is deliberately a coverage smoke, not provider selection or production readiness.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.provider.test_us_egs_coverage_count_packet -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_coverage_count_access_packet_approval_schema tests.schema.test_provider_p1_coverage_count_execution_summary_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\us_egs_coverage_count_packet.py
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_coverage_count_access_packet_approval_schema tests.schema.test_provider_p1_coverage_count_execution_summary_schema tests.provider.test_us_egs_coverage_count_packet -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_coverage_count_execution_summary_20260602.json
git check-ignore -v provider_samples\us_egs_coverage_count_20260602\fmp_stable\raw\financial_modeling_prep\AAPL\profile_or_company_metadata.json
Select-String -Path docs\provider_evidence_p1_us_coverage_count_execution_summary_20260602.json -Pattern "apikey=|FMP_API_KEY|Bearer |financialmodelingprep.com" -CaseSensitive
```

**Validation results**:

- Bundled Python provider runner tests: 4 tests passed.
- Bundled Python schema tests: 10 tests ran; 3 passed, 7 skipped because this interpreter lacks `jsonschema`.
- Python313 actual packet: completed; 30/30 endpoint calls succeeded; secrets_logged = false.
- Python313 jsonschema + provider tests: 14 tests passed.
- `json.tool` parsed the execution summary.
- `git check-ignore -v` confirmed raw payloads are covered by `.gitignore:50 provider_samples/`.
- Secret / URL scan of the tracked summary returned no matches.

**Invalid conclusions**:

- "30/30 FMP stable calls mean FMP is selected" is false.
- "This proves full US universe, inactive, delisted, or survivorship-safe coverage" is false.
- "This authorizes Phase 7c, DataHub, adapter, runner consumption, or production storage" is false.
- "Missing key-metrics fields can be silently defaulted" is false; they are recorded as blockers.

**Next-step notes**:

1. Claude review should verify the approval boundary, runner scope, raw gitignore proof, tracked no-secret summary, schema tests, and that `SR-PROVIDER-001` remains open.
2. Any broader FMP / SEC endpoint call, current terms review, production storage decision, PIT row validation, price-adjustment / corporate-action validation, SEC parser implementation, fixture generation, fallback execution, provider selection, adapter, DataHub table, runner consumption, or Phase 7c work still requires separate explicit approval and reviewed decision.

## 2026-06-02 append: Missing key-metrics resolution plan

**What changed**:

- Added `schemas/provider_p1_missing_key_metrics_resolution_plan.schema.json`, a no-access schema-first plan for the three FMP stable key-metrics fields missing in the approved coverage-count summary.
- Added `docs/provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json`, based only on the tracked no-secret coverage summary and existing reviewed repo artifacts. It classifies `peRatio`, `revenuePerShare`, and `netIncomePerShare` as potentially derivable only after separate field-presence and lineage review.
- Added `tests/schema/test_provider_p1_missing_key_metrics_resolution_plan_schema.py`, covering schema/artifact validation, no-access locks, exact missing-field count, candidate derivation status, no-silent-default policy, decision gates, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md` to route the plan while keeping `SR-PROVIDER-001` open.

**Why**:

- The coverage-count smoke found 30/30 FMP stable endpoint successes but also 15 missing key-metrics fields: `peRatio`, `revenuePerShare`, and `netIncomePerShare` missing across AAPL / MSFT / NVDA / JPM / XOM.
- These fields may be derivable from price, statement, and share-count inputs, but the repo must not silently compute them without PIT-safe field presence, formula, denominator, fiscal-period, unit / currency, restatement, and price-adjustment lineage.
- This slice intentionally performs no provider call, no raw-payload parse, no fixture generation, no derivation implementation, no field mapping, no return calculation, no corporate-action reconciliation, no provider selection, no DataHub / runner change, and no Phase 7c authorization.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_provider_p1_missing_key_metrics_resolution_plan_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_missing_key_metrics_resolution_plan_schema tests.schema.test_provider_p1_coverage_count_execution_summary_schema tests.schema.test_provider_p1_fmp_pit_observed_date_semantics_contract_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\provider_p1_missing_key_metrics_resolution_plan.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Invalid conclusions**:

- "Missing key-metrics fields can be silently computed" is false. Any derivation needs reviewed field-presence and lineage evidence.
- "The resolution plan authorizes raw-payload parsing" is false. Reading existing ignored raw payloads or making fresh provider calls still requires separate explicit approval and reviewed scope.
- "This closes `SR-PROVIDER-001`" is false. Direct ratio availability, safe derivation, current terms / production storage, field-level PIT, price adjustment, SEC parser work, fallback / stability, provider selection, DataHub, runner consumption, and Phase 7c remain blocked.

**Next-step notes**:

1. Claude review should verify that the plan is no-access and does not authorize raw-payload parsing, derivation implementation, field mapping, provider selection, DataHub / runner consumption, ship-gate claims, or Phase 7c.
2. If review passes and the change is committed, the next concrete missing-field step would need a separate user-approved field-presence / lineage packet before any raw parsing or fresh endpoint calls.

## 2026-06-02 append: A-short screening threshold governance parity

**What changed**:

- Added `schemas/a_short_screening_threshold_governance.schema.json`, a schema-first governance contract for A-share short screening thresholds.
- Added `presets/a_short_screening_threshold_governance_20260602.json`, mirroring 13 current literal `A-EGS/egs_main.py::CONF` screening thresholds into a governed preset artifact.
- Updated `presets/a_short.yaml` with a flat `screening_threshold_governance` route to the artifact, source code ref, and parity test.
- Added `tests/schema/test_a_short_screening_threshold_governance_schema.py`, which statically parses `A-EGS/egs_main.py` with AST and asserts exact artifact/code parity without importing EGS or requiring `TUSHARE_TOKEN`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `presets/README.md`, and `docs/system_risk_register.md`; `SR-GOV-001` is resolved.

**Why**:

- `SR-GOV-001` tracked that production-relevant A-short screening thresholds lived only in `A-EGS/egs_main.py::CONF` while `presets/a_short.yaml` still said detailed thresholds would be filled later.
- This slice takes the smaller safe closure path allowed by the risk entry: assert preset / artifact / code parity under test instead of migrating runtime threshold loading now.
- This round intentionally performs no screening run, no research / backtest run, no provider call, no data fetch, no `A-EGS/egs_main.py` runtime change, no DataHub / adapter implementation, no ship-gate claim, and no broker / order automation.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_a_short_screening_threshold_governance_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_a_short_screening_threshold_governance_schema tests.schema.test_datahub_local_resource_budget_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\a_short_screening_threshold_governance.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool presets\a_short_screening_threshold_governance_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Invalid conclusions**:

- "The runtime now loads thresholds from YAML" is false. Current runtime still reads `A-EGS/egs_main.py::CONF`; this slice only adds a reviewed parity gate.
- "This changes candidate selection / scoring / output" is false. `A-EGS/egs_main.py` was not modified.
- "This authorizes provider access, research, DataHub, Phase 7c, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify that the artifact exactly mirrors current `CONF` values and that the test does not import or run `A-EGS/egs_main.py`.
2. Any future runtime preset-loader migration or threshold behavior change must be a separate reviewed slice with behavior-preservation tests.

## 2026-06-02 append: DataHub job spec contract

**What changed**:

- Added `schemas/datahub_job_spec.schema.json`, a Phase 7c precondition schema for future DataHub / runner job specs.
- Added `schemas/examples/datahub_job_spec.example.json`, a schema-only, non-executable example that declares `local_interactive_default`, one market, one lane, one as-of date, resource estimates, lazy / incremental / checkpoint / abort policy, data boundaries, and approval gates.
- Added `tests/schema/test_datahub_job_spec_schema.py`, covering schema/example validation, no-runtime scope locks, budget profile, partition scope, resource estimates, execution policy, approval gates, and scope-creep rejection.
- Updated `docs/datahub_design.md`, `docs/README.md`, `docs/CURRENT.md`, `AGENTS.md`, `docs/system_risk_register.md`, and `docs/datahub_local_resource_budget_contract_20260602.json` to route the job-spec contract while keeping `SR-RESOURCE-001` open.

**Why**:

- The local resource budget contract already required future reviewed job specs, but it did not define the job-spec shape.
- This slice adds the missing schema-first bridge without implementing DataHub, changing runners, or executing any broad job.
- `SR-RESOURCE-001` remains open because future executable DataHub / runner jobs still need code-level enforcement and tests.

**Validation commands**:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_datahub_job_spec_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_job_spec_schema tests.schema.test_datahub_local_resource_budget_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\datahub_job_spec.schema.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool schemas\examples\datahub_job_spec.example.json
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m json.tool docs\datahub_local_resource_budget_contract_20260602.json
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Bundled Python: `tests.schema.test_datahub_job_spec_schema` ran 8 tests; non-jsonschema boundary tests passed; jsonschema-dependent checks skipped in this interpreter (`skipped=8` due skipped subtests).
- Python313 with `jsonschema`: `tests.schema.test_datahub_job_spec_schema` + `tests.schema.test_datahub_local_resource_budget_schema` ran 14 tests, all pass.
- `json.tool` parsed the new schema, new example, and updated resource-budget contract artifact.
- `docs/CURRENT.md` line count remained 149.
- `git diff --check` exited 0 with only normal LF/CRLF working-copy warnings.

**Invalid conclusions**:

- "SR-RESOURCE-001 is closed" is false; code-level enforcement does not exist yet.
- "This authorizes Phase 7c implementation" is false.
- "This authorizes provider calls, raw-payload parsing, DataHub tables, runner changes, production runner consumption, full-system runs, or ship-gate claims" is false.

**Next-step notes**:

1. Claude review should verify the new schema/example do not authorize provider access, data fetch, raw parse, full-market refresh, DataHub implementation, runner changes, production consumption, Phase 7c, or ship-gate claims.
2. A future Phase 7c implementation slice must make executable job specs validate against `schemas/datahub_job_spec.schema.json` and enforce the budget / partition / abort policy in code before `SR-RESOURCE-001` can close.

## 2026-06-02 append: DataHub job-spec guardrail hardening

**What changed**:

- `schemas/datahub_job_spec.schema.json` now rejects partition scopes where `market=A` is paired with `us_*` lanes or `market=US` is paired with `a_*` lanes.
- `schemas/datahub_local_resource_budget.schema.json` now caps `budget_profiles[].max_concurrent_lanes` at 2.
- `docs/datahub_local_resource_budget_contract_20260602.json` fixes the limitation reference from `SR-PROVIDER-001` to `SR-RESOURCE-001`.
- `docs/system_risk_register.md` keeps `SR-RESOURCE-001` open but updates mitigation / required-next-action / verification text for market-lane consistency and reviewed lane-concurrency bounds.

**Validation results**:

- Python313 with `jsonschema`: `tests.schema.test_datahub_job_spec_schema` + `tests.schema.test_datahub_local_resource_budget_schema` passed as part of the 30-test forward-live / DataHub suite.
- Bundled Python non-jsonschema checks passed where available; jsonschema-dependent checks skipped in that interpreter.
- `json.tool` parsed both DataHub schemas and the resource-budget contract artifact.
- `git diff --check` exited 0 with only normal LF/CRLF working-copy warnings.

**Invalid conclusions**:

- "The job-spec schema accepts cross-market lane mismatches" is now false.
- "The resource-budget schema has no upper bound for `max_concurrent_lanes`" is now false.
- "SR-RESOURCE-001 is closed" remains false; executable code-level enforcement is still required before Phase 7c / runner implementation.

## 2026-06-02 append: P3 hygiene slice after Phase 6-to-now audit

**What changed**:

- `runners/materialize_benchmark_monthly_returns_tushare.py` now skips boundary months with fewer than two usable `index_daily` rows into metadata `skipped_months` when other months remain usable; fully unusable ranges still raise.
- `runners/forward_tracker.py` now excludes terminal forward statuses from the pending backfill mask and filters work rows by that same mask.
- `runners/backtest_rank.py` now leaves close-to-close diagnostic return empty when the actual as-of bar close / adj_factor is missing, without blocking primary `t1` / `t1_net`.
- `runners/us_egs_sample_validation.py` removed an unused `sys` import and checks endpoint-call budget before each fetch in the approved legacy small-sample and stable retry paths.
- `runners/aggregate_execution_reports.py` collapsed a dead `report_total_return_for_aggregation` branch without behavior change.

**Validation results**:

- Python313: `tests.execution.test_materialize_benchmark_monthly_returns_tushare`, `tests.phase6.test_forward_tracker_cache_guard`, `tests.test_backtest_rank_phase3`, `tests.provider.test_us_egs_sample_validation`, and `tests.execution.test_aggregate_execution_reports` ran 48 tests, all pass.
- Python313: `tests.provider.test_us_egs_coverage_count_packet` ran 4 tests, all pass.
- `git diff --check` exited 0 with only normal LF/CRLF working-copy warnings.
- `rg --files -g 'tmp*' -g '!provider_samples/**'` returned no output.

**Invalid conclusions**:

- "This changes provider authorization, Phase 7c, DataHub, production runner consumption, ship-gate policy, or full-size permission" is false.
- "This closes `SR-PROVIDER-001` or `SR-RESOURCE-001`" is false; both remain open by design.

## 2026-06-03 append: Provider validation authorization packet

**What changed**:

- `schemas/provider_p1_validation_authorization_packet.schema.json` defines the machine-checkable authorization boundary for a future bounded US EGS provider validation packet.
- `docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json` records the user's FMP Basic confirmation and authorization for existing FMP key + SEC EDGAR public API, $0 spend, 5-10 symbols, max 60 calls, active symbols plus inactive / delisted candidates if supported, gitignored raw storage, tracked no-secret summary, and validation-only raw parsing for PIT row / price adjustment / corporate-action / SEC parser / SEC field-mapping / field-presence feasibility.
- `tests/schema/test_provider_p1_validation_authorization_packet_schema.py` validates the new schema / artifact, boundary locks, validation-only permissions, pre-execution gates, prohibited claims, and scope-creep rejection.
- `docs/provider_evidence_drift_monitor.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/system_risk_register.md`, and `AGENTS.md` now route the new packet as the active `SR-PROVIDER-001` authorization boundary for a later reviewed execution packet.

**Validation results**:

- Python313: `json.tool` parsed `schemas/provider_p1_validation_authorization_packet.schema.json` and `docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json`.
- Python313: `tests.schema.test_provider_p1_validation_authorization_packet_schema` ran 8 tests, all pass.
- Python313: adjacent provider schema regression suite ran 34 tests, all pass: sample-validation approval, coverage-count approval / summary, missing key-metrics resolution plan, and the new validation authorization packet.
- `docs/CURRENT.md` line count is 149.

**Invalid conclusions**:

- "This slice executed FMP or SEC calls" is false; it executed no provider calls and created no `provider_samples/` files.
- "This authorizes provider selection, adapter, DataHub, runner consumption, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.
- "FMP Basic is production license clearance" is false; it is only the user-confirmed plan boundary for a later bounded validation packet.
- "SR-PROVIDER-001 is closed" is false; the authorization narrows one approval blocker but leaves current terms, production storage, PIT, price adjustment, corporate action, SEC parser / field mapping, fallback, stability, and production-readiness evidence open.

**Next-step notes**:

1. Claude review should verify that the new schema/artifact allows only the authorized future 5-10 symbol / max 60 call / FMP Basic existing-key / SEC public-API validation packet and does not silently authorize implementation.
2. A future execution slice may consume this authorization only through a reviewed execution packet that fixes exact symbols, endpoints, call budget, raw storage subdir, no-secret summary fields, environment precheck, SEC fair-access handling, gitignore proof, and abort behavior.
3. Any scope beyond this authorization still requires separate explicit approval and reviewed decision.

## 2026-06-03 append: Provider validation execution packet

**What changed**:

- Added `schemas/provider_p1_validation_execution_packet.schema.json`, a schema-first execution-packet contract that consumes the 2026-06-03 provider validation authorization without executing it.
- Added `docs/provider_evidence_p1_us_validation_execution_packet_20260603.json`, fixing the later packet to `AAPL`, `MSFT`, `JPM`, `TWTR`, and `SIVB`, 41 planned calls, zero retries, gitignored raw path `provider_samples/us_egs_validation_packet_20260603/`, tracked no-secret summary, environment precheck, and abort-on-scope-violation gates.
- Added `tests/schema/test_provider_p1_validation_execution_packet_schema.py`, validating schema/artifact shape, exact sample, endpoint family boundaries, zero-call split/dividend candidate families, storage / secret gates, prohibited claims, and scope-creep rejection.
- Updated `docs/provider_evidence_drift_monitor.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/system_risk_register.md`, and `AGENTS.md` to route the execution packet through `SR-PROVIDER-001`.

**Why**:

- The prior authorization packet allowed a future bounded validation run but intentionally did not fix the exact sample / endpoint families / call budget.
- This slice records the execution packet for review before any provider call, preserving the project rule that provider work must be exact-scope, reviewed, no-secret, and manually approved.
- The packet intentionally leaves FMP split / dividend endpoint families at zero calls because no reviewed current FMP corporate-action endpoint template exists in repo evidence; execution must record that blocker unless a later reviewed mapping resolves it.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_validation_execution_packet.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_validation_execution_packet_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_validation_execution_packet_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_validation_authorization_packet_schema tests.schema.test_provider_p1_validation_execution_packet_schema tests.schema.test_provider_p1_missing_key_metrics_resolution_plan_schema -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Invalid conclusions**:

- "This slice executed FMP or SEC calls" is false; it records no provider calls and creates no `provider_samples/` files.
- "Corporate actions are now validated" is false; split / dividend endpoint families are zero-call blocked pending reviewed template mapping.
- "This authorizes provider selection, adapter, DataHub, runner consumption, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify that the execution packet exactly consumes the authorization boundary and still requires a later execute command before network access.
2. If review passes and the change is committed, a later `执行` may run only this exact five-symbol / 41-call packet after environment, gitignore, budget, no-secret, and fair-access prechecks.
3. Any broader symbols, retries, FMP split / dividend endpoint call, implementation, DataHub, Phase 7c, or production claim requires separate explicit approval and reviewed decision.

## 2026-06-03 append: Provider validation execution summary

**What changed**:

- Added `runners/us_egs_validation_packet.py`, a narrow runner that consumes only the reviewed validation execution packet, validates the fixed symbol / endpoint / budget / storage / environment / no-secret boundary, requires explicit review + execute confirmations, and writes raw payloads only under gitignored `provider_samples/us_egs_validation_packet_20260603/`.
- Added `schemas/provider_p1_validation_execution_summary.schema.json` and `tests/schema/test_provider_p1_validation_execution_summary_schema.py` for the tracked no-secret summary.
- Added `tests/provider/test_us_egs_validation_packet.py`, covering fake-client FMP / SEC calls, no-secret summary, SEC CIK skip behavior, missing-env abort-before-fetch, live confirmation gates, and raw-root restriction.
- Executed the reviewed packet after the user's post-review `执行`; generated `docs/provider_evidence_p1_us_validation_execution_summary_20260603.json`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Execution result**:

- Actual calls: 37/41 within budget; 30 FMP stable calls + 7 SEC public calls; zero retries.
- Endpoint outcomes: 32 successes, 5 FMP SIVB HTTP 402 endpoint errors, 6 skips.
- Skips: FMP split / dividend candidate families remain zero-call blocked pending current template review; TWTR / SIVB SEC submissions and companyfacts were skipped because SEC company-tickers mapping did not yield CIKs for those symbols.
- Field-presence clues: active AAPL / MSFT / JPM had all six FMP stable families successful and SEC submissions / companyfacts successful; TWTR had all six FMP stable families successful but no SEC follow-up; SIVB had only FMP profile success and five FMP stable endpoint errors.
- Tracked summary contains no secret, request URL, or raw rows; raw payloads stayed under gitignored `provider_samples/us_egs_validation_packet_20260603/`.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_validation_execution_summary_schema tests.provider.test_us_egs_validation_packet tests.schema.test_provider_p1_validation_execution_packet_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_validation_execution_summary_20260603.json
git diff --check
```

**Invalid conclusions**:

- "The provider validation packet is still unexecuted" is false after this slice.
- "The validation summary selects FMP, authorizes DataHub / Phase 7c, proves inactive / delisted coverage, proves PIT / price adjustment / corporate actions at scale, or supports production / ship-gate evidence" is false.
- "Corporate-action endpoint calls were made" is false; split / dividend families remain zero-call blocked.

**Next-step notes**:

1. Claude review should verify the runner / summary schema / generated summary / docs all preserve the fixed packet scope, no-secret boundary, raw gitignore boundary, and `SR-PROVIDER-001` open status.
2. Future provider work should route from the recorded SIVB FMP endpoint errors, TWTR / SIVB SEC CIK gaps, missing key-metrics direct fields, and still-blocked split / dividend endpoint template review.
3. Do not broaden symbols, endpoints, retries, yfinance, full-market fetches, current terms review, implementation, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence without separate explicit approval and reviewed decision.

## 2026-06-03 append: Inactive / delisted gap resolution plan

**What changed**:

- Added `schemas/provider_p1_inactive_delisted_gap_resolution_plan.schema.json`, a no-access schema for routing the TWTR / SIVB inactive-delisted coverage gap found by the provider validation execution summary.
- Added `docs/provider_evidence_p1_us_inactive_delisted_gap_resolution_plan_20260603.json`, consuming only the tracked no-secret validation summary and existing reviewed contracts.
- Added `tests/schema/test_provider_p1_inactive_delisted_gap_resolution_plan_schema.py`, covering schema / artifact validation, scope locks, exact TWTR / SIVB gap facts, no-silent-default rules, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Why**:

- The first real validation run showed mixed inactive-delisted behavior: TWTR returned all six FMP stable endpoint families but no SEC CIK follow-up; SIVB returned only FMP profile and five FMP HTTP 402 errors, also with no SEC CIK follow-up.
- Those facts are useful, but they must not become a silent coverage pass. The plan splits the blocker into FMP Basic entitlement / endpoint behavior, SEC historical CIK or symbol lookup, security-master source review, alternate-provider or paid-access decision, and a future bounded follow-up packet if the user approves it.
- This slice performs no FMP call, SEC call, raw-payload read / parse, fixture generation, security-master implementation, field mapping, provider selection, DataHub work, Phase 7c authorization, production-readiness claim, alpha evidence, or ship-gate claim.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_inactive_delisted_gap_resolution_plan.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_inactive_delisted_gap_resolution_plan_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_inactive_delisted_gap_resolution_plan_schema -v
git diff --check
```

**Invalid conclusions**:

- "TWTR FMP success proves inactive / delisted coverage" is false.
- "SIVB HTTP 402 can be treated as ordinary missing rows or a safe default" is false.
- "SEC company-tickers misses prove TWTR / SIVB do not exist or that SEC can be used as a historical security master" is false.
- "This plan authorizes another provider call, raw-payload inspection, security-master implementation, provider selection, DataHub, Phase 7c, production readiness, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify this is a no-access plan that uses only the tracked validation summary and keeps `SR-PROVIDER-001` open.
2. Any follow-up inactive / delisted call, raw-payload inspection, SEC historical CIK lookup, security-master source review, paid-access decision, alternate-provider review, DataHub work, or Phase 7c work requires separate explicit approval and reviewed packet / decision.

## 2026-06-03 append: FMP entitlement / corporate-action no-access diagnostic

**What changed**:

- Added `schemas/provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic.schema.json`, a no-access schema for the FMP Basic entitlement / SIVB 402 / split-dividend endpoint-template diagnostic.
- Added `docs/provider_evidence_p1_us_fmp_entitlement_corporate_action_no_access_diagnostic_20260603.json`, using official FMP public docs plus existing tracked validation evidence and existing gitignored SIVB 402 wrappers; no new provider call was made.
- Updated `runners/us_egs_sample_validation.py` so future non-JSON HTTP error bodies are preserved inside gitignored raw wrappers, while tracked summaries still exclude response bodies, request URLs, and secrets.
- Added schema and runner regression tests for scope locks, SIVB 402 hypothesis classification, split / dividend template candidates, no-silent-default policy, and non-JSON HTTP error body capture.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Why**:

- The previous inactive / delisted plan correctly routed SIVB 402 but could not classify whether it was Basic entitlement, SIVB-specific lifecycle behavior, historical / delisted tiering, or transient / quota behavior.
- FMP public docs identify current stable `splits` and `dividends` endpoint templates, so the split / dividend blocker is no longer "template unknown"; it is now "template identified, not called, not entitlement-cleared, not reconciled".
- SIVB 402 is not converted into a paid-wall conclusion or a missing-data default. TWTR success refutes a universal "delisted symbols always unsupported" claim and narrows the problem to SIVB / endpoint-family behavior.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_fmp_entitlement_corporate_action_no_access_diagnostic_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic_schema tests.provider.test_us_egs_sample_validation -v
git diff --check
```

**Invalid conclusions**:

- "SIVB 402 means paid wall" is unproven and prohibited as a direct conclusion.
- "SIVB 402 can be treated as missing data / zero / drop symbol" is false.
- "FMP split / dividend templates are identified, therefore corporate-action evidence is validated" is false; no split / dividend endpoint call, return calculation, or reconciliation was performed.
- "This diagnostic authorizes SIVB re-probe, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify the artifact uses only docs + existing evidence, keeps the SIVB 402 classification open, and leaves `SR-PROVIDER-001` open.
2. A real SIVB re-probe requires a separate reviewed execution packet: SIVB only, the five failed endpoint families only, max 5 calls, zero retry, $0, existing FMP key, gitignored raw capture, tracked no-secret summary, then a later user `执行`.
3. Any split / dividend endpoint call or corporate-action reconciliation also requires separate explicit approval and reviewed decision.

## 2026-06-03 append: SIVB-only FMP 402 re-probe execution packet

**What changed**:

- Added `schemas/provider_p1_sivb_reprobe_execution_packet.schema.json`, a const-locked schema for a future SIVB-only FMP 402 re-probe execution packet.
- Added `docs/provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json`, fixing `SIVB` as the only symbol, the five previously failed FMP endpoint families only, max 5 endpoint calls, zero retry, `$0`, existing FMP key only, gitignored raw body capture, tracked no-secret summary, and review / execute gates.
- Added `tests/schema/test_provider_p1_sivb_reprobe_execution_packet_schema.py`, covering schema validation, SIVB-only scope, exact endpoint families, budget / retry locks, raw / summary boundaries, classification strategy, no-silent-default policy, prohibited claims, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Why**:

- The entitlement diagnostic established that SIVB 402 remains an open hypothesis set and that a useful re-probe must capture the provider's non-JSON error body in gitignored raw storage.
- This packet turns that future call into a reviewable contract before any network access, avoiding silent broadening into active symbols, SEC calls, split / dividend calls, provider selection, DataHub, or Phase 7c.
- The future summary is constrained to category signals only: endpoint entitlement, symbol lifecycle, historical / delisted paid tier, or transient quota / provider incident. It cannot copy body text, request URLs, raw rows, or secrets.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_sivb_reprobe_execution_packet.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_sivb_reprobe_execution_packet_schema -v
git diff --check
```

**Invalid conclusions**:

- "The SIVB re-probe has run" is false.
- "This packet proves why SIVB returned HTTP 402" is false.
- "This packet authorizes active symbols, SEC calls, split / dividend calls, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.
- "The future summary may store response body text or request URLs" is false.

**Next-step notes**:

1. Claude review should verify this artifact is a contract only, with no provider call, no raw read, no runner implementation, and `SR-PROVIDER-001` still open.
2. If review passes and this slice is committed, a later user `执行` may run only the fixed SIVB-only / five-FMP-family / five-call / zero-retry packet.
3. Any broader provider work still requires separate explicit approval and reviewed decision.

## 2026-06-03 append: SIVB-only FMP 402 re-probe execution summary

**What changed**:

- Added `runners/us_egs_sivb_reprobe_packet.py`, a narrow runner that consumes only the reviewed SIVB packet, validates the fixed symbol / endpoint / budget / storage / environment / no-secret boundary, requires explicit review + execute confirmations, and writes raw payloads only under gitignored `provider_samples/us_egs_sivb_reprobe_20260603/`.
- Added `schemas/provider_p1_sivb_reprobe_execution_summary.schema.json` and `docs/provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json` for the tracked no-secret execution summary.
- Added `tests/provider/test_us_egs_sivb_reprobe_packet.py` and `tests/schema/test_provider_p1_sivb_reprobe_execution_summary_schema.py`, covering fake 402 body capture, summary body / URL / secret exclusion, exact SIVB-only URL scope, confirmation gates, missing-env abort-before-fetch, schema validation, and scope-creep rejection.
- Executed the reviewed packet after the user's post-review `执行`; updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Execution result**:

- Actual calls: 5/5 FMP stable calls, SIVB only, zero SEC calls, zero retries.
- Endpoint outcomes: 0 successes, 5 HTTP 402 errors across the five fixed endpoint families.
- Body capture: 5/5 non-JSON bodies captured only under gitignored raw wrappers; tracked summary contains no body text, request URL, raw rows, or secret.
- Category signal: weak `historical_or_delisted_paid_tier` across the five endpoint families. This is not paid-wall proof, not inactive / delisted coverage proof, and not provider readiness.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_sivb_reprobe_execution_summary.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\us_egs_sivb_reprobe_packet.py --dry-run-env
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\us_egs_sivb_reprobe_packet.py --confirm-independent-review-pass --confirm-post-review-execute
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.provider.test_us_egs_sivb_reprobe_packet tests.schema.test_provider_p1_sivb_reprobe_execution_summary_schema -v
```

**Invalid conclusions**:

- "SIVB 402 is now proven paid-wall" is false.
- "Inactive / delisted coverage is proven" is false.
- "This authorizes SEC calls, split / dividend calls, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.
- "Tracked summary may store response body text or request URLs" is false.

**Next-step notes**:

1. Claude review should verify the runner / summary schema / generated summary / docs preserve the five-call boundary, raw gitignore boundary, no-secret summary boundary, weak category-signal wording, and `SR-PROVIDER-001` open status.
2. Future provider work should not rerun or broaden SIVB silently. Any broader inactive / delisted follow-up, FMP split / dividend endpoint call, current terms review, provider selection, DataHub, or Phase 7c work requires separate explicit approval and reviewed decision.

## 2026-06-03 append: FMP paid-tier / license public-docs review

**What changed**:

- Added `schemas/provider_p1_fmp_paid_tier_license_public_docs_review.schema.json`, a const-locked schema for a public-docs-only FMP pricing / endpoint / license review.
- Added `docs/provider_evidence_p1_us_fmp_paid_tier_license_public_docs_review_20260603.json`, recording FMP public pricing-plan, endpoint-doc, and Terms signals without API calls, signup, purchase, trial, account changes, provider contact, raw reads, provider selection, DataHub, Phase 7c, production-readiness, legal-clearance, or ship-gate claims.
- Added `tests/schema/test_provider_p1_fmp_paid_tier_license_public_docs_review_schema.py`, covering schema validation, source refs, plan observations, endpoint-template observations, terms observations, no-route-selection boundaries, no-silent-default policy, prohibited claims, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/provider_evidence_drift_monitor.md`, and `docs/system_risk_register.md`; `SR-PROVIDER-001` remains open.

**Plain result**:

- FMP Basic remains usable only for the narrow active-symbol evidence already proven; it does not cover SIVB or complete inactive / delisted needs.
- Paid FMP may help because public pages show higher history / feature tiers, but public pages do not prove SIVB access or inactive / delisted coverage.
- Public Terms review does not clear local raw retention, DataHub storage, redistribution, or legal use.
- No provider route was selected.

**Why**:

- SIVB re-probe narrowed the gap to a subscription / historical-or-delisted signal, but not enough to decide provider or paid tier.
- The earlier 2026-06-02 license-storage review did not perform a current public-terms web refresh; this fills that public-docs gap without replacing user / legal judgment.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool schemas\provider_p1_fmp_paid_tier_license_public_docs_review.schema.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m json.tool docs\provider_evidence_p1_us_fmp_paid_tier_license_public_docs_review_20260603.json
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_provider_p1_fmp_paid_tier_license_public_docs_review_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
git diff --check
```

**Invalid conclusions**:

- "Paid FMP is proven to fix SIVB" is false.
- "Public pricing / endpoint docs prove inactive-delisted coverage" is false.
- "Public Terms review clears storage / license / legal use" is false.
- "This authorizes paid upgrade, API calls, provider selection, DataHub, Phase 7c, production readiness, alpha evidence, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify this slice is public-docs only, keeps all scope locks false, and leaves `SR-PROVIDER-001` open.
2. Any paid upgrade, account change, provider contact, API call, raw parse, provider selection, DataHub, or Phase 7c work requires separate explicit approval and reviewed decision.

## 2026-06-03 append: temporary US free-data working boundary

**What changed**:

- Current working posture is cost-saving and temporary: no buying / adding specialized US delisted data for now.
- This is not a final provider or spending decision; the user may later buy / connect EODHD, Norgate, Sharadar, paid FMP, or another source.
- Updated `AGENTS.md`, `docs/CURRENT.md`, `docs/system_risk_register.md`, and `docs/SESSION_LOG.md`.

**Plain result**:

- US work may continue with FMP Basic / SEC EDGAR only as exploration, paper, minimal-size, or live-normalized forward-evidence accumulation.
- US historical backtests with inactive / delisted, PIT, price-adjustment, corporate-action, and license / storage gaps are reference-only.
- They cannot prove alpha, support full-size manual use, authorize DataHub / Phase 7c / production readiness, or count as ship-gate evidence.
- A-share 35% / US 65% capital policy remains unchanged. Unvalidated US allocation stays in US cash / paper / minimal buckets unless the user explicitly makes a manual transfer decision.
- Revisit trigger: when a US idea shows forward-live promise, or when the user asks.

**Next-step notes**:

1. Future LLMs must not use free-data US historical backtests to justify full-size US sizing.
2. Any paid data, specialized source, provider selection, DataHub, or Phase 7c work still requires separate explicit approval and reviewed decision.

## 2026-06-03 append: Phase 7c-a DataHub job-spec runtime enforcement

**What changed**:

- Added `engine/datahub/job_spec_contract.py` as the code-level pre-execution validator for future DataHub / runner / report job specs.
- Added `engine/datahub/__init__.py`.
- Added `tests/schema/test_datahub_job_spec_contract.py`, covering the schema example, reviewed executable plans, heavy-run approval, resource-budget profile matching, market/lane mismatch, bounded date windows, blocking gates, scope-creep rejection, resource-budget lane-concurrency bounds, and non-mutation.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/datahub_design.md`, `docs/system_risk_register.md`, and `docs/SESSION_LOG.md` to route the helper.

**Plain result**:

- Future executable DataHub / runner / report jobs must call `validate_datahub_job_spec_contract` or `validate_datahub_job_spec_file` before running.
- This closes the current `SR-RESOURCE-001` code-level enforcement gap.
- It still does not fetch provider data, select a provider, create DataHub tables, implement adapters, change production runners, authorize Phase 7c broad implementation, prove local-machine capacity, or count as ship-gate evidence.
- `SR-PROVIDER-001` remains open.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_job_spec_contract tests.schema.test_datahub_local_resource_budget_schema tests.schema.test_datahub_job_spec_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Python313 DataHub suite: 27 tests, all pass.
- Python313 full unittest discover: 551 tests, all pass.
- `docs/CURRENT.md` line count = 149.
- `git diff --check` passed with only normal LF/CRLF working-copy warnings.

**Invalid conclusions**:

- "Phase 7c DataHub implementation is done" is false.
- "US provider data can now feed DataHub / runner" is false.
- "Full-market / all-lane / full-refresh local jobs are default-allowed" is false.
- "This closes `SR-PROVIDER-001`" is false.

**Next-step notes**:

1. Claude review should verify that the helper cannot be bypassed by future executable job specs in documented routing, and that the helper rejects provider calls, DataHub table implementation authorization, runner changes, production consumption, all-market / all-lane / full-refresh behavior, raw writes, and ship-gate claims.
2. After review and commit, the natural next Phase 7c slice is still implementation-design for the shared layer / report contracts / reproducibility plumbing. It must consume this helper and cannot use unresolved US provider evidence as production input.

## 2026-06-03 append: Phase 7c shared-layer / report / reproducibility contract batch

**What changed**:

- Added `schemas/datahub_shared_layer_contract.schema.json` and `docs/datahub_shared_layer_contract_20260603.json`.
- Added `schemas/datahub_report_contract.schema.json` and `docs/datahub_report_contract_20260603.json`.
- Added `schemas/datahub_reproducibility_manifest.schema.json` and `docs/datahub_reproducibility_manifest_contract_20260603.json`.
- Added `tests/schema/test_datahub_phase7c_contract_batch.py`, validating all three schemas/artifacts, ODS / DWD / DWS / factor coverage, report-family coverage, reproducibility requirements, no-secret / no-raw policies, and scope-creep rejection.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, and `docs/datahub_design.md`.

**Plain result**:

- DataHub now has the next schema-first baseline: what shared layers are allowed to contain, what reports must say / must not say, and what a future reproducibility manifest must record.
- This is still not a DataHub implementation. No table was created, no report generator was implemented, no manifest writer was implemented, no runner was changed, and no provider data was consumed.
- Future executable DataHub / runner / report work must still create a reviewed job spec and pass `engine/datahub/job_spec_contract.py` before running.
- `SR-PROVIDER-001` remains open; US provider data is still not production usable.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_phase7c_contract_batch -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_phase7c_contract_batch tests.schema.test_datahub_job_spec_contract tests.schema.test_datahub_local_resource_budget_schema tests.schema.test_datahub_job_spec_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Python313 target test: 6 tests, all pass.
- Python313 DataHub suite: 33 tests, all pass.
- Python313 full unittest discover: 557 tests, all pass.
- `docs/CURRENT.md` line count = 149.
- `git diff --check` passed with only normal LF/CRLF working-copy warnings.

**Invalid conclusions**:

- "Phase 7c implementation is done" is false.
- "DataHub tables / reports / manifest writer now exist" is false.
- "US provider data can now feed DataHub or reports" is false.
- "This authorizes production runner consumption, ship-gate evidence, or full-size sizing" is false.

**Next-step notes**:

1. Claude review should treat this as one coherent batch: three schema-first DataHub contracts plus routing docs and tests.
2. After review and commit, the next natural Phase 7c slice is data-quality monitor contract or a reviewed implementation-design packet for one minimal local A-share-only DataHub read path. Any executable implementation still needs a job spec and must not use unresolved US provider evidence.

## 2026-06-03 append: Phase 7c data-quality monitor + minimal A-share read-path planning batch

**What changed**:

- Added `schemas/datahub_data_quality_monitor_contract.schema.json` and `docs/datahub_data_quality_monitor_contract_20260603.json`.
- Added `schemas/datahub_minimal_a_share_read_path_plan.schema.json` and `docs/datahub_minimal_a_share_read_path_plan_20260603.json`.
- Added `tests/schema/test_datahub_data_quality_and_minimal_read_path_contracts.py`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/datahub_design.md`, and `docs/SESSION_LOG.md`.

**Plain result**:

- DataHub now has a schema-first quality gate: future outputs cannot silently pass if coverage, freshness, PIT/as-of, survivorship, corporate-action, calendar, incident, or outlier checks are missing or failing.
- The first future read-path is intentionally small: A-share short lane, one as-of day, local cache / fixture only, reviewed job spec, job-spec helper pass, manifest, and data-quality summary.
- This is still not a DataHub implementation. It does not run a monitor, read cache, call Tushare/FMP/SEC, create tables, change runners, authorize production use, or provide ship-gate evidence.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_data_quality_and_minimal_read_path_contracts -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_datahub_data_quality_and_minimal_read_path_contracts tests.schema.test_datahub_phase7c_contract_batch tests.schema.test_datahub_job_spec_contract tests.schema.test_datahub_local_resource_budget_schema tests.schema.test_datahub_job_spec_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Python313 target test: 5 tests, all pass.
- Python313 DataHub suite: 38 tests, all pass.
- Python313 full unittest discover: 562 tests, all pass.
- `docs/CURRENT.md` line count = 149.
- `git diff --check` passed with only normal LF/CRLF working-copy warnings; targeted secret scan found only no-secret field names and schema URLs.

**Invalid conclusions**:

- "DataHub quality monitor is implemented" is false.
- "A-share local read-path has run" is false.
- "Provider / Tushare data can now feed DataHub" is false.
- "This authorizes production runner consumption, ship-gate evidence, or full-size sizing" is false.

**Next-step notes**:

1. Claude review should verify all scope locks stay false and that the minimal read-path plan cannot become a provider/Tushare/full-market job by schema mutation.
2. After review and commit, the next natural Phase 7c slice is a separate reviewed implementation packet for the minimal A-share local-cache read path. Any execution still needs a reviewed job spec and must pass `engine/datahub/job_spec_contract.py`.

## 2026-06-03 append: US active-only + forward-validation operating model

**Plain result**: the current US model is active-only universe + live-normalized forward evidence only. US historical backtests are exploration / idea-only and never count as alpha, ship-gate, full-size, DataHub, or production evidence.

**Boundary**: inactive / delisted historical coverage is user-accepted as scoped out for now, not proven solved. Forward universes must be frozen point-in-time at the forward start date, and real halt / delisting / merger / no-trade outcomes during forward validation must be captured. `SR-PROVIDER-001` remains open for license / storage, active PIT if fundamentals are used, active price / corporate-action semantics if used, SEC parser / mapping if used, fallback / stability, provider selection, DataHub / runner consumption, and production readiness.

## 2026-06-03 append: A-short steady alpha re-audit preregistration

**What changed**:

- Added `schemas/a_short_steady_alpha_reaudit_preregistration.schema.json`.
- Added `research/preregistrations/a_short_steady_alpha_reaudit_20260603.json`.
- Added `research/ledgers/a_short_steady_alpha_reaudit_program_test_budget_ledger_20260603.json`.
- Extended `schemas/program_test_budget_ledger.schema.json` so `a_short_steady` can use a planned-test ledger with zero spent tests.
- Added `tests/schema/test_a_short_steady_alpha_reaudit_preregistration_schema.py`.
- Updated `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`, `docs/system_risk_register.md`, `research/README.md`, and `docs/SESSION_LOG.md`.

**Plain result**:

- A-short steady alpha is still not proven.
- The next test is frozen: check whether the old 5d CSI1000 clue survives same-anchor correction.
- The future run must also report 20d / CSI300 and check multiple testing, monthly / stock concentration, regime slices, factor exposure, veto/filter usefulness, and PIT / survivorship.
- This slice does not run the result. It only registers the plan and planned-test budget.

**Validation commands**:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_a_short_steady_alpha_reaudit_preregistration_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_a_short_steady_alpha_reaudit_preregistration_schema tests.schema.test_research_preregistration_schema -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -v
(Get-Content -Encoding UTF8 docs\CURRENT.md).Count
git diff --check
```

**Validation results**:

- Python313 target test: 8 tests, all pass.
- Python313 target + research regression: 33 tests, all pass.
- Python313 full unittest discover: 570 tests, all pass.
- `docs/CURRENT.md` line count = 148.
- `git diff --check` passed with only normal LF/CRLF working-copy warnings.
- New-file sensitive-pattern scan found no API key, request URL, secret, or credentials text.

**Invalid conclusions**:

- "A-short steady alpha is validated" is false.
- "The outcome run has been authorized" is false.
- "A-short steady can now be full-size" is false.
- "This authorizes DataHub, provider work, runner changes, production use, or ship-gate evidence" is false.

**Next-step notes**:

1. Claude review should verify the preregistration is scoped to A-short steady, not a hidden burst rescue or parameter search.
2. If review passes and the user later gives `执行`, run only the frozen same-anchor re-audit on existing local evidence and write a research-only evidence report.

## 2026-06-03 append: A-short steady alpha re-audit outcome repair

**Plain result**:

- The old 5d CSI1000 clue did not survive the repaired same-anchor statistical gate.
- A-short steady remains risk-filter-only / research reference, not alpha evidence.
- It cannot support full-size manual use or ship-gate evidence.

**What changed**:

- Added `runners/a_short_steady_alpha_reaudit.py`.
- Added `tests/test_a_short_steady_alpha_reaudit_runner.py`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/evidence_report.json`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/diagnostics.json`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/monthly_stats.csv`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/metric_summary.csv`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/stock_concentration.csv`.
- Added `research/results/a_short_steady_alpha_reaudit_20260603/veto_filter_stats.csv`.
- Updated `research/ledgers/a_short_steady_alpha_reaudit_program_test_budget_ledger_20260603.json` from planned to spent.
- Updated `AGENTS.md`, `docs/CURRENT.md`, `docs/README.md`, `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`, `docs/system_risk_register.md`, `docs/phase7a_alpha_plausibility_audit.json`, `research/README.md`, and `docs/SESSION_LOG.md`.

**Key numbers**:

- 5d CSI1000 true same-anchor net excess mean: `0.6158673222` pp.
- 5d CSI1000 monthly clustered t-stat: `1.7623850474`.
- Old uncorrected 5d CSI1000 monthly t-stat: `2.8769227582`.
- Positive months: 14/23.
- Bonferroni-normal adjusted p: `0.3120170532`.
- 20d CSI1000 monthly t-stat: `-0.0994154668`.
- 5d CSI300 monthly t-stat: `0.9291247792`.

**Important limitation**:

- `runners/a_short_steady_alpha_reaudit.py` now re-derives benchmark entry-open to exit-close returns from local `forward_daily.pkl`; old `rank_samples.csv` excess columns are uncorrected controls only.
- `SR-ALPHA-001` is resolved for this clue because the repaired test failed before promotion; any future candidate still needs preregistered regime / factor checks.

**Invalid conclusions**:

- "A-short steady alpha is proven" is false.
- "The old uncorrected 5d t-stat can be treated as same-anchor evidence" is false.
- "A-short steady can be full-size" is false.
- "This is ship-gate evidence" is false.
- "This authorizes DataHub, provider work, runner consumption, strategy rule changes, or parameter rescue" is false.

**Next-step notes**:

1. Claude review should verify this repaired outcome used the local benchmark-open cache, did not fetch data, rerun EGS, alter production outputs, or overclaim sizing.
2. After review and commit, do not rerun this result. Any new alpha search needs a new reviewed preregistration and user approval.

## 2026-06-03 append: A-long data-integrity audit preregistration

**Plain result**:

- Current active alpha-search route is A-long only.
- A-short 5d is not rescued; it remains risk-filter-only / forward-observation-only after the repaired same-anchor test failed its statistical gate.
- A-long must pass hard data-integrity checks and declare a usable signal-search window before any signal-search preregistration can be created.

**What changed**:

- Added `schemas/a_long_data_integrity_audit_preregistration.schema.json`.
- Added `research/preregistrations/a_long_data_integrity_audit_20260603.json`.
- Added `research/ledgers/a_long_data_integrity_audit_program_test_budget_ledger_20260603.json`.
- Extended `schemas/program_test_budget_ledger.schema.json` with `a_long_data_integrity`.
- Added `tests/schema/test_a_long_data_integrity_audit_preregistration_schema.py`.
- Updated `AGENTS.md`, `docs/CURRENT.md`, `docs/README.md`, `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`, `docs/strategy_design_synthesis.md`, `docs/long_alpha_spec.md`, `docs/provider_data_requirements_audit.md`, `docs/system_risk_register.md`, `research/README.md`, and `docs/SESSION_LOG.md`.

**Frozen audit checks**:

1. Frozen schedule + runner self-tests: monthly last A-share trading day `2018-01-31..2025-12-31`; future runner must prove planted violations fire before trusting real output.
2. PIT fundamentals: Tushare `income`, `balancesheet`, `fina_indicator`; `ann_date > as_of` tolerance = 0 hard fail; missing / invalid `ann_date` is excluded and reported, not a global hard fail.
3. Restatement / revision as-of: same `ts_code + end_date` may use only the version known at the as-of date.
4. PIT universe / survivorship: no replaying today's active list / constituents into history; later delisted or suspended names must not be silently removed from eligible historical periods, and held delisting terminal returns must be captured.
5. Return / benchmark measurement: dividend + `adj_factor` total return, frozen qfq/hfq treatment, same entry/exit anchors, same-anchor benchmark excess, terminal delisting returns, no silent zero fill.
6. Temporal coverage: yearly required fundamental-table coverage is characterized to declare the usable start year; sparse early years do not globally fail the lane.

**Invalid conclusions**:

- "A-long alpha search is authorized" is false.
- This preregistration slice did not run the audit; see the later execution append below for the now-run blocked result.
- "A-long data is proven clean" is false.
- "This permits production / ship-gate / full-size use" is false.

**Next-step notes**:

1. Claude review should verify this is an executable hard-check + usable-window preregistration, not another descriptive contract.
2. Superseded by the later execution append below: the frozen data-integrity audit has now run and is blocked.
3. If any hard check fails or blocks, repair the data route before any signal backtest. If hard checks pass in a future repaired audit, create a separate reviewed A-long signal-search preregistration limited to the declared usable window.

## 2026-06-03 append: A-long data-integrity audit execution

**Plain result**:

- The frozen audit ran local-cache-only after Claude review and user `执行`.
- `research/results/a_long_data_integrity_audit_20260603/audit_report.json` is `blocked_missing_required_source`.
- Self-tests passed 6/6, so the runner can catch planted bad data.
- Real local data is not enough: raw PIT fundamentals, full PIT universe, dividend / total-return handling, and terminal delisting return lineage are missing.
- A-long signal search is still not authorized.

**What changed**:

- Added `runners/a_long_data_integrity_audit.py`.
- Added `schemas/a_long_data_integrity_audit_report.schema.json`.
- Added `tests/test_a_long_data_integrity_audit_runner.py`.
- Wrote `research/results/a_long_data_integrity_audit_20260603/audit_report.json`, `check_summary.csv`, and `coverage_by_year.csv`.
- Updated the A-long ledger to `active_no_new_test_authorized` with status `spent_voided_by_data_integrity_failure`.

**Next-step notes**:

1. Do not rerun the spent A-long data audit without a new reviewed authorization.
2. Repair or replace the A-long data route first: raw PIT fundamentals with `ann_date` / `end_date`, full PIT universe, dividend / total-return treatment, and terminal delisting return lineage.
3. Only after a repaired data route passes a new reviewed audit may A-long create a separate signal-search preregistration.

## 2026-06-04 append: A-long full-period fixed-panel audit execution

**Plain result**:

- The 2018-2025 fixed panel is downloaded, but it still cannot be used to find alpha.
- The full-period raw-only audit failed with two hard data-route blockers.
- Blocker 1: `fina_indicator` has 6 same-ann-date duplicate conflicts on `profit_dedt`.
- Blocker 2: delisted sample `000666.SZ` has no SW membership rows in the materialized membership payload.

**What changed**:

- Added `runners/a_long_materialized_full_period_data_integrity_audit.py`.
- Added `schemas/a_long_materialized_full_period_data_integrity_audit_report.schema.json`.
- Added `tests/test_a_long_materialized_full_period_data_integrity_audit.py`.
- Added `tests/schema/test_a_long_materialized_full_period_data_integrity_audit_schema.py`.
- Wrote `research/results/a_long_materialized_full_period_data_integrity_audit_20260604/audit_report.json`, `check_summary.csv`, and `coverage_by_year.csv`.

**Passed parts**:

- PIT `ann_date` gating is feasible for the fixed panel.
- Terminal delisting return inputs exist for `000666.SZ`.
- Daily / adj_factor / dividend source shape and CSI300 / CSI1000 open-close benchmark inputs exist.
- Temporal coverage meets the threshold from 2018 for the fixed panel.

**Next-step notes**:

1. Do not start A-long signal search.
2. Repair `fina_indicator` duplicate handling/source lineage and SW membership coverage for `000666.SZ`.
3. Rerun the full-period audit after the repair.

## 2026-06-04 append: A-long full-period audit blocker repair rerun

**Plain result**:

- A-long still cannot search for alpha.
- The `profit_dedt` duplicate blocker is repaired.
- One blocker remains: delisted sample `000666.SZ` still has no SW membership rows.

**What changed**:

- `runners/a_long_materialized_full_period_data_integrity_audit.py` now resolves same `ts_code` / `end_date` / `ann_date` duplicate rows only when the only differing field is an allowed nullable field (`profit_dedt`) and exactly one non-null value exists.
- Any other same-ann-date duplicate difference remains a hard failure.
- The rerun report records 6 resolved `profit_dedt` duplicate groups and `restatement_revision_asof = pass_fixed_panel`.
- The rerun report still records `survivorship_pit_universe = fail_data_not_ready` because `sw_membership_missing_symbols = ["000666.SZ"]`.

**Next-step notes**:

1. Do not start A-long signal search.
2. Repair or supplement the `000666.SZ` SW industry source under review.
3. Rerun the full-period audit after that repair.

## 2026-06-04 append: A-long 000666 SW membership supplement packet

**Plain result**:

- The next packet is prepared, but it has not run.
- It targets only the remaining `000666.SZ` SW membership gap.
- It allows at most 3 fixed Tushare calls after Claude PASS plus user `执行`.
- It still does not make A-long data usable for alpha.

**What changed**:

- Added `schemas/a_long_000666_sw_membership_supplement_packet.schema.json`.
- Added `docs/a_long_000666_sw_membership_supplement_packet_20260604.json`.
- Added `runners/a_long_000666_sw_membership_supplement_packet.py`.
- Added `schemas/a_long_000666_sw_membership_supplement_execution_summary.schema.json`.
- Added tests for fake execution, no-candidate routing, dry-run status, no-secret/no-raw tracked summary, and scope-creep rejection.

**Next-step notes**:

1. Do not run the supplement until independent review passes and the user gives a separate `执行`.
2. If the supplement finds a candidate source, wire it into a reviewed audit repair and rerun the full-period audit.
3. Do not start A-long signal search until the repaired audit passes.

## 2026-06-04 append: A-long 000666 SW membership supplement execution

**Plain result**:

- The reviewed 3-call supplement ran.
- Later review reclassified this result as inconclusive, not a reliable no-source finding.
- Therefore the combined "supplement + audit repair + audit rerun + alpha prereg" package correctly stopped at the first gate, but the source gap needs a corrected probe before any no-source/design decision.
- A-long still cannot search for alpha.

**Result details**:

- `stock_basic` succeeded and confirmed `000666.SZ` exists in the delisted list, but it did not request `industry` / `area`.
- `index_member` returned an interface-name error, so that leg did not test data.
- `index_member_all(ts_code=000666.SZ)` returned zero rows.
- `docs/a_long_000666_sw_membership_supplement_execution_summary_20260604.json` records `partial_or_failed_supplement_probe`.

**Next-step notes**:

1. Do not patch audit or rerun it from this inconclusive supplement.
2. Next route is the corrected reviewed 4-call supplement packet; only after that result can a source/design decision be made.
3. Do not start A-long signal search until a repaired audit passes.

## 2026-06-04 append: A-share main-board-only scope guard

**Plain result**:

- User confirmed A-share trading access is main-board only.
- A-short already excludes ChiNext / STAR / BSE before analysis.
- A-long current path now enforces the same main-board-only boundary.
- The old A-long 2018-2025 panel included `300750.SZ` (ChiNext), so it is historical-only and cannot be used for current audit rerun, alpha search, production, ship-gate, or full-size evidence.

**Changed boundary**:

- `engine/data/a_share_board_scope.py` defines the shared A-share board classifier.
- `runners/a_long_tushare_broader_materialization_packet.py` now uses `600887.SH` instead of `300750.SZ` in the active fixed panel.
- `runners/a_long_materialized_full_period_data_integrity_audit.py` rejects any materialization summary whose active symbols include non-main-board names.
- `002` / `003` Shenzhen names remain allowed as main-board names; `300/301`, `688/689`, `.BJ`, `920`, `8`, and `4` are rejected for the current A-share scope.

**Next route**:

1. Do not start A-long signal search from the old `300750.SZ` panel.
2. After review and commit, the next data step is a reviewed main-board-only fixed-panel replacement, then a repaired data-integrity audit path.
3. No provider call, data fetch, audit rerun, or alpha search was executed in this guard slice.

## 2026-06-04 append: A-long main-board candidate-universe preflight

**Plain result**:

- The fixed-panel data route passed, but the full main-board A-long alpha run is still blocked.
- The block is not compute capacity. It is data readiness: the full candidate universe does not yet have accepted industry coverage.
- Existing raw has 3,200 main-board active names; 1,193 active names are missing SW membership in the existing raw.
- A 4-call preflight showed `index_member_all(ts_code=...)` can supplement active missing SW rows.
- 187 main-board names delisted during 2018-2025 still lack SW membership under the current route, so delisted no-industry handling must be reviewed before full alpha search.

**What changed**:

- Added `runners/a_long_main_board_candidate_universe_preflight.py`.
- Added `schemas/a_long_main_board_candidate_universe_preflight_execution_summary.schema.json`.
- Added tracked summary `docs/a_long_main_board_candidate_universe_preflight_execution_summary_20260604.json`.
- Added tests for blocking behavior, no-raw tracked summaries, schema validation, and scope-creep rejection.

**Next route**:

1. Do not start the full A-long alpha pull/search yet.
2. Next combined package should supplement active SW membership and make a reviewed delisted no-industry boundary decision.
3. Only after that universe gate passes should the project proceed to full-period data pull and signal execution.

## 2026-06-04 append: A-long main-board SW coverage repair

**Plain result**:

- The combined repair ran, but A-long is still not ready for full alpha.
- Active missing SW membership fell from 1,193 to 4.
- The remaining active symbols are `600421.SH`, `600599.SH`, `600636.SH`, and `600696.SH`.
- All four are `退市*`-named `stock_basic` rows still marked `list_status = L`, with no `stock_basic.industry` / `area` and no `index_member_all(ts_code=...)` rows.
- The 187 delisted missing-SW names now have no-usable-SW-source evidence under the scaled delisted-only boundary; exception rate is 5.52111%, within the 12.5% cap.

**What changed**:

- Added `runners/a_long_main_board_sw_coverage_repair.py`.
- Added `schemas/a_long_main_board_sw_coverage_repair_execution_summary.schema.json`.
- Added tracked summary `docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json`.
- Added tests for fake pass/block behavior, no-raw tracked summaries, schema validation, and scope-creep rejection.
- Raw repair payloads are only under gitignored `data/a_long/raw/tushare/main_board_sw_coverage_repair_20260604/`.

**Next route**:

1. Do not start full alpha pull/search yet.
2. Next package should handle the four active `退市*` unresolved names through a reviewed active-name boundary or a repaired source.
3. The delisted-only boundary must not be silently applied to active symbols.

## 2026-06-05 append: A-long four active-name delisting-shell repair

**Plain result**:

- Claude rejected the four-name manual SW 2021 patch as the wrong fix.
- The four active unresolved names are now identified as `退市*` delisting-shell rows: `600421.SH`, `600599.SH`, `600636.SH`, and `600696.SH`.
- The refreshed SW repair summary reused existing raw payloads and made no new Tushare call.
- Candidate industry handling is still blocked. This is not alpha, production, ship-gate evidence, or full-size permission.

**What changed**:

- Removed the manual SW 2021 patch route and deleted the patch schema / artifact / tests.
- Updated `runners/a_long_main_board_sw_coverage_repair.py` and `docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json` so active `退市*` shells are detected but do not close the gate.
- Added tests proving a `退市*` active row remains blocked without scaled boundary approval.

**Next route**:

1. Superseded by the next append: the 191-name boundary packet is now prepared.
2. Claude should review the repair and boundary packet together before commit.
3. Do not run full alpha search before that boundary passes.

## 2026-06-05 append: A-long final pre-full-pull no-industry boundary packet

**Plain result**:

- The full pull still has not run.
- The last pre-full-pull decision packet is now written: `docs/a_long_scaled_delisted_no_industry_boundary_decision_20260605.json`.
- It recommends one boundary: 191 no-industry names (`187` already delisted + `4` active `退市*` shell rows) stay in returns/risk, but are excluded only from industry-normalization denominators.
- It blocks manual industry fill, silent default industry, and dropping these names from returns/risk.
- It still authorizes no alpha, no production, no ship-gate evidence, and no full-size use.

**What changed**:

- Added `schemas/a_long_scaled_delisted_no_industry_boundary_decision.schema.json`.
- Added `docs/a_long_scaled_delisted_no_industry_boundary_decision_20260605.json`.
- Added `tests/schema/test_a_long_scaled_delisted_no_industry_boundary_decision_schema.py`.
- Updated routing docs / CURRENT / risk register / research README / session log.

**Next route**:

1. Claude should review the SW repair plus this boundary packet together.
2. If Claude passes and the user approves, the next separate package can be the full main-board pull plus signal-search execution.
3. Do not run the full pull from this artifact alone.

## 2026-06-05 append: A-long full main-board execution packet prepared

**Plain result**:

- The 191-name no-industry boundary passed Claude review, received user approval, and was committed in `e51798b`.
- The next large execution package is now prepared: `docs/a_long_full_main_board_signal_search_execution_packet_20260605.json`.
- The package locks main-board only, 2018-2025, 3,387 candidate names, 23,717 planned Tushare calls, checkpoint/resume, full data-integrity audit before signal search, and the frozen A-long signal families.
- The signal preregistration now references the approved 191-name boundary instead of the old single `000666.SZ` exception.
- This slice still executes no network call and computes no alpha.

**What changed**:

- Added `schemas/a_long_full_main_board_signal_search_execution_packet.schema.json`.
- Added `docs/a_long_full_main_board_signal_search_execution_packet_20260605.json`.
- Added `tests/schema/test_a_long_full_main_board_signal_search_execution_packet_schema.py`.
- Updated the A-long signal-search preregistration / ledger boundary wording and routing docs.

**Next route**:

1. Claude should review this execution packet plus the synchronized preregistration boundary update.
2. If Claude passes and the user approves / commits, a later explicit execute command can run the real full main-board pull.
3. The real run must stop after data pull if the full data-integrity audit fails; signal search runs only after audit pass.

## 2026-06-05 append: A-long full main-board materialization runner package

**Plain result**:

- The execution packet has passed review / commit, but the full raw pull has still not run.
- Added the runner for only the first executable stop: 2018-2025 full main-board raw materialization.
- This runner does not run the full data-integrity audit and does not search alpha.
- Tracked summary is intentionally small: endpoint-level details go to a gitignored manifest, not into tracked docs.

**What changed**:

- Added `runners/a_long_full_main_board_materialization_packet.py`.
- Added `schemas/a_long_full_main_board_materialization_execution_summary.schema.json`.
- Added `tests/test_a_long_full_main_board_materialization_packet.py`.
- Added `tests/schema/test_a_long_full_main_board_materialization_execution_summary_schema.py`.
- Updated routing/status docs.

**Runner boundaries**:

- Validates `docs/a_long_full_main_board_signal_search_execution_packet_20260605.json`.
- Validates the approved 191-name no-industry boundary and prior active SW repair summary.
- Locks 23,717 planned Tushare calls, max 24,000, zero retry, 1.25s pacing, checkpoint/resume.
- Stops before symbol calls if the base `stock_basic` universe no longer matches 3,200 active + 187 delisted.
- Writes raw payloads and endpoint manifest only under gitignored `data/a_long/raw/tushare/full_main_board_signal_search_20260605/`.
- Does not authorize audit, signal search, alpha, production, ship-gate evidence, full-size use, DataHub, or broker/order automation.

**Next route**:

1. Claude should review the runner, summary schema, tests, and docs for scope creep.
2. If Claude passes and the user approves / commits, a later explicit execute command may run the ~8h full raw materialization.
3. After materialization passes, the next separate gate is full main-board data-integrity audit. Signal search still waits for audit pass.

## 2026-06-05 append: A-long full main-board data-integrity audit failed

**Plain result**:

- The full raw materialization completed before this append, but the data audit failed.
- Report: `research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json`.
- Simple meaning: A-long full main-board data still cannot be used to search alpha.

**What passed**:

- Fundamental PIT field shape passed.
- Time coverage is usable from 2018.
- Active investable missing industry is now 0 after consuming the reviewed supplement summary.

**What failed**:

- 3,108 same-ann-date restatement / duplicate conflict groups remain.
- 5 delisted symbols lack terminal return input near delisting: `000638.SZ`, `600355.SH`, `600485.SH`, `600677.SH`, `600680.SH`.
- 14 symbols have incomplete return-input shape.

**What changed**:

- Added `runners/a_long_full_main_board_data_integrity_audit.py`.
- Added `schemas/a_long_full_main_board_data_integrity_audit_report.schema.json`.
- Added `research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json`.
- Added `research/results/a_long_full_main_board_data_integrity_audit_20260605/check_summary.csv`.
- Added `research/results/a_long_full_main_board_data_integrity_audit_20260605/coverage_by_year.csv`.
- Added `tests/test_a_long_full_main_board_data_integrity_audit.py`.
- Added `tests/schema/test_a_long_full_main_board_data_integrity_audit_schema.py`.

**Next route**:

1. Claude should review the failed audit runner/report and the two runner fixes made during execution.
2. After review / commit, the next package should repair or explicitly route the three failed checks.
3. Do not run signal search until a repaired full audit passes.

## 2026-06-05 append: A-long full main-board data-integrity audit repaired and passed

**Plain result**:

- The repaired full audit passed.
- Report: `research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json`.
- Simple meaning: data is ready for the next reviewed signal-search gate. This is still not alpha.

**Repair treatment**:

- Same-ann-date rows with distinct `f_ann_date` are treated by as-of disambiguation: future signal code must use the latest `f_ann_date <= as_of`.
- Same-ann-date rows that still have no disambiguator are not used silently. They are written to `research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv` and must be excluded from future signal inputs.
- The ambiguous exclusion rate is `0.367838%`, below the frozen `0.5%` cap.
- The 1,189 active SW supplements are verified from reviewed repair raw, not just credited from the tracked summary.
- The 14 symbols with empty 2018-2025 daily / adj rows are all 2026 post-panel listings and are excluded from return-shape checks.
- Post-panel delists are not treated as 2018-2025 terminal-return failures; long no-trade delisted names are reported separately.

**What changed**:

- Updated `runners/a_long_full_main_board_data_integrity_audit.py`.
- Updated `schemas/a_long_full_main_board_data_integrity_audit_report.schema.json`.
- Updated `tests/test_a_long_full_main_board_data_integrity_audit.py`.
- Updated `tests/schema/test_a_long_full_main_board_data_integrity_audit_schema.py`.
- Regenerated `research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json`.
- Added `research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv`.

**Next route**:

1. Claude should review the repaired audit runner/report and the exclusion-list treatment.
2. If Claude passes and the user commits, the next separate gate may run the frozen signal search.
3. Do not treat this audit as alpha, production, ship-gate evidence, or full-size permission.

## 2026-06-05 append: A-long full main-board audit R1 route-A exclusion repair

**Plain result**:

- The prior repaired audit had one review failure: the 0.5% restatement exclusion cap lived only in the runner.
- This repair moves that cap and rule into preregistration and makes future signal search consume the exclusion CSV.
- Simple meaning: the 1,504 ambiguous rows are not being trusted; they are blocked from signal inputs.

**What changed**:

- `research/preregistrations/a_long_data_integrity_audit_20260603.json` now records the route-A amendment: `f_ann_date` as-of disambiguation when deterministic, unresolved same-ann-date groups excluded, 0.5% cap, observed 0.367838%, above cap means fail / re-review.
- `research/preregistrations/a_long_signal_search_preregistration_20260604.json` now requires future signal execution to consume `research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv` and abort if missing or unapplied.
- `runners/a_long_full_main_board_data_integrity_audit.py` now reads and cross-checks the preregistered cap, keeps the full 1,504-row list out of tracked JSON, writes the full list to CSV, and records extended no-trade terminal verification.
- `research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json` was regenerated. Full exclusion list remains in the CSV; JSON has only samples.

**Validation**:

- Local-only full audit rerun: `passed_full_main_board_data_integrity_for_signal_search`, with mandatory exclusions.
- `restatement_ambiguous_exclusions.csv` has 1,505 lines including header.
- Tests passed 36/36 for the full audit runner/report schema, data-integrity preregistration schema, and signal-search preregistration schema.

**Next route**:

1. Claude should review this R1 repair before commit.
2. If Claude passes and the user commits, the next separate gate may run the frozen signal search.
3. Do not run signal search before review / commit; this repair is still not alpha evidence.

## 2026-06-06 append: A-long signal-search runner package implemented, not executed

**Plain result**:

- The A-long signal-search runner package now exists for review.
- No true signal search has run yet, so there is still no A-long alpha result.

**What changed**:

- Added `runners/a_long_full_main_board_signal_search.py`.
- Added `schemas/a_long_signal_search_execution_summary.schema.json`.
- Added `tests/test_a_long_full_main_board_signal_search.py`.
- Added `tests/schema/test_a_long_signal_search_execution_summary_schema.py`.
- Updated routing docs and `SR-ALONG-DATA-001`.

**Execution locks**:

- The runner aborts unless both independent-review and post-review execute confirmations are passed.
- It validates the PASS full audit, unspent singleton ledger, mandatory 1,504-row restatement exclusion CSV, approved 191-name no-industry boundary, frozen four signal families, same-anchor net returns, and FDR correction.
- Future output is research-only. It cannot authorize production, ship-gate evidence, full-size use, provider selection, DataHub, or broker/order automation.

**Next route**:

1. Claude should review the runner, summary schema, tests, and docs.
2. If Claude passes and the user commits, a later explicit `执行` may run the frozen signal search.
3. If the signal search later runs, update the singleton ledger and keep any positive result as research-only until forward-live ship gate evidence exists.

## 2026-06-06 append: A-long signal-search runner optional hardening

**Plain result**:

- The optional hardening from Claude's PASS review is implemented.
- The true signal search still has not run.

**What changed**:

- Delisted names leave the scored PIT cross-section at / after `delist_date`.
- Result cells now include a single-year concentration diagnostic and gate.
- Restatement exclusion application now records expected / found raw-key counts and aborts if the 1,504 groups are not fully matched.
- A valid true signal-search run now writes the singleton ledger spend immediately after the summary.

**Next route**:

1. Claude should re-review the optional hardening.
2. If Claude passes and the user commits, a later explicit `执行` may run the frozen signal search.
3. No signal result, alpha, production, ship-gate evidence, or full-size permission exists yet.

## 2026-06-06 append: A-long signal-search R1/O2 return-contribution fix

**Plain result**:

- Claude found the first single-year guard was a dead guard because it counted cohorts.
- The runner now measures whether one calendar year contributes too much of the positive cohort excess.
- The true signal search still has not run.

**What changed**:

- Replaced `max_single_year_cohort_share` with `max_single_year_positive_return_share`.
- `passes_single_year_concentration_guard` now depends on positive-return contribution share, not monthly cohort counts.
- Added real-summary fixture tests: a year-dominated result is rejected, and a year-spread result is accepted.

**Next route**:

1. Claude should re-review only this R1/O2 delta plus the unchanged no-run state.
2. If Claude passes and the user commits, a later explicit `执行` may run the frozen signal search.
3. No signal result, alpha, production, ship-gate evidence, or full-size permission exists yet.

## 2026-06-19 append: A-long value-yield forward-paper capture repair closeout

**Plain result**:

- The A-long value-yield forward-paper capture implementation is now coherent as a research-only, per-run-gated monthly accumulator path.
- This did not run Tushare, capture a real month, spend the singleton ledger, authorize production, or authorize real-money use.

**What changed**:

- `runners/a_long_large_cap_value_yield_forward_paper_capture.py` now validates prior accumulators before fetch, rejects duplicate/out-of-order monthly `as_of`, preserves frozen cohort entry anchors, rejects incomplete month calendars / any `result/` output path, and records mixed member exit policy instead of labeling delist/terminal exits as scheduled.
- `runners/a_long_large_cap_value_yield_forward_paper_data_layer.py` now uses explicit date windows, member-scoped `index_member_all` / `namechange`, stricter min-field and returned-row lineage checks, stock-basic security-master coverage checks, and a short default post-`as_of` window to freeze the next-open entry anchor.
- `docs/README.md` now routes the capture implementation separately from the design artifact; `docs/CURRENT.md` no longer says the data layer is future work.

**Validation**:

- A-long forward-paper target modules: 84 tests OK.
- Doc-governance + route-doc guards: 30 tests OK.
- Full `unittest discover`: 2723 tests OK.
- `py_compile`, `git diff --check`, and BOM/FFFD checks passed; only CRLF warnings were reported.

**Next route**:

1. Review this A-long forward-paper repair only; do not mix in A-short, US lanes, provider selection, DataHub, or broker/order work.
2. Any real monthly capture still requires separate user authorization and the runner confirmation flags.
3. Full-size / production / ship-gate claims remain blocked until the separate forward evidence policy is met.

## 2026-08-11 追加：问题3 独立审查 FAIL（analyst 同源腿成立 / 健康身份腿未做）

- **结论**：FAIL，未提交。桌面 `us_testrun0810.md` §问题3 的 A/B 腿已成立，§2.C/§2.D 未实现。
- **已核实无问题（下一轮别改回去）**：packet 边界 `_resolve_active_analyst_source()` 单点解析、`active_source_payloads` 喂 `build_result_source_facts`、Pass2 `analyst_source` 单点派生四处 summary 语义、`fetch_fmp_grades and fmp_env is None` 的纵深门。这些是本轮真正修好的东西。
- **为什么 FAIL**：`R-USSHORT-ANALYST-SOURCE-COVERAGE-HEALTH-DRIFT` — Required 1（§2.C/§2.D 健康身份与消费腿未做，`derive_provider_health()` 零行恒 `fmp=down`，`overall_run_state` 永不可能 `clean`）、Required 2（register/SESSION_LOG 把它记成问题6 范围并给 R-ID 打 `repaired`）。取证与闭合判据只在 register。
- **顺序**：先 Required 1（health 身份 → receipt → emit → 周报 §11 一条链一起做，别只改中间 JSON），再 Required 2 更正状态位；Optional O-P3-1 待 health 消费者建起来后随手锁死。
- **唯一有效命令**：`Codex：修复`

## 2026-08-11 追加：桌面 us_testrun0810 问题3 + 问题6 修复（Codex，待 Claude 独立审查）

### 结果与实现边界

- 按当前桌面稿的去重顺序，问题3与问题6分别实现、同一工作树串行验证。问题3修复 active analyst source：source-packet 一次解析，打分与 analyst coverage 同源；Pass2 只有 FMP fallback 读 `FMP_API_KEY`；yfinance summary/coverage 诚实且不进入 global health。Optional O-P3-1 的 summary 读时语义 validator 已接入，锁定 source、key sentinel、FMP calls 与 exclusion sentinel 的交叉一致性。
- 问题6只消费 Universe、Momentum、SIC、Pass2、VIX 五个 producer 的既有结果，唯一 projector 输出八键：`universe_status`、`universe_market_cap`、`massive_momentum`、`sec_sic`、`fmp_grades`、`sec_offering_audit`、`massive_events`、`fmp_vix`。`fmp_grades` 只读 FMP 自身事实；yfinance 不进入 health facts、classifier 或 emit。
- receipt 绑定五个 producer summary 与 exact 八键 facts；report §11/§13、classifier/emit、private-write 均复核同一份事实。旧 `{fmp, sec_edgar}` 形状、缺键、多键、外来 yfinance key fail-closed。测试 incident writer 使用临时目录，未再写 canonical `state/us_short`；inventory 快照已由既有生成器同步。

### 验证与边界

- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`。
- 综合 focused：`Ran 395 tests ... OK`，receipt=`receipt:ed9ab62940115d488ec7b190`；隔离/清单/真实根增长子集 `44 OK`。
- 最终 full lane：`discover -s tests -p test_us_short*.py`，`discovered=5752 ran=5752 equal=True`，`RESULT status=PASS exit=0 tests=5752 elapsed=425.9s deadline=860s`，fingerprint 前缀 `ef075028974b`；静态 `diff_check=PASS py_compile=21`。
- 反向控制：移除 `massive_events` 时预期测试转红；让 yfinance 状态改变 global health 时预期边界测试转红；两项均已还原。没有 provider/network/live/account/real-key/真实周跑、DataHub、broker/order 或 production/ship-gate 运行。
- 状态：`R-USSHORT-ANALYST-SOURCE-COVERAGE-HEALTH-DRIFT` 与 `R-USSHORT-PROVIDER-HEALTH-EIGHT-FAMILY-CONSUMPTION-CHAIN` 均为 `repaired / OPEN-NOT_VERIFIED`。Codex 不提交；Claude Code 独立审查通过后再提交本刀覆盖文件。

## 2026-08-11 追加：问题3 复审 + 问题6 首审 —— 独立审查 FAIL

- **结论**：FAIL，未提交。八键 health 管道（projector→receipt→classifier/emit→周报 §11/§13→private-write 反向核对）是真的、做得好；三条 Required 全是**口径接错**，不是没接线。
- **已核实无问题（下一轮别改回去）**：§11/§13 的 tamper 门（private-write 把明细绑回运行级 classifier）、receipt 五份 producer digest + 八键 exact facts、旧两键 `derive_provider_health` 已只剩测试调用且无双契约残留、问题3 的 packet 边界单点解析与同源 coverage。
- **为什么 FAIL**：`R-USSHORT-PROVIDER-HEALTH-EIGHT-FAMILY-CONSUMPTION-CHAIN` Required A/B/C —— A：`_universe_health` 读 universe summary 的 worst-of `overall_run_state`（含机会性 FMP 市值兜底）且 `universe_status` 是 critical，仓内三份真实 summary 实测全 `degraded` → `restricted` → **每周硬 no-emit**；B：同函数在健康块缺失时返回 `ok`，critical 家族 fail-open；C：评级家族仍叫 `fmp_grades` 且 `calls==0→down`，一键路径下恒真，`clean` 结构性不可达。取证与闭合判据只在 register。
- **顺序**：先 A（它今天就让周报出不来），再 B（同一函数，一起改），C 需要用户先在 Options 里选口径再动手；Optional 五条随修。
- **唯一有效命令**：`Codex：修复`

## 2026-08-11 追加：问题3复审意见与问题6口径修复（238a，Codex，待 Claude 独立审查）

### 当前结果

- 上一段 `repaired` 状态已由本段更正为 `partially_repaired / OPEN-NOT_VERIFIED`；分析师健康身份属于问题3，问题6 只在 `analyst_grades` 功能身份上扩展，不能把它写成问题3已无条件闭合。
- `universe_status` 现在只从 `provider_health.status_sources.state/outcome` 派生；机会性市值兜底单独归入 non-critical `universe_market_cap`。健康块缺失、坏形状或冲突 fail-closed；真实状态源坏时仍由 critical 门阻断 emit。
- 评级家族已由 `fmp_grades` 改为 non-critical `analyst_grades`。yfinance 选择时校验 yfinance stage summary 的 provider status、计数自洽、日期、预检路径、目标数与 Pass2 来源；显式 FMP fallback 才读取真实 FMP grades rows。缺失/冲突/边界不一致降为 `down`，不会阻断 emit；yfinance 不再列入 `UNAUTHORIZED_SOURCES`。
- receipt→classifier/emit→周报 §11/§13→private-write 的共享事实链保持，六个 producer summary（Universe、Momentum、SIC、Pass2、yfinance grades、VIX）均纳入 receipt digest。

### 验证与交接

- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`；问题3/6广覆盖 `Ran 357 tests ... OK`，文档治理/路由门禁 `Ran 95 tests ... OK`，修改 Python `py_compile=20`，`git diff --check=0`。验证仅使用本地离线 fixture/临时根，不触 provider/network/live/account/real-key/生产周跑。
- 本次修复和本交接只落 `D:\cnhea\Codex\worktrees\238a\Stock`；桌面 `us_testrun0810.md` 只作 guideline，未修改；1302 不承接问题3/6。
- Codex 不提交。下一步由 Claude Code 独立审查问题3/6，复核状态源口径、analyst health 身份、receipt-bound 六 stage digest、emit/report/private-write 全链和反向控制后按流程决定是否提交。

## 2026-08-11 追加：问题3 + 问题6 修复轮 —— 独立审查 FAIL（差两行）

- **结论**：FAIL，未提交。上一轮三条 Required 全部真修好，唯一阻断是改名时漏改两个已提交样例。
- **已核实无问题（下一轮别改回去）**：`_universe_health` 改读 `status_sources.state/outcome` 并对缺失/坏形状 fail-closed；`analyst_grades` 家族由 yfinance stage summary 驱动且交叉校验 Pass2 来源身份/时钟/target 数；non-critical 不阻断 emit；`docs/us_short_system_design.md:9` 只改 provider-health 半句、保留 "never gate emit"；receipt 已绑六个 producer summary（含 yfinance）；§11/§13 tamper 双门。
- **为什么 FAIL**：`R-USSHORT-BATCH4-CONTEXT-EXAMPLE-KEEPS-THE-RENAMED-HEALTH-KEY` — 两个样例仍写 `fmp_grades`，`classify_provider_health` 抛未接住的 `ProviderHealthError`，batch4 runner exit 2，三条测试红。取证、闭合判据与六条 Optional 只在 register。
- **顺序**：改两处键名 → 顺手更正 register 第 103/105 行旧口径 → 重跑 `tests.test_us_short_weekend_batch4_context_builder` → **自己跑一次全量并记账**（本轮 `full-lane=not rerun`，而这条 P1 恰恰只有全量抓得到）→ 再看六条 Optional。
- **唯一有效命令**：`Codex：修复`

## 2026-08-11 追加：问题3 + 问题6 样例健康键修复（238a，待 Claude 独立审查）

### 结果与实现边界

- 修复 `R-USSHORT-BATCH4-CONTEXT-EXAMPLE-KEEPS-THE-RENAMED-HEALTH-KEY`：两个 batch4 context packet 示例的 `provider_health` 家族键均已从旧 `fmp_grades` 改为 `analyst_grades`，与当前 health classifier 合同一致。
- `docs/system_risk_register.md` 中上一轮遗留的两处旧口径已标为历史段落并指向当前契约；前三条 Required 保持上一轮 reviewer 已独立验证的修复状态，本轮不扩展 `O-P6R-1`~`O-P6R-6`。

### 验证与交接

- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`；focused `tests.test_us_short_weekend_batch4_context_builder`=`20 OK`，receipt=`receipt:2a5d9b70d2469355fed85474`。
- official full lane：`discover -s tests -p test_us_short*.py`，`discovered=5755 ran=5755 equal=True`，`RESULT status=PASS exit=0 tests=5755 elapsed=520.7s deadline=860s`，fingerprint=`7a7be6b95677`；静态 `diff_check=PASS`、`py_compile=21`；文档治理/路由门 `95 OK`，receipt=`receipt:e18f64ee96434a716cfb307c`。验证仅为本地离线测试/fixture，不触 provider/network/live/account/real-key/生产周跑。
- 本次修复与交接只落 `D:\cnhea\Codex\worktrees\238a\Stock`；桌面 `us_testrun0810.md` 只作 guideline，未修改；1302 不承接问题3/6；Codex 不提交。当前结论仍为 `OPEN-NOT_VERIFIED`，下一步由 Claude Code 独立审查并按流程决定是否提交。

## 2026-08-11 追加：问题3 + 问题6 —— 独立审查 PASS 并收口

- **结论**：PASS，已提交并合入 master。桌面 `us_testrun0810.md` 的问题3与问题6 全链闭合。
- **已核实无问题（下一轮别改回去）**：八键功能族契约（`analyst_grades` 由 yfinance stage summary 驱动、non-critical 不阻断 emit）、`universe_status` 只读 `status_sources.state/outcome` 且缺证据 fail-closed、机会性市值兜底只进 `universe_market_cap`、receipt 绑六个 producer summary、§11/§13 tamper 双门、两份 batch4 样例与八键契约一致。
- **本轮做了什么**：只把两份样例的家族键改名并把 register 旧口径标为 superseded；reviewer 走 rule 8 快档（整读消费链 + 反向控制 + 验收超集 378 OK，含上一轮转红的模块），未起 agent、未起全量（用户指示；执行方账本指纹与当前代码态逐字相同）。
- **失效旧结论**：register 中「健康家族为 `fmp_grades`」「yfinance 不进 global health」的表述已作废，现行契约是 `analyst_grades` + yfinance 驱动；`docs/us_short_system_design.md:9` 已同步，只改 provider-health 半句、保留 "never gate emit"。
- **下一步注意事项**：`clean` 仍不可达，因为 `universe_market_cap` 与 `sec_sic` 在真实产物上长期 `degraded`——这是问题7 的数据缺口，按桌面 §问题6 §3.A.2 属预期，不要当回归查。剩余 `O-P6R-2`~`O-P6R-6`、`O-P3-1` 为非阻断 Optional。

## 2026-08-11 追加：provider-health Optional O-P6R-2~6 自修自审收口

- **结论**：PASS，已提交并合入 master。五条 Optional 转 `resolved`；`O-P3-1` 按用户指示保持 `open`。
- **改了什么**：`runners/us_short_weekly_capstone_stages.py` —— `_pass2_rows` 类型检查前置到 `set()` 之前、`_massive_events_health` 加 symbol 类型守卫、`_vix_health` 安全 float 转换、离线 seam 的 pass2 校验失败改为降级（receipt 分支仍 raise）、`_universe_health` 从 `per_source` 重算失败列表以拒收空洞证据。测试侧补了敌意输入类、空洞证据类，以及**第一条真正跑通生产 receipt 分支**的测试（含三 stage 篡改反控）。
- **为什么**：这些投影器的契约是返回状态词，抛异常等于让一行坏数据打断整份健康图；而 emit-critical 家族靠空洞证据判 `ok` 是反方向的洞。
- **验证**：焦点超集 `288 OK`（`receipt:e9fd04f4cdda1f469a54aea2`）；植入把守卫顺序改回原样 → 精确复现 `TypeError`，还原后 sha 一致；三份真实 universe summary 在收紧后仍 `ok`（正向控制）。
- **失效旧结论**：register 里「这五条只在离线 seam 可达、暂不处理」的表述作废——已修完。
- **下一步注意事项**：本刀按用户指示**未跑全量**，改的是共享 fail-closed 投影器，跨 lane 回归是已声明的证据边界；下次有全量机会时顺带确认一次。

## 2026-08-11 追加：桌面 us_testrun0810 问题8 Massive 429 恢复与问题6消费闭环（1302，待 Claude 独立审查）

### 结果与实现边界

- 先只读比较主分支已提交代码，确认问题6已有唯一 `massive_events → derive_provider_health → receipt → emit/report` 链及对应测试；1302 仅 fast-forward 同步该链，未另建 health 实现。
- 按更新后的问题8方案修复三条 active 入口：Pass2 Massive news/splits/dividends；one-click forward corporate-action；ETF total-return sidecar。Massive 429 只在 Massive 入口按同一逻辑请求固定等待 `65s`、最多 `2` 次；FMP/SEC 429 不重试。
- Pass2 逻辑调用先全部预留，retry 只消费物理 headroom；one-click 在 preflight target 后自动计算 `exact_pass2_calls + 2 * ceil(target_count * 3 / 10)`，显式 cap 不得低于逻辑预算或高于自动上限。forward 只有最终成功写 canonical raw，持久 429 为 `incomplete_no_count` 且无 coverage/evidence；exact rerun 可恢复。ETF 为 `32` logical / `40` physical，单家族持久失败不阻断其他家族。
- news 已恢复到 source packet/data-context/score/selection 可观察结果；split/dividend 通过既有问题6 health projector、receipt facts、classifier/report 被消费。checkpoint run identity 不包含 retry 参数，并有反向测试。

### 验证与交接

- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`；问题8/问题6消费 focused `249 OK`，checkpoint/inventory 快照验证后 `18 OK`；验证均为本地 fake client/临时根，无 provider/network/live/真实周跑。
- 新增测试造成的首次 inventory 快照漂移已用既有生成器同步；最终 full lane ledger 为 `discover -s tests -p test_us_short*.py`、`discovered=5773 ran=5773 equal=True`、`317/317` modules、`PASS`、`392.8s/860s`，fingerprint=`12201c29c333…`；静态 `diff_check=PASS`、`py_compile=11`。
- 状态：`R-USSHORT-MASSIVE-429-RECOVERY-WIRING-GAP` 为 `repaired / OPEN-NOT_VERIFIED`。Claude Code：独立审查三入口 retry/physical cap/持久失败语义、news 与 split/dividend 消费可见性、问题6 receipt/report 绑定和 checkpoint identity；通过后按流程提交。

## 2026-08-11 追加：问题8 独立审查 FAIL（1302，未提交）

### 改了什么

- 审查方零代码改动。只在 `docs/system_risk_register.md` 新建两条 Required、记 5 条 Optional 并写下已确认成立的不变量清单；`docs/SESSION_LOG.md` 顶部 prepend 一条极简 FAIL entry。

### 为什么

- `R-USSHORT-FORWARD-CA-SIBLING-FAMILY-RAW-PERSISTS-BEFORE-RUN-OUTCOME`：`_fetch_family` 在页循环体内即时 `_write_once` canonical raw，而 429 早返回是在两个 family 都跑完之后才做。混合轮（一 family 成功、一 family 持久 429）会留下成功 family 的 raw 页却没有 coverage；`_write_once` 的逐字节 drift 守卫会让限流恢复后的 rerun 在 payload 有任何字节差异时永久失败。上文「forward 只有最终成功写 canonical raw…exact rerun 可恢复」这句**与代码不符**，以本节和 register 为准。
- `R-USSHORT-CAPSTONE-HTTP-ATTEMPT-CAP-VALIDATED-AFTER-THREE-GATED-PROVIDER-STAGES`：显式 `max_total_http_attempts` 的类型/下界/上界校验只在 `pass2_preflight` 之后（`us_short_weekly_capstone.py:2707-2719`），而 `universe_fetch` / `momentum_fetch` / `sic_fetch` 三个 gated stage 与 current-output 归档事务都在它之前。方案 A.3 要求「任何非法值必须在 provider stage 前失败」。

### 验证命令

- `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.provider.test_us_short_batch5_full_candidate_live_source_packet tests.provider.test_us_short_batch5_pass2_fetch_retry_pacing tests.provider.test_us_short_forward_policy_corporate_action_fetch tests.provider.test_us_short_weekly_capstone tests.test_us_short_market_diagnostic_etf_sidecar tests.test_us_short_paper_one_click`
- 植入反控：中和 `_fetch_with_retry` 的 `provider_id == "massive"` 后单跑 `tests.provider.test_us_short_batch5_pass2_fetch_retry_pacing`。
- reviewer 自写探针：离线导入两处 normalizer 与两处 cap 公式，跑 16 组敌意输入 + 5 组 cap 参数三方比对。

### 验证结果

- 焦点超集 `Ran 168 in 93.2s OK`，`receipt:9bad141034020ee5d95b05d6`。
- 植入后**仅** `test_fmp_429_is_not_retried` 转红（`AssertionError: True is not false`），还原后 `git diff --numstat` 回到 `81 13`、全仓无 `PLANTED` 残留。
- cap 公式五组（1121/1061/1001/12/12）与两处实现逐值相同；normalizer 对 `3`/`-1`/`True`/`"2"`/`2.0`/`64.9`/`65.0000001`/`inf`/`nan`/`retries=0 配 65` 全部拒绝。
- full lane 按 AGENTS rule 4 不重跑，独立读 `.tools/state/full_pack_ledger.json` 核对 `5773/5773`、`317/317`、`392.8s`、fingerprint `12201c29c333…`，且 `_prepares` 当前指纹与之逐字相等。
- 全程零联网、零真实 provider、零真钱、未推进诊断时钟、未写真实 `state/us_short`。

### 失效旧结论

- 上一节「forward 只有最终成功写 canonical raw」与「exact rerun 可恢复」在混合-family 场景下不成立，作废；修复并复审通过后再改回。
- `test_persistent_massive_429_..._recovers_on_exact_rerun` 目前只证明「逐字节相同的重放可重跑」，不证明「限流恢复后可重跑」，不得再被引用为后者的证据。

### 下一步注意事项

- 两条 Required 属同一刀的同一缺陷类，按 §16 一轮批量修完再交复审；ETF sidecar 的预算共享（`O-P8-1`）与整周降级冻结（`O-P8-2`）机制早于本 diff，不要顺手扩进本刀。

## 2026-08-11 追加：问题8 Required/Optional 审查意见核对后修复（1302，待 Claude 独立复审）

### 审查意见合理性判断

- 先对当前代码和 0810 方案逐条核对后，2 条 Required 均是方案明确要求的 fail-before-side-effect / outcome-boundary 硬门；5 条 Optional 也都能在当前实现中复现为预算、恢复、配置漂移或测试隔离缺口，因此本轮全部接受并修复。

### 修复内容

- Forward corporate-action 两个 family 的成功 raw 页改为先内存缓存；只有本轮没有持久 Massive 429 时才统一写 canonical raw。混合 429 不留下 sibling raw，恢复后 provider wrapper 不同字节的 rerun 可以成功写 coverage 与 adjustment evidence；`_write_once` 漂移守卫未放松。
- Capstone 在任何 gated provider stage 前校验显式 `max_total_http_attempts` 为 exact positive int 且非 bool；依赖 approval 的 exact lower/automatic upper bound 仍在后续保留。
- ETF sidecar 增加 logical-slot 初始尝试预留，保持 `physical=logical+retry`/`physical<=40`；整周全 family 持久 429 且无成功页返回 `incomplete_no_count`、不写 sidecar，同日成功 rerun 可恢复；429 raw 路径不会阻塞恢复后的新字节写入，混合 family 仍局部降级。
- retries>0 的 backoff 严格为 `65`，window capacity、wait、max2 统一引用 `universe_fetch`；Pass2 sleep 支持注入。问题6既有 `massive_events → derive_provider_health → receipt → emit/report` 消费链未另建第二条 health 链。

### 验证与边界

- 固定主 Python；focused `415 OK`（receipt `receipt:5328794d756e3be6929c54f6`）；full lane `5779/5779 equal=True PASS`、`317/317`、`388.4s/860s`，static `diff_check=PASS`、`py_compile=13`，fingerprint=`95bd1354d6dc9a6d7ac74f08c77a7c32030d922a10c9a780ae99e904bec9e335`。
- 证据来自 fake client、临时根和离线测试；无 provider/network/live、无真实周跑、无诊断时钟推进、无真实 `state/us_short` 写入。状态为 `OPEN-NOT_VERIFIED`，下一步是 Claude Code 独立复审后按流程提交。

## 2026-08-12 追加：0810 问题7市值获取链与候选池消费闭环（1302，待 Claude 独立审查）

### 结果与实现边界

- **风险身份**：`R-USSHORT-UNIVERSE-MARKET-CAP-ACQUISITION-GAP`，状态 `repaired / OPEN-NOT_VERIFIED`；本段是问题7的唯一当前交接，不删除或改写历史 `R-USSHORT-BATCH5-UNIVERSE-FMP-FALLBACK-STARVES-PASS2-GRADES` finding。
- **生产链**：最终唯一链为 `run_fetch → dynamic recent 4 completed SEC frames → initial Pass1 → exact missing-CIK CompanyFacts → Pass1-B → exact residual FMP profile (max 240) → Pass1-C → exact residual Massive ticker-overview (price_basis_date, existing 13s pacing and issue8 65s/max2 429 contract) → Pass1-D → final candidate artifact/eligible_tickers → existing data-context → Pass2 preflight/final choice → market_cap_completion → existing problem6 universe_market_cap health → existing receipt/emit/report`。问题7没有复制问题6 classifier/receipt/report，也没有复制问题8 retry。
- **相邻接口**：问题2 的 OHLCV source-packet→价格链、问题3 的 analyst source/coverage/provenance、问题8 的 Massive retry 常量/语义、问题9 的 `context_components` exact shape 均保持 owner 不变；问题7只消费最终候选和既有下游合同。
- **SEC / schema / provenance**：frames 根据 `price_basis_date` 动态取最近四个已完成 quarter（`20260807` 实际列表为 `CY2026Q2I,CY2026Q1I,CY2025Q4I,CY2025Q3I`）；四 frame 全失败仍阻断。CompanyFacts 按首次 `needs_market_cap` 去重 CIK、每 CIK 一次、DEI→us-gaap、合法表单/`shares` 单位/正有限值/PIT 边界，保留 source/end/filed/accession；schema `1.2.0` 固定 `sec_xbrl_frames|sec_xbrl_companyfacts|none` 与 `sec_shares_x_close|fmp_profile|massive_ticker_overview|none`。
- **残余与守恒**：FMP 逐票最多 240、沿用既有 403/429 stop 与 0.2s pacing；显式 identity mismatch 也不救援。Massive 只处理 FMP 后精确 residual，正有限且 identity match 才救援；失败保持 unresolved。`market_cap_completion` 守恒并记录 CompanyFacts/FMP/Massive target/request/attempt/rescued/final-unresolved；问题6 对完整/部分/坏 aggregate 分别给 `ok/degraded/down`，历史 FMP-only summary 兼容。
- **真实消费者证明**：最终 Pass1 rows 产生 artifact summary/eligible/count；离线真实 `run_fetch` 形状用例证明 COIN 类初始市值缺口经 Massive 补齐进入 data-context candidates 和 Pass2 preflight target；失败 residual 不能通过 catalyst recall/default 旁路。

### 验证与未验证边界

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`。规定聚焦模块为 `Ran 274 tests in 9.0s ... OK`，machine receipt=`receipt:b0a73f22c910a79b62a274d4`；相关 7 个 Python 文件 `py_compile=PASS`，`git diff --check=PASS`。
- 按 AGENTS rule 4 对冻结代码只执行一次 full-pack ledger：`discover -s tests -p test_us_short*.py`，`discovered=5801 ran=5801 equal=True`、`317/317` modules、`PASS`、`487.4s/860s`，full/prepare/code fingerprint=`0b7a0b9b17fe6f6f7b7fd537e6554be8afeb61f016c25561ae76586f430a3b52`。
- 聚焦覆盖动态 frame/CompanyFacts PIT、43 条超过旧 40 限制的完整残余链、FMP/Massive/none lineage/schema/反伪造、consumer closure、problem6 aggregate health reverse；ripple 检查确认无生产 first-40 静默截断、无第二套 health/retry、旧 `SEC_SHARE_FRAMES` 生产符号无残留。测试均为 fake transport/临时根/离线。
- 未执行 bounded live acceptance、未访问 provider/真实 key、未写真实 `state/us_short`，未核对真实 `MSTR`、`COIN`、`RDDT`、`HIMS`、`DKNG`、`SNAP` 或 20260810 的 544/504 产物；不得据此声称 20260810 全量问题已修复、production/ship gate 已开放。Codex 不提交；下一步由 Claude Code 独立审查并按 PASS 流程提交。

## 2026-08-12 追加：问题7 独立审查 FAIL（1302，未提交）

### 改了什么

- 审查方零代码改动。`docs/system_risk_register.md` 新建三条 Required、记 6 条 Optional、2 条「明确不是发现」与已验成立的不变量清单；`docs/SESSION_LOG.md` 顶部 prepend 一条极简 FAIL entry。

### 为什么

- `R-USSHORT-MARKET-CAP-LAYER-TARGET-TRUNCATION-HAS-NO-ORCHESTRATION-GUARD`：`us_short_universe_fetch.py:1695` 与 `:1710` 两处决定每层目标集的编排行没有任何测试钉住。我在**最后一层**种回 `[:40]` 后全部 114 条测试仍绿——第 41 名之后的票拿不到 overview、落进 `final_unresolved`、被静默移出候选池，正是本刀要根除的 504 只死法。守恒式结构上抓不到（丢掉的票只是落进 `final`，等式照样成立）。
- `R-USSHORT-COMPANYFACTS-PRECEDENCE-TEST-IS-TAUTOLOGICAL`：`test_companyfacts_target_is_only_a_frame_hole` 把生产的 merge 循环手抄进测试体再对自己抄的那份断言，无任何生产调用。
- `R-USSHORT-UNIVERSE-SUMMARY-UNRESOLVED-COUNT-IGNORES-THE-MASSIVE-LAYER`：`unresolved_count` 由 CompanyFacts 残余减 FMP 救回得出，无视 Massive 层，与同一摘要里的 `final_unresolved_count` 系统性矛盾，违反本刀完成判据 #5。

### 验证命令

- `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.provider.test_us_short_universe_fetch tests.schema.test_us_short_universe_candidate_artifact_schema tests.provider.test_us_short_batch5_data_context tests.provider.test_us_short_batch5_full_candidate_pass2_preflight tests.provider.test_us_short_provider_health_capstone_matrix tests.provider.test_us_short_weekly_capstone`
- 植入反控：分别在 `:1695` 与 `:1710` 加 `[:40]` 后单跑 `tests.provider.test_us_short_universe_fetch`。

### 验证结果

- 焦点超集 `Ran 291 in 10.6s OK`，`receipt:d63a39e62d763448b761f3cb`。
- 两次植入均 `Ran 114 OK`（**应红未红**，即本轮 P1 Required 的证据）；还原后 `git diff --numstat` 回 `462 48`、全仓零 `PLANTED` 残留。
- full lane 按 rule 4 不重跑，独立读账本核对 `5801/5801`、`317/317`、`487.4s`、fingerprint `0b7a0b9b17fe…`，与执行方所述一致。

### 失效旧结论

- 上一节「ripple 检查确认无生产 first-40 静默截断」只对**当前代码**成立，不代表该缺陷类已被守住——它可以原样种回而无测试转红。修完 P1 前不得把本刀读成「截断问题已根除」。

### 下一步注意事项

- 三条 Required 属同一轮批量修（§16），修完再交复审。
- 1302 落后 master 8 个提交（`O-P7-5`），修复前建议先做 step-0 `ff-only` 同步，否则合并会走双侧 widening。
- 未做 bounded live acceptance，不得声称 20260810 的 504 只已修复。

## 2026-08-12 追加：0810 问题7 Required + Optional 修复交接（1302，待 Claude 独立审查）

### 范围与结论

- **风险身份**：`R-USSHORT-UNIVERSE-MARKET-CAP-ACQUISITION-GAP`；3 条 Required 与 `O-P7-1`~`O-P7-6` 均已实现，状态为 `repaired / OPEN-NOT_VERIFIED`。没有提交或 merge；所有编辑仅在 1302，桌面 `us_testrun0810.md` 未修改。
- **同步**：先把 1302 fast-forward 到 master `d99f0cab`，再恢复原有工作并解决唯一的 `docs/system_risk_register.md` 冲突；因此 `O-P7-5` 已消除，后续没有在主树工作。
- **唯一链不变**：`run_fetch -> SEC frames -> missing-CIK CompanyFacts -> FMP residual -> Massive residual -> final artifact/eligible -> existing data-context/Pass2 -> market_cap_completion -> existing problem6 health -> existing receipt/emit/report`。没有新 health family、receipt、emit/report 或 retry 链。

### 本轮修复

- 两个 fallback seam 均用逐元素 exact-residual guard 锁住；43 ticker 的生产 `run_fetch` fake-transport 用例记录并断言 FMP 与 Massive 各自收到全量 residual，且最后层可救回 ticker 保留在 `eligible_tickers`。
- CompanyFacts precedence 改成生产路径验证：frames 已有的 CIK 即使 CompanyFacts 回传冲突 shares 也不被覆盖；仅 frames hole 可由 CompanyFacts 填补。相同 `(end,filed,accession)` 的相同值可接受、不同值 fail-closed。
- health 兼容字段把 `unresolved_count` 绑定到最终 whole-chain unresolved，并分列 `unresolved_after_fmp_count`；Massive overview 还输出 target/physical/rescued/final-unresolved/outcome 与 13 秒初始请求 pacing 下界，仍不是独立 health family，也没有 hard cap。
- FMP fallback identity 改为至少一个非空 identity、所有提供的 `symbol`/`ticker` 都需 canonical-match；`shares * close` 只在有限正值时作为 SEC 市值，否则正常落入 fallback/none。
- Pass2 继续使用审批 Top-K，不把所有 eligible 强推入昂贵调用；preflight 与 live consumer 共同生成/核验 eligible-selected、eligible-scored-not-selected、eligible-unscored-not-selected 的 count/SHA-256 分区。任何已升级 preflight 的分区伪造会在 provider call 前拒绝；历史 preflight 完全缺这组 Optional 字段时保持可读。

### 验证与边界

- 固定主 Python wrapper：`Ran 375 tests ... OK`，receipt=`receipt:63d0f2831ee2c7773aa4d2ab`；包含问题7规定模块和本轮触及的 funnel/live/schema。`py_compile`、`git diff --check HEAD` 通过。
- 植入反控均实际转红后还原：FMP seam `[:40]`、Massive seam `[:40]` 分别触发 exact-residual guard；移除 frames 优先级使生产 precedence 断言从 `2_000_000.0` 变为冲突的 `1000.0`。零 `PLANTED` 残留。
- 按 rule 4 在代码冻结后只启动一次 `full_pack_ledger.py run us_short ...`。静态门先通过（`diff_check=PASS`、`py_compile=12`），但 full lane 在既有 soft-discovery conformance baseline 报红而 fail-fast：`discovered=5810, ran=4804, equal=False, FAIL`。因此本交接**没有**全量绿结论，不能以旧 `5801/5801` 替代。
- 隔离检查中，失败模块同 full-worker 参数直接为 `29 OK`；紧接其 serial predecessor `provider.test_us_short_weekly_capstone_soft_discovery` 后亦为 `53 OK` + `29 OK`。根因未定位，单列 `R-USSHORT-FULL-LANE-CONFORMANCE-BASELINE-FLAKE`，不把它伪称为问题7回归，也不原样重跑 full lane。
- 全部测试使用 fake transport 和临时根；未访问 provider/真实 key，未写真实 `state/us_short`，未做 bounded live acceptance，未推进诊断时钟，未得出 production/ship 或 20260810 504/544 已修复的结论。

### Claude 审查入口

- 审查 Required 的三个真实生产路径与全部 Optional（尤其是 live consumer 分区绑定），核对 `docs/system_risk_register.md` 的 full-lane `FAIL` 边界。若修复该独立 full-lane gate，代码指纹变化后再按 rule 4 运行唯一一次完整 ledger；否则不得提交为“全量验证通过”。

## 2026-08-12 追加：SESSION_LOG header 与 full-lane conformance 诊断修复（1302，待 Claude 独立审查）

### 修复内容

- review gate 的 newest-entry parser 现与 doc-governance 共用同一 header grammar：`## YYYY-MM-DD — ...`（亦允许既有 en-dash/hyphen 变体）。最新 dated header 漏分隔符会立即拒绝，不能再绕去验证旧 entry。
- `LaneGuardRegistryConformance._run()` 保留 nested unittest 的 captured output；baseline 失败将携带实际内部 traceback。所有 executable/resource consumer 已随四元返回契约更新，资源隔离 module 的遗漏 unpack 由第一次 full-ledger 立即发现并修正。

### 验证与边界

- 固定主 Python focused conformance/gate closure：`54 OK`，receipt `receipt:716a5695e4e09645993a5750`；另有 header-missing-separator 与 nested-error-output 回归测试。
- 首次新 fingerprint ledger 只跑到 `4528/5811`，原因是本刀漏改 resource consumer 的 `ValueError`；修正后新的 fingerprint 的唯一 ledger 为 `5811/5811`、317/317、`PASS`、383.4s/860s，static `diff_check=PASS`、`py_compile=15`。
- 原始 soft-discovery baseline 未在本轮重现，因此只关闭其诊断黑洞，不编造根因；无 provider/network/live、无真实 `state/us_short` 写入、无诊断时钟/production/ship 结论。状态仍 `OPEN-NOT_VERIFIED`，由 Claude Code 独立审查、提交。

## 2026-08-12 追加：问题7 复审 —— 三条 Required 闭合确认，新增审查门 Required（1302，未提交）

### 改了什么

- 审查方零代码改动。register 记三条旧 Required 翻 `resolved` 的实测证据、新建一条审查门 Required、一条 Optional；SESSION_LOG 顶部 prepend 极简 FAIL entry。

### 为什么

- 三条旧 Required 确已闭合：编排层两处 seam 加了逐元素比对的 `_assert_exact_market_cap_layer_targets`；自证的 precedence 测试换成走生产 `run_fetch` 的冲突用例；`unresolved_count` 改读全链最终值并保留 `unresolved_after_fmp_count`。
- 新 Required `R-DOCGOV-REVIEW-GATE-STILL-VALIDATES-AN-OLDER-ENTRY-WHEN-THE-NEWEST-HEADER-IS-MALFORMED`：`_top_review_entry` 的锚点是「第一条匹配日期正则的行」，最新 header 若连该正则都不匹配（`##` 后无空格、日期未补零），门会拿更老的合规条目放行本轮回复。这是反造假机制本身，且正是本轮 R-ID 名字里的那一格。

### 验证命令

- `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 1200 <本轮全部 10 个改动测试模块>`
- 再植入：最后一层 `massive_overview_targets` 加 `[:40]` 后单跑 `tests.provider.test_us_short_universe_fetch`
- 审查门探针：直接调 `_top_review_entry`，喂四种 header 形状

### 验证结果

- 焦点超集 `Ran 335 in 58.8s OK`，`receipt:c2f1ff9de307453291cc354e`。
- 再植入 `RuntimeError` 精确转红在 `test_run_fetch_sends_the_full_43_residual_to_both_fallback_layers`；**上一轮同一植入是 `Ran 114 OK` 全绿**——这是 P1 闭合的前后对照。还原后零残留。
- 审查门四格：合法 → 取最新；分隔符错 → 正确报错；`##` 后无空格 / 日期未补零 → `err=None` 且 picked 落到 2026-08-01 的旧条目。

### 失效旧结论

- 上一节「ripple 检查确认无生产 first-40 静默截断」现已由编排级 guard 与 43 条残余的 run_fetch 用例真正守住，可以引用了。
- 本轮 `R-DOCGOV-SESSIONLOG-HEADER-SEPARATOR-GATE-DIVERGENCE` 的「已修复」不涵盖其 R-ID 名字里的 skip 那一格，勿据其宣称审查门已无跳过风险。

### 下一步注意事项

- 只剩审查门那一条 Required，锚点从「第一条匹配日期正则的行」改成「compliant zone 里的第一条 `^## ` 行」即可，三格闭合测试见 register。
- 仍未做 bounded live acceptance，不得声称 20260810 的 504 只已修复。

## 2026-08-12 追加：审查门 header anchor 与问题7 Optional 哈希最小修复（1302，待 Claude 独立审查）

### 修复与取舍

- `R-DOCGOV-REVIEW-GATE-STILL-VALIDATES-AN-OLDER-ENTRY-WHEN-THE-NEWEST-HEADER-IS-MALFORMED`：review gate 现在先取 compliant zone 的第一条 `^##` 行，而非第一条匹配日期正则的行；随后仍用原有严格 header grammar 判定。漏分隔符、`##` 后无空格、日期未补零都 fail-closed，且不能退回验证后面的旧 entry。
- `O-P7-7` 的 4 个 `eligible_*_tickers_sha256` 被判为过度设计并删除：它们是不可解释的摘要指纹，无法给出具体排除项；live runner 已在花 provider call 前独立重推导且精确比对 `target_symbols`。保留分区计数、守恒与 upgraded preflight 对 live re-derivation 的一致性校验；forced-holding/catalyst-recall 的既有 binding hashes 不在本 Optional 范围。

### 验证与边界

- 固定主 Python 的聚焦集 `86 OK`，receipt=`receipt:754625ea870daae6b600d4ac`；`diff_check=PASS`、`py_compile=15`。
- rule 4 的当前指纹唯一 US-short ledger 为 `5811/5811`、317/317 modules、`PASS`、`480.4s/860s`、fingerprint=`e8813231743d…`。
- 全部为离线/fake/临时根测试；没有 provider/network/live、真实 `state/us_short` 写入、主树或桌面文档变更。状态 `OPEN-NOT_VERIFIED`，下一步由 Claude Code 独立审查，不提交、不 merge。

## 2026-08-12 追加：审查门 anchor 复审 PASS（1302 → master）

### 改了什么

- 审查方零代码改动；register 记 `R-DOCGOV-REVIEW-GATE-STILL-VALIDATES-AN-OLDER-ENTRY-WHEN-THE-NEWEST-HEADER-IS-MALFORMED` 翻 `resolved`、新记 `O-P7-8`；SESSION_LOG 顶部 prepend 极简 PASS entry。

### 为什么

- `_top_review_entry` 的锚点从「第一条匹配日期正则的行」改为 compliant zone 里的第一条 `##` 行，再用既有严格 grammar 判定。这样最新 header 无论何种畸形都不可能让门回退去验更老的合规条目。

### 验证命令

- `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_claude_review_gate tests.test_us_short_pass2_funnel tests.provider.test_us_short_batch5_full_candidate_pass2_preflight tests.provider.test_us_short_batch5_full_candidate_live_source_packet tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency`
- 植入：把 `_SESSION_HEADER_RE` 改回 `^## \d{4}-\d{2}-\d{2}\b.*$` 后单跑 `tests.test_claude_review_gate`
- 探针：直接调 `_top_review_entry` 喂五种 header 形状

### 验证结果

- 焦点超集 `Ran 127 in 45.3s OK`，`receipt:4008497fbc2de396a027ad7b`。
- 植入 → `test_stop_validation_rejects_malformed_newest_header_before_validating_body` 在 `##2026-08-12` 与 `## 2026-8-12` 两个 subTest 精确转红；还原后 numstat 回 `21 7`、零残留。
- 五格探针全部 fail-closed；上轮 C/D 两格的静默回退已消除。
- full lane 按 rule 4 引账本 `5811/5811`、`317/317`、`480.4s`；直接计算当前代码态指纹 `e8813231743d…` 与记录值逐字相同，确认绑定最终 diff。

### 失效旧结论

- 上一节「`R-DOCGOV-SESSIONLOG-HEADER-SEPARATOR-GATE-DIVERGENCE` 已修复」当时只覆盖分隔符那一格；skip 那一格由本轮补齐，两者合起来才是该 R-ID 名字承诺的范围。

### 下一步注意事项

- `O-P7-8`：`^##.*$` 亦匹配 `###`，正文含三级标题的 entry 会被截断（fail-closed，不放行）；若将来评审 entry 需要子标题，改成 `^##(?!#).*$`。
- 仍未做 bounded live acceptance，不得声称 20260810 的 504 只已修复。

## 2026-08-12 追加：问题7 live acceptance 的结构性阻塞与替代收口路径

### 改了什么

- 零代码改动。register 新增 `R-USSHORT-PROBLEM7-LIVE-REPLAY-CONFLICTS-WITH-THE-STATUS-SOURCE-PIT-CONTRACT` 并附下次真实周跑的五条验收清单；SESSION_LOG 顶部 prepend 裁决 entry。

### 为什么

- 用户授权后真跑了 `--now-et 2026-08-10T09:00:00`，在 2/5 阶段 fail-closed：status record 的 `observed_at`（真实墙钟 2026-08-12）不在决策 session 2026-08-10 的 [上一 session 收盘, 决策 session 开盘] 窗口内。守卫拒绝把两天后的观测盖成决策时刻的观测——PIT 契约在正确工作。
- 因此桌面 §4.8「对 20260810/20260807 做 PIT 规则回放」在带 live provider 时**无法满足**。这是方案缺陷，不是实现缺陷；**不得为满足该条而放宽 status-source**。
- 附带确认：`_validate_candidate_path` 把候选产物硬绑到 canonical `state/us_short/candidate_universe_<date>.json`，连私有 kwarg 也必须等于它，所以 §4.8 说的「注入式 gitignored 临时根」对 universe 产物同样做不到；可行隔离只有换一棵工作树。

### 验证命令

- `python runners/us_short_universe_fetch.py --confirm-user-authorization --now-et 2026-08-10T09:00:00`（分离进程 + 日志）

### 验证结果

- 停在 `[2/5] Status source` 的 `StatusSourceError`；`[1/5]` 已返回 7659 ticker。
- **FMP 240 次与 Massive ticker-overview 全部未发生**，当日配额基本未损耗；零产物落盘，主树真实 `candidate_universe_20260810.json` 未被触碰。

### 失效旧结论

- 本 handoff 与 register 中所有「待 bounded live acceptance / 另行授权后回放 20260810」的表述作废：授权已给、已尝试、结构上不可行。改以下次真实周跑收口。

### 下一步注意事项

- 下次 `us_short_paper_one_click.ps1` 真实周跑完成后，按 register 该节的五条清单逐项核对（守恒 / 每层完整残余 / 动态 frames / 六只代表票 / 不得宣读的边界），核完即删除该清单并翻 live 腿。
- 编排层 `_assert_exact_market_cap_layer_targets` 会在任一层拿不到完整残余时直接 `raise`，所以「周跑跑完了」本身就是第 2 条的证据。
## 2026-08-12 追加：0810 问题9 context_components 单一形状合同修复（1302，待 Claude 独立审查）

### 修复

- 新建风险 `R-USSHORT-CONTEXT-COMPONENTS-SHAPE-AUTHORITY-DRIFT`，状态 `repaired / OPEN-NOT_VERIFIED`。此前 current source-packet 是 6 键 carrier，而 bridge 和 shadow 分别复制 3/5/6 与旧 5 键规则，存在规则分叉。
- source-packet producer 现在唯一持有 immutable legacy/a1/cut4 exact-key table 与 mapping validator；`run_packet()` 在 `result_linkage_sources` 绑定后、写组件 carrier 前验证 cut4。bridge 调共享 validator 兼容 legacy/a1/cut4，shadow 调 current-only wrapper；未新增 schema/hash/migration/adapter/context/provider/live 行为。
- 真实 source-packet carrier 进入同一文件 bridge 后再进入 shadow，并由既有 source capture/H20 comparison consumer 读到；shadow 对 legacy/current 缺键在生成输出前拒绝。bridge 的历史 3/5/6 carrier 兼容性以独立参数化测试保留。

### 验证与边界

- 固定主 Python 聚焦超集 `228 OK`，receipt=`receipt:6c6aeed30b8817c5cb349a4d`。包括 I/O inventory、producer、bridge、shadow、source capture/comparison、capstone 与 discovery conformance。
- code-freeze 后唯一 full ledger `5816/5816`、`317/317` modules、`PASS`、`487.1s/860s`、fingerprint=`db0fd268cbf7`；`diff_check=PASS`、`py_compile=6`。
- 首次 I/O inventory guard 识别到测试 `unlink` 与生成清单的写计数漂移；已移除该不合规 I/O、以项目 generator 更新 `docs/us_short_test_io_inventory_20260801.json`，allowlist 未扩大。所有测试 fake/temporary/offline；无 provider/network/live、无真实 `state/us_short` 写入、无诊断时钟或 production/ship 结论。

### Claude 审查入口

- 审查 shared validator 的 exact closed-world/type 约束、producer 的 pre-write current gate、bridge 的 legacy/a1/cut4 compatibility 和 shadow 的 current-only pre-output failure path；确认 source-capture/H20 test 是同一真实 carrier 的既有 consumer，而非新建 health 或 comparison 链。PASS 后由 Claude Code 按流程提交；Codex 不提交、不 merge。

## 2026-08-12 追加：问题9 独立审查 PASS（1302 → master）

### 改了什么

- 审查方零代码改动。register 记 `R-USSHORT-CONTEXT-COMPONENTS-SHAPE-AUTHORITY-DRIFT` 翻 `resolved` 与逐条方案对照、5 条 Optional；SESSION_LOG 顶部 prepend 极简 PASS entry。

### 为什么

- 形状表收敛为 `CONTEXT_COMPONENT_SHAPES`（`MappingProxyType`，真只读），legacy/a1/cut4 三种精确形状；`validate_current_context_components` 是 cut4-only 薄封装。bridge 与 shadow 的本地键集全删、改调同一合同，全仓零残留。
- 校验点在 `result_linkage_sources` 插入（:1143）之后、落盘（:1163）之前（:1160），且真测断言被校验对象即被写盘对象。

### 验证命令

- `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 1200 tests.provider.test_us_short_batch5_data_context_source_packet tests.provider.test_us_short_batch5_to_batch4_e2e tests.test_us_short_forward_policy_shadow_stage tests.provider.test_us_short_weekly_capstone tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency`
- 植入：把 `actual_keys != expected_keys` 改成 `expected_keys <= actual_keys`（subset 放宽）后单跑两个契约模块。

### 验证结果

- 焦点超集 `Ran 201 in 15.9s OK`，`receipt:6907191c32af5c17b3b6ec4b`。
- 植入 → `test_exact_shape_contract_accepts_historical_shapes_and_only_current_cut4` 在 a1 / cut4 / 未知键三个 subTest 精确转红；还原后 numstat 回 `70 0`、零残留。
- 13 格只读探针：6 键通过；5 键 a1 与 3 键 legacy 在 shadow 侧被拒并报缺失键；未知第 7 键报 `unexpected_keys`；类型错报 `invalid_value_types`；bridge 侧三种历史形状照收。
- full lane 按 rule 4 引账本 `5816/5816`、`317/317`、`487.1s`；当前代码态指纹 `db0fd268cbf7…` 与记录逐字相同。

### 失效旧结论

- 「forward_policy_shadow 只认 5 键、每周静默作废六头对比轨」自此不再成立；shadow 现只认 current/cut4，且拒绝发生在任何输出写盘之前。

### 下一步注意事项

- `O-P9-1`：`data_context.json` 在门之前写盘，形状被拒时会留半对产物（已确认无消费者受害）；把门移到该写盘之上即可零成本消除。
- `O-P9-5`（既有、超出本刀）：`forward_policy_shadow` 先于 `weekly_bridge`，而 bridge 会重写同一个 `context_components_path`，soft-boost 异常回落 OFF 使两次产出不保证字节相同——六头账本可能绑到正式周报没用过的 carrier。建议单独立刀。
- 按去重顺序，下一个是**问题10（soft-boost result usability 三态）**。
