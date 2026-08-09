# Handoff Index

This directory stores phase-level historical context and validation records. It is not the first-stop routing layer.

Use this file to decide which handoff to open. Do not read every handoff by default.

## Reading Policy

- Start from `AGENTS.md`, `docs/README.md`, `docs/CURRENT.md`, the top 1-3 entries of `docs/SESSION_LOG.md`, and `docs/AI_REVIEW_PROTOCOL.md`.
- Open a handoff only when the current task touches that phase, schema, runner, benchmark policy, provider contract, or historical finding.
- Old handoffs are historical records. Do not merge, rewrite, or delete them for ordinary cleanup.
- Append to the current phase handoff by default. Create a new handoff only for the high-threshold cases listed in `AGENTS.md §交接记录`.

## Current Phase Handoff

- `2026-08-09_us_serenity_annotation_blade0_handoff.md` — Serenity `structural_theme_annotation` Blade 0 feasibility smoke + Blade 1 contrast calibration；仅限 research/advisory，保持 `unverified_lead`/`GO_FOR_CALIBRATION_ONLY` 与全 effect flags false；触及 Serenity 研究刀时打开。

- `2026-08-04_us_short_market_diagnostic_knife1_handoff.md` — US-short 26 周市场诊断轨 Knife1 纯计算、Knife2 本地只读适配、Knife3 不可变周记录/计数/reminder 契约、Knife10c 报告行接进周报已注册 §12 区块、演练刀（rehearsal harness）规格与实施、断供周写 no_count 自愈（钟不再永久卡死）、triage Required ① 的 8 条状态回写（逐条现行代码复核，全数 resolved）、首周门（canonical 决策周 + `issued_at` 不得在未来）、前视门放行默认删除改必传（六个签名 + AST 守卫）、KNIFE7 家族五条定点探针、演练台 O(n²) 的真正位置（在调用方不在读取链，每周整店读校 22.8→11.2 次、模块 176→109.4s）及其审查结论（PASS，两条 Optional）、lane 地板两刀（owned-root git-check seam 提到 setUp：soft-discovery 62.7→25.0s、地板 199.5→130.0s）、刀 5 后半段 ETF sidecar producer/gated fetch/settle binding、四条兄弟腿 Required 收口、Knife7 tests-only 18 项回归清账、RECEIPT-DIGESTS 通知源 canonical JSON/O_EXCL/全消费点复核与 rehearsal 接线、空白/typed-error/operator producer 三条审查 Required 收口、中断恢复完整 pending receipt 绑定与零增益 `notification_sha256` 删除及 focused/full-lane 边界、代码/测试入口；触及该诊断轨时打开。

- `2026-08-03_review_gate_task_notification_repair_handoff.md` — review-gate P1 repair for real async task-notification row visibility and Stop-hook transcript plumbing; open this when reviewing `R-REVIEWGATE-OUTSTANDING-AGENT-CHECK-CANNOT-SEE-REAL-TASK-NOTIFICATIONS`.

- `2026-05-27_phase7_kickoff_spec_handoff.md` — Phase 7 provider capability / field catalog contract boundary, with later Phase 7a alpha-validation route and Phase 7a+ alpha reality action guide additions; schema-first, no provider selection, no data fetch, no adapter / DataHub table.

- `2026-07-28_us_short_soft_discovery_x_live_shape_review_handoff.md` — US-short X response-shape repair for K3-R68/K3-R69; step ② awaits independent review and K3-R34 remains frozen.

## Phase Index

- `2026-08-01_a_short_leaf_wiring_classification_handoff.md` — A-short analysis_input 全叶（数量取自 schema 动态计算）的效果分类漏斗与逐类归属，**并已成为「序 N」工程队列的主 handoff**（队列表、逐刀执行方案、每刀的执行与审查收口都追加在此）；查「某字段到底有没有影响 M6.7」或任何一把序 N 刀时开。
- `2026-08-01_a_short_rule6_severity_classification_repair_handoff.md` — Rule6 `severity` 由主决策改判展示审计的纠错记录与反向控制。

- `2026-08-01_a_short_knife11_official_rolling_handoff.md` — A-short desktop Knife 11 official rolling crash-veto verdict repair; focused evidence is complete and independent review remains pending.

