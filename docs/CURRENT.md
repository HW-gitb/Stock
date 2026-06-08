# Stock 项目 - 当前状态快照
**最后更新**：2026-06-08（A-long large-cap cash_conversion signal-search EXECUTED → `statistical_alpha_clue_research_only`，NOT tradeable；实时 commit / 复审状态见 §0 + `docs/SESSION_LOG.md` 顶部）

**文档定位**：跨会话接续的短 snapshot。完整路由见 `docs/README.md`；过程、review verdict 和 rejected alternatives 见 `docs/SESSION_LOG.md` 顶部 1-3 条；历史 phase 细节见 `docs/handoff/README.md`。

---

## 0. Latest Delta
- 2026-06-08 the A-long `low_volatility` signal-search RUNNER slice has now Codex re-`审查` PASSED after Claude repaired the two pre-execution blockers (ledger gate + summary-schema invariants). Reviewed scope: `runners/a_long_large_cap_low_volatility_signal_search.py` + `schemas/a_long_large_cap_low_volatility_signal_search_execution_summary.schema.json` (28 cells) + 2 test files + closeout docs. It mirrors the executed cash_conversion runner package, swapping in the **price-only** signal (negative trailing 252-trading-day realized volatility of daily adj_factor total returns, sample stdev, min 120 valid daily returns; diagnostics = idiosyncratic-vol-vs-CSI300 + downside-semideviation, neither can rescue/define alpha), **drops** the restatement exclusion (price-only, with reason), and reuses the same top-500 PIT circ_mv universe + full-main-board daily close series + rolling relative-NAV risk gate + two-tier verdict + frozen `-15%` gate + HAC-t/cohort/concentration/sub-period clue gates. Startup months without a sufficient trailing window are excluded from cohort formation and asserted disjoint from the primary cohort. Verification: low_vol suite 56/56, full `tests/schema` 591/591, cash_conversion 24/24; independent bad-sample probes reject non-active / spent / multi-spend / misrouted ledgers and reject cell-id↔metadata, verdict/flag/count, startup-list, result-count, and tradeable/drawdown contradictions. The upstream DESIGN slice is already committed `71c652f`; singleton ledger still UNSPENT; no fetch, no execution, no spend. Next: Claude `提交`, then a separate user `执行` spends the singleton once. No `执行` yet.
- 2026-06-08 the A-long `cash_conversion` signal-search runner was built, committed (`527ac58`, after Codex PASS), and EXECUTED. Result `research/results/a_long_large_cap_cash_conversion_20260607/execution_summary.json` = **`statistical_alpha_clue_research_only`**: the primary cell PASSED the frozen statistical-alpha-clue gates (HAC t `2.47` vs CSI300, 68 cohorts, mean net excess `+0.0970`, both median sub-period halves positive, concentration OK) but is **NOT a tradeable candidate** — rolling relative-NAV drawdown `-0.1822` is worse than the `-0.15` gate. Singleton ledger now SPENT (`tests_spent_count=1`, `active_no_new_test_authorized`, `spent_passed_research_continue_only`). Research-only in-sample clue (vs-CSI300 single-sample); NO rerun / threshold-rescue / production / ship-gate / full-size without a new reviewed prereg+ledger or forward-live evidence. The result + spent ledger + the post-exec test/route repair (incl. the v2 route-doc convention) were **committed to local master** after Codex re-`审查` PASS (both Required findings resolved); the `cash_conversion` research line is now DONE. Any further A-long candidate requires a NEW reviewed prereg + ledger.
- 2026-06-08 the A-long `cash_conversion` design slice was reviewed by Codex (PASS) and committed (`63f5048` design + `f35f786` protocol): prereg flipped to `passed_independent_review_ready_for_freeze`, new singleton ledger unspent, 15/15 schema tests. Protocol committed: `批准修改` is no longer required between a Codex `审查` and a Claude `修复` (the user's `修复` authorizes directly), and `AGENTS.md` now carries the Claude implementer judge-before-execute standard. (That runner slice was later built, committed `527ac58`, and executed — see the top entry for the result.)
- 2026-06-07 (history — superseded; full step-by-step detail in `docs/SESSION_LOG.md` + commit log) large-cap pure-quality path: committed and FALSIFIED. `research/results/a_long_large_cap_pure_quality_20260607/execution_summary.json` = `falsified_large_cap_pure_quality_under_frozen_rules`, 0 clues, primary composite 68 cohorts, HAC t `0.9057` vs CSI300, max drawdown `-2.07`, singleton ledger spent (`spent_failed_outcome_threshold`); 4 diagnostic-only cells had t≥2 but cannot rescue the failed primary. Path ran `daily_basic circ_mv` probe → 96/96 materialization → local market-cap audit PASS (reviewed `000043.SZ` / `20191129` bounded data-quality exclusion) → signal search; intermediate repairs committed (R-NEUT-BUCKET marginal 0.5/0.5 industry+size neutralization, R-SIZE-GATE-SCOPE cohort-forming-only size gate). cash_conversion was the strongest single-factor diagnostic here and is the current path; do NOT re-route to this closed path without a new reviewed prereg+ledger.
- 2026-06-05→06 (history — superseded; full step-by-step detail in `docs/SESSION_LOG.md` + commit log) full-main-board frozen signal search: committed and FALSIFIED. `research/results/a_long_signal_search_20260604/execution_summary.json` = `no_alpha_found_under_frozen_rules`, 0 clues, 32 cells, 417,407 return rows, singleton ledger spent (`spent_failed_outcome_threshold`). Path ran the 23,718-call materialization (PIT `namechange_2018_2025` + `H00300.CSI` / `H00852.CSI` TR close) → data-integrity audit PASS → signal search; committed methodology repairs include R-SPLIT/R-BENCH close-to-close total-vs-total (`adj_factor` / H-code TR close), Newey-West HAC-t for overlapping cohorts, PIT name-veto without `stock_basic.name` look-ahead, 1,504 restatement-ambiguous exclusions, perf caching, and schema-hard `jsonschema`. Do NOT re-route to this closed path without a new reviewed prereg+ledger.
- US operating model is active-only + forward-live validation; historical US backtests stay idea-only. A-short steady is `risk_filter_only`. A-share scope is main-board only: A-short already filters non-main boards before analysis, and A-long materialization / audit runners now reject non-main active symbols. The old A-long panel containing `300750.SZ` is historical only and cannot be used as the current alpha/data-readiness path.
---

## 1. 当前 Phase 与目标

- **当前 Phase**：A-share alpha validation。两条已冻结路线均已证伪并入库(全主板 frozen signal search `no_alpha`;large-cap pure-quality composite `falsified`, `cfb4058`)。diagnostic-derived 单因子 `cash_conversion`(单因子 OCF/|NI|、两层判决、504d/CSI300 primary)设计已审过入库(`63f5048`)、信号搜索 runner 已执行(`527ac58`)。该线终判与 ledger 花费状态见 §0 + `docs/SESSION_LOG.md` 顶部 verdict + `research/results/a_long_large_cap_cash_conversion_20260607/execution_summary.json`。三条线均**不得 rerun / 换阈值 / 换基准 / 换 universe / 诊断 rescue**,除非新 reviewed prereg+ledger 或 forward-live。
- **当前 P0 / P1 目标**：已执行的 `cash_conversion` slice(result + 已花 ledger + post-exec test/route 修复)的 Codex 复审 → 提交闭环进度见 §0 + `docs/SESSION_LOG.md`(单一实时来源)。三条已入库/已花的线**均不得 rerun / 换阈值 / 换基准 / 换 universe / 诊断 rescue**,除非新 reviewed prereg+ledger 或 forward-live;后续新候选需新 prereg+ledger。
- **当前 P1 provider blocker**：US inactive / delisted historical coverage is user-accepted as scoped out for the current active-only forward model. `SR-PROVIDER-001` remains open for license / storage, active-symbol PIT if fundamentals are used, active price-adjustment / corporate actions if used, SEC parser / mapping if used, fallback / stability, provider selection, DataHub / runner consumption, and production readiness. US forward universes must be PIT-frozen at start and must capture real delisting / halt / merger / no-trade outcomes during the forward window; the 12-month forward-live ship-gate requirement is unchanged.
- **执行锁**：`cash_conversion`、large-cap pure-quality、全主板三条线的 singleton ledger 均已花;**不得 rerun / 换阈值 / 换基准 / 换 universe / 诊断 rescue / production / ship-gate / full-size**,除非新 reviewed prereg+ledger 或 forward-live。各线终判与 ledger 状态见 §0 + `docs/SESSION_LOG.md` + 各自 `execution_summary.json`。
- **协作模式**：Claude = Designer + Implementer；Codex = Independent Reviewer；用户 = Final Approver(2026-06-07 角色互换;详 `AGENTS.md` §角色分工 与 commit `bf26f13`)。
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
- `docs/AI_REVIEW_PROTOCOL.md` - review/修复/提交 工作流的兼容指针;**权威角色分工(2026-06-07 互换:Claude = 设计+实现,Codex = 独立审查)、命令绑定、对抗式深审标准均以 `AGENTS.md` 为准**。
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
- The A-long `cash_conversion` signal-search runner (`runners/a_long_large_cap_cash_conversion_signal_search.py`, committed `527ac58`) is EXECUTED. Its two-tier verdict and the singleton-ledger spend state are recorded in the single live source — `docs/CURRENT.md` §0 + `docs/SESSION_LOG.md` top + `research/results/a_long_large_cap_cash_conversion_20260607/execution_summary.json`. Research-only in-sample clue; no rerun / threshold-rescue / production / ship-gate / full-size without a new reviewed prereg+ledger or forward-live. The old full-main-board and large-cap pure-quality routes are both falsified, committed, and closed; do not route work back to them.
- Do not run `research/preregistrations/a_share_minimal_data_burst_20260531.json`; it remains `BLOCKED_DO_NOT_RUN`.
- The full-universe redesigned outcome / excess slice has failed its registered thresholds; do not rerun EGS, change preregistered parameters, full-refresh forward_daily, or reinterpret it as production evidence.
- Any further redesigned A-share burst test must append a planned test to `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` and create a new reviewed preregistration before it runs.
### P1 - US active-only + forward；A-share alpha priority

- Current US model is active-only universe + forward-live validation only. Historical US backtests are exploration / idea-only forever; they cannot prove alpha, support ship-gate, unlock full-size, or authorize DataHub / production.
- Forward universe must be frozen point-in-time at the forward start date; real delisting / halt / merger / bankruptcy / no-trade outcomes during the forward window must be captured, not deleted.
- No further inactive / delisted historical coverage work or paid / specialized US data purchase is required now. Remaining provider work is only license / storage, active-PIT if used, active price / corporate actions if used, SEC parser / mapping if used, fallback / stability, and production-readiness gates.

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
