# Phase 2 Rank Backtest Findings - Codex

> **Measurement caveat (2026-05-31)**: All benchmark excess fields in this findings document (`excess_csi1000`, `excess_csi300`, and `excess_eligible`, across all horizons) are now treated as measurement-contaminated / uncorrected until same-anchor benchmark excess is re-run. The known issue is stock T+1 open entry semantics mixed with benchmark close-basis returns. Keep `t1_net` diagnostics, but do not use any excess line here as validated alpha, research-continuation evidence, or promotion evidence before corrected-basis revalidation.

生成时间：2026-05-24

## 结论

Phase 2 rank backtest 的工程链路可以标记为通过：正式周五实盘输出已重跑到 EGS v7.9，24 期 production 回测也已重跑，`backtest_report.json` 通过 schema 校验，360 条样本的 5/10/20 日收益全部可计算。

策略层面不能直接结论为“模型已稳定有效”。当前结果显示：绝对收益为正，但相对 CSI300/CSI1000 的超额收益不稳定；Tier1 明显优于 Tier2；低基数极端增长标的明显拖累 20 日表现。下一步应优先改进 ESP 低基数惩罚和 Tier2 填充策略，而不是简单提高仓位。

## 本轮修复

- EGS v7.8：修复 SW L1 行业映射全为“未知”的问题。Tushare L2 `parent_code` 对应 L1 `industry_code`，不是 `index_code`。
- SW 行业缓存升级到 `sw_industry_map_v6_*`，隔离旧 v4 薄覆盖坏缓存和 v5 L1 缺失缓存。
- EGS v7.9：`data_quality.completeness_score` 从硬编码 60 改为按候选股实际字段缺失动态计算。
- 正式周五输出 `result/a_short/20260522/analysis_input.json` 已重跑为 v7.9，Top15 全 Tier1，L1/L2 行业无未知。

## 回测口径

- 命令：`python runners\backtest_rank.py --mode production --periods 24 --freq monthly --end-date 20260301 --refresh-forward-daily`
- 样本：24 期 × 每期 15 只 = 360 条
- 日期：2024-01-31 至 2025-12-31，月频
- 入场：T+1 开盘
- 出场：T+5 / T+10 / T+20 收盘
- 交易成本：`t1_net` 已扣默认 0.16%
- L3：`neutralize`，即 `cat_score=50.0`
- 报告 schema：`rank_backtest_report` 1.5.0

## 工程验收

- `selected_dates`：24/24
- generated 候选池版本：24/24 均为 EGS v7.9
- 每期候选数：24/24 均为 15
- `backtest_report.json` schema errors：0
- `rank_samples.csv`：360 行
- 5/10/20 日 `ret_*_status`：全部 `ok`
- 正式输出 Top15：Tier1 15 只，L1/L2 行业未知 0 只

注意：24 期回测样本中有 14 条 Tier2 填充样本行业未知，但没有进入 Tier1。这是 backtest 为维持每期 15 样本而补 Tier2 的副作用，不影响 Tier1 子集判断；后续可以选择禁止未知行业进入 Tier2 filler。

## 核心收益

| 窗口 | t1_net 平均 | t1_net 胜率 | 月度 t | excess CSI300 | excess CSI1000 |
|---|---:|---:|---:|---:|---:|
| 5d | +0.13% | 51.67% | +0.13 | +0.40% | +0.83% |
| 10d | +0.29% | 52.22% | +0.27 | +0.37% | +0.39% |
| 20d | +1.72% | 48.33% | +1.17 | +0.28% | -0.27% |

解读：20 日绝对收益为正，但胜率不到 50%，且相对 CSI1000 为负。5 日相对 CSI1000 的结果最好，月度 t=2.09，但只说明短窗口有可继续观察的信号，不足以直接加仓。

## 关键分组

20 日 `t1_net`：

| 分组 | 样本 | 平均收益 | 胜率 | 月度 t |
|---|---:|---:|---:|---:|
| Top 1-5 | 120 | +1.87% | 43.33% | +1.19 |
| Top 6-10 | 120 | +1.61% | 48.33% | +0.85 |
| Top 11-15 | 120 | +1.69% | 53.33% | +1.05 |
| Tier1 | 302 | +2.96% | 51.66% | +1.72 |
| Tier2 | 58 | -4.71% | 31.03% | -2.27 |

最重要的结论是 Tier1 明显优于 Tier2。Top5 并没有明显压倒 Top6-15，所以当前不能只靠排名前 5 证明排序能力很强。

## 低基数增长

20 日 `t1_net`：

| 条件 | 样本 | 平均收益 | 胜率 | 月度 t |
|---|---:|---:|---:|---:|
| `q0_dt_yoy > 200%` | 33 | -2.44% | 39.39% | -1.57 |
| `q0_dt_yoy <= 200%` | 327 | +2.14% | 49.24% | +1.26 |
| `esp_raw > 200` | 34 | -2.34% | 41.18% | -1.51 |
| `esp_raw <= 200` | 326 | +2.15% | 49.08% | +1.27 |

这是本轮最明确的可执行发现：`q0_dt_yoy > 200%` 和 `esp_raw > 200` 不是增强信号，反而是负面信号。下一步应在 EGS 的 ESP 模型里加入 winsorize 或低基数惩罚。

## 月度稳定性

20 日 `t1_net` 最好月份：

| 日期 | 平均收益 | 胜率 |
|---|---:|---:|
| 2024-08-30 | +22.20% | 100.0% |
| 2025-07-31 | +8.68% | 86.7% |
| 2025-06-30 | +8.58% | 73.3% |
| 2025-05-30 | +8.40% | 80.0% |
| 2024-01-31 | +8.29% | 73.3% |

20 日 `t1_net` 最差月份：

| 日期 | 平均收益 | 胜率 |
|---|---:|---:|
| 2024-09-30 | -10.70% | 6.7% |
| 2024-07-31 | -9.02% | 6.7% |
| 2024-12-31 | -6.05% | 33.3% |
| 2025-10-31 | -4.63% | 26.7% |
| 2024-03-29 | -3.82% | 20.0% |

收益有明显月份集中效应，不是平滑稳定输出。应继续保持小仓位观察，不应把 24 期结果解释成稳态收益。

## Rule 6

当前 Rule 6 统计仍然不可用于强结论。大部分 Rule 6 字段仍是 `pending_data` 或 `pending_llm`，`rule6_any_status=triggered` 只有极少样本。Phase 3 analyzer 建立后，才有条件做 Rule 6 各否决项的真实预测力统计。

## 下一步建议

1. 在 EGS ESP 模型中加入低基数惩罚：优先处理 `q0_dt_yoy > 200%` 和 `esp_raw > 200`。
2. backtest filler 策略收紧：Tier1 不足 15 时，Tier2 filler 应排除 `l2_name=未知` 或完整度过低样本。
3. 继续保持 `Top15 观察、Top5 深度分析`，不要因为本次 20 日均值为正而提高实盘风险。
4. Phase 3 analyzer 建立后，补齐 Rule 6 的 deterministic 字段，再重跑 Rule 6 预测力。
