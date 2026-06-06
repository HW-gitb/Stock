# Stock 项目 - 当前状态快照
**最后更新**：2026-06-06（A-long fina_indicator PIT contract repair）

**文档定位**：跨会话接续的短 snapshot。完整路由见 `docs/README.md`；过程、review verdict 和 rejected alternatives 见 `docs/SESSION_LOG.md` 顶部 1-3 条；历史 phase 细节见 `docs/handoff/README.md`。

---

## 0. Latest Delta
- 2026-06-06 latest A-long `修复` disposes the materialization preflight blocker without running data or alpha: `fina_indicator` is now explicitly ann_date-only in the current Tushare route (`ts_code,ann_date,end_date,roe,profit_dedt`), while `income` / `balancesheet` / `cashflow` still hard-require `f_ann_date`. Signal selection uses `ann_date <= as_of` for `fina_indicator` and still consumes `restatement_ambiguous_exclusions.csv` for unresolved same-ann-date groups; latest-fill remains forbidden. The execution packet/schema/preregistration/tests lock this table-specific PIT contract.
- 2026-06-06 A-long materialization `执行` stopped at the required preflight probe and did not clear stale checkpoints or run the 23,718-call materialization: project Tushare helper returned `namechange_2018_2025` 5,053 rows, `H00300.CSI` full-period close 1,940 rows, and `H00852.CSI` full-period close 1,940 rows, but `fina_indicator(ts_code=000001.SZ, fields=...f_ann_date...)` returned 55 rows without `f_ann_date`. This preflight result is now dispositioned by the table-specific PIT contract above; no materialization/audit/signal has run yet.
- 2026-06-06 latest A-long `修复` closes the schema-sync / schema-hard FAIL without running data or alpha: materialization summary `table_rollup` is locked to 14, full-audit `required_runner_self_tests` is locked to 12, full-audit `check_results` is locked to 6, and current A-long schema-gated producers hard-fail if `jsonschema` is missing. Codex bundled Python now has `jsonschema 4.26.0`; the A-long schema tests no longer skip because of missing `jsonschema`.
- 2026-06-06 latest A-long `修复` closes the third-review code/design blockers without running data or alpha: selection-time ST / delisting-name veto now requires PIT `namechange_2018_2025` history and forbids current `stock_basic.name` look-ahead; full audit benchmark checks now target H-code total-return close inputs; statement-table `f_ann_date` is locked; checkpoint reuse rejects request-shape drift; critical empty base endpoints no longer pass materialization shape; ledger spend uses pending-summary -> ledger -> final-summary ordering.
- Under this amendment, the old 23,717-call materialization summary and old full audit PASS are stale. The future reviewed materialization plan is 23,718 calls and must include `namechange_2018_2025` plus `H00300.CSI` / `H00852.CSI` full-period close rows before any new full audit or signal run.
- 2026-06-06 prior consolidated repair is superseded where it used current/final `stock_basic.name` for selection-time veto. The still-valid parts are terminal same-anchor exits, drawdown gate, tail diagnostics, H-code TR-close requirement, HAC t-statistics, same-period YoY `earnings_stability`, and CSI300+CSI1000 candidate robustness.
- 2026-06-06 second `修复` fixed Claude R-SPLIT: the prior price-vs-price implementation is invalid because raw A-share prices are discontinuous across split / bonus / transfer / rights events. The working-tree amendment now selects close-to-close total-vs-total: stock `adj_factor`-adjusted next-trading-day close to exit close, versus CSI300 / CSI1000 total-return index close to same-exit close (`H00300.CSI` / `H00852.CSI`). No signal search was run.
- 2026-06-06 the signal runner now hard-fails if no evaluated return rows are produced, so missing local full-period total-return benchmark close materialization cannot silently emit a no-alpha summary or spend the singleton ledger.
- 2026-06-06 `修复` also selected O-SIZE: a candidate clue must clear the same family / view / horizon against both CSI300 and CSI1000, and any future verdict must disclose the equal-weight top-quintile vs cap-weighted CSI300 size / exposure caveat.
- 2026-06-06 A-long overlap/stat-method repair remains part of the same review bundle: future result cells must use Newey-West HAC t-statistics for overlapping monthly long-horizon cohorts, and `earnings_stability` must use same-period YoY `profit_dedt` growth volatility instead of mixed 3/6/9/12-month YTD cumulative values. This still runs no alpha.
- 2026-06-06 A-long R-BENCH probe found a hard total-return route blocker: existing Tushare can read CSI300 / CSI1000 total-return index close values (`H00300.CSI` / `H00852.CSI`) but not the same-anchor `open` values. `docs/a_long_total_return_benchmark_access_probe_summary_20260606.json` remains the no-raw evidence packet; derived total-return-open construction remains forbidden.
- 2026-06-06 A-long signal-search first real run is invalid and discarded: a row-building indentation bug wrote only `excess_CSI1000`, so the primary `excess_CSI300` cohorts were all zero. The runner now writes both benchmark excess fields, hard-fails on "return rows but zero cohorts", deleted the false summary, and reverted the singleton ledger to unspent. This does not permit rerun before review / commit / explicit user execute.
- 2026-06-05 A-long full main-board raw materialization completed after the atomic-writer hotfix and checkpoint refetch. Final summary: `docs/a_long_full_main_board_materialization_execution_summary_20260605.json`; endpoint manifest has 23,717 results = 23,677 success + 40 empty + 0 error. This is now stale under the amended 23,718-call PIT `namechange` / H-code TR-close gates.
- 2026-06-05 A-long full main-board local data-integrity audit R1 repair passed Claude review and was committed. The audit is data-readiness only: future signal search must consume `restatement_ambiguous_exclusions.csv` and exclude 1,504 ambiguous same-ann-date groups; this is not alpha.
- US operating model is active-only + forward-live validation; historical US backtests stay idea-only. A-short steady is `risk_filter_only`. A-share scope is main-board only: A-short already filters non-main boards before analysis, and A-long materialization / audit runners now reject non-main active symbols. The old A-long panel containing `300750.SZ` is historical only and cannot be used as the current alpha/data-readiness path.
- The corrected `000666.SZ` SW supplement executed 4/4 calls and found no usable SW membership source. The approved design boundary is now implemented in the full-period audit runner: reviewed already-delisted no-industry names can be logged as bounded exceptions, kept in returns/risk, and excluded only from industry-normalization denominators. Active-symbol missing industry still fails.
---

