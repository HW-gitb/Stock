# Phase 3 kickoff spec handoff

**日期**：2026-05-24
**范围**：Phase 3 minimal analyzer + state 接口启动规格
**状态**：待开工。本文是 Phase 3 开工边界，不是实现记录。

---

## 1. 背景

Phase 2 / 2.5 / 2.6 已完成，当前结论只支持工程签收，不支持策略实盘签收。24 期 v7.10 production findings 显示，框架核心问题不是继续“挑出更好的票”，而是先把已识别坏票过滤掉。

EGS v7.10 已把部分坏信号从 Tier1 降到 Tier2，但 Tier2 filler 仍可能把这些票捡回样本。Phase 3 的最小目标是把这些降级信号升级为 analyzer 层 deterministic veto，并通过 rank 回测量化 veto 的边际贡献。

---

## 2. Phase 3 最小完成线

Phase 3 是 **minimal analyzer + state 接口**，不是完整 analyzer。

完成线如下：

1. `engine/analyzer/rule6_hard_veto.py`
   - 提供 `run_veto(candidate_dict, enabled_rules=None)` 或等价接口。
   - 对单个 candidate 返回结构化结果：
     ```json
     {
       "vetoed": true,
       "reasons": [
         {
           "code": "overheat",
           "version": 1,
           "severity": "hard",
           "detail": {}
         }
       ]
     }
     ```
   - veto 模块不能是空骨架；必须真实返回 deterministic decision。

2. `engine/analyzer/state_manager.py`
   - 定义 Phase 3 所需 state 接口。
   - 初版方法可以返回空 dict / False，但函数签名要稳定。

3. `state/a_short/positions.json`、`state/a_short/veto_log.json`、`state/a_short/circuit_breaker.json`
   - 初始化为空 stub。
   - JSON 写入必须使用 atomic write；不要引入 SQLite。
   - `execution_log.csv` 保持 CSV，作为后续 append-only 执行日志。

4. `tests/analyzer/`
   - 每条 veto rule 至少 1 个 positive fixture + 1 个 negative fixture。
   - 单测应直接覆盖 `run_veto(candidate_dict)`，避免只能靠全量回测发现规则回归。

5. `runners/backtest_rank.py`
   - 增加 analyzer veto replay。
   - 新增 subset：`tier1_veto_passed`。
   - 保留 `all` 和 `tier1_only` 作为 baseline；`tier1_only` 仍是当前 primary baseline，不被 `tier1_veto_passed` 自动替代。
   - `--analyzer-veto` 默认可开启，但只新增统计 subset，不改变原有 baseline 样本口径。
   - 支持 `--veto-rules chasing_high,overheat,l2_unknown,esp_non_positive` 或等价 flag，用于 ablation。

6. `schemas/rank_backtest_report.schema.json`
   - schema `1.10.0 -> 1.11.0`。
   - `settings.primary_subset` enum / subset 允许值加入 `tier1_veto_passed`。
   - `date_warnings.warning_type` 加入 `low_tier1_veto_passed_count`。
   - veto 后 Tier1 池告警：`<5` warn，`<3` critical。

7. Phase 3 replay findings
   - 至少比较 `all` / `tier1_only` / `tier1_veto_passed`。
   - 至少提供核心 ablation：只 veto `chasing_high,overheat` vs 4 条全开。
   - 报告必须给出 5d/10d/20d 的 mean、monthly_t、win_rate，并明确是否改善 Tier1-only baseline。

---

## 3. 第一批 hard veto rules

Phase 3 第一批 hard veto 是 4 条：

| code | version | 触发含义 | 备注 |
|---|---:|---|---|
| `chasing_high` | 1 | entry flag 明确为追高风险 | 24p 最强可执行负信号之一 |
| `overheat` | 1 | OVERHEAT 明确命中 | 24p 显著负信号 |
| `l2_unknown` | 1 | `l2_name == "未知"` 或等价明确未知行业字段 | 防止 filler 捡回行业不可判定票 |
| `esp_non_positive` | 1 | ESP / esp_raw 明确 `<= 0` | 防止非正预期票被 filler 捡回 |