This index is the single annotated handoff list (it absorbs the per-file one-line descriptions that
used to live in `AGENTS.md §交接记录`). Open a file only when the current task touches that phase /
schema / runner / policy / historical finding.

- Phase 2:
  - `2026-05-24_phase2_v7.9_handoff.md` — EGS v7.8/v7.9 脚本修改、正式周五实盘重跑、24 期 production 回测验收、当时有效 findings、下一步策略优先级。
  - `2026-05-24_phase2_tier1only_subset_handoff.md` — Tier1-only 主口径切片、stats CSV 加 `subset` 列、schema 1.6.0、`settings.primary_subset`。
  - `2026-05-24_phase2_git_init_handoff.md` — 项目首次进入 git 管理、`.gitignore` 排除清单、commit `dca8367`、git 私密性约束。
  - `2026-05-24_phase2_validation_tooling_handoff.md` — EGS v7.10、rank backtest schema 1.8.0、split/variant/eligible benchmark/T+1 不可买/portfolio stats/reason observability。
  - `2026-05-24_phase2_6_datahub_guardrail_handoff.md` — Phase 2.6 DataHub guardrail,"先补 lineage、不做大重构"的边界。
  - `2026-05-24_phase2_24p_v710_results_handoff.md` — v7.10 24 期 production 实跑结果、schema 校验、核心 findings 与结论边界。
  - `2026-05-24_phase2_tier1_count_warning_handoff.md` — rank backtest schema 1.9.0、报告加日期级 Tier1-count 告警。
  - `2026-05-24_phase2_data_lineage_handoff.md` — rank backtest schema 1.10.0、新增 `data_lineage` 对象、Phase 2.6 lineage 闭环。
- Phase 3:
  - `2026-05-24_phase3_kickoff_spec_handoff.md` — Phase 3 开工规格:minimal veto analyzer + JSON state + replay/ablation 完成线(含 3.3 子分数预测力 / 3.4 ESP 反向 PIT / 3.5 实盘 forward tracker)。
- Phase 4:
  - `2026-05-25_phase4_kickoff_spec_handoff.md` — Phase 4 开工规格:deterministic_report schema-first + runner 纯 Python + Skill 是使用文档(非执行入口)。
- Phase 5:
  - `2026-05-25_phase5_kickoff_spec_handoff.md` — Phase 5 kickoff 规格:execution backtest contract 边界;schema/runner/simulator 代码当时未开始。
- Phase 6:
  - `2026-05-26_phase6a_kickoff_spec_handoff.md` — Phase 6a 开工边界:forward evidence、A 短 benchmark sensitivity、forward tracker → aggregate evidence flow、steady/variant/burst/long-spec 边界。
  - `2026-07-28_a_short_knife6a_repair_handoff.md` — **桌面 `ashort_r1.md` 批次的主 handoff（第六刀 6A/6B + 第七刀）**：A-short 第六刀 6A（组合事实价格时钟、北向因子退役、provider 三态、I1 历史 schema 兼容、H1 runtime-policy 孤儿读点守卫与 repair-closeout 机器门）**及 6B 追加节**（候选 `close` 改取 price_series 末根、官方档 `source_trade_date == price_data_through` 加严、`_is_official_analysis_input_path`）；6B 审查判 Pass-with-Required、第六刀未闭，状态见 SESSION_LOG 顶部与 register。
  - `2026-07-28_repair_closeout_shared_flow_handoff.md` — Shared A-short/US-short repair-closeout matrix, lane-specific focused/full-lane evidence boundary, and the parallel full-lane runner (T1 isolation scan + T2 driver; implemented 2026-08-06, a_short full lane 826s -> 338.7s recorded at `mode=parallel`, awaiting independent review).
- Phase 7:
  - `2026-05-27_phase7_kickoff_spec_handoff.md` — Phase 7 开工边界:provider capability / field catalog contract v1.0.0;schema-first,不选 provider、不抓数据、不建 adapter/DataHub table。**含** Phase 7a alpha-validation route + Phase 7a+ alpha reality action guide additions(同一文件,非独立 handoff)。