## 1. 当前 Phase 与目标

- **当前 Phase**：A-share alpha validation is the active priority. A-long full main-board data route is not clean yet because PIT `namechange` and H-code TR-close were only preflight-probed, not materialized/audited. The `fina_indicator.f_ann_date` preflight blocker is repaired by the reviewed ann_date-only table contract, pending independent review / commit.
- **当前 P0 / P1 目标**：review the A-long `fina_indicator` ann_date-only PIT contract repair. Each step remains a Claude-reviewed gate with a commit between; NO alpha until the materialization and audit gates pass and the signal result is reviewed.
  - **Step 0 (commit + packet review)**: commit the reviewed schema-sync/jsonschema-hard + amended materialization-packet/runner changes. Claude must review the amended **23,718-call materialization packet** (the call plan itself) BEFORE any run — it changed by adding `namechange_2018_2025`, swapping price-index → H-code TR-close, and now locking statement-table `f_ann_date` plus the `fina_indicator` ann_date-only contract.
  - **Step 1 (reviewed materialization `执行`)**: after this repair gets independent review PASS and commit, rerun the reviewed materialization gate. Required payloads: `namechange_2018_2025`; `H00300.CSI` / `H00852.CSI` full-period close; `income` / `balancesheet` / `cashflow` with `f_ann_date`; `fina_indicator` with ann_date-only contract. Do not clear reused `fina_indicator` checkpoints merely because they lack `f_ann_date`; request-shape validation should decide reuse. → Claude reviews the materialization summary.
  - **Step 2 (amended full data-integrity audit, local raw, no alpha)**: must pass the gates — PIT `namechange`/selection-status source, H-code TR-close benchmark, statement-table `f_ann_date`, `fina_indicator` ann_date-only contract, restatement-exclusion, survivorship, coverage. This is a REAL gate that may surface new data issues → another repair loop (do not assume one-pass). → Claude reviews.
  - **Step 3 (first VALID frozen A-long signal search, `执行` double-confirm)**: only if Steps 1-2 pass AND the singleton ledger is unspent AND the 1,504-group `restatement_ambiguous_exclusions.csv` is applied AND both `--confirm-*` gates are set. (The prior zero-cohort run was an invalid bug run, discarded, ledger reverted — so the singleton is unspent; this is the FIRST VALID use, not "the second run".) → Claude reviews the actual alpha result (candidate-clue vs no-alpha, CSI300+CSI1000 robustness, drawdown, concentration, size caveat). No alpha/production/ship-gate/full-size authorized before that review.