重要边界：

- 4 条都是 hard veto，不做“只记 reason 不 veto”的软档。
- 每条 rule 必须独立 reason code，便于 attribution 和 ablation。
- **missing 不等于 negative**。字段缺失、空值、不可解析，不自动触发上述 hard veto；应返回 `pending_data` / `data_missing` 类诊断，除非 EGS 当前逻辑已明确把该缺失当作降级原因。
- `LOCK` 暂不 hard veto。当前 N=4 太小，只进入辅助 flag；扩样本到 N>=15 后再决策。

---

## 4. Reason code 契约

Reason code 是 analyzer 对外契约的一部分，必须版本化。

推荐结构：

```json
{
  "code": "overheat",
  "version": 1,
  "severity": "hard",
  "detail": {
    "field": "entry_flag",
    "value": "OVERHEAT"
  }
}
```

不要把主 code 写成 `overheat@v1`。主 code 保持稳定，version 单独字段；展示层可以渲染成 `overheat@v1`。

实现建议：

```python
RULE_VERSIONS = {
    "chasing_high": 1,
    "overheat": 1,
    "l2_unknown": 1,
    "esp_non_positive": 1,
}
```

如果未来阈值或语义变更，例如 OVERHEAT 阈值从 22 改到 25，则 `overheat` version 升到 2，旧 `veto_log.json` 仍可追溯。

---

## 5. 放置位置和依赖边界

- analyzer 新代码直接放 `engine/analyzer/`。
- 不要先放进 `A-EGS/`。
- `A-EGS/egs_main.py` 当前不移动；Phase 7 再做正式 DataHub / engine modularization。
- Phase 3 analyzer 不得反向 import `A-EGS/egs_main.py`。
- 如需 helper，放入轻量共享模块或在 analyzer 内部实现最小纯函数；不要制造 Phase 7 迁移债。
- state 用 JSON，不用 SQLite。

---

## 6. 回测解释口径

Phase 3 replay 的目的不是证明策略已经可实盘，而是验证 deterministic veto 是否改善 Phase 2 baseline。

必须保留以下口径：

- `all`：全样本 baseline。
- `tier1_only`：当前 primary baseline。
- `tier1_veto_passed`：Phase 3 analyzer veto 后的新对照口径。
- ablation subsets / runs：用于解释每条 veto rule 的边际贡献。

如果 `tier1_veto_passed` 没有提升 `tier1_only` 的 5d/10d/20d mean、monthly_t 或 win_rate，需要回查 rule 定义，不得直接宣称 analyzer 生效。

---

## 7. 下一步注意事项

- 开工前先读 `AGENTS.md`、`docs/CURRENT.md` 和本文。
- Phase 3 实现时 schema 先行；`rank_backtest_report` 升级到 1.11.0 后再接 replay 输出。
- 不要重跑 `A-EGS/egs_main.py` 才开始 Phase 3；第一版可以基于已有 24p generated artifacts 做 stats-only replay。
- 不要改写 DataHub / ODS / DWD / DWS；那是 Phase 7。
- 完成 Phase 3 后需要更新 `docs/CURRENT.md`，并按本 handoff 或新实现 handoff 记录验证命令和结果。

---

## 2026-05-24 追加：Phase 3 minimal veto replay 首轮落地

### 改了什么

- 新增 `engine/analyzer/rule6_hard_veto.py`。
  - `run_veto(candidate_dict, enabled_rules=None)` 支持嵌套 `analysis_input` candidate 和扁平 `rank_samples` row。
  - 四条 hard veto：`chasing_high@v1`、`overheat@v1`、`l2_unknown@v1`、`esp_non_positive@v1`。
  - reason code 与 version 分离；missing / unparseable 只进 diagnostics，不自动 veto。
- 新增 `engine/analyzer/state_manager.py`。
  - 提供 JSON state loader、`atomic_write_json()`、`append_veto_record()`、`has_position()`、`is_circuit_breaker_active()` 等 Phase 3 稳定接口。
  - 现有 `state/a_short/*.json` stub 保持 JSON，不引入 SQLite。
