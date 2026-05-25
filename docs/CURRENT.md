# Stock 项目 — 当前状态快照

**最后更新**：2026-05-25（Phase 4 启动规格 handoff 落地；validation 依赖声明补齐）
**文档定位**：跨会话接续的精简事实表。AGENTS.md 是不变约定，本文件是动态状态。**所有新会话先读这两个文件，再按需读 handoff。**

---

## 1. 当前 Phase 与目标

- **当前 Phase**：Phase 3 全部子阶段（3.0-3.5）完成；**Phase 4 启动规格已固化**（见 `docs/handoff/2026-05-25_phase4_kickoff_spec_handoff.md`），待用户拍板 §8 两件事后开工
- **当前目标**：Phase 4 minimal — deterministic_report schema first，runner 纯 Python 不调 LLM，Skill 是使用文档不是执行入口；v1 必须本地可复现，缺 LLM 判断的字段标 `unknown + requires_llm`
- **下一阶段大目标**：Phase 5 execution 回测（需 Phase 4 schema-validated report 作 contract）；Phase 3.5 forward tracker 继续后台累积，不阻塞

---

## 2. 已完成事项（不重做）

- Phase 1a/1b：`analysis_input.schema.json` v1.1.0、`egs_main.py` 输出三件套（candidates/snapshot/analysis_input）
- Phase 2 工程链路：`runners/backtest_rank.py` 跑通 24 期 production；T+1 入场、双边 0.16% 摩擦、CSI300/CSI1000/eligible 三层 benchmark
- Phase A+B 修复（2026-05-22）：A1 qfq、A4 benchmark、A5-A11 全部、B2 退市股 PIT、B3a 行业图 PIT、B3b 财务 PIT
- L3 PIT 三模式（2026-05-23）：`--l3-mode {pit,today,neutralize}`，production 默认 neutralize，snapshot 累计中
- v7.10 升级（2026-05-24）：SW 行业 v5 fix、L1 mapping fix、completeness_score 动态化
- Tier1-only 主口径切片（2026-05-24）：`backtest_rank.py` 双跑 subset=all/tier1_only，schema 升 1.6.0，settings.primary_subset="tier1_only"
- Phase 2.5 auto stats（2026-05-24）：`monthly_t/sharpe_m/win_rate` 直接产出在 summary/factor_group/monthly_stats CSV，免手算
- git init（2026-05-24，commit `dca8367`）：**私密本地仓库，禁止 push / 禁止 add remote**
- 报告 schema 1.8.0：含 strategy_variant_stats、portfolio_stats、eligible_benchmark、reason observability
- 报告 schema 1.9.0（2026-05-24）：date_warnings 数组，`tier1_count<5` 自动告警
- v7.10 P0/P1 优化全部落地（2026-05-24）：追高（egs_main.py:2325）/OVERHEAT（egs_main.py:2327）做 Tier1→Tier2 降级；ESP 低基数 cap@200（egs_main.py:2233 + score_penalty_reasons="esp_raw_cap_200"）；Tier2 filler 排除 `l2_name="未知"`（egs_main.py:2843）；SW 覆盖率三段回退 + active_count 监控（egs_main.py:1144-1175）。**注**：追高/OVERHEAT 当前是 Tier 降级（filler 路径仍可能以 Tier2 身份出现），完整 deterministic veto 留到 Phase 3 analyzer
- Phase 2.6 完成（2026-05-24）：`docs/datahub_design.md` + AGENTS guardrail + 报告 schema 1.10.0 增加 `data_lineage` 对象（data_provider/api_families/forward_return_adjustment_mode/benchmark_sources/pit_limitations）
- data canary 旁路对账（2026-05-24）：`runners/data_canary.py` 每周选股后抽 5 只对比 Tushare vs akshare 的 close/pe/pb/name；不阻断、不进打分、不比行业；输出 `logs/data_canary_<as_of>.json`
- Phase 3 首轮（2026-05-24）：新增 `engine/analyzer/rule6_hard_veto.py`、`engine/analyzer/state_manager.py`、`tests/analyzer/`；`backtest_rank.py` 接入 analyzer replay，新增 `tier1_veto_passed` subset、`--veto-rules` ablation、schema 1.11.0、`low_tier1_veto_passed_count` warning；24p stats-only replay 已通过 schema 校验
- Phase 3 v2 修正（2026-05-24）：`esp_non_positive` 升到 v2，只 hard veto 明确负 `esp_raw < 0`；`esp_raw == 0` 记录 `neutral_zero_not_vetoed` 诊断。原因：24p Tier1 中 78 条旧 v1 命中里 75 条是 `esp_raw=0`，多数为 `DATA-INC`，且该组 20d 表现反而更强
- Phase 3.2 Tier1 坏票诊断（2026-05-24）：新增 `runners/diagnose_tier1_bad_signals.py`，输出 `Phase3_tier1_bad_signal_diagnostics.md` 与 4 份 CSV。诊断显示 `final_score < 60` 是当前最清晰的 Tier1 内坏票候选特征；`score_ge_60/65` replay 在 validation 的 5d/10d/20d 均优于 Tier1-only，但仍需正式接入 `backtest_rank.py` variant 后再决定是否进 analyzer
- Phase 3 audit fixes（2026-05-24）：`_first_present` 改返回 `(value, path)` tuple；`_check_l2_unknown` 空串归 data_missing；`_check_esp_non_positive` `"nan"` 字符串归 data_unparseable；`_coerce_bool_column` 修 CSV bool round-trip latent bug；analyzer 与 backtest 的 `l2_unknown` 语义对齐；`--no-analyzer-veto` 或 0 命中时跳过冗余 veto subset
- Phase 3 比较口径修正 + overlap 分析（2026-05-24）：新增 `all_veto_passed` subset，并对 analyzer 与 EGS v7.10 做了 overlap 分析。**关键发现**：4 条 hard veto 在当前 24p 的真实独立贡献仅 3 条 Tier1 `esp_non_positive` catch；`chasing_high` / `overheat` Tier1 命中 0（EGS 已前置降级），`l2_unknown` 命中 0（EGS 已过滤）。`all → all_veto_passed` 20d t 1.08→1.56 看似大胜，本质是 Tier2 被剔除（EGS 已能做），不是 analyzer 独立发现 — 详见 handoff "analyzer-EGS overlap 分析"节。重复部分保留作防御纵深
- Phase 3 score_ge_60 variant（2026-05-24）：把 Phase 3.2 诊断的 `final_score >= 60` 升级为正式 strategy variant（不进 analyzer hard veto，因为 score floor 是 ranking 决策不是事件 veto）。24p portfolio_stats：discovery max_dd -18.75 → -16.59，validation max_dd -12.12 → -10.92；monthly_t 几乎不变（risk-mitigation，不是 alpha 增益）
- Phase 3.3 子分数预测力分析（2026-05-25）：新增 `runners/diagnose_subscore_predictive.py`。**关键发现**：(1) backtest 下 `cat_score` 全部硬编码 50（`egs_main.py:2202`，`l3_mode=neutralize` 设计）— 不是 EGS 不能区分，是 backtest 数据路径决定；cat_score 真实预测力需等 L3 PIT 累积满 6 月（~2026-12）；(2) `esp_score` 在 backtest 下呈**反向预测力**（low > neutral > high 跨 5d/10d/20d，validation 5d Spearman=-1.0）— Phase 3.4 已排除是 EGS sign bug；(3) `l4_score` 是 backtest validation 主驱动 (l4=100 vs <70 在 20d 上 +4.12 vs -4.74)，但 discovery 反向 — regime-dependent；(4) `final_score < 60` 在 validation 20d 是 -4.57 / t=-3.82（比 chasing_high 的 t=-2.36 还强），验证 score_ge_60 选择正确
- Phase 3.4 ESP 反向 PIT 调查（2026-05-25）：纯诊断无代码改动。结论：(a) EGS 代码 PIT filter 完全正确（`egs_main.py:1664` 用 `ann_date <= as_of`）；(b) Tushare API 行为限制（返回最新修订版数值）通过 API 单独**结构性不可验证**；(c) 24p 季度 cohort 检验 PIT 单调衰减假说**不被支持** — 反向强度集中在 2024Q4 + 2025Q1（-19.64 / -9.28 spread），不是从老到新单调减弱。最可能机制：行为金融 priced-in + 该段 regime event 共同作用。**PIT 不是主因**
- Phase 3.5 实盘 forward tracker（2026-05-25）：新增 `runners/forward_tracker.py`（capture + backfill）+ `logs/forward_tracker.csv`（25 列 schema），`weekly_screening.ps1` 接 Stage 3。设计：旁路约束，capture 每周五自动跑（轻量），backfill 用户手动跑且 cache 不覆盖时主动 bail；复用 `attach_forward_returns` 保证与 backtest 同口径。已验证 3 个 as_of capture + idempotency + cache-coverage gate。累积 ~12 期实盘 as_of 后可跑 esp_score / score_ge_60 / veto overlap 分析对比 backtest 结论
- Phase 3.6 收尾 audit 修复（2026-05-25）：修正 analyzer ablation 命名与输出，新增 `all_analyzer_veto_*` 和 `tier1_analyzer_veto_*`，避免旧 `analyzer_veto_* + subset=all` 被误读为全样本；`l2_unknown` 归一化与 analyzer 对齐（strip/lower，支持 `unknown`/`unk`）；`state_manager.is_circuit_breaker_active()` 开始尊重 `expires_at`；测试增至 21 个；24p stats-only 已重算并通过 schema 1.11.0 校验
- Validation 依赖声明（2026-05-25）：新增 `requirements-dev.txt`，声明 `jsonschema>=4.0`；schema-validating 命令应使用项目/本机 Python（如 Python 3.13）并先 `python -m pip install -r requirements-dev.txt`。Codex bundled Python 可用于 compile/unit tests，但不作为项目依赖来源。

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
- `runners/diagnose_tier1_bad_signals.py` — Phase 3.2 Tier1 坏票特征诊断入口
- `engine/analyzer/rule6_hard_veto.py` — Phase 3 首轮 deterministic hard veto：`chasing_high` / `overheat` / `l2_unknown` / `esp_non_positive`
- `engine/analyzer/state_manager.py` — Phase 3 JSON state 接口与 atomic write helper
- `tests/analyzer/test_state_manager.py` / `tests/test_backtest_rank_phase3.py` — Phase 3 state expiry、l2 normalization、analyzer ablation 命名回归测试
- `schemas/analysis_input.schema.json` — v1.1.0
- `schemas/rank_backtest_report.schema.json` — v1.11.0（含 date_warnings + data_lineage + analyzer veto replay settings）
- `schemas/data_health.schema.json` — v1.1.0（每周实盘 egs_main 自动产 `data_health.json` 的契约；2026-05-24 第二轮 audit 时 `pe_missing_count` 字段语义不清，rename 为 `pe_ttm_or_pe_missing_count`）
- `requirements-dev.txt` — validation-only 依赖；当前至少包含 `jsonschema>=4.0`

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