- **当前 P1 provider blocker**：US inactive / delisted historical coverage is user-accepted as scoped out for the current active-only forward model. `SR-PROVIDER-001` remains open for license / storage, active-symbol PIT if fundamentals are used, active price-adjustment / corporate actions if used, SEC parser / mapping if used, fallback / stability, provider selection, DataHub / runner consumption, and production readiness. US forward universes must be PIT-frozen at start and must capture real delisting / halt / merger / no-trade outcomes during the forward window; the 12-month forward-live ship-gate requirement is unchanged.
- **执行锁**：A-long signal-search code exists, but no valid result exists. The invalid zero-cohort run was discarded and the ledger is unspent. The runner must abort unless the amended materialization count is 23,718, PIT `namechange` status history exists, H-code TR-close payloads are successful/non-empty, the amended full audit passes, the exclusion CSV is applied, and all close-to-close / terminal / drawdown / concentration / pipeline sanity guards pass. No alpha / production / ship-gate / full-size use is authorized now.
- **协作模式**：Codex = Designer + Implementer；Claude = Independent Reviewer；用户 = Final Approver。详 `docs/AI_REVIEW_PROTOCOL.md`。
- **后台线**：A-short Phase 6b 只保留 weekly forward capture、comparison-track accumulator、forward evidence accumulation；不扩无关小工具。

---

## 2. 最近已完成

