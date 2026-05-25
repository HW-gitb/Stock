# Stock 项目 — 当前状态快照

**最后更新**：2026-05-25（reference framework policy 已写入 AGENTS；Phase 5 schema 已提交）
**文档定位**：跨会话接续的精简事实表。AGENTS.md 是不变约定，本文件是动态状态。**所有新会话先读这两个文件，再按需读 handoff。**

---

## 1. 当前 Phase 与目标

- **当前 Phase**：Phase 4 minimal 已完成；Phase 5 kickoff spec 已建立；Phase 5 前置 deterministic report v1.1.0 已提交；execution report schema v1.0.0 已提交；runner / simulator 尚未开始
- **当前目标**：下一条最小实现任务是 Phase 5 runner / simulator skeleton，必须输出 schema-valid `execution_report.json`，并继续遵守 schema-first / review-first 节奏。
- **当前协作模式**：Codex = Designer + Implementer；Claude = Independent Reviewer；用户 = Final Approver。详 `docs/AI_REVIEW_PROTOCOL.md`
- **后台任务**：Phase 3.5 forward tracker 继续后台累积，不阻塞

---

## 2. 已完成事项（最近 8 条；过程细节见 SESSION_LOG）

本节只保留当前接续需要的 high-level snapshot；争议、被否方案、review verdict、pending fixes 统一查 `docs/SESSION_LOG.md` 顶部 1-3 条。

- **协作协议精简**（2026-05-25，commits `ef12fbf` `e9a2b18`）：`docs/REVIEW_PACKET.md` 已移除；Codex 的 SESSION_LOG 顶部 entry 作为 review handoff；`[trivial]` 轻量通道已启用。详 `docs/AI_REVIEW_PROTOCOL.md`。
- **Reference framework policy**（2026-05-25，当前工作树）：`AGENTS.md` 明确 A 股短线 / 美股短线 reference 文档是工程设计参考源；两套 v14.x 是独立框架，不是版本继承；长线框架尚未建立，不能硬套短线。
- **Phase 5 execution report schema-first**（2026-05-25，commit `636f0fd`）：新增 `schemas/execution_backtest_report.schema.json` v1.0.0 与最小 schema meta-validation 测试，并应用 Claude 4 条 Optional contract 加固；未实现 runner / simulator。
- **deterministic report v1.1.0 前置升级**（2026-05-25，commit `da26a2b`）：deterministic report / enrichment patch contract 已对齐 L3 与 enrichment lineage。
- **Phase 5 kickoff spec**（2026-05-25，commit `6c90f56`）：新增 [phase5 handoff](handoff/2026-05-25_phase5_kickoff_spec_handoff.md)。Phase 5 边界已锁定：schema first，再 runner / simulator。
- **Phase 4 minimal 收口**（2026-05-25）：deterministic report schema + runner + coverage + Skill + prompt 骨架 + enrichment patch/example + smoke/tests 已完成。
- **Phase 3+4 audit fix sweep**（2026-05-25，commits `a312e57` `9476d4c` `278f917` `911e49b`）：analyzer / runner / tracker / Skill fixture 加固；34 tests pass。
- **Phase 3.6 收尾 audit**（2026-05-25，commit `e342452`）：analyzer ablation 命名、`l2_unknown` 归一化、circuit breaker expiry、测试增至 21 个。
- **Phase 3.5 forward tracker**（2026-05-25，commit `17fb70e`）：`forward_tracker.py` capture + backfill；`weekly_screening.ps1` Stage 3 自动 capture。
- **Phase 3.4 ESP 反向 PIT 调查**（2026-05-25，commit `f18f282`）：EGS PIT filter 正确；Tushare revision history 不可验证；priced-in + 2024Q4-2025Q1 regime event 是当前最可能解释。
- **Phase 3.3 子分数预测力**（2026-05-25，commit `2a4f46f`）：`esp_score` 反向预测、`l4_score` regime-dependent、`final_score < 60` validation 20d t=-3.82。

