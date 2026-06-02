# Stock 项目 - 当前状态快照

**最后更新**：2026-06-02（US EGS SEC parser scope contract）

**文档定位**：跨会话接续的短 snapshot。完整路由见 `docs/README.md`；过程、review verdict 和 rejected alternatives 见 `docs/SESSION_LOG.md` 顶部 1-3 条；历史 phase 细节见 `docs/handoff/README.md`。

---

## 0. Latest Delta

- Original A-share `minimal_data_burst` remains blocked; corrected-basis supersession failed preflight with `valid_signal_events = 0`, is spent as `failed_preflight_zero_signal_events`, and must not run outcome / benchmark-excess.
- The full-universe redesigned A-share burst outcome / excess slice has run on frozen local data only: raw signal events 134, selected 123, available returns 116.
- `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json` records `decision = falsified_or_redesign_required`: mean net CSI1000 excess `-2.8696001309` pp, monthly clustered t-stat `-0.6312965283`, max monthly signal-excess drawdown `26.5735343137` pp.
- Owner audit/spec now reflect the failure: `docs/phase7a_alpha_plausibility_audit.json` marks `a_share_burst_minimal_data = redesign_required`, and `docs/burst_lane_spec.md` blocks further A-share minimal-data burst tests without a new ledger planned test and reviewed preregistration.
- `docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json` routes post-stable-retry blockers; fallback playbook, incident-log contract, license-storage review, and `docs/provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json` now classify default-deny behavior, future incident records, FMP / SEC storage blockers, and SEC audit-only parser scope from existing repo evidence only; none authorizes SEC calls, raw payload parsing, current terms legal review, provider calls, status polling, data fetch, production storage, fallback execution, DataHub / runner consumption, Phase 7c, or ship-gate claim.
- `schemas/datahub_local_resource_budget.schema.json` / `docs/datahub_local_resource_budget_contract_20260602.json` define the Phase 7c precondition that local defaults are single-slice / incremental / lazy / checkpointed, not all-system full refresh; this does not implement DataHub, change runners, fetch provider data, or authorize Phase 7c.

---

## 1. 当前 Phase 与目标

- **当前 Phase**：Phase 7b-2 P1 closure plan is documented; US EGS direction remains FMP primary candidate + SEC EDGAR fundamentals audit, FMP stable endpoints have only a two-symbol AAPL / MSFT access / shape retry result, license-storage and SEC audit parser scope are classified only from existing repo evidence, and Phase 7c now has a schema-first local resource budget precondition.
- **当前 P0 / P1 目标**：do not rerun or rescue the failed redesigned burst test；use the remaining-blocker plan, fallback playbook, incident-log contract, license-storage review, and SEC parser scope contract to prevent broad provider deployment after the FMP stable retry。
- **当前 P1 provider blocker**：FMP stable small sample succeeded, and fallback / incident / stability / incident-log / license-storage / SEC audit-scope behavior is schema-first designed or classified, but coverage / current terms and production storage rights / PIT semantics / actual SEC parser implementation / incident-log writer / executed fallback / stability evidence / production readiness remain unresolved；仍不允许 FMP new token / trial / paid access、`yfinance`、provider selection、full-market data fetch、status polling、adapter、DataHub、production runner consumption 或 Phase 7c，除非另有 explicit approval + reviewed decision。
- **执行锁**：原 prereg 仍为 `BLOCKED_DO_NOT_RUN`；corrected-basis prereg 已消耗 test budget 且不得运行 outcome / excess；redesigned test 已消耗 ledger planned test 且 outcome 失败。任何 material audit finding 必须修复或进入 risk register，不能只留在 chat。
- **协作模式**：Codex = Designer + Implementer；Claude = Independent Reviewer；用户 = Final Approver。详 `docs/AI_REVIEW_PROTOCOL.md`。
- **后台线**：A-short Phase 6b 只保留 weekly forward capture、comparison-track accumulator、forward evidence accumulation；不扩无关小工具。

---

## 2. 最近已完成