- 新增 `tests/analyzer/`。
  - 每条 veto rule 覆盖 positive + negative fixture。
  - 覆盖 missing 不触发 veto、未知 rule 报错。
- 修改 `runners/backtest_rank.py`。
  - 默认开启 analyzer veto replay；新增 `--no-analyzer-veto` 和 `--veto-rules`。
  - stats-only 继承上一份 report 设置时，`analyzer_veto` / `veto_rules` 仍以当前 CLI 为准，因为它们是 replay 配置，不是 generated pool 的数据事实。
  - `rank_samples.csv` 增加 `analyzer_vetoed`、`analyzer_veto_codes`、`analyzer_veto_reason_count`、`analyzer_veto_diagnostics`、`tier1_veto_passed`。
  - stats/portfolio 新增 `tier1_veto_passed` subset；保留 `all` / `tier1_only` baseline，`primary_subset` 仍为 `tier1_only`。
  - `strategy_variant_stats.csv` 增加 `analyzer_veto_chase_overheat` 与 `analyzer_veto_all_rules`，用于核心 ablation。
- 修改 `schemas/rank_backtest_report.schema.json`。
  - `1.10.0 -> 1.11.0`。
  - `settings` 增加 `analyzer_veto` / `veto_rules`。
  - `settings.primary_subset` enum 增加 `tier1_veto_passed`。
  - `date_warnings.warning_type` 增加 `low_tier1_veto_passed_count`，并允许 `tier1_veto_passed_count` 字段。
- 更新 `docs/CURRENT.md` 和 `AGENTS.md` 的当前状态 / schema 版本引用。

### 为什么改