更早事项（Phase 1a/1b、Phase 2 工程链路、v7.10、Phase 2.5/2.6、git init、Phase 3 首轮等）→ 见 `AGENTS.md §交接记录`、相关 handoff 与 `git log --all`。

---

## 3. 当前有效结论（24 期 v7.10 production，Tier1-only 主口径）

### 3.1 工程层

✅ 框架代码健康。SW + L1 修复有效，L3 三模式工作，schema 校验全通过。**Phase 2 工程签收。**

### 3.2 策略层（基于 24p Tier1-only N≈305）

- **20d 对 benchmark 几乎无显著超额**（t1_net t=1.60, excess_csi300 t=0.57, excess_csi1000 t=0.17）
- **5d excess_csi1000 t=+2.88**：**唯一统计显著的正 alpha 信号**，且只在 5 日窗口
- **三个统计显著的强负信号（按 |t| 排序）**：
  1. `entry_flag=追高风险，周一确认`：N=40, **t=-2.36**, 20d -6.35%, win 27.5%（**24p 最强可执行负信号**）
  2. OVERHEAT：N=25, **t=-2.34**, win 16%
  3. Tier2：N=58, **t=-2.27**, mean -4.71%
- **方向性但样本不足**：
  - `esp_raw>200` / `q0_dt_yoy>200`：t≈-1.5（ESP 低基数噪音）
  - LOCK：N=4 全亏（mean -13.42%, win 0%），需扩样本验证
- **final_score 不单调**：70-75 是甜区，75-85 反而弱；85+ 样本太少

### 3.3 框架本质判断

**"过滤坏票" > "挑出好票"**。强右偏分布（多数 trade 亏损、靠少数大涨拉平均）。**目前不具备可实盘部署的 alpha 强度。**

---

## 4. 已失效 / 已撤回结论

| 结论 | 失效原因 |
|---|---|
| 12 期 "Top 5 monthly_t=+2.18 显著" | 24p 重测 t=+1.19（all subset） / t=+1.61（tier1_only），失去显著性 |
| 12 期 "Top 5 主分析"建议 | 24p Top11-15 反而优于 Top1-5，rank monotonicity 不成立 |
| 12 期 "突破型 -6.31% 反向信号" | 24p N=13 无显著性，可能是 12p SW 污染所致 |
| 12 期 "OVERHEAT 弱负不显著" | 24p N=25, t=-2.34 显著负 |
| 12 期 "Tier2 略正 +2.14%" | 24p t=-2.27 显著负 |
| 旧 `_cc.md` 整体结论 | INVALIDATED，基于 12p + SW 污染数据 |
| v7.9 之前的 `completeness_score` 分组结论 | v7.9 之前硬编码 60 无判别力 |
| "重新校准排序权重"（外部建议）作为 P0 | 决策：降级到 P3 长期方向。理由：框架核心问题是结构性（强右偏），重调权重未必能根治；且当前数据量易过拟。先走 veto 路径性价比高 |
| "重点验证 5-10 日持有周期"（外部建议）作为独立 P0 | 决策：合并到 Phase 3 设计文档作为执行回测的 horizon target，不单独立项 |

---

## 5. 关键文件

