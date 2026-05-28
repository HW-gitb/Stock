# Stock 项目 — 当前状态快照

**最后更新**：2026-05-28（Phase 7a-4 evidence feasibility controls）
**文档定位**：跨会话接续的短 snapshot。完整路由见 `docs/README.md`；过程、review 和 rejected alternatives 见 `docs/SESSION_LOG.md` 顶部 1-3 条；历史 phase 细节见 `docs/handoff/README.md`。

---

## 0. Latest Delta

- Phase 7a-4 evidence feasibility controls 已建立：`docs/evidence_feasibility_controls.md` 与 `schemas/evidence_feasibility_controls.schema.json` 固化 burst minimal-to-full promotion、evidence capital、concentration / liquidity / ADV、slippage / borrow / limit-risk、circuit-breaker playbook；未选 provider、未抓数据、未改 runner。
- Phase 7a-3 provider priority / provisional benchmark contract 已建立：`docs/provider_priority_benchmark_contract.md` 将 provider evidence queue 固化为 P1 US fundamentals / filings / security master、P2 A-share fundamentals / announcements / SW history、P3 burst event / flow / options / borrow、P4 already-proven A-share EOD / CSI helpers。
- Phase 7a-2 owner-spec routing 已建立：`docs/strategy_design_synthesis.md`、`docs/burst_lane_spec.md`、`docs/long_alpha_spec.md`、`docs/us_short_spec.md` 已吸收第一版 audit verdict。
- Phase 7a-1 first formal alpha plausibility audit 已建立：`docs/phase7a_alpha_plausibility_audit.json`。结论分布为 3 条 `continue_as_risk_filter`、2 条 `continue`、6 条 `defer_until_provider_ready`；该 audit 不是 ship-gate evidence。
- Phase 7a-1 lightweight provider status snapshot 已建立：`docs/phase7a_provider_status_snapshot.json`。它只 inventory known readiness / blockers，不选 provider、不抓数据、不建 adapter / DataHub table。

---

## 1. 当前 Phase 与目标

- **当前 Phase**：Phase 7a-4 evidence feasibility controls established；下一步进入 Phase 7a-5 evidence report schemas。
- **当前 P0 目标**：定义 immutable decision packet、cost-adjusted return、cash drag、manual override、minimal reconciliation、thesis outcome log、research experiment log；不得选 provider、抓数据或改 runner。
- **当前 blocker**：无待用户决策 blocker。
- **协作模式**：Codex = Designer + Implementer；Claude = Independent Reviewer；用户 = Final Approver。详 `docs/AI_REVIEW_PROTOCOL.md`。
- **后台线**：A-short Phase 6b 只保留 weekly forward capture、comparison-track accumulator、forward evidence accumulation；不扩无关小工具。

---

## 2. 最近已完成

