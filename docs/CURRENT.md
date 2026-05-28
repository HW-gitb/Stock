# Stock 项目 - 当前状态快照

**最后更新**：2026-05-28（Phase 7b-2 P1 US coverage / fallback / incident candidate evidence snapshot）

**文档定位**：跨会话接续的短 snapshot。完整路由见 `docs/README.md`；过程、review verdict 和 rejected alternatives 见 `docs/SESSION_LOG.md` 顶部 1-3 条；历史 phase 细节见 `docs/handoff/README.md`。

---

## 0. Latest Delta

- Phase 7b-2 P1 evidence snapshots now include six reviewed artifacts: public-source, market-data-candidate, authorization / cost / stability, benchmark / GICS, fundamentals observed-date, and coverage / fallback / incident candidate evidence. The latest artifact is `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json`.
- P1 remains `partial` and implementation-blocked. These snapshots do not select a provider, fetch provider data, approve paid access, build adapters, create DataHub tables, or modify runners.
- `schemas/provider_evidence_drift_monitor.schema.json` remains v1.1.0: it validates `provider_evidence_population_snapshot` artifacts and requires source refs for `reviewed_provider_evidence`.
- Next P1 work should produce a readiness review matrix comparing the six snapshots field-by-field; it still must not select a provider, fetch data, or start DataHub implementation.

---

## 1. 当前 Phase 与目标

- **当前 Phase**：Phase 7b-2 provider capability evidence population is in progress.
- **当前 P0 目标**：按 `docs/provider_priority_benchmark_contract.md` 的 P1-P4 queue 和 `docs/provider_evidence_drift_monitor.md` contract 继续填充 provider capability evidence，不得 silent default、latest-only 回填，或把 provider guess 写成 production-ready evidence。
- **当前 blocker**：无待用户决策 blocker；但 P1 仍需 readiness review、sample-row/license validation、coverage-count verification 和 fallback / incident playbook 后才能供 Phase 7c 消费。
- **协作模式**：Codex = Designer + Implementer；Claude = Independent Reviewer；用户 = Final Approver。详 `docs/AI_REVIEW_PROTOCOL.md`。
- **后台线**：A-short Phase 6b 只保留 weekly forward capture、comparison-track accumulator、forward evidence accumulation；不扩无关小工具。

---

## 2. 最近已完成

- **Phase 7b-2 P1 US coverage / fallback / incident candidate evidence snapshot**（2026-05-28）：`docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json` 已建立；覆盖 Intrinio / FMP / Massive / Norgate / Nasdaq Data Link 的 coverage、status / incident、fallback / error-code、license / sample-row validation evidence；P1 仍 `partial / blocked`，下一步是 P1 readiness review matrix。
- **Phase 7b-2 P1 earlier evidence snapshots**（2026-05-28）：public-source、market-data-candidate、authorization / cost / stability、benchmark / GICS、fundamentals observed-date 五份 artifact 均已建立并各有 regression test；这些只证明 candidate evidence，不等于 provider selection、PIT-safe production factor 或 implementation readiness。
- **Phase 7b-1 provider evidence / drift monitor contract**（2026-05-28）：`docs/provider_evidence_drift_monitor.md`、`schemas/provider_evidence_drift_monitor.schema.json`、example 和 schema tests 已建立；覆盖 P1-P4 queue、provider evidence records、readiness rollup、drift dimensions/action set。
- **Phase 7a-5 evidence report schema contract**（2026-05-28）：`docs/evidence_report_schema_contract.md`、`schemas/evidence_report.schema.json`、example 和 schema tests 已建立。
- **Phase 7a-4 evidence feasibility controls**（2026-05-28）：`docs/evidence_feasibility_controls.md`、`schemas/evidence_feasibility_controls.schema.json`、example 和 schema tests 已建立。
- **Phase 7a-3 provider priority / provisional benchmark contract**（2026-05-28）：`docs/provider_priority_benchmark_contract.md` 已建立，锁定 provider evidence priority 与 provisional evidence benchmark table。
- **Phase 7a-2 owner-spec routing**（2026-05-27）：`strategy_design_synthesis`、`burst_lane_spec`、`long_alpha_spec`、`us_short_spec` 已记录 audit verdict、minimal/full burst 边界、long defer blocker、US microstructure / calendar / monitoring 边界。
- **Phase 7a-1 first formal alpha audit**（2026-05-27）：`docs/phase7a_alpha_plausibility_audit.json` 已建立并通过 schema validation；该 audit 不是 ship-gate evidence。
- **Phase 7 provider capability / field catalog contract**（2026-05-27）：`schemas/provider_capability_catalog.schema.json` v1.0.0 已建立；不选 provider、不抓数据、不建 adapter / DataHub table。
- **Phase 6 spec pack**（2026-05-27）：`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/long_alpha_spec.md`、`docs/provider_data_requirements_audit.md` 完成 docs-only baseline。

更早事项见 `docs/handoff/README.md`、`AGENTS.md §交接记录`、`docs/SESSION_LOG.md` 和 `git log --all`。

---

## 3. 当前有效策略结论

基于 24 月 v7.10 production、Tier1-only 主口径：