### 代码 / schema
- `A-EGS/egs_main.py` — v7.10（v7.9 内存里仍有引用，以文件为准）
- `runners/backtest_rank.py` — Phase 2 回测入口，subset=all+tier1_only 双跑
- `runners/run_analysis_report.py` — Phase 4 单票 deterministic report runner，schema 校验后输出 JSON + Markdown
- `runners/diagnose_tier1_bad_signals.py` — Phase 3.2 Tier1 坏票特征诊断入口
- `runners/forward_tracker.py` — Phase 3.5 forward tracker；后台累计实盘样本
- `runners/weekly_screening.ps1` — 每周筛选脚本；筛选后自动 capture forward tracker
- `runners/data_canary.py` — 旁路数据对账；不阻断主流程
- `engine/analyzer/rule6_hard_veto.py` — Phase 3 首轮 deterministic hard veto：`chasing_high` / `overheat` / `l2_unknown` / `esp_non_positive`
- `engine/analyzer/state_manager.py` — Phase 3 JSON state 接口与 atomic write helper
- `tests/analyzer/test_state_manager.py` / `tests/test_backtest_rank_phase3.py` — Phase 3 state expiry、l2 normalization、analyzer ablation 命名回归测试
- `schemas/analysis_input.schema.json` — v1.1.0
- `schemas/deterministic_report.schema.json` — v1.1.0（Phase 4 minimal report contract；runner 输出 JSON 必须先过它；含 L3/enrichment lineage）
- `schemas/deterministic_report_enrichment.schema.json` — v1.1.0（可选 LLM notes patch；只允许合并 `llm_notes`，target report version 对齐 deterministic_report v1.1.0）
- `schemas/examples/deterministic_report_enrichment.example.json` — enrichment patch 最小样例
- `schemas/deterministic_report_coverage.md` — Phase 4 v1 对 v14.2 M0-M6 / M6.7 的覆盖矩阵与 unknown 原因约定
- `schemas/execution_backtest_report.schema.json` — v1.0.0（Phase 5 execution backtest report contract；commit `636f0fd`；runner / simulator 尚未实现）
- `schemas/rank_backtest_report.schema.json` — v1.11.0（含 date_warnings + data_lineage + analyzer veto replay settings）
- `schemas/data_health.schema.json` — v1.1.0（每周实盘 egs_main 自动产 `data_health.json` 的契约；2026-05-24 第二轮 audit 时 `pe_missing_count` 字段语义不清，rename 为 `pe_ttm_or_pe_missing_count`）
- `requirements-dev.txt` — validation-only 依赖；当前至少包含 `jsonschema>=4.0`

### Reference framework policy
- `skills/a_short_analysis/reference/` — A 股短线分析框架参考源。
- `skills/us_short_analysis/reference/` — 美股短线选股框架与分析框架参考源。
- A 股短线与美股短线的 `v14.x` 只是各自框架的版本号，不是前后版本关系；工程设计要参考但不照搬。
- A 股长线 / 美股长线框架尚未建立，后续到对应 Phase 时从头设计。

### 当前有效 findings（**只读这两份，旧 12p findings 已 INVALIDATED**）
- `result/a_short/backtest/Phase2_rank_backtest_findings_cc_24p.md` — cc 合并版（OVERHEAT/entry_flag/LOCK + 时间序列分析）
- `result/a_short/backtest/Phase2_rank_backtest_findings_codex_24p_v7.10.md` — codex 24p v7.10 视角

### 最新 handoff（按需读，不要全量展开）
- `docs/handoff/2026-05-24_phase2_24p_v710_results_handoff.md` — v7.10 24p 实跑结果
- `docs/handoff/2026-05-24_phase2_validation_tooling_handoff.md` — schema 1.8.0 + 验证工具
- `docs/handoff/2026-05-24_phase2_tier1only_subset_handoff.md` — Tier1-only 主口径
- `docs/handoff/2026-05-24_phase2_v7.9_handoff.md` — v7.8/v7.9 修改
- `docs/handoff/2026-05-24_phase2_git_init_handoff.md` — **git 私密性约束（必读）**
- `docs/handoff/2026-05-24_phase2_6_datahub_guardrail_handoff.md` — Phase 2.6 边界
- `docs/handoff/2026-05-24_phase2_tier1_count_warning_handoff.md` — schema 1.9.0 date_warnings
- `docs/handoff/2026-05-24_phase2_data_lineage_handoff.md` — schema 1.10.0 data_lineage 对象（Phase 2.6 lineage 闭环）
- `docs/handoff/2026-05-24_phase3_kickoff_spec_handoff.md` — Phase 3 开工规格：minimal veto analyzer + JSON state + replay/ablation 完成线
- `docs/handoff/2026-05-25_phase4_kickoff_spec_handoff.md` — Phase 4 开工规格：deterministic_report schema first + runner-as-executor + Skill-as-doc
- `docs/handoff/2026-05-25_phase5_kickoff_spec_handoff.md` — Phase 5 kickoff 规格：execution backtest contract 边界；代码未开始
- `docs/AI_REVIEW_PROTOCOL.md` — Codex / Claude / 用户三方审查流程