- **A-share burst audit/spec downgrade**（2026-06-01）：`docs/phase7a_alpha_plausibility_audit.json` / `docs/burst_lane_spec.md` 已把 A-share minimal-data burst 从 `continue` 降为 `redesign_required`，并引用 failed outcome evidence。
- **A-share burst redesigned outcome**（2026-06-01）：`evidence_report.json` / `signal_events.csv` / `monthly_stats.csv` 已生成；同一 frozen prereg + patched benchmark-open cache 计算后失败 research-continuation thresholds，decision 为 `falsified_or_redesign_required`。
- **Risk-register maintenance group**（2026-06-01）：benchmark-open input、forward tracker、forward-live evidence、analysis_input PIT/schema、daily stats insufficiency、forward-return status、relisted lookback、LLM prompt boundary、drawdown evidence guard 等已按 `docs/system_risk_register.md` resolved entries 收敛；细节见 risk register。
- **US EGS remaining blocker / fallback / incident / license / SEC scope contracts**（2026-06-02）：remaining-blocker plan, fallback playbook, incident-log contract, license-storage review, and `schemas/provider_p1_sec_edgar_audit_parser_scope_contract.schema.json` / `docs/provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json` now route or classify post-stable-retry blockers while keeping `SR-PROVIDER-001` open.
- **DataHub local resource budget contract**（2026-06-02）：`schemas/datahub_local_resource_budget.schema.json` / `docs/datahub_local_resource_budget_contract_20260602.json` require future DataHub / runner jobs to default to single-market, single-lane, bounded-window, lazy / incremental / checkpointed slices; `SR-RESOURCE-001` remains open until code-level enforcement exists.

---

## 3. 当前有效策略结论

基于 24 月 v7.10 production、Tier1-only 主口径：

- 工程链路健康；Phase 2 工程签收。
- 20d benchmark excess 仍不显著：`t1_net t=1.60`、`excess_csi300 t=0.57`、`excess_csi1000 t=0.17`。
- 5d `excess_csi1000 t=+2.88` 已降级为未校正、疑似 measurement-basis artifact 的线索；same-anchor corrected re-run 前不得当作 validated alpha。
- 强负信号仍是重点风控证据：`entry_flag=追高风险，周一确认`、`OVERHEAT`、`Tier2`。
- 当前 A-short steady 更像“过滤坏票”而不是“挑出好票”，不得当作 full-size alpha lane。
- 24p findings 尚未完成 multiple-testing / survivorship / regime sensitivity 重审；Phase 7a-1 audit 已要求重新标注证据等级。

失效旧结论：12 月 Top5 显著、12 期突破型反向信号、旧 `_cc.md` 整体结论、v7.9 前 completeness_score 分组结论均不可继续引用。

---

## 4. 当前关键文件

