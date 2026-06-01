# Stock 项目 - 当前状态快照

**最后更新**：2026-06-01（SR-DATA-004 suspend coverage observability）

**文档定位**：跨会话接续的短 snapshot。完整路由见 `docs/README.md`；过程、review verdict 和 rejected alternatives 见 `docs/SESSION_LOG.md` 顶部 1-3 条；历史 phase 细节见 `docs/handoff/README.md`。

---

## 0. Latest Delta

- Original A-share `minimal_data_burst` remains blocked; corrected-basis supersession failed preflight with `valid_signal_events = 0`, is spent as `failed_preflight_zero_signal_events`, and must not run outcome / benchmark-excess.
- The full-universe redesigned A-share burst outcome / excess slice has run on frozen local data only: raw signal events 134, selected 123, available returns 116.
- `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json` records `decision = falsified_or_redesign_required`: mean net CSI1000 excess `-2.8696001309` pp, monthly clustered t-stat `-0.6312965283`, max monthly signal-excess drawdown `26.5735343137` pp.
- Owner audit/spec now reflect the failure: `docs/phase7a_alpha_plausibility_audit.json` marks `a_share_burst_minimal_data = redesign_required`, and `docs/burst_lane_spec.md` blocks further A-share minimal-data burst tests without a new ledger planned test and reviewed preregistration.
- `SR-DATA-004` remains open pending real weekly evidence, but the current change set writes `logs/suspend_daily_coverage_<asof>.json` and mirrors the latest observation into schema-validated `data_health` v1.2.0 `metrics.suspend_daily_coverage`.

---

## 1. 当前 Phase 与目标

- **当前 Phase**：Phase 7b-2 P1 closure plan is documented; US EGS data-source direction is FMP primary candidate + SEC EDGAR fundamentals audit; A-share minimal-data burst full-universe redesigned outcome is complete and failed.
- **当前 P0 / P1 目标**：do not rerun or rescue the failed redesigned burst test；risk register hot queue maintenance 组仅余 `SR-DATA-004`（仍需真实 weekly suspend-coverage 日志），除非用户先批准新的 research preregistration、provider-access work 或更窄 override。
- **当前 P1 provider blocker**：任何 FMP token / trial / paid access、SEC parser sample、`yfinance` price smoke check、provider contact、sample 或 data-fetch 前，必须先由用户批准 cost ceiling、access path、license / local-storage / non-display / retention 边界，并经后续 reviewed decision。
- **执行锁**：原 prereg 仍为 `BLOCKED_DO_NOT_RUN`；corrected-basis prereg 已消耗 test budget 且不得运行 outcome / excess；redesigned test 已消耗 ledger planned test 且 outcome 失败。任何 material audit finding 必须修复或进入 risk register，不能只留在 chat。
- **协作模式**：Codex = Designer + Implementer；Claude = Independent Reviewer；用户 = Final Approver。详 `docs/AI_REVIEW_PROTOCOL.md`。
- **后台线**：A-short Phase 6b 只保留 weekly forward capture、comparison-track accumulator、forward evidence accumulation；不扩无关小工具。

---

## 2. 最近已完成