### 报告产出
- `result/a_short/backtest/backtest_report.json` — 最近一次 24p production，schema 1.11.0, primary_subset=tier1_only
- `result/a_short/backtest/{summary_by_window,factor_group_stats,monthly_stats,strategy_variant_stats,portfolio_stats}.csv`
- `result/a_short/backtest/Phase3_3_subscore_predictive.md` + `phase3_3_subscore_{detail,monotonicity}.csv` — Phase 3.3 子分数预测力（BACKTEST scope）
- `runners/diagnose_subscore_predictive.py` — Phase 3.3 诊断脚本
- `runners/forward_tracker.py` — Phase 3.5 实盘 forward tracker（capture + backfill）
- `logs/forward_tracker.csv` — 实盘累计数据（gitignored；不进版本控制）

---

## 6. 下一步（按优先级 P0 → P3）

### P0 — Phase 3 收官 / Phase 4 准备

1. **ESP 反向信号下一步**：Phase 3.4 已排除 sign bug，弱化 PIT artifact 假说。最可能 priced-in + regime event。**不改 EGS、不加 strategy variant**；Phase 3.5 实盘 forward tracker 已落地，3 个月后（~12 期 as_of）可跑实盘 esp_score 分组对比 backtest 结论。Phase 7 DataHub 设计时把"财务 PIT"列为与 L3 PIT 并列的设计问题。
2. **forward tracker 运维**：每周五 `weekly_screening.ps1` 自动 capture（无须手动）；backfill 建议每月一次，且只在跑完 `backtest_rank.py --refresh-forward-daily` 之后跑（cache 同步问题）。
2. **不在 backtest 数据上下任何 cat_score 结论**：等 L3 PIT snapshots 累积 6 月（约 2026-12），再 `--l3-mode pit` 跑同样分析。
3. **在新 as_of 上跟 overlap 分析** — 当前 24p 4 条 rule 的真实独立贡献只有 3 条 Tier1 esp_non_positive；`chasing_high` / `overheat` Tier1=0，`l2_unknown` 整体=0。新 as_of 上要重跑 overlap 分析看是否随 EGS 行为变化。
4. **决策 esp_non_positive 归属**：把 `esp_raw < 0` 也放进 EGS Tier1→Tier2 降级（与 analyzer 一致），还是保留 analyzer 专属作为 EGS validator？看 Phase 4 Skill 路径需求。
5. **观察 score_ge_60 在新 as_of**：当前 24p 显示 discovery/validation max_dd 和 win_rate 改善，但 monthly_t 几乎不变（risk-mitigation 而非 alpha）。
6. **不要急着加 `score_ge_65`**：数据挖掘嫌疑；等 60 在更多 as_of 上稳定再决定。
7. **保留 `l2_unknown` / `chasing_high` / `overheat` 三条休眠/重复 rule**：当前 24p 没独立贡献，但保留作 EGS 改阈值时的兜底；不要因为"没贡献"就移除。
8. **保留 `esp_non_positive` v2**：v1 的 `esp_raw <= 0` 已证明过宽；v2 只杀 `esp_raw < 0`。

### P1 — 短期跟进

4. **撤回"Top 5 主分析"对外说法** — 改成"Top15 为观察池；Top5 用于 Phase 3 人工/analyzer 深度分析，不作实盘加仓信号"（文档面已完成；实盘说法对外口径同步）
5. **LOCK 标记进入 analyzer veto 辅助 flag** — N=4 太小，先不硬过滤；扩样本到 N≥15 再决策

### P2 — 待扩样本 / 中期

6. **L3 snapshot 累积满 6 月后跑 pit 对照**（约 2026-12）— 测 L3 因子在 PIT 下边际贡献
7. **扩 36 期+** — 覆盖 2023 段不同 regime；当前 2024+2025 偏强势
8. **5-10 日持有周期作为 execution 回测 horizon target** — 24p 数据显示 5d 是唯一显著甜区

### P3 — 长期 / Phase 7

9. **重新校准排序权重** — 等 36 期 + L3 PIT 数据齐备后再做，否则易过拟 24p
10. **Phase 7 DataHub 实施** — ODS/DWD/DWS/factor 四层 + `engine/data/` + `engine/factors/`，详见 `docs/datahub_design.md`

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
