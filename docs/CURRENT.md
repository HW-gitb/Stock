# Stock 项目 - 当前状态快照
**最后更新**：2026-06-04（A-long Tushare route-gap repair pass）

**文档定位**：跨会话接续的短 snapshot。完整路由见 `docs/README.md`；过程、review verdict 和 rejected alternatives 见 `docs/SESSION_LOG.md` 顶部 1-3 条；历史 phase 细节见 `docs/handoff/README.md`。

---

## 0. Latest Delta

- Original A-share `minimal_data_burst` remains blocked; corrected-basis supersession failed preflight with `valid_signal_events = 0`, is spent as `failed_preflight_zero_signal_events`, and must not run outcome / benchmark-excess.
- The full-universe redesigned A-share burst outcome / excess slice has run on frozen local data only: raw signal events 134, selected 123, available returns 116.
- `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json` records `decision = falsified_or_redesign_required`: mean net CSI1000 excess `-2.8696001309` pp, monthly clustered t-stat `-0.6312965283`, max monthly signal-excess drawdown `26.5735343137` pp.
- Owner audit/spec now reflect the failure: `docs/phase7a_alpha_plausibility_audit.json` marks `a_share_burst_minimal_data = redesign_required`, and `docs/burst_lane_spec.md` blocks further A-share minimal-data burst tests without a new ledger planned test and reviewed preregistration.
- User approved the exact US EGS coverage-count packet; `runners/us_egs_coverage_count_packet.py` executed 5 active symbols × 6 FMP stable endpoint families (`AAPL`, `MSFT`, `NVDA`, `JPM`, `XOM`) with 30/30 HTTP 200, raw payloads only under gitignored `provider_samples/us_egs_coverage_count_20260602/fmp_stable/`, and tracked no-secret summary at `docs/provider_evidence_p1_us_coverage_count_execution_summary_20260602.json`.
- `schemas/provider_p1_missing_key_metrics_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json` now route the three missing key-metrics fields as candidate derivations pending separate field-presence / lineage review; this performs no raw-payload parse, no new provider call, no derivation implementation, no DataHub / runner consumption, and no Phase 7c authorization.
- Phase 7c now has schema-first contracts for local resource/job-spec enforcement, shared ODS/DWD/DWS/factor layers, report families, reproducibility manifests, data-quality monitor boundaries, and a minimal A-share local-cache read-path plan (`engine/datahub/job_spec_contract.py`, `schemas/datahub_shared_layer_contract.schema.json`, `schemas/datahub_report_contract.schema.json`, `schemas/datahub_reproducibility_manifest.schema.json`, `schemas/datahub_data_quality_monitor_contract.schema.json`, `schemas/datahub_minimal_a_share_read_path_plan.schema.json`). These still do not fetch provider data, read cache, create DataHub tables, change runners, authorize provider selection / full-size US / production claims, or provide ship-gate evidence.
- `execution_aggregate_report` v1.1.4 now binds reviewed forward-live evidence to aggregate `capital_context`, validates source-window coverage for claimed months, and requires at least 12 monthly alpha / return observations before alpha t-stat or Sharpe metrics can pass; full-size remains blocked by the concurrency gate.
- US operating model is fixed as active-only + forward-live validation; historical US backtests stay idea-only. The repaired A-short steady re-audit is `risk_filter_only`. A-long route validation touched existing Tushare data and the follow-up route-gap repair passed small-sample field checks: SW membership maps through `index_member_all` current fields (`ts_code` / `l2_code`), and an older delisted sample (`000666.SZ`) returned terminal daily price and adj_factor rows. A-long still cannot search for alpha until reviewed materialization and a new data-integrity audit pass.
---

## 1. 当前 Phase 与目标