- **A-share burst audit/spec downgrade**（2026-06-01）：`docs/phase7a_alpha_plausibility_audit.json` / `docs/burst_lane_spec.md` 已把 A-share minimal-data burst 从 `continue` 降为 `redesign_required`，并引用 failed outcome evidence。
- **A-share burst redesigned outcome**（2026-06-01）：`evidence_report.json` / `signal_events.csv` / `monthly_stats.csv` 已生成；同一 frozen prereg + patched benchmark-open cache 计算后失败 research-continuation thresholds，decision 为 `falsified_or_redesign_required`。
- **Forward-live aggregate evidence hardening**（2026-06-02）：`runners/aggregate_execution_reports.py` / `schemas/execution_aggregate_report.schema.json` now reject cross-context forward-live evidence, reject insufficient source-window coverage, and prevent two-month alpha / Sharpe diagnostics from passing ship-gate metric checks.
- **US EGS coverage-count / missing-field routing**（2026-06-02）：the approved FMP stable coverage smoke produced `docs/provider_evidence_p1_us_coverage_count_execution_summary_20260602.json`; `schemas/provider_p1_missing_key_metrics_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json` route `peRatio`, `revenuePerShare`, and `netIncomePerShare` without authorizing raw parse or derivation; `SR-PROVIDER-001` stays open.
- **DataHub Phase 7c contract batches**（2026-06-03）：`engine/datahub/job_spec_contract.py` enforces the resource-budget / job-spec contracts; `schemas/datahub_shared_layer_contract.schema.json`, `schemas/datahub_report_contract.schema.json`, `schemas/datahub_reproducibility_manifest.schema.json`, `schemas/datahub_data_quality_monitor_contract.schema.json`, and `schemas/datahub_minimal_a_share_read_path_plan.schema.json` define future shared-layer, report, manifest, quality-monitor, and minimal A-share read-path boundaries without implementation authorization.
- **A-short steady alpha re-audit outcome repair**（2026-06-03）：`runners/a_short_steady_alpha_reaudit.py` now re-derives same-anchor benchmark returns from local `result/a_short/backtest/cache/forward_daily.pkl` and uses old CSV excess only as an uncorrected control. Plain result: old 5d CSI1000 clue fails the corrected statistical gate; A-short steady remains risk-filter-only / research reference.
- **A-long Tushare route validation / gap repair**（2026-06-04）：route validation was partial, then route-gap repair passed small-sample field checks; neither authorizes alpha search.
- **A-long thin-slice materialization execution**（2026-06-04）：`runners/a_long_tushare_incremental_materialization_packet.py` executed the reviewed 2022-2023 three-symbol packet and wrote `docs/a_long_tushare_incremental_materialization_execution_summary_20260604.json`; 29/29 calls succeeded, raw rows stayed under gitignored `data/a_long/raw/tushare/materialization_thin_slice_20260604/`, but no data is ready for alpha.
- **A-long broader materialization / paced rerun**（2026-06-04）：the prior 2018-2025 run produced a shape-passed historical panel, but it contained `300750.SZ` (ChiNext), so it is no longer a valid current path for the user's main-board-only A-share scope.
- **A-long main-board-only guard**（2026-06-04）：`engine/data/a_share_board_scope.py`, `runners/a_long_tushare_broader_materialization_packet.py`, and `runners/a_long_materialized_full_period_data_integrity_audit.py` now reject non-main-board active symbols before A-long materialization/audit use.
- **A-long corrected 000666 supplement execution**（2026-06-04）：the 4-call corrected probe ran and found no usable SW membership source for `000666.SZ`; the approved bounded exception is now enforced by the audit runner.
- **A-long main-board fixed-panel materialization / audit / preregistration**（2026-06-04）：the current 2018-2025 main-board-only fixed panel (`600887.SH` replacing old `300750.SZ`) materialized successfully, the local audit passed with 11/11 self-tests and usable start year 2018, and the first signal-search preregistration was registered. This authorizes no signal run by itself.
- **A-long candidate-universe preflight**（2026-06-04）：the reviewed next step stopped before full alpha pull. Active SW membership can be supplemented by `index_member_all(ts_code=...)`, but 187 delisted main-board names still have no SW membership in the current route. No alpha search was run.
- **A-long SW coverage repair fix + boundary packet**（2026-06-05）：the manual SW 2021 patch was removed after Claude FAIL. The combined repair keeps the real 1,189 / 1,193 active supplement result, identifies the remaining four as `退市*` delisting-shell rows, and the 191-name boundary is now user-approved / committed.
- **A-long full main-board materialization / audit execution**（2026-06-05）：the old reviewed runner completed 2018-2025 full main-board raw materialization: 23,717 endpoint results, 23,677 success, 40 empty, 0 error. The old local-only full audit passed after route-A exclusion repair, but under the latest amended gates it is stale because it lacks PIT `namechange_2018_2025`, full-period H-code TR-close materialization, and the updated audit benchmark/status-source checks. It is not alpha evidence and cannot unlock signal search.
- **A-long signal-search runner package / latest repair**（2026-06-06）：`runners/a_long_full_main_board_signal_search.py` now records the blocked total-return-open probe and selects close-to-close total-vs-total measurement using split-safe stock adjusted closes and total-return benchmark closes. Future valid summaries must report 32 cells across CSI300 / CSI1000, require both benchmarks for any candidate clue, use HAC t-statistics, use same-period YoY earnings-stability, use PIT `namechange` for selection-time ST / delisting-name veto, align terminal benchmark exits to the actual stock exit date, enforce a `-15%` monthly excess drawdown gate, and report tail excess fields; no true signal result exists.
---

## 3. 当前有效策略结论

基于 24 月 v7.10 production、Tier1-only 主口径：

- 工程链路健康；Phase 2 工程签收。
- 5d CSI1000 true same-anchor net excess is positive but not enough: mean net excess `0.6158673222` pp, monthly clustered t `1.7623850474`, 14/23 positive months, Bonferroni-normal adjusted p `0.3120170532`。旧未校正 t `2.8769227582` was the measurement-basis artifact under review.
- 20d benchmark excess 仍不显著：`excess_csi1000 monthly t=0.172873488`、`excess_csi300 monthly t=0.5714019896`；5d CSI300 也偏弱（monthly t `1.3934659699`）。
- 直接 `momentum_std` regime 切片不可评估；size 只能用 CSI1000-CSI300 proxy，不能当完整 factor proof。
- 强负信号仍是重点风控证据：`OVERHEAT` flagged subset 表现差；Tier1 相对 Tier2 更稳，但这不等于 full-size alpha。
- 当前 A-short steady 只能保留为“风控 filter / research reference / evidence loop”，不得当作 production alpha 或 full-size lane。

失效旧结论：12 月 Top5 显著、12 期突破型反向信号、旧 `_cc.md` 整体结论、v7.9 前 completeness_score 分组结论均不可继续引用。

---

## 4. 当前关键文件