### 报告产出
- `result/a_short/backtest/backtest_report.json` — 最近一次 24p production，schema 1.11.0, primary_subset=tier1_only
- `result/a_short/backtest/{summary_by_window,factor_group_stats,monthly_stats,strategy_variant_stats,portfolio_stats}.csv`
- `result/a_short/backtest/Phase3_3_subscore_predictive.md` + `phase3_3_subscore_{detail,monotonicity}.csv` — Phase 3.3 子分数预测力（BACKTEST scope）
- `runners/diagnose_subscore_predictive.py` — Phase 3.3 诊断脚本
- `runners/forward_tracker.py` — Phase 3.5 实盘 forward tracker（capture + backfill）
- `logs/forward_tracker.csv` — 实盘累计数据（gitignored；不进版本控制）

---

## 6. 下一步（按优先级 P0 → P3）

### P0 — Phase 5 启动边界

1. **Phase 5 runner / simulator skeleton** — 基于已提交的 `execution_backtest_report.schema.json` v1.0.0，实现最小骨架并输出 schema-valid `execution_report.json`。
2. **Reference 框架约束** — 后续设计必须参考 A 股短线 / 美股短线 reference 文档的业务逻辑，但不能把 chatbox 框架机械照搬为运行时提示词或代码。
3. **Claude 审查点** — execution schema、撮合假设、输出目录隔离均需 Claude 独立审查后由用户确认。
4. **保留所有 Phase 3 / Phase 4 既定结论**：4 条 hard veto 不动 / `esp_non_positive` v2 保留 / `score_ge_60` variant 保留 / 不改 EGS / Phase 4 runner v1 只输出 `skip/watch`。

### P1 — Phase 3 后台累积（不阻塞 Phase 4）

4. **forward tracker 运维** — 每周五 `weekly_screening.ps1` 自动 capture；backfill 每月一次，前置跑 `backtest_rank.py --refresh-forward-daily`。
5. **观察 score_ge_60 / ESP 反向 / 4 veto overlap 在新 as_of**：累积 ~12 期后对比 backtest 结论决定是否进 analyzer。
6. **撤回"Top 5 主分析"对外说法** — 改成"Top15 观察池；Top5 用于 Phase 3 人工/analyzer 深度分析，不作实盘加仓信号"。

### P2 — 待扩样本 / 中期

7. **L3 snapshot 累积满 6 月后跑 pit 对照**（约 2026-12）— 测 L3 因子 PIT 下边际贡献 + cat_score 真实预测力。
8. **扩 36 期+** 覆盖 2023 段不同 regime；当前 2024+2025 偏强势。诊断 2024Q4-2025Q1 ESP 反向 regime event 也需扩样本。
9. **LOCK veto** — N=4 太小，扩到 N≥15 再决策。

### P3 — 长期 / Phase 7

10. **Phase 7 DataHub 实施** — ODS/DWD/DWS/factor 四层，详见 `docs/datahub_design.md`。同时把"财务 PIT"列为与 L3 PIT 并列的设计问题（来自 Phase 3.4）。
11. **重新校准 EGS 排序权重** — 等 36 期 + L3 PIT 数据齐备后再做。ESP 反向是否需要 sign 反转 / contrarian 因子重设计也在此阶段决定。

---

## 7. 运行命令（常用）