- **Phase 7a-4 evidence feasibility controls**（2026-05-28）：`docs/evidence_feasibility_controls.md`、`schemas/evidence_feasibility_controls.schema.json`、example 和 schema tests 已建立；覆盖 4 条 burst maturity lanes、paper-only minimal tier、capital pooling lock、liquidity / ADV / slippage / borrow / limit-risk、five-action circuit breaker。
- **Phase 7a-3 provider priority / provisional benchmark contract**（2026-05-28）：`docs/provider_priority_benchmark_contract.md` 已建立，锁定 provider evidence priority、provisional evidence benchmark table、benchmark switch rule、provider / benchmark evidence packet minimum。
- **Phase 7a-2 owner-spec routing**（2026-05-27）：`strategy_design_synthesis`、`burst_lane_spec`、`long_alpha_spec`、`us_short_spec` 已记录 audit verdict、minimal/full burst边界、long defer blocker、US microstructure / calendar / monitoring边界。
- **Phase 7a-1 first formal alpha audit**（2026-05-27）：`docs/phase7a_alpha_plausibility_audit.json` 已建立并通过 schema validation；覆盖 11 sub-lane / 6 parent lane，引用 `provider_status_snapshot_20260527_phase7a1`。
- **Phase 7a-1 provider status snapshot**（2026-05-27）：`docs/phase7a_provider_status_snapshot.json` 已建立；记录 A-share EOD / CSI helper ready evidence、US fundamentals / filings / security master unknown、burst full-data blocked、manual evidence partial、provider drift monitoring blocked。
- **Phase 7a-1 alpha audit schema contract**（2026-05-27）：`schemas/alpha_plausibility_audit.schema.json`、example 和 schema tests 已建立；覆盖 11 sub-lane / 6 parent lane、risk-filter evidence、long-lane fraud red flags、hypothesis registration、provider readiness confidence、paper/live-normalized evidence 边界。
- **Docs routing / owner cleanup**（2026-05-27）：`AGENTS.md` / `docs/README.md` 路由职责分离，`alpha_plausibility_audit.md` 删除字段 mirror，`portfolio_allocation_policy.md` phase-neutral 化。
- **Phase 7a+ alpha reality action guide**（2026-05-27）：`docs/ALPHA_VALIDATION_ACTION_GUIDE.md` 固化为当前 Phase 7a+ 最高行动指南，覆盖 survivorship、multiple testing、statistical power、PIT/security master、fraud red flags、regime / factor exposure、execution cost、risk-filter evidence、decision reproducibility、position reconciliation、production monitoring 等非可选护栏。
- **Phase 7a alpha-validation route**（2026-05-27）：`docs/alpha_plausibility_audit.md` 与 `docs/evidence_capital_policy.md` 建立。paper evidence 与 live-normalized ship-gate evidence 必须分离；不改变 35/65、bucket、cash non-fungibility 或 ship gate。
- **Phase 7 provider capability / field catalog contract**（2026-05-27）：`schemas/provider_capability_catalog.schema.json` v1.0.0、example 和 schema tests 已建立；不选 provider、不抓数据、不建 adapter / DataHub table。
- **Phase 6 spec pack**（2026-05-27）：`docs/burst_lane_spec.md`、`docs/us_short_spec.md`、`docs/long_alpha_spec.md`、`docs/provider_data_requirements_audit.md` 完成 docs-only baseline。
- **Phase 6a / 6b evidence helpers**（2026-05-26/27）：CSI1000 primary / CSI300 secondary benchmark policy、benchmark monthly return materializer、candidate-universe overlap audit、A-short variant tracking contract / materializer 已建立。

更早事项见 `docs/handoff/README.md`、`AGENTS.md §交接记录`、`docs/SESSION_LOG.md` 和 `git log --all`。

---

## 3. 当前有效策略结论

基于 24 期 v7.10 production、Tier1-only 主口径：

- 工程链路健康；Phase 2 工程签收。
- 20d benchmark excess 仍不显著：`t1_net t=1.60`、`excess_csi300 t=0.57`、`excess_csi1000 t=0.17`。
- 5d `excess_csi1000 t=+2.88` 是唯一当前显著正 alpha 线索。
- 强负信号仍是重点风控证据：`entry_flag=追高风险，周一确认`、`OVERHEAT`、`Tier2`。
- 框架本质判断：当前 A-short steady 更像 "过滤坏票" 而不是 "挑出好票"；不得当作 full-size alpha lane。
- 24p findings 尚未完成 multiple-testing / survivorship / regime sensitivity 重审；Phase 7a-1 audit 必须重新标注证据等级。

失效旧结论：12 期 Top5 显著、12 期突破型反向信号、旧 `_cc.md` 整体结论、v7.9 前 completeness_score 分组结论均不可继续引用。

---

## 4. 当前关键文件