Phase 2 结论是工程签收，不是策略签收。v7.10 已把追高 / OVERHEAT 等坏信号从 Tier1 降到 Tier2，但 filler 仍可能捡回坏票。Phase 3 首轮目标是把这些信号升级成 analyzer 层 deterministic veto，并在不改变 baseline 样本口径的前提下量化边际贡献。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in ['engine/analyzer/rule6_hard_veto.py','engine/analyzer/state_manager.py','runners/backtest_rank.py']]; print('compile ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests -p "test_*.py" -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\backtest_rank.py --mode production --stats-only --windows 5,10,20 --split-date 20250101
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); r=json.load(open('result/a_short/backtest/backtest_report.json',encoding='utf-8')); errs=list(Draft7Validator(s).iter_errors(r)); print('errors', len(errs)); print('schema_version', r['schema_version'])"
```

### 验证结果

- Compile：`compile ok`。
- Unit tests：10 tests passed。
- Schema meta-validation：`schema ok`。
- 24p stats-only replay：成功；复用 forward cache；`backtest_report.json` 通过 `rank_backtest_report v1.11.0` 校验。
- 独立 report validation：`errors 0`，`schema_version 1.11.0`。
- Report settings：`primary_subset=tier1_only`，`analyzer_veto=True`，`veto_rules=['chasing_high','overheat','l2_unknown','esp_non_positive']`。
- `date_warnings`：11 条；新增 warning 覆盖低 `tier1_veto_passed_count` 日期。

### 首轮 replay 关键结果

24p production stats-only，`period_split=all`，variant=`t1_net`：

| subset | N | 5d mean / t / win | 10d mean / t / win | 20d mean / t / win |
|---|---:|---:|---:|---:|
| `tier1_only` | 305 | +0.63 / 0.91 / 51.80% | +0.98 / 1.04 / 54.10% | +2.84 / 1.60 / 51.15% |
| `tier1_veto_passed` | 227 | +0.27 / 0.13 / 48.46% | +0.85 / 0.64 / 51.54% | +2.41 / 0.55 / 50.66% |

结论：四条 hard veto 全开后没有改善 Tier1-only baseline。不能宣称 analyzer 首轮策略有效。

Rule hit 分布（`rank_samples.csv`）：

| analyzer_veto_codes | count |
|---|---:|
| `none` | 227 |
| `esp_non_positive` | 87 |
| `chasing_high|overheat|esp_non_positive` | 19 |
| `chasing_high|esp_non_positive` | 9 |
| `chasing_high` | 9 |
| `chasing_high|overheat` | 9 |

核心 ablation：

- `analyzer_veto_chase_overheat` 对 Tier1-only 无边际影响：N=305，数字等于 `tier1_only`。原因是 v7.10 已把追高 / OVERHEAT 从 Tier1 降到 Tier2。
- `analyzer_veto_all_rules` 等于当前 `tier1_veto_passed`：N=227，表现弱于 Tier1-only。

### 失效旧结论

- “四条 hard veto 全开会改善 Tier1-only baseline”不成立。首轮 replay 结果相反。
- “chasing_high / overheat analyzer replay 会在 Tier1-only 内产生明显边际贡献”不成立；v7.10 已在 EGS 层先降级，Tier1 内没有可过滤样本。

### 下一步注意事项

1. 优先拆解 `esp_non_positive`：当前 `esp_raw <= 0` hard veto 大量过滤早期 Tier1，其中可能混有 `neutralize` / 独立池 / 数据不足导致的 0，不能直接等同“真实非正预期”。
2. 保留 analyzer 工程链路；后续只调整 rule 语义和启用组合，不要回滚 replay 框架。
3. 不要把 `tier1_veto_passed` 提升为 primary subset；`tier1_only` 仍是主 baseline。
4. 如继续 Phase 3，下一轮应先跑 `--veto-rules chasing_high,overheat,l2_unknown` 和单规则 ablation，验证是否只是 `esp_non_positive` 语义过宽造成首轮变差。

---

## 2026-05-24 追加：esp_non_positive v2 修正与 ablation

### 改了什么

- `engine/analyzer/rule6_hard_veto.py`
  - `esp_non_positive` 版本从 1 升到 2。
  - v2 只对明确负值 `esp_raw < 0` hard veto。
  - `esp_raw == 0` 改为 diagnostic：`neutral_zero_not_vetoed`，不再 hard veto。
- `tests/analyzer/test_rule6_hard_veto.py`
  - 新增/调整 v2 单测：负值触发，0 不触发，正值不触发。
- 重新生成 `result/a_short/backtest/*` stats/report，仍为 schema 1.11.0。
- 更新 `AGENTS.md` 和 `docs/CURRENT.md` 的当前 rule 语义。

### 为什么改

按首轮结果继续做 ablation 后，问题集中在 `esp_non_positive`：

- `chasing_high,overheat,l2_unknown` 在 Tier1 内命中 0 条，完全不改变 Tier1-only。
- 旧 v1 的 `esp_non_positive` 单独命中 78 条 Tier1，且结果与四条全开完全相同。
- 这 78 条里 75 条是 `esp_raw=0`，73 条带 `DATA-INC`，不是明确负预期，更像数据不足/中性占位。
- 被 v1 杀掉的 78 条 20d `t1_net` 反而更强：mean +4.08%，monthly_t 2.16，win 52.56%。

结论：`esp_raw == 0` 不能等同 negative；v1 违反“missing 不等于 negative”的精神，应升版本修正。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in ['engine/analyzer/rule6_hard_veto.py','runners/backtest_rank.py']]; print('compile ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests -p "test_*.py" -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\backtest_rank.py --mode production --stats-only --windows 5,10,20 --split-date 20250101
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); r=json.load(open('result/a_short/backtest/backtest_report.json',encoding='utf-8')); errs=list(Draft7Validator(s).iter_errors(r)); print('errors', len(errs)); print('schema_version', r['schema_version'])"
```

### 验证结果

- Compile：`compile ok`。
- Unit tests：11 tests passed。
- 24p stats-only replay：成功；复用 forward cache；`backtest_report.json` 通过 `rank_backtest_report v1.11.0` 校验。
- 独立 report validation：`errors 0`，`schema_version 1.11.0`。
- `date_warnings`：旧 v1 11 条，v2 后 6 条。

### Ablation 结果

快速 ablation（Tier1-only 内）：

| ruleset | Tier1 passed N | 结论 |
|---|---:|---|
| baseline `tier1_only` | 305 | 主 baseline |
| `chasing_high,overheat,l2_unknown` | 305 | Tier1 内命中 0 条，无边际影响 |
| old v1 `esp_non_positive` (`esp_raw <= 0`) | 227 | 误杀 78 条，显著弱于 baseline |
| v2 `esp_non_positive` (`esp_raw < 0`) | 302 | 只杀 3 条，接近 baseline |

最终 v2 report，`period_split=all`，variant=`t1_net`：

| subset | N | 5d mean / t / win | 10d mean / t / win | 20d mean / t / win |
|---|---:|---:|---:|---:|
| `tier1_only` | 305 | +0.63 / 0.91 / 51.80% | +0.98 / 1.04 / 54.10% | +2.84 / 1.60 / 51.15% |
| `tier1_veto_passed` | 302 | +0.62 / 0.74 / 51.66% | +0.97 / 0.95 / 53.97% | +2.84 / 1.56 / 50.99% |

Tier1 hit distribution after v2:

| analyzer_veto_codes | count |
|---|---:|
| `none` | 302 |
| `esp_non_positive` | 3 |

### 失效旧结论

- “`esp_raw <= 0` 应作为 hard veto”失效；当前证据显示这会误杀大量 `DATA-INC` / 中性 0 样本。
- “四条 hard veto 全开明显过滤坏票”仍不成立；v2 后几乎等同 Tier1-only，未形成可用边际改善。

### 下一步注意事项

1. 保留 `esp_non_positive` v2，不回到 `<=0`。
2. `tier1_veto_passed` 仍不能升级为 primary subset；`tier1_only` 继续是主 baseline。
3. Phase 3 后续应寻找 Tier1 内仍有命中的坏票特征。当前四条中，`chasing_high` / `overheat` 已被 EGS v7.10 前置降级，`l2_unknown` 在 Tier1 内无命中，`esp_non_positive` v2 样本太少。

---

## 2026-05-24 追加：Phase 3.2 Tier1 坏票特征诊断

### 改了什么

- 新增 `runners/diagnose_tier1_bad_signals.py`。
  - 只读取现有 `result/a_short/backtest/rank_samples.csv` 和 `generated/_intermediate/egs_full_YYYYMMDD.csv`。
  - 不重跑 EGS，不改候选池，不改 `primary_subset`。
  - 以 `20250101` 切 discovery / validation。
  - 默认坏票定义：`t1_net <= -5%`。
  - 输出 baseline、feature diagnostics、replay variants、bad sample list 和 Markdown 报告。
- 新增/更新输出：
  - `result/a_short/backtest/phase3_tier1_bad_signal_baseline.csv`
  - `result/a_short/backtest/phase3_tier1_bad_signal_features.csv`
  - `result/a_short/backtest/phase3_tier1_bad_signal_replay_variants.csv`
  - `result/a_short/backtest/phase3_tier1_bad_signal_samples.csv`
  - `result/a_short/backtest/Phase3_tier1_bad_signal_diagnostics.md`
- 更新 `AGENTS.md`、`docs/CURRENT.md`、`runners/README.md` 指针。

### 为什么改

首批四条 veto 已经没有足够边际：

- `chasing_high` / `overheat` / `l2_unknown` 在 Tier1 内无命中。
- `esp_non_positive` v2 只命中 3 条。
- `tier1_veto_passed` 接近 Tier1-only，不能作为新主口径。

因此 Phase 3.2 转向 Tier1 内坏票特征挖掘，但必须用 discovery/validation 拆分防止过拟合。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; compile(Path('runners/diagnose_tier1_bad_signals.py').read_text(encoding='utf-8'), 'runners/diagnose_tier1_bad_signals.py', 'exec'); print('compile ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe runners\diagnose_tier1_bad_signals.py
```

### 验证结果

- Compile：`compile ok`。
- Script run：success。
- Loaded Tier1 samples：305。
- Bad 20d samples (`t1_net <= -5%`)：85。
- Candidate negative features passing conservative discovery + validation filter：3。

### Baseline

Tier1-only:

| split | N | 5d t1_net | 10d t1_net | 20d t1_net | 20d bad rate |
|---|---:|---:|---:|---:|---:|
| all | 305 | +0.63 / t=0.91 / win 51.80% | +0.98 / t=1.04 / win 54.10% | +2.84 / t=1.60 / win 51.15% | 27.87% |
| discovery | 131 | -0.39 / t=0.22 / win 44.27% | -0.08 / t=0.27 / win 49.62% | +2.49 / t=0.71 / win 45.80% | 30.53% |
| validation | 174 | +1.39 / t=1.05 / win 57.47% | +1.77 / t=1.38 / win 57.47% | +3.10 / t=1.77 / win 55.17% | 25.86% |

### Candidate negative features

Three features passed the mechanical candidate filter:

| feature | discovery N / bad20 / mean20 | validation N / bad20 / mean20 | judgment |
|---|---:|---:|---|
| `final_score_bucket_fine=lt_60` | 47 / 42.55% / +1.01 | 26 / 46.15% / -3.38 | strongest candidate; plausible absolute score floor |
| `q1_dt_yoy=-100..-30` | 14 / 50.00% / +1.20 | 7 / 28.57% / +1.21 | N too small; observation only |
| `q1_dt_yoy=30..100` | 29 / 44.83% / -0.40 | 47 / 38.30% / +2.43 | bad-rate elevated, but mean still positive; observation only |

### Replay checks

Quick replay variants from the diagnostic script:

| variant | validation N | 5d t1_net | 10d t1_net | 20d t1_net |
|---|---:|---:|---:|---:|
| `tier1_only` | 174 | +1.39 / t=1.05 / win 57.47% | +1.77 / t=1.38 / win 57.47% | +3.10 / t=1.77 / win 55.17% |
| `score_ge_60` | 149 | +1.83 / t=1.14 / win 61.74% | +2.60 / t=1.26 / win 63.09% | +4.39 / t=1.79 / win 59.06% |
| `score_ge_65` | 135 | +1.93 / t=1.34 / win 62.22% | +2.47 / t=1.44 / win 62.22% | +4.21 / t=1.97 / win 57.78% |
| `drop_q1_30_100` | 127 | +1.96 / t=1.37 / win 60.63% | +2.37 / t=1.86 / win 61.42% | +3.35 / t=1.80 / win 60.63% |
| `drop_q1_neg_100_30` | 167 | +1.23 / t=1.03 / win 56.89% | +1.72 / t=1.41 / win 56.89% | +3.18 / t=1.78 / win 56.29% |

Interpretation:

- `score_ge_60` / `score_ge_65` are the most defensible next replay candidates.
- `score_ge_60` keeps more names and improves all validation windows.
- `score_ge_65` gives slightly better 5d/20d t-stat but cuts more names; risk of over-tightening is higher.
- q1 buckets are not ready for hard veto; they are weaker and more likely to be sample/regime artifacts.

### 失效旧结论

- “首批四条 veto 继续调参即可找到 Tier1 内坏票”不成立；它们在 Tier1 内几乎没有命中。
- “财务 yoy bucket 可以直接做 hard veto”不成立；当前 q1 bucket 信号不够稳定，最多 observation。

### 下一步注意事项

1. 下一步应把 `score_ge_60` / `score_ge_65` 作为 strategy variants 接入 `runners/backtest_rank.py`，生成正式 report/portfolio stats，而不是直接写进 analyzer hard veto。
2. 如果正式 replay 仍改善 validation 且不过度降低每期候选数，再讨论是否进入 analyzer 的 `absolute_score_floor` rule。
3. 保持 `tier1_only` 为 primary baseline；不要把 score floor subset 改成主口径。