- `AGENTS.md` - 最高项目规则、固化决策、命令别名、启动顺序。
- `docs/README.md` - 完整 routing table 和文档维护规则。
- `docs/AI_REVIEW_PROTOCOL.md` - Codex / Claude / 用户三方 review / 修复 / 提交流程。
- `docs/system_risk_register.md` - durable open-risk queue；`执行` / `审查` 必读。
- `docs/SESSION_LOG.md` - 最新 cross-LLM reasoning / review verdict；只读顶部 1-3 条。
- `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` - Phase 7a+ 最高行动指南。
- `research/README.md` / `schemas/research_preregistration.schema.json` / `schemas/research_preflight_result.schema.json` / `schemas/program_test_budget_ledger.schema.json` / `schemas/evidence_report.schema.json` / `research/preregistrations/a_share_minimal_data_burst_20260531.json` / `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json` / `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json` / `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json` / `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json` / `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json` / `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/signal_events.csv` / `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/monthly_stats.csv` / `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` - research-only preregistration, preflight, evidence, and ledger owner files。
- `docs/provider_priority_benchmark_contract.md` - Phase 7a-3 provider evidence priority / provisional benchmark contract。
- `docs/provider_evidence_drift_monitor.md` / `schemas/provider_evidence_drift_monitor.schema.json` - Phase 7b provider evidence / drift monitor contract。
- `schemas/provider_p1_access_decision_plan.schema.json` / `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` / `schemas/provider_p1_sample_validation_access_approval.schema.json` / `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json` / `runners/us_egs_sample_validation.py` / `schemas/provider_p1_us_egs_sample_validation_summary.schema.json` / `docs/provider_evidence_p1_us_sample_validation_summary_20260602.json` / `schemas/provider_p1_fmp_endpoint_mapping_review.schema.json` / `docs/provider_evidence_p1_us_fmp_current_endpoint_mapping_review_20260602.json` / `schemas/provider_p1_fmp_stable_endpoint_retry_summary.schema.json` / `docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json` / `schemas/provider_p1_remaining_blocker_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json` / `schemas/provider_p1_fallback_incident_stability_playbook.schema.json` / `docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json` / `schemas/provider_p1_incident_log_contract.schema.json` / `docs/provider_evidence_p1_us_incident_log_contract_20260602.json` / `schemas/provider_p1_license_storage_retention_review.schema.json` / `docs/provider_evidence_p1_us_license_storage_retention_review_20260602.json` / `schemas/provider_p1_sec_edgar_audit_parser_scope_contract.schema.json` / `docs/provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json` - Phase 7b-2 P1 access plan, approval, no-secret sample summary, FMP mapping / retry, remaining-blocker routing, fallback / incident contracts, license-storage review, and SEC parser scope contract。
- `schemas/provider_p1_readiness_review.schema.json` / `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json` - Phase 7b-2 P1 readiness review matrix（collection complete；Phase 7c / provider selection / broad data fetch blocked）。
- `docs/evidence_feasibility_controls.md` / `schemas/evidence_feasibility_controls.schema.json` - Phase 7a-4 burst promotion / evidence feasibility controls。
- `docs/evidence_report_schema_contract.md` / `schemas/evidence_report.schema.json` - Phase 7a-5 evidence report schema contract。
- `docs/alpha_plausibility_audit.md` / `schemas/alpha_plausibility_audit.schema.json` - Phase 7a-1 audit owner and contract。
- `docs/evidence_capital_policy.md` - paper vs live-normalized evidence owner。
- `docs/strategy_design_synthesis.md` - 总体策略架构 owner。
- `docs/burst_lane_spec.md` / `docs/us_short_spec.md` / `docs/long_alpha_spec.md` - lane owner specs。
- `docs/provider_data_requirements_audit.md` / `schemas/provider_capability_catalog.schema.json` - provider requirements / capability contract。
- `docs/portfolio_allocation_policy.md` - 35/65、bucket、cash non-fungibility、manual-only capital policy。
- `docs/datahub_design.md` / `schemas/datahub_local_resource_budget.schema.json` / `docs/datahub_local_resource_budget_contract_20260602.json` - DataHub / provider / factor-layer guardrails and Phase 7c local resource budget precondition。
- `docs/handoff/README.md` - phase handoff index；不要全量读 handoff。

---

## 5. 下一步

### P0 / P1 - Post redesigned outcome boundary

- Read `docs/system_risk_register.md` before choosing the next `执行`.
- The preregistration / ledger-planned-test slice passed review and was committed as `1a3e71e`; do not run the current corrected-basis artifact for outcome / excess calculation.
- Do not run `research/preregistrations/a_share_minimal_data_burst_20260531.json`; it remains `BLOCKED_DO_NOT_RUN`.
- The full-universe redesigned outcome / excess slice has failed its registered thresholds; do not rerun EGS, change preregistered parameters, full-refresh forward_daily, or reinterpret it as production evidence.
- Any further redesigned A-share burst test must append a planned test to `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` and create a new reviewed preregistration before it runs.
- If no new research test or provider-access work is user-approved, the next default work is the risk-register maintenance group; reviewed forward-live evidence must now use `schemas/forward_live_evidence.schema.json` and real provenance / reconciliation, not the example artifact.

### P1 - US EGS sample-validation follow-up

- Treat the remaining-blocker plan, fallback playbook, incident-log contract, license-storage-retention review, and SEC parser scope contract as the active `SR-PROVIDER-001` router; a safe next no-access slice is FMP PIT / observed-date semantics design or SEC parser field-family mapping contract, while any current terms web/legal review, SEC endpoint call, raw-payload parse, parser implementation, log-writer, fallback-execution, status polling, or provider call needs separate approval.
- 不得 silent default、latest-only 回填历史证据，或把 provider status guess 写成 production-ready evidence。
- 不得建 adapter / DataHub table、把 sample runner 接入 production runner、抓 broader provider data 或接 broker / OS automation。

### P2 - DataHub local resource boundary

- Future Phase 7c / runner implementation must consume `schemas/datahub_local_resource_budget.schema.json`; default all-system / all-market / all-lane / full-refresh runs remain disallowed without explicit approval + reviewed job spec.

### P2 - A-short maintenance line

- 继续 weekly forward capture、comparison-track accumulator、forward evidence accumulation。
- 12 期新增 forward 样本后再重新审查 score / ESP / veto overlap。

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