- `AGENTS.md` - 最高项目规则、固化决策、命令别名、启动顺序。
- `docs/README.md` - 完整 routing table 和文档维护规则。
- `docs/AI_REVIEW_PROTOCOL.md` - Codex / Claude / 用户三方 review / 修复 / 提交流程。
- `docs/system_risk_register.md` - durable open-risk queue；`执行` / `审查` 必读。
- `docs/SESSION_LOG.md` - 最新 cross-LLM reasoning / review verdict；只读顶部 1-3 条。
- `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` - Phase 7a+ 最高行动指南。
- `research/README.md` / `schemas/research_preregistration.schema.json` / `schemas/a_long_signal_search_preregistration.schema.json` / `research/preregistrations/a_long_signal_search_preregistration_20260604.json` / `research/ledgers/a_long_signal_search_program_test_budget_ledger_20260604.json` / `schemas/a_long_total_return_benchmark_access_probe_summary.schema.json` / `docs/a_long_total_return_benchmark_access_probe_summary_20260606.json` / `runners/a_long_total_return_benchmark_access_probe.py` / `runners/a_long_full_main_board_signal_search.py` / `schemas/a_long_signal_search_execution_summary.schema.json` / `schemas/evidence_report.schema.json` - research-only A-long signal-search owners.
- `runners/a_long_data_integrity_audit.py` / `research/preregistrations/a_long_data_integrity_audit_20260603.json` / `research/results/a_long_data_integrity_audit_20260603/audit_report.json` / `research/ledgers/a_long_data_integrity_audit_program_test_budget_ledger_20260603.json` / `schemas/a_long_tushare_data_route_repair_plan.schema.json` / `docs/a_long_tushare_data_route_repair_plan_20260603.json` / `runners/a_long_tushare_route_validation_packet.py` / `schemas/a_long_tushare_route_validation_execution_summary.schema.json` / `docs/a_long_tushare_route_validation_execution_summary_20260604.json` / `runners/a_long_tushare_route_gap_repair_packet.py` / `schemas/a_long_tushare_route_gap_repair_execution_summary.schema.json` / `docs/a_long_tushare_route_gap_repair_execution_summary_20260604.json` / `schemas/a_long_tushare_incremental_materialization_packet.schema.json` / `docs/a_long_tushare_incremental_materialization_packet_20260604.json` / `runners/a_long_tushare_incremental_materialization_packet.py` / `schemas/a_long_tushare_incremental_materialization_execution_summary.schema.json` / `docs/a_long_tushare_incremental_materialization_execution_summary_20260604.json` / `runners/a_long_materialized_thin_slice_data_integrity_audit.py` / `schemas/a_long_materialized_thin_slice_data_integrity_audit_report.schema.json` / `research/results/a_long_materialized_thin_slice_data_integrity_audit_20260604/audit_report.json` / `schemas/a_long_tushare_broader_materialization_packet.schema.json` / `docs/a_long_tushare_broader_materialization_packet_20260604.json` / `runners/a_long_tushare_broader_materialization_packet.py` / `schemas/a_long_tushare_broader_materialization_execution_summary.schema.json` / `docs/a_long_tushare_broader_materialization_execution_summary_20260604.json` / `runners/a_long_tushare_daily_price_route_diagnostic_packet.py` / `docs/a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604.json` / `runners/a_long_materialized_full_period_data_integrity_audit.py` / `research/results/a_long_materialized_full_period_data_integrity_audit_20260604/audit_report.json` - A-long data-integrity gate, route-repair, route-validation, materialization, audit, and diagnostic owner files.
- `docs/provider_priority_benchmark_contract.md` - Phase 7a-3 provider evidence priority / provisional benchmark contract。
- `docs/provider_evidence_drift_monitor.md` / `schemas/provider_evidence_drift_monitor.schema.json` - Phase 7b provider evidence / drift monitor contract。
- `schemas/provider_p1_access_decision_plan.schema.json` / `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` / `schemas/provider_p1_sample_validation_access_approval.schema.json` / `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json` / `runners/us_egs_sample_validation.py` / `schemas/provider_p1_us_egs_sample_validation_summary.schema.json` / `docs/provider_evidence_p1_us_sample_validation_summary_20260602.json` / `schemas/provider_p1_fmp_stable_endpoint_retry_summary.schema.json` / `docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json` / `schemas/provider_p1_remaining_blocker_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json` / `schemas/provider_p1_coverage_count_access_packet_plan.schema.json` / `docs/provider_evidence_p1_us_coverage_count_access_packet_plan_20260602.json` / `schemas/provider_p1_coverage_count_access_packet_approval.schema.json` / `docs/provider_evidence_p1_us_coverage_count_access_packet_approval_20260602.json` / `runners/us_egs_coverage_count_packet.py` / `schemas/provider_p1_coverage_count_execution_summary.schema.json` / `docs/provider_evidence_p1_us_coverage_count_execution_summary_20260602.json` / `schemas/provider_p1_missing_key_metrics_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json` / `schemas/provider_p1_validation_authorization_packet.schema.json` / `docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json` / `schemas/provider_p1_validation_execution_packet.schema.json` / `docs/provider_evidence_p1_us_validation_execution_packet_20260603.json` / `runners/us_egs_validation_packet.py` / `schemas/provider_p1_validation_execution_summary.schema.json` / `docs/provider_evidence_p1_us_validation_execution_summary_20260603.json` / `schemas/provider_p1_inactive_delisted_gap_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_inactive_delisted_gap_resolution_plan_20260603.json` / `schemas/provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic.schema.json` / `docs/provider_evidence_p1_us_fmp_entitlement_corporate_action_no_access_diagnostic_20260603.json` / `schemas/provider_p1_sivb_reprobe_execution_packet.schema.json` / `docs/provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json` / `runners/us_egs_sivb_reprobe_packet.py` / `schemas/provider_p1_sivb_reprobe_execution_summary.schema.json` / `docs/provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json` / `schemas/provider_p1_fmp_paid_tier_license_public_docs_review.schema.json` / `docs/provider_evidence_p1_us_fmp_paid_tier_license_public_docs_review_20260603.json` - Phase 7b-2 P1 access / sample / coverage-count / missing-field / validation / inactive-delisted / entitlement-corporate-action / SIVB re-probe / FMP paid-tier-license public-docs owner files。
- `schemas/provider_p1_readiness_review.schema.json` / `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json` - Phase 7b-2 P1 readiness review matrix（collection complete；Phase 7c / provider selection / broad data fetch blocked）。
- `docs/evidence_feasibility_controls.md` / `schemas/evidence_feasibility_controls.schema.json` - Phase 7a-4 burst promotion / evidence feasibility controls。
- `docs/evidence_report_schema_contract.md` / `schemas/evidence_report.schema.json` - Phase 7a-5 evidence report schema contract。
- `docs/alpha_plausibility_audit.md` / `schemas/alpha_plausibility_audit.schema.json` - Phase 7a-1 audit owner and contract。
- `docs/evidence_capital_policy.md` - paper vs live-normalized evidence owner。
- `docs/strategy_design_synthesis.md` - 总体策略架构 owner。
- `docs/burst_lane_spec.md` / `docs/us_short_spec.md` / `docs/long_alpha_spec.md` - lane owner specs。
- `docs/provider_data_requirements_audit.md` / `schemas/provider_capability_catalog.schema.json` - provider requirements / capability contract。
- `docs/portfolio_allocation_policy.md` - 35/65、bucket、cash non-fungibility、manual-only capital policy。
- `docs/datahub_design.md` / `engine/datahub/job_spec_contract.py` / `schemas/datahub_local_resource_budget.schema.json` / `schemas/datahub_job_spec.schema.json` / `schemas/datahub_shared_layer_contract.schema.json` / `schemas/datahub_report_contract.schema.json` / `schemas/datahub_reproducibility_manifest.schema.json` / `schemas/datahub_data_quality_monitor_contract.schema.json` / `schemas/datahub_minimal_a_share_read_path_plan.schema.json` - DataHub / provider / factor-layer guardrails, job-spec enforcement, shared-layer/report/reproducibility/data-quality/minimal-read-path contracts。
- `presets/a_short.yaml` / `presets/a_short_screening_threshold_governance_20260602.json` / `schemas/a_short_screening_threshold_governance.schema.json` - A-short screening threshold governance parity owner。
- `docs/handoff/README.md` - phase handoff index；不要全量读 handoff。

