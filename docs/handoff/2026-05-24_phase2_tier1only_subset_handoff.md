# Phase 2 Tier1-only 主口径切片 Handoff

生成时间：2026-05-24
作者：cc (claude-opus-4-7)
前置 handoff：[`2026-05-24_phase2_v7.9_handoff.md`](./2026-05-24_phase2_v7.9_handoff.md)

## 读取说明

本 handoff 在 `2026-05-24_phase2_v7.9_handoff.md` 之后。继续 Phase 2 / rank 回测 / `backtest_rank.py` / findings 工作前，**两份都读**，本文件覆盖 v7.9 handoff 之后的额外改动。

## 本轮改动

### `runners/backtest_rank.py`

**功能性改动**：所有 stats 函数加 `subset` 参数支持，`build_stats` 改为双跑 `all` + `tier1_only`。

具体函数签名变化：
- `summarize_returns(samples, windows, subset="all")`
- `group_stats(samples, windows, group_col, label, variant="t1_net", subset="all")`
- `monthly_stats(samples, windows, subset="all")`
- 新增模块级常量 `PRIMARY_SUBSET = "tier1_only"`
- 新增内部函数 `_build_stats_for_subset()` + `_factor_group_specs()`（重构提取，便于双跑）

**输出 CSV 变化**（所有都加 `subset` 列）：
- `summary_by_window.csv`：行数 15 → **30**（all + tier1_only 各 15）
- `factor_group_stats.csv`：行数翻倍
- `monthly_stats.csv`：行数翻倍
- `rule6_stats.csv`：行数翻倍
- `rank_samples.csv`：**不变**（始终是原样本，没有 subset 维度）
- `backtest_report.json`：schema_version 1.5.0 → **1.6.0**，settings 新增 `primary_subset: "tier1_only"`

### `schemas/rank_backtest_report.schema.json`

- `$id` 升 1.6.0
- `settings.required` 新增 `primary_subset`
- `settings.properties.primary_subset` 枚举 `["all", "tier1_only"]`，默认通过代码常量为 `"tier1_only"`

## 为什么改

reviewer 在 24p findings 审查中指出：Tier2 整体显著差（N=58, t=−2.27），混进"all"聚合稀释 Tier1 真实信号。主口径应改 Tier1-only。

**实证证据**（24p 数据，比较 all vs tier1_only）：

| 20d 关键指标 | all (N=360) | tier1_only (N=302) | 稀释幅度 |
|---|---:|---:|---|
| t1_net mean | +1.72% | +2.96% | Tier2 拉低 1.24pp |
| t1_net monthly_t | +1.17 | +1.72 | 显著性下降 32% |
| **excess_csi1000 mean** | **−0.27%** | **+0.40%** | **翻负** ← 误导性最强 |
| excess_csi1000 monthly_t | −0.25 | +0.36 | 翻正 |
| 5d excess_csi1000 t | +2.09 | **+2.62** | 信号更显著 |

## 已重跑验证

```powershell
python runners\backtest_rank.py --mode production --stats-only --windows 5,10,20
```

验收结果：
- `backtest_report.json` schema 1.6.0 校验 0 error
- `summary_by_window.csv`: 30 行（15 all + 15 tier1_only），均含新 `subset` 列
- `settings.primary_subset = "tier1_only"`
- 所有数字跟手算 / 单 Tier1 过滤一致

## 旧报告/CSV 兼容性

- 旧 v1.5.0 报告（如 archive 里的）schema 不再通过 v1.6.0 校验（缺 `primary_subset` + `subset` 列缺失）
- 不影响读取数据，但严格 schema 校验会失败
- **下次任何 backtest_rank 跑都会自动覆盖成 v1.6.0**

## 失效旧结论

无 —— 本次只改输出形式不改样本/算法。所有 v7.9 数据结论仍然成立，**只是从 "all" 视角切换成 "tier1_only" 视角后数字更宽松**。

## 当前有效 findings

两份并列阅读：
- `result/a_short/backtest/Phase2_rank_backtest_findings_codex.md`（codex 视角）
- `result/a_short/backtest/Phase2_rank_backtest_findings_cc_24p.md`（cc 互补合并版 + Tier1-only 主口径修订）

cc_24p §9 P0 优先级表已更新，新增 "主统计口径改 Tier1-only" 条目。

## 下一步

cc 这边到此告一段落。下一轮工作建议：
1. **Phase 3 analyzer 优先建 veto 模块**（追高风险 / OVERHEAT / Tier2 / ESP 低基数）
2. **如果继续 backtest 调优**：考虑加 `--subset {all,tier1_only,both}` CLI 让用户切换；当前是双跑硬编码
3. **L3 snapshot 持续累积**，6 月后跑 `--l3-mode=pit` 对照
4. **扩到 36 期**（覆盖 2023 段）— 但前提是 Phase 3 veto 规则已落地，否则 24p 已经够看

## 文件状态提醒

- `A-EGS/egs_main.py` 当前版本：**EGS v7.9**（不变）
- `runners/backtest_rank.py`：双 subset 切片已加
- `schemas/analysis_input.schema.json`: **1.1.0**（不变）
- `schemas/rank_backtest_report.schema.json`: **1.6.0**（本次升级）
- 当前有效 findings: codex.md + cc_24p.md 并列