### 正式回测（24 期 production）
```powershell
python runners\backtest_rank.py --mode production --periods 24 --freq monthly --end-date 20260301 --split-date 20250101 --refresh-forward-daily
```

### Stats-only 重统计（不重跑候选池）
```powershell
python runners\backtest_rank.py --stats-only --mode production --periods 24 --freq monthly --end-date 20260301
```

### 实时选股（每周五）
```powershell
python A-EGS\egs_main.py --as-of <YYYYMMDD>
```
（默认 `--l3-mode today`，自动落 snapshot 到 `state/l3_snapshots/`）

### 数据对账 canary（选股后跑，可选）
```powershell
python runners\data_canary.py --as-of <YYYYMMDD>
```
（默认 `--source sina`：close+name 跨源对账，不受 VPN 影响；输出 `logs/data_canary_<as_of>.json`；不阻断；akshare 未装时 graceful skip）

### 周五一键（推荐）
```powershell
.\runners\weekly_screening.ps1                 # as-of=今天
.\runners\weekly_screening.ps1 -AsOf 20260530
.\runners\weekly_screening.ps1 -SkipCanary     # 只跑选股
```
（依次跑 `egs_main.py` + `data_canary.py`；egs_main 失败时跳过 canary；canary 失败不影响整体 exit code，符合旁路约束）

### Smoke 测试
```powershell
python runners\backtest_rank.py --mode smoke --periods 3 --freq monthly --windows 1,3,5 --stats-only --include-immature
```

---

## 8. 注意事项 / 雷区

### 不可碰
- **不可 `git push`，不可 `git remote add`**（私密本地仓库，commit `dca8367` 之后所有提交同规则）
- **不可改 v14.2 原文档**（已迁到 `skills/a_short_analysis/reference/v14.2_spec.md` 作设计参考）
- **不可写到 `result/a_short/YYYYMMDD/`**（回测必须用 `result/a_short/backtest/generated/YYYYMMDD/`）

### 易错点
- **production 模式拒绝 `--reuse-l3-cache` + `--include-immature`**（设计如此，不要绕过）
- **`--stats-only` 强制读 `analysis_input.json:source.l3_mode`**，不一致会 SystemExit
- **report `settings.l3_mode` 决定 L3 解读**：neutralize=无 lookahead/反映 L1+L2+L4+ESP；today=有 lookahead（仅 smoke）；pit=未来路径
- **引用收益**优先 `t1_net` 或 `excess_*`，不用 `close`（已废）
- **多维分析铁律**：时间序列 + 横截面 + 分布三类切片都要做，禁止单维聚合得结论
- **AGENTS.md 写入需谨慎**：跨 LLM 共享文档，2026-05-24 解除 off-limits

### 数据限制
- Tushare 财务返回最新修订版（非原始披露），ann_date 过滤无法解决
- L3 概念无 as_of 参数，PIT 模式靠 snapshot 累积
- Backtest 模式跳过 cninfo / 网络新闻 / DeepSeek Stage3 检查

---

## 维护规则

- **每轮重要修改后更新本文件**（小修：直接改；大修：加新 handoff 并在本文件 §5 更新指针）
- **本文件保持 < 300 行**，超出说明该归档到 handoff 了
- **失效结论搬到 §4**，不在 §3 留旧版
- **新 handoff 命名**：`docs/handoff/YYYY-MM-DD_short-topic_handoff.md`
- **handoff 写作门槛 = `AGENTS.md §交接记录`**（2026-05-24 收紧）：默认**追加到 phase 主 handoff** 末尾的 `## YYYY-MM-DD 追加：<topic>` 小节；新建独立 handoff 仅在 4 类高门槛情况：跨 phase 转换 / breaking change（schema major、口径反转、findings INVALIDATED）/ 新数据源或新模块 / 一次性强约束事件（git init、安全口径变化）。schema minor+patch / 同主题迭代 / 工程增量 一律追加，不另建文件。**旧 handoff 不重组**