---

## 5. 下一步

### P0 / P1 - Post redesigned outcome boundary
- Read `docs/system_risk_register.md` before choosing the next `执行`.
- The current active alpha-search route is A-long, but execution is still review-gated. Review target: the latest A-long `fina_indicator` ann_date-only PIT contract repair across `runners/a_long_full_main_board_materialization_packet.py`, `runners/a_long_full_main_board_signal_search.py`, `runners/a_long_full_main_board_data_integrity_audit.py`, their tests/schemas, the amended preregistration / execution packet, and `docs/SESSION_LOG.md` top entry. After PASS + commit, do not run alpha; the next separate `执行` may retry the reviewed materialization gate for PIT `namechange_2018_2025`, H-code TR-close rows, statement-table `f_ann_date`, and `fina_indicator` ann_date-only raw.
- Do not run `research/preregistrations/a_share_minimal_data_burst_20260531.json`; it remains `BLOCKED_DO_NOT_RUN`.
- The full-universe redesigned outcome / excess slice has failed its registered thresholds; do not rerun EGS, change preregistered parameters, full-refresh forward_daily, or reinterpret it as production evidence.
- Any further redesigned A-share burst test must append a planned test to `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` and create a new reviewed preregistration before it runs.
### P1 - US active-only + forward；A-share alpha priority