- **当前 Phase**：A-share alpha validation is the active priority; A-long data-integrity is blocked until Tushare data is materialized under review and then re-audited. Phase 7c implementation remains not started.
- **当前 P0 / P1 目标**：review the A-long route-gap repair result, then create a reviewed incremental materialization packet；do not full-materialize, rerun the spent audit, or start signal search without separate reviewed authorization。
- **当前 P1 provider blocker**：US inactive / delisted historical coverage is user-accepted as scoped out for the current active-only forward model. `SR-PROVIDER-001` remains open for license / storage, active-symbol PIT if fundamentals are used, active price-adjustment / corporate actions if used, SEC parser / mapping if used, fallback / stability, provider selection, DataHub / runner consumption, and production readiness. US forward universes must be PIT-frozen at start and must capture real delisting / halt / merger / no-trade outcomes during the forward window; the 12-month forward-live ship-gate requirement is unchanged.
- **执行锁**：A-long signal search is blocked because the data audit is `blocked_missing_required_source`; route field checks are only small-sample evidence and do not replace materialization + re-audit. A-short steady is `risk_filter_only` and spent；burst paths remain blocked/failed. Material audit findings must be fixed or entered in the risk register.
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
- **A-long Tushare route validation**（2026-06-04）：`runners/a_long_tushare_route_validation_packet.py` executed 23 fixed Tushare calls and wrote `docs/a_long_tushare_route_validation_execution_summary_20260604.json`; result is partial, not usable for alpha.
- **A-long Tushare route-gap repair**（2026-06-04）：`runners/a_long_tushare_route_gap_repair_packet.py` executed 5 fixed Tushare calls and wrote `docs/a_long_tushare_route_gap_repair_execution_summary_20260604.json`; the two failed route pieces passed small-sample field checks, but this still does not authorize alpha search.

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
- `research/README.md` / `schemas/research_preregistration.schema.json` / `schemas/a_short_steady_alpha_reaudit_preregistration.schema.json` / `schemas/a_long_data_integrity_audit_preregistration.schema.json` / `schemas/a_long_data_integrity_audit_report.schema.json` / `schemas/research_preflight_result.schema.json` / `schemas/program_test_budget_ledger.schema.json` / `schemas/evidence_report.schema.json` - research-only contract owners。
- `runners/a_long_data_integrity_audit.py` / `research/preregistrations/a_long_data_integrity_audit_20260603.json` / `research/results/a_long_data_integrity_audit_20260603/audit_report.json` / `research/ledgers/a_long_data_integrity_audit_program_test_budget_ledger_20260603.json` / `schemas/a_long_tushare_data_route_repair_plan.schema.json` / `docs/a_long_tushare_data_route_repair_plan_20260603.json` / `runners/a_long_tushare_route_validation_packet.py` / `schemas/a_long_tushare_route_validation_execution_summary.schema.json` / `docs/a_long_tushare_route_validation_execution_summary_20260604.json` / `runners/a_long_tushare_route_gap_repair_packet.py` / `schemas/a_long_tushare_route_gap_repair_execution_summary.schema.json` / `docs/a_long_tushare_route_gap_repair_execution_summary_20260604.json` - A-long data-integrity gate, route-repair, route-validation, and route-gap-repair owner files.
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
- The current active alpha-search route is A-long, but signal search is still blocked by the executed data-integrity audit. The route gaps have only passed small-sample repair validation. The next step is Claude review of the repair result and then a reviewed incremental materialization packet. Do not full-materialize, rerun the audit, or start signal search from this route evidence.
- Do not run `research/preregistrations/a_share_minimal_data_burst_20260531.json`; it remains `BLOCKED_DO_NOT_RUN`.
- The full-universe redesigned outcome / excess slice has failed its registered thresholds; do not rerun EGS, change preregistered parameters, full-refresh forward_daily, or reinterpret it as production evidence.
- Any further redesigned A-share burst test must append a planned test to `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` and create a new reviewed preregistration before it runs.
### P1 - US active-only + forward；A-share alpha priority

- Current US model is active-only universe + forward-live validation only. Historical US backtests are exploration / idea-only forever; they cannot prove alpha, support ship-gate, unlock full-size, or authorize DataHub / production.
- Forward universe must be frozen point-in-time at the forward start date; real delisting / halt / merger / bankruptcy / no-trade outcomes during the forward window must be captured, not deleted.
- No further inactive / delisted historical coverage work or paid / specialized US data purchase is required now. Remaining provider work is only license / storage, active-PIT if used, active price / corporate actions if used, SEC parser / mapping if used, fallback / stability, and production-readiness gates.
- Next high-value work is a reviewed incremental A-long Tushare materialization packet. Until a new audit passes, A-long cannot search for alpha.

### P2 - DataHub local resource boundary

- Future Phase 7c / runner implementation must call `engine.datahub.job_spec_contract.validate_datahub_job_spec_contract` / `validate_datahub_job_spec_file` and consume the shared-layer / report / reproducibility / data-quality / minimal-read-path contracts; default all-system / all-market / all-lane / full-refresh runs remain disallowed unless explicit approval + reviewed job spec says otherwise.

### P2 - A-short maintenance line

- 继续 weekly forward capture、comparison-track accumulator、forward evidence accumulation。
- 12 期新增 forward 样本后再重新审查 score / ESP / veto overlap。
- `SR-ALPHA-001` is no longer an active blocker for this clue because the corrected test failed before promotion; any new alpha search needs a new reviewed preregistration.

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

- `CURRENT.md` 保持短 snapshot，目标 <150 行；超出说明应移到 owner doc / handoff / SESSION_LOG。
- 最新状态放 `CURRENT.md`；过程、争议、review verdict 和 rejected alternatives 放 `SESSION_LOG.md`。
- 新 handoff 高门槛；默认追加到当前 phase 主 handoff，旧 handoff 不重组；新增文档必须先在 `docs/README.md` routing table 中说明 owner role。
- Material audit findings must be fixed in-round or entered in `docs/system_risk_register.md`.