- 工程链路健康；Phase 2 工程签收。
- 20d benchmark excess 仍不显著：`t1_net t=1.60`、`excess_csi300 t=0.57`、`excess_csi1000 t=0.17`。
- 5d `excess_csi1000 t=+2.88` 是当前唯一显著正 alpha 线索。
- 强负信号仍是重点风控证据：`entry_flag=追高风险，周一确认`、`OVERHEAT`、`Tier2`。
- 当前 A-short steady 更像“过滤坏票”而不是“挑出好票”，不得当作 full-size alpha lane。
- 24p findings 尚未完成 multiple-testing / survivorship / regime sensitivity 重审；Phase 7a-1 audit 必须重新标注证据等级。

失效旧结论：12 月 Top5 显著、12 期突破型反向信号、旧 `_cc.md` 整体结论、v7.9 前 completeness_score 分组结论均不可继续引用。

---

## 4. 当前关键文件

- `AGENTS.md` - 最高项目规则、固化决策、命令别名、启动顺序。
- `docs/README.md` - 完整 routing table 和文档维护规则。
- `docs/AI_REVIEW_PROTOCOL.md` - Codex / Claude / 用户三方 review / 修复 / 提交流程。
- `docs/SESSION_LOG.md` - 最新 cross-LLM reasoning / review verdict；只读顶部 1-3 条。
- `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` - Phase 7a+ 最高行动指南。
- `docs/provider_priority_benchmark_contract.md` - Phase 7a-3 provider evidence priority / provisional benchmark contract。
- `docs/provider_evidence_drift_monitor.md` / `schemas/provider_evidence_drift_monitor.schema.json` - Phase 7b provider evidence / drift monitor contract。
- `docs/provider_evidence_p1_us_public_sources_20260528.json` - Phase 7b-2 P1 public-source evidence snapshot（partial / blocked）。
- `docs/provider_evidence_p1_us_market_data_candidates_20260528.json` - Phase 7b-2 P1 market-data-candidate evidence snapshot（partial / blocked）。
- `docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json` - Phase 7b-2 P1 authorization / cost / stability evidence snapshot（partial / blocked）。
- `docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json` - Phase 7b-2 P1 benchmark / GICS candidate evidence snapshot（partial / blocked）。
- `docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json` - Phase 7b-2 P1 fundamentals observed-date candidate evidence snapshot（partial / blocked）。
- `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json` - Phase 7b-2 P1 coverage / fallback / incident candidate evidence snapshot（partial / blocked）。
- `docs/evidence_feasibility_controls.md` / `schemas/evidence_feasibility_controls.schema.json` - Phase 7a-4 burst promotion / evidence feasibility controls。
- `docs/evidence_report_schema_contract.md` / `schemas/evidence_report.schema.json` - Phase 7a-5 evidence report schema contract。
- `docs/alpha_plausibility_audit.md` / `schemas/alpha_plausibility_audit.schema.json` - Phase 7a-1 audit owner and contract。
- `docs/phase7a_provider_status_snapshot.json` / `docs/phase7a_alpha_plausibility_audit.json` - Phase 7a-1 audit inputs and artifact。
- `docs/evidence_capital_policy.md` - paper vs live-normalized evidence owner。
- `docs/strategy_design_synthesis.md` - 总体策略架构 owner。
- `docs/burst_lane_spec.md` / `docs/us_short_spec.md` / `docs/long_alpha_spec.md` - lane owner specs。
- `docs/provider_data_requirements_audit.md` / `schemas/provider_capability_catalog.schema.json` - provider requirements / capability contract。
- `docs/portfolio_allocation_policy.md` - 35/65、bucket、cash non-fungibility、manual-only capital policy。
- `docs/datahub_design.md` - DataHub / provider / factor-layer guardrails。
- `docs/handoff/README.md` - phase handoff index；不要全量读 handoff。

---

## 5. 下一步

### P0 - Phase 7b-2 P1 readiness review matrix

- 基于 6 份 P1 evidence snapshots 做 field-by-field readiness review matrix：coverage counts、PIT / observed-date、security master、benchmark / GICS、license、fallback、incident / stability、sample-row validation。
- 不得 silent default、latest-only 回填历史证据，或把 provider status guess 写成 production-ready evidence。
- 不得建 adapter / DataHub table、改 runner、抓 provider data 或接 broker / OS automation；provider selection 若需要也必须另走 reviewed decision。

### P1 - A-short maintenance line

- 继续 weekly forward capture、comparison-track accumulator、forward evidence accumulation。
- 12 期新增 forward 样本后再重新审查 score / ESP / veto overlap。

### P2 - Later implementation / cleanup

- Phase 8 lane implementation with production monitoring / circuit breaker / execution feasibility controls。
- Phase 9 coordinator: cross-lane conflict resolution、unified report、position reconciliation、alert priority。

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
.\runners\weekly_screening.ps1 -AsOf 20260530
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
- 新 handoff 高门槛；默认追加到当前 phase 主 handoff。旧 handoff 不重组。
- 新增文档必须先在 `docs/README.md` routing table 中说明 owner role。