- `AGENTS.md` — 最高项目规则、固化决策、命令别名、启动顺序。
- `docs/README.md` — 完整 routing table 和文档维护规则。
- `docs/AI_REVIEW_PROTOCOL.md` — Codex / Claude / 用户三方 review / 修复 / 提交流程。
- `docs/SESSION_LOG.md` — 最新 cross-LLM reasoning / review verdict；只读顶部 1-3 条。
- `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` — Phase 7a+ 最高行动指南。
- `docs/alpha_plausibility_audit.md` — Alpha plausibility / lane objective audit owner。
- `schemas/alpha_plausibility_audit.schema.json` — Phase 7a-1 audit artifact contract。
- `docs/phase7a_provider_status_snapshot.json` — Phase 7a-1 first-audit provider readiness input。
- `docs/phase7a_alpha_plausibility_audit.json` — Phase 7a-1 first formal alpha audit artifact。
- `docs/provider_priority_benchmark_contract.md` — Phase 7a-3 provider evidence priority / provisional benchmark contract。
- `docs/evidence_feasibility_controls.md` / `schemas/evidence_feasibility_controls.schema.json` — Phase 7a-4 burst promotion / evidence feasibility controls。
- `docs/evidence_capital_policy.md` — paper vs live-normalized evidence owner。
- `docs/strategy_design_synthesis.md` — 总体策略架构 owner。
- `docs/burst_lane_spec.md` / `docs/us_short_spec.md` / `docs/long_alpha_spec.md` — lane owner specs。
- `docs/provider_data_requirements_audit.md` / `schemas/provider_capability_catalog.schema.json` — provider requirements / capability contract。
- `docs/portfolio_allocation_policy.md` — 35/65、bucket、cash non-fungibility、manual-only capital policy。
- `docs/handoff/README.md` — phase handoff index；不要全量读 handoff。
- `docs/archive/README.md` — archive 说明；旧 docx 不作为当前执行依据。

---

## 5. 下一步

### P0 — Phase 7a-5 evidence report schemas

- Immutable decision packet。
- Cost-adjusted return、cash drag、manual override、minimal reconciliation。
- Thesis outcome log、research experiment log。

### P1 — Phase 7b provider evidence / drift monitor

- 按 `docs/provider_priority_benchmark_contract.md` 的 P1-P4 queue 填充 provider capability evidence。
- 建立 data quality / provider drift monitor；仍不得 silent default 或 latest-only 回填历史证据。

### P2 — A-short maintenance line

- 继续 weekly forward capture、comparison-track accumulator、forward evidence accumulation。
- 12 期新增 forward 样本后再重新审查 score / ESP / veto overlap。

### P3 — Later implementation / cleanup

- Phase 8 lane implementation with production monitoring / circuit breaker / execution feasibility controls。
- Phase 9 coordinator: cross-lane conflict resolution、unified report、position reconciliation、alert priority。

---

## 6. 常用命令

```powershell
# 24 期 production rank 回测
python runners\backtest_rank.py --mode production --periods 24 --freq monthly --end-date 20260301 --split-date 20250101 --refresh-forward-daily

# Stats-only 重统计
python runners\backtest_rank.py --stats-only --mode production --periods 24 --freq monthly --end-date 20260301

# 每周五实时选股
python A-EGS\egs_main.py --as-of <YYYYMMDD>

# 周五一键
.\runners\weekly_screening.ps1
.\runners\weekly_screening.ps1 -AsOf 20260530
.\runners\weekly_screening.ps1 -SkipCanary
```

---

## 7. 雷区

- 不接券商 / OS automation / 自动下单；所有交易动作仍由用户手动执行。
- 不因 Phase 7a audit 或 DataHub 工程放松 ship gate；full-size 必须满足 monthly alpha t-stat ≥ 2.0、Sharpe ≥ 1.0、max drawdown ≤ 15%、forward live data ≥ 12 个月。
- A/US cash 默认不互通；跨市场资金转移必须显式人工决策或后续 coordinator 规则。
- 不把 paper evidence 当 ship-gate evidence；ship gate 只接受 live-normalized evidence。
- 不用旧 12p findings 或旧 `_cc.md` 结论。
- 改 `A-EGS/egs_main.py` 前必须先 view 当前文件。

---

## 维护规则

- `CURRENT.md` 保持短 snapshot，目标 <150 行；超出说明该移到 owner doc / handoff / SESSION_LOG。
- 最新状态放 `CURRENT.md`；过程、争议、review verdict 和 rejected alternatives 放 `SESSION_LOG.md`。
- 新 handoff 高门槛；默认追加到当前 phase 主 handoff。旧 handoff 不重组。
- 新增文档必须先在 `docs/README.md` routing table 中说明 owner role。