- Current US model is active-only universe + forward-live validation only. Historical US backtests are exploration / idea-only forever; they cannot prove alpha, support ship-gate, unlock full-size, or authorize DataHub / production.
- Forward universe must be frozen point-in-time at the forward start date; real delisting / halt / merger / bankruptcy / no-trade outcomes during the forward window must be captured, not deleted.
- No further inactive / delisted historical coverage work or paid / specialized US data purchase is required now. Remaining provider work is only license / storage, active-PIT if used, active price / corporate actions if used, SEC parser / mapping if used, fallback / stability, and production-readiness gates.
- Next high-value work, after Claude review / user approval / commit of this repair, is the reviewed materialization retry. Full audit comes only after materialization summary review; signal search comes only after amended full audit PASS + review. Until then, do not run full alpha search.

### P2 - DataHub local resource boundary

- Future Phase 7c / runner implementation must call `engine.datahub.job_spec_contract.validate_datahub_job_spec_contract` / `validate_datahub_job_spec_file` and consume the shared-layer / report / reproducibility / data-quality / minimal-read-path contracts; default all-system / all-market / all-lane / full-refresh runs remain disallowed unless explicit approval + reviewed job spec says otherwise.

### P2 - A-short maintenance line

- 继续 weekly forward capture / comparison-track accumulator / forward evidence accumulation；12 期新增 forward 样本后再重新审查 score / ESP / veto overlap；any new alpha search needs a new reviewed preregistration.

---

## 6. 常用命令

```powershell
# 24 月 production rank 回测
python runners\backtest_rank.py --mode production --periods 24 --freq monthly --end-date 20260301 --split-date 20250101 --refresh-forward-daily

# Stats-only 重统计
python runners\backtest_rank.py --stats-only --mode production --periods 24 --freq monthly --end-date 20260301

# 每周五实时选股
python A-EGS\egs_main.py --as-of <YYYYMMDD>

# 周五一键
.\runners\weekly_screening.ps1 -AsOf 20260530 -L3Mode neutralize
.\runners\weekly_screening.ps1 -SkipCanary
```

---

## 7. 雷区

- 不接券商 / OS automation / 自动下单；所有交易动作仍由用户手动执行。
- 不因 Phase 7a audit、Phase 7b provider evidence 或 DataHub 工程放松 ship gate；full-size 必须满足 monthly alpha t-stat >= 2.0、Sharpe >= 1.0、max drawdown <= 15%、forward live data >= 12 个月。
- A/US cash 默认不互通；跨市场资金转移必须显式人工决策或后续 coordinator 规则。
- 不把 paper evidence 当 ship-gate evidence；ship gate 只接受 live-normalized evidence。
- 不用旧 12p findings 或旧 `_cc.md` 结论。
- 改 `A-EGS/egs_main.py` 前必须先 view 当前文件。

---

## 维护规则

- `CURRENT.md` 保持短 snapshot，目标 <150 行；最新状态放这里，过程 / review verdict / rejected alternatives 放 `SESSION_LOG.md`。
- 新 handoff 高门槛；默认追加到当前 phase 主 handoff，旧 handoff 不重组；新增文档必须先在 `docs/README.md` routing table 中说明 owner role。
- Material audit findings must be fixed in-round or entered in `docs/system_risk_register.md`.