- **A-share burst audit/spec downgrade**（2026-06-01）：`docs/phase7a_alpha_plausibility_audit.json` / `docs/burst_lane_spec.md` 已把 A-share minimal-data burst 从 `continue` 降为 `redesign_required`，并引用 failed outcome evidence。
- **A-share burst redesigned outcome**（2026-06-01）：`evidence_report.json` / `signal_events.csv` / `monthly_stats.csv` 已生成；同一 frozen prereg + patched benchmark-open cache 计算后失败 research-continuation thresholds，decision 为 `falsified_or_redesign_required`。
- **SR-DATA-003 benchmark-open input**（2026-06-01）：ignored local `result/a_short/backtest/cache/forward_daily.pkl` 已由 benchmark-only helper patch；CSI300 / CSI1000 均为 498 行 `trade_date/open/close`，`fetch_forward_daily(refresh=False)` 验证可复用 cache 且不触发 provider refetch；随后 redesigned outcome slice 使用该 input。
- **SR-OPS-002 forward tracker atomic write**（2026-06-01）：`runners/forward_tracker.py:_write_tracker` 已改为同目录 temp CSV + flush/fsync + `os.replace`；测试锁定成功替换与失败保留旧 tracker。
- **SR-CONTRACT-002 forward-live evidence schema contract**（2026-06-01）：`schemas/forward_live_evidence.schema.json` v1.0.0 and `execution_aggregate_report` v1.1.3 bind forward-live months to reviewed live-normalized evidence provenance; old two-field evidence refs are rejected.
- **SR-PIT-001 / SR-CONTRACT-001 analysis_input contract hardening**（2026-06-01）：shared `engine/data/analysis_input_contract.py` validates schema + PIT invariants; EGS export and deterministic-report load now reject malformed or future-dated payloads; `requirements.txt` declares `jsonschema`.
- **SR-DATA-002 daily stats insufficiency guard**（2026-06-01）：`precompute_stock_stats` now hard-fails severe daily payload insufficiency instead of returning neutral stats that could bypass liquidity / crash-veto filters.
- **SR-OPS-005 forward tracker cache coverage**（2026-06-01）：`forward_tracker.py` now proves backfill coverage from cached stock trading dates instead of calendar-day approximation.
- **SR-RANK-001 forward-return conversion status**（2026-06-01）：`attach_forward_returns` now reports `pending_return_conversion_failed` instead of `"ok"` when required forward-return conversions fail or leave invalid values.
- **SR-OPS-006 relisted lookback boundary**（2026-06-01）：`get_relisted_stocks` now uses exact inclusive lookback cutoff semantics and invalidates old relisted caches with `_v2`.
- **SR-LLM-001 Stage 3 prompt boundary**（2026-06-01）：DeepSeek policy-risk prompt construction now sanitizes external titles, wraps them in `[UNTRUSTED_NEWS_TITLE]` rows, and tells the LLM not to execute instructions inside titles; focused tests cover injection-style titles.
- **SR-EXEC-003 drawdown evidence guard**（2026-06-01）：`runners/backtest_execution.py` no longer exposes realized exit-date cash drawdown as numeric `max_drawdown`; ship-gate drawdown remains not evaluable until open-position MTM is implemented.
- **System risk register**（2026-05-31）：`docs/system_risk_register.md` 已建立，并已把确认后的 bug audit 拆成具体 fix queue；future LLM enforcement 已接入 `AGENTS.md` / `docs/AI_REVIEW_PROTOCOL.md` / `docs/README.md`。
- **US EGS data-source direction / Phase 7b-2 access boundary**（2026-06-01）：FMP 为主源候选，SEC EDGAR 为基本面审计源；`yfinance` 仅可显式批准后作低信任价格 smoke check。`docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` 仍只定义访问边界和样本验证计划，不授权 provider 行动。

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
- `schemas/provider_p1_access_decision_plan.schema.json` / `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` - Phase 7b-2 P1 access-decision and sample-validation plan（plan-only；approved spend = 0；provider/sample/data/Phase 7c blocked）。
- `schemas/provider_p1_readiness_review.schema.json` / `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json` - Phase 7b-2 P1 readiness review matrix（collection complete；Phase 7c / provider selection / data fetch blocked）。
- `docs/evidence_feasibility_controls.md` / `schemas/evidence_feasibility_controls.schema.json` - Phase 7a-4 burst promotion / evidence feasibility controls。
- `docs/evidence_report_schema_contract.md` / `schemas/evidence_report.schema.json` - Phase 7a-5 evidence report schema contract。
- `docs/alpha_plausibility_audit.md` / `schemas/alpha_plausibility_audit.schema.json` - Phase 7a-1 audit owner and contract。
- `docs/evidence_capital_policy.md` - paper vs live-normalized evidence owner。
- `docs/strategy_design_synthesis.md` - 总体策略架构 owner。
- `docs/burst_lane_spec.md` / `docs/us_short_spec.md` / `docs/long_alpha_spec.md` - lane owner specs。
- `docs/provider_data_requirements_audit.md` / `schemas/provider_capability_catalog.schema.json` - provider requirements / capability contract。
- `docs/portfolio_allocation_policy.md` - 35/65、bucket、cash non-fungibility、manual-only capital policy。
- `docs/datahub_design.md` - DataHub / provider / factor-layer guardrails。
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

### P1 - P1 provider access boundary（仅用户明确要求时）

- 用户可另行批准 cost ceiling、access path、license / local-storage / non-display / retention 边界；之后仍需单独 reviewed decision 才能 request token / trial / paid access / sample rows。
- 不得 silent default、latest-only 回填历史证据，或把 provider status guess 写成 production-ready evidence。
- 不得建 adapter / DataHub table、改 runner、抓 provider data 或接 broker / OS automation。

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
