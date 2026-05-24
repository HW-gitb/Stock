# Phase 2 Validation Tooling Handoff

生成时间：2026-05-24

## 背景

上一轮 LLM 已经开始做时间切分，但只完成了 `--split-date` / `period_split` 的一半。本文记录本轮继续完成的 Phase 2 回测验证工具升级。

本轮目标不是证明策略有效，而是提高后续验证的真实性、可归因性和可解释性。

## 本轮代码修改

### `runners/backtest_rank.py`

- 保留并补完时间切分机制：
  - 新增/保留 `--split-date YYYYMMDD`
  - stats CSV 增加 `period_split=all/discovery/validation`
  - 用于 2024 规则发现、2025 样本外验证，避免同一批样本发现又验证规则
- 新增 T+1 不可买入模拟：
  - `fetch_forward_daily()` 拉取并缓存 `pro.stk_limit`
  - `attach_forward_returns()` 在 T+1 开盘价接近涨停价时标记 `pending_no_entry_limit_up`
  - 优先用 Tushare `stk_limit.up_limit`
  - 缺少 `stk_limit` 时 fallback 到 ST/主板/创业科创/北交所涨跌幅规则
- 新增 eligible-universe benchmark：
  - 读取 `result/a_short/backtest/generated/_intermediate/egs_full_YYYYMMDD.csv`
  - eligible universe 定义为同 as_of 的 Tier1 + Tier2 全量可选池
  - 输出 `eligible_benchmark.csv`
  - 新增 return variant：`excess_eligible`
- 新增策略变体对照回测：
  - 输出 `strategy_variant_stats.csv`
  - 输出 `strategy_variant_monthly.csv`
  - post-hoc mask 变体：
    - `baseline`
    - `no_chase`
    - `no_overheat`
    - `no_low_base`
    - `tier1_only`
    - `no_tier2_unknown`
    - `no_lock`
    - `combined_p0`
  - 重排变体：
    - `esp_cap_200_rerank`
    - 该变体从 `egs_full_YYYYMMDD.csv` 重放 score_l5 风格排序，不只做 mask
- 新增 portfolio-level 回测：
  - 输出 `portfolio_period_returns.csv`
  - 输出 `portfolio_stats.csv`
  - 统计每期等权组合收益、复合收益、最大回撤、最佳/最差期、组合胜率、monthly_t、monthly Sharpe
- 新增 reason observability：
  - `rank_samples.csv` 增加 `risk_reasons`
  - 用于标记 `chasing_high` / `overheat` / `lock` / `low_base_growth` / `tier2` / `unknown_industry`
- report schema version 升至 `1.8.0`

### `A-EGS/egs_main.py`

- EGS 版本升至 `v7.10`
- 新增 `CONF["esp_raw_cap"] = 200.0`
- `score_l5()` 中 `esp_raw_w` 上限改为 `min(p99, 200)`
- 新增 `low_base_growth_flag`
- 输出 `downgrade_reasons` / `score_penalty_reasons`
- backtest 模式下 Tier2 filler 排除 `l2_name == "未知"`

注意：`analysis_input.schema.json` 未升级。本轮 reason chain 先写入 CSV / backtest samples，不改 `analysis_input` 契约，避免 Phase 3 前过早扩大跨模块 schema。

### `schemas/rank_backtest_report.schema.json`

- schema `$id` 升到 `1.8.0`
- `forward_daily` 增加 `limit_rows`
- `outputs` 增加：
  - `eligible_benchmark`
  - `strategy_variant_stats`
  - `strategy_variant_monthly`
  - `portfolio_period_returns`
  - `portfolio_stats`
- 新增 `strategy_variants`
- `return_variants` 增加 `excess_eligible`

## 验证命令与结果

### 语法检查

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['runners/backtest_rank.py','A-EGS/egs_main.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]; print('syntax ok')"
```

结果：`syntax ok`

### schema 元校验

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema ok')"
```

结果：`schema ok`

### 临时 report 写入 + schema 校验

使用 `20251231` 单期、`window=5`、现有 forward cache 做无联网内部自测，临时输出到：

```text
result/a_short/backtest/_tmp_validate
```

结果：

```text
[OK] backtest_report.json validated against rank_backtest_report v1.8.0
tmp report ok
```

临时目录已删除。

### stale pool 保护

执行旧 generated pool 的 stats-only：

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe runners\backtest_rank.py --stats-only --periods 1 --split-date 20250101
```

结果：按预期拒绝旧池：

```text
[FATAL] stats-only refuses stale or incompatible candidate pools
engine_version 'v7.6' != 'v7.10'
```

## 失效旧结论

- 任何基于 EGS v7.9 或更早 generated pools 的 `stats-only` 新结论都不能直接使用。
- EGS 已升 v7.10，必须重新生成候选池后再做正式 24 期 / 36 期比较。
- 旧 `rank_backtest_report` 1.6/1.7 输出不包含 T+1 涨停不可买、eligible benchmark、strategy variants、portfolio stats，不能用于新一轮方法论判断。

## 下一步

正式验证推荐命令：

```powershell
python A-EGS\egs_main.py --as-of 20260522
```

然后跑 24 期 production，带时间切分：

```powershell
python runners\backtest_rank.py --mode production --periods 24 --freq monthly --end-date 20260301 --split-date 20250101 --refresh-forward-daily
```

重点检查：

- 周五实盘 Top15 数量、Tier1 数量、`downgrade_reasons`、`score_penalty_reasons`
- `summary_by_window.csv` 中 `subset=tier1_only` 且 `period_split=validation`
- `strategy_variant_stats.csv` 中 `combined_p0`、`no_chase`、`no_overheat`、`esp_cap_200_rerank` 的 validation 表现
- `eligible_benchmark.csv` 和 `excess_eligible`
- `portfolio_stats.csv` 的组合级最大回撤、复合收益、monthly_t
- `rank_samples.csv` 中 `pending_no_entry_limit_up` 数量

