# Phase 5 kickoff spec handoff

**日期**：2026-05-25
**范围**：Phase 5 execution backtest 启动边界与 contract 规格
**状态**：kickoff spec 已建立；Phase 5 schema / runner / simulator 代码尚未开始。
**前置 handoff**：`docs/handoff/2026-05-25_phase4_kickoff_spec_handoff.md`（Phase 4 minimal 完成：deterministic report schema + runner + Skill 使用文档）

---

## 1. 背景

Phase 4 已完成单票 deterministic report 的最小闭环：

- `schemas/deterministic_report.schema.json` v1.0.0
- `runners/run_analysis_report.py`
- `schemas/deterministic_report_coverage.md`
- `skills/a_short_analysis/SKILL.md`
- prompt 骨架与 enrichment patch contract

但 Phase 4 runner v1 只输出 `skip/watch`，不会输出 `buy`，也不会计算入场价、止损、止盈或仓位。Phase 5 因此不能把 Phase 4 Markdown 或 LLM notes 当成交易指令，也不能把 `watch` 直接解释成买入。

Phase 5 的目标是建立可复现的 execution backtest contract 和模拟器，验证“如果把筛选/分析结果转成可执行交易计划，止损、时间止损、熔断、仓位限制、冷静期会怎样影响结果”。它不是新的选股优化阶段，也不是 Phase 7 DataHub 重构。

---

## 2. Phase 5 边界

Phase 5 = execution 回测。最小范围包括：

1. execution report schema first。
2. deterministic execution plan / decision 来源清楚。
3. 用历史日线 forward data 模拟交易事件。
4. 完整记录 entry、exit、stop、time stop、position、circuit breaker、cooldown 的触发路径。
5. 输出 machine-readable report + CSV 明细，便于 Claude / Codex / 用户复核。

明确不做：

- 不改 `A-EGS/egs_main.py` 选股逻辑。
- 不改 Phase 3 hard veto 规则。
- 不把 LLM enrichment 或 Markdown 自由文本解析成交易指令。
- 不启动 Phase 7 DataHub / ODS-DWD-DWS 重构。
- 不用单一收益切片冒充 execution 回测。
- 不在没有 contract 的情况下直接写撮合模拟大实现。

---

## 3. 第一条后续代码任务

**下一条最小代码任务**：

新增 `schemas/execution_backtest_report.schema.json` v1.0.0，并加最小 schema meta-validation 测试。

该任务只定义 report contract，不写 simulator，不生成交易，不改 rank backtest。

最低字段范围建议：

```text
schema_name: "execution_backtest_report"
schema_version: "1.0.0"
generated_at
preset
mode
settings
inputs
execution_assumptions
data_lineage
outputs
metrics
date_warnings
limitations
```

`settings` 的具体字段由 `schemas/execution_backtest_report.schema.json` 任务定义；本 handoff 只锁定必须承载的语义范围。

其中 `execution_assumptions` 必须显式描述：

- entry timing：默认 T+1 open，且沿用 limit-up unbuyable 约束
- price adjustment：qfq via adj_factor
- transaction cost：默认沿用 rank backtest `cost_pct`
- stop loss semantics
- take profit semantics
- time stop days
- position sizing cap
- portfolio circuit breaker
- cooldown / re-entry rules

---

## 4. 输入 contract

Phase 5 不直接读 LLM 自由文本。允许输入来源分三层：

1. `analysis_input.json`：候选池、scores、technical、fundamental、source lineage。
2. Phase 3 analyzer：`run_veto(candidate)` 的 deterministic veto 输出。
3. Phase 4 deterministic report：只读 JSON 结构化字段；如果字段是 `unknown` / `requires_llm` / `not_implemented_phase4`，simulator 必须按规则跳过或标 warning，不能猜。

第一版可以先选择更保守路径：

- 不要求预生成每只股票的 Phase 4 report；
- runner 从 `analysis_input.json` + analyzer/state 直接构造 execution candidate；
- report 仍记录是否引用了 deterministic report，以及缺失原因。

如果后续决定必须消费 Phase 4 report，则应先定义输入路径和 version guard，不得读 Markdown。

---

## 5. 输出位置

Phase 5 输出应隔离在 backtest 目录，避免污染实盘结果目录：

```text
result/a_short/backtest/execution/
├── execution_report.json
├── trades.csv
├── daily_equity.csv
├── order_events.csv
└── skipped_candidates.csv
```

`execution_report.json` 必须先通过 `schemas/execution_backtest_report.schema.json`。

---

## 6. 模拟完成线

Phase 5 不能只复用 rank 回测的 `ret_5d/10d/20d_t1_net`。完成线必须覆盖：

1. **Entry**
   - T+1 open entry。
   - limit-up / no entry 时明确标 `entry_unbuyable`，不产生持仓。
2. **Stop loss**
   - 至少支持固定 stop price 或 schema 中声明的 stop rule。
   - 若输入没有 stop，则交易必须 skipped 或标 `missing_stop`, 不能默认无止损。
   - Phase 4 v1 的 `exit_plan.stop_loss` 恒为 `null` / `not_implemented_phase4`；若 Phase 5 v1 直接消费 Phase 4 report，将在 `missing_stop` 规则下 100% skipped。因此 §4 的保守路径（默认从 `analysis_input.json` + analyzer/state 构造 execution candidate）是 v1 默认路径。
3. **Time stop**
   - 到期未触发止盈止损时按 time stop exit。
4. **Take profit**
   - 如果 v1 不支持止盈，report 必须明确 limitation；若支持，触发优先级要写入 assumptions。
5. **Position sizing**
   - 单票仓位上限、总资金约束、现金余额变化必须可追踪。
6. **Circuit breaker**
   - 组合级熔断触发后，新开仓应停止；已有仓位处理规则必须明确。
7. **Cooldown**
   - 同一 ts_code 止损后再入场冷静期必须可模拟或显式 skipped。
8. **Event log**
   - 每笔交易的 entry / exit / stop / time_stop / circuit / cooldown 事件必须有行级记录。

---

## 7. 与 Phase 4 schema v1.1.0 的关系

Claude audit 留下的 Phase 4 schema v1.1.0 设计点已定为 Phase 5 前置：

- `data_lineage.l3_mode`
- `data_lineage.enrichment_applied`
- `data_lineage.enrichment_source`

Phase 5 schema 任务开始前，先单独升级 `schemas/deterministic_report.schema.json` 到 v1.1.0，补齐以上 lineage / enrichment 字段，并同步 runner 输出与测试。完成后再进入 `schemas/execution_backtest_report.schema.json`。

不能在 execution runner 里隐式假设这些字段存在，也不能只在 `execution_backtest_report.data_lineage` 中局部补字段而让 Phase 4 deterministic report contract 继续缺口。

---

## 8. 验证要求

第一条 schema 任务完成时至少验证：

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/execution_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; import json; json.load(open('schemas/execution_backtest_report.schema.json',encoding='utf-8')); print('json parse ok')"
```

后续 runner 任务完成时再运行 unittest / smoke，不在 schema 任务里提前写大实现。

---

## 9. 下一步注意事项

1. 下一步先做 deterministic report schema v1.1.0 lineage / enrichment 字段升级。
2. 再做 `schemas/execution_backtest_report.schema.json` + 最小 schema 测试。
3. 不要在 schema 任务里新建 simulator。
4. 不要改变 rank backtest 输出口径。
5. 不要把 Phase 4 `watch` 当成 Phase 5 `buy`。
6. Claude 需要重点审查：schema 字段是否足够承载 execution 完成线、Phase 4 schema v1.1.0 升级是否完整、输出目录是否与现有 backtest 目录隔离。

## 2026-05-25 追加：deterministic_report v1.1.0 前置升级

### 改了什么

- `schemas/deterministic_report.schema.json`：v1.0.0 -> v1.1.0，`data_lineage` 新增必填字段：
  - `l3_mode`
  - `enrichment_applied`
  - `enrichment_source`
- `runners/run_analysis_report.py`：
  - `REPORT_SCHEMA_VERSION` 升到 `1.1.0`。
  - 默认输出 `data_lineage.l3_mode`，来源为 `analysis_input.source.l3_mode`；legacy 缺失时按 analysis_input schema 约定 fallback 为 `today`。
  - 默认输出 `enrichment_applied=false` / `enrichment_source=null`。
  - 合并 enrichment patch 后，只替换 `llm_notes`，同时把 patch `source` 镜像到 `data_lineage.enrichment_source` 并置 `enrichment_applied=true`。
- `schemas/deterministic_report_enrichment.schema.json` 与 example：同步升到 v1.1.0，`target.report_schema_version` 对齐 deterministic report v1.1.0。
- `tests/skill/test_run_analysis_report.py`：覆盖 v1.1.0 schema_version、L3 mode lineage、legacy 缺失 L3 mode fallback、无 enrichment 默认 lineage、enrichment source lineage。
- `result/a_short/20260522/reports/600415.SH.{json,md}`：重生成 tracked sample report，避免 repo 内样例停留在 v1.0.0 contract。
- `schemas/deterministic_report_coverage.md` 与 `docs/CURRENT.md`：同步当前 contract 口径。

### 为什么改

Phase 5 execution schema 不能在自己的 `data_lineage` 里局部补字段，同时让 Phase 4 deterministic report contract 继续缺口。先补 `deterministic_report` v1.1.0，可以让后续 execution schema 明确引用同一套 L3 / enrichment lineage 口径。

### 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/deterministic_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('deterministic schema ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/deterministic_report_enrichment.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('enrichment schema ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.skill.test_run_analysis_report -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\run_analysis_report.py --as-of 20260522 --ts-code 600415.SH
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; schema=json.load(open('schemas/deterministic_report.schema.json',encoding='utf-8')); report=json.load(open('result/a_short/20260522/reports/600415.SH.json',encoding='utf-8')); errors=list(Draft7Validator(schema).iter_errors(report)); print('sample_schema_errors', len(errors)); print('schema_version', report.get('schema_version')); print('l3_mode', report['data_lineage'].get('l3_mode')); print('enrichment_applied', report['data_lineage'].get('enrichment_applied')); print('enrichment_source', report['data_lineage'].get('enrichment_source'))"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['schemas/deterministic_report.schema.json','schemas/deterministic_report_enrichment.schema.json','schemas/examples/deterministic_report_enrichment.example.json','schemas/deterministic_report_coverage.md','docs/CURRENT.md']; [Path(f).read_text(encoding='utf-8') for f in files]; print('utf8 ok')"
```

### 验证结果

- deterministic report schema meta-validation：`deterministic schema ok`
- enrichment schema meta-validation：`enrichment schema ok`
- `tests.skill.test_run_analysis_report`：11 tests passed
- sample report schema validation：`sample_schema_errors 0`, `schema_version 1.1.0`, `l3_mode today`, `enrichment_applied False`, `enrichment_source None`
- UTF-8 read check：`utf8 ok`

### 失效旧结论

- `deterministic_report.schema.json` 当前版本不再是 v1.0.0；后续 Phase 5 设计必须按 v1.1.0 读取 `data_lineage.l3_mode` / `enrichment_applied` / `enrichment_source`。
- `deterministic_report_enrichment.schema.json` 当前版本不再是 v1.0.0；patch 的 `target.report_schema_version` 必须是 `1.1.0`。

### 下一步注意事项

1. 先让 Claude 审查本轮 uncommitted diff。
2. 通过并提交后，再进入 `schemas/execution_backtest_report.schema.json` v1.0.0 + 最小 schema meta-validation。
3. 不要在 execution schema 任务里回头改 Phase 4 `watch/skip` 语义；Phase 4 runner v1 仍不产生 `buy`。

## 2026-05-25 追加：execution_backtest_report v1.0.0 schema-first

### 改了什么

- 新增 `schemas/execution_backtest_report.schema.json`，JSON Schema Draft 7，schema id:
  `https://stock.local/schemas/execution_backtest_report/1.0.0/schema.json`。
- 顶层 contract 固定为：
  - `schema_name = execution_backtest_report`
  - `schema_version = 1.0.0`
  - required fields: `schema_name`, `schema_version`, `generated_at`, `preset`, `mode`, `settings`, `inputs`, `execution_assumptions`, `data_lineage`, `outputs`, `metrics`, `date_warnings`, `limitations`
- `execution_assumptions` 明确承载 Phase 5 完成线需要审查的撮合语义：
  - T+1 open entry
  - limit-up unbuyable -> `entry_unbuyable`
  - qfq via adj_factor / none
  - transaction cost `cost_pct`
  - missing stop -> `skip_trade` or `mark_missing_stop`
  - take profit / time stop trigger order
  - position sizing cap / cash constraint
  - portfolio circuit breaker
  - cooldown
  - event log required event codes
- `inputs` 明确 v1 默认 primary input 为 `analysis_input`；`deterministic_reports` 只能作为可选 JSON refs，必须 version-guard，不能读取 Markdown。
- `outputs` 固定 Phase 5 目录下五个产物名：`execution_report`, `trades`, `daily_equity`, `order_events`, `skipped_candidates`。
- 新增 `tests/schema/test_execution_backtest_report_schema.py` 与 `tests/schema/__init__.py`，只做 schema meta-validation 和关键 contract block 名称护栏，不实现 runner / simulator。
- 更新 `docs/CURRENT.md`：deterministic report v1.1.0 已提交，当前待审查对象切换为 execution report schema v1.0.0。

### 为什么改

Phase 5 必须先把 execution-level report 的机器契约固定下来，再写 runner / simulator。这样 Claude 可以先独立审查撮合假设、输入边界、输出目录和 lineage 字段是否足够承载后续 execution 回测，而不会被实现细节掩盖 schema 缺口。

### 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/execution_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; import json; json.load(open('schemas/execution_backtest_report.schema.json',encoding='utf-8')); print('json parse ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_execution_backtest_report_schema -v
```

### 验证结果

- Schema meta-validation：`schema ok`
- Bundled Python JSON parse：`json parse ok`
- `tests.schema.test_execution_backtest_report_schema`：2 tests passed

### 失效旧结论

- `docs/CURRENT.md` 中“deterministic_report v1.1.0 待 Claude 审查 / execution schema 尚未开始”的状态已失效；`da26a2b` 已提交 deterministic report lineage contract，本轮待审查对象是 execution report schema v1.0.0。
- Phase 5 schema 任务不再是“下一步”；当前工作树已经实现 schema-first 合同。后续必须先完成 Claude review + 用户提交，再进入 runner / simulator。

### 下一步注意事项

1. 先让 Claude 审查本轮 uncommitted diff，重点看 `execution_assumptions` 是否足够承载 Phase 5 完成线。
2. 通过并提交后，再实现最小 runner / simulator；不要在 review 前抢跑实现。
3. 后续 runner 只能输出 JSON 并先通过 `schemas/execution_backtest_report.schema.json`，不得读取 Phase 4 Markdown。

## 2026-05-25 追加：execution_backtest_report Optional contract hardening

### 改了什么

- `settings` 删除与 `execution_assumptions` 重复的执行参数：
  - `cost_pct`
  - `max_position_pct`
  - `max_positions`
  - `time_stop_days`
- `execution_assumptions` 继续作为撮合规则的单一权威来源：
  - cost 只在 `transaction_cost.cost_pct`
  - position cap 只在 `position_sizing.max_position_pct` / `position_sizing.max_positions`
  - time stop days 只在 `time_stop.days`
- `settings.primary_input` 从单值 `enum: ["analysis_input"]` 改为 `const: "analysis_input"`。
- `execution_assumptions.event_log.event_codes` 加强为：
  - `minItems: 2`
  - `allOf + contains` 强制包含 `entry` 与 `exit`
  - description 明确最小事件行要求
- `$defs.stringList` 加 `minItems: 1`，从而约束 `data_lineage.api_families.candidate_generation` / `execution_price` / `state_replay` 不能为空数组。
- `tests/schema/test_execution_backtest_report_schema.py` 增加断言，覆盖以上 contract hardening。
- `docs/CURRENT.md` 更新为 Optional 修复后待 Claude 复审状态。

### 为什么改

这些改动来自 Claude 对 schema-first diff 的 4 条 Optional 建议，用户已批准。核心目标是减少 contract drift：执行参数只保留在实际撮合假设中；lineage 不允许语义为空；事件日志至少声明 entry / exit 两个基本事件。

### 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/execution_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; import json; json.load(open('schemas/execution_backtest_report.schema.json',encoding='utf-8')); print('json parse ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m unittest tests.schema.test_execution_backtest_report_schema -v
```

### 验证结果

- Schema meta-validation：`schema ok`
- Bundled Python JSON parse：`json parse ok`
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed

### 失效旧结论

- 旧 schema 草案中 `settings` 同时记录 cost / position cap / time stop days 的方式已失效；后续 runner 必须从 `execution_assumptions` 读取这些实际撮合参数。
- 旧 schema 草案中 `event_log.event_codes` 只需 1 个事件码、`api_families.*` 可以为空数组的宽松口径已失效。

### 下一步注意事项

1. 先让 Claude 复审 Optional 修复后的 uncommitted diff。
2. 通过并提交后，再实现最小 runner / simulator skeleton。
3. 后续 runner 写入 report 时，必须让 `settings` 只表达 run-level 设置，撮合细节统一写入 `execution_assumptions`。

## 2026-05-26 追加：execution runner skeleton

### 改了什么

- 新增 `runners/backtest_execution.py`，作为 Phase 5 execution backtest 的最小 runner skeleton。
- Runner 读取 `analysis_input.json` 作为唯一 primary input，调用 Phase 3 `run_veto(candidate)` 做 analyzer replay，不读取 Phase 4 Markdown 或 LLM free text。
- 默认输出目录为 `result/a_short/backtest/execution/`，输出：
  - `execution_report.json`
  - `trades.csv`
  - `daily_equity.csv`
  - `order_events.csv`
  - `skipped_candidates.csv`
- `execution_report.json` 写入前必须通过 `schemas/execution_backtest_report.schema.json` v1.0.0 校验。
- 新增 `tests/execution/test_backtest_execution.py`，覆盖最小 fixture 到 schema-valid report + CSV shells 的 smoke path。
- 更新 `docs/CURRENT.md` 与 `runners/README.md`，标记 runner skeleton 已实现但真实 simulator / fill logic 尚未开始。

### 为什么改

Phase 5 已完成 schema-first contract，下一条最小实现任务就是把 contract 接到一个可运行、可审查的 runner skeleton。此轮刻意不实现行情获取、撮合、止损触发、组合记账或退出模拟，避免在 contract 还未由 Claude 复审前扩大实现面。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pip install -r requirements-dev.txt
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_backtest_execution tests.schema.test_execution_backtest_report_schema -v
```

### 验证结果

- `jsonschema>=4.0` 已按 `requirements-dev.txt` 安装到本次 Codex bundled Python runtime。
- `tests.execution.test_backtest_execution`：1 test passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- Smoke test 实际写出临时目录下的 `execution_report.json` 与 4 个 CSV，并用 JSON Schema 校验 report。

### 失效旧结论

- “Phase 5 runner / simulator 尚未开始”已失效；当前准确状态是 runner skeleton 已开始并待审，真实 simulator / fill logic 尚未开始。
- “下一步是实现 runner skeleton”已失效；下一步是 Claude 审查当前 uncommitted runner skeleton，通过并提交后再进入 price simulation / fill logic。

### 下一步注意事项

1. Claude 审查重点应放在：schema 输出是否严格对齐 v1.0.0、`execution_assumptions` 是否仍是撮合参数唯一权威、输出目录是否隔离、是否误读了 Markdown/LLM 文本。
2. 通过并提交前，不继续写真实 fill simulator。
3. 后续实现 price simulation 时，先定义 price data 输入 contract；不能把 rank backtest 的 `ret_*` 当作 execution fill 结果复用。

## 2026-05-26 追加：execution runner skeleton review fixes

### 改了什么

- 修复 Claude review R1：`normalized_l3_mode()` 现在与 `analysis_input.schema.json` 和 Phase 4 runner 对齐。
  - 缺失 `source.l3_mode` -> `today`
  - `pit` / `today` / `neutralize` 原样保留
  - 其他值直接 `ValueError`
- 采纳 Optional O1：`main()` 只计算一次 `classify_skips()`，并把 `skipped_rows` 传给 `build_report()` / `write_outputs()`，避免重复跑 `run_veto()`。
- 采纳 Optional O2：`skipped_candidates.csv.analyzer_reason_codes` 改为逗号分隔，避免与 Markdown table cell 的 `|` 冲突。
- 采纳 Optional O3：补充 L3 lineage 分支测试与 `trade_date` / `--as-of` 不一致测试。
- 采纳 Optional O4：`missing_stop` 的 order event message 改成明确说明 skeleton 尚未接入 deterministic stop input，而不是重复 event code。

### 为什么改

R1 是实际 lineage bug：`pit` 会被错误写成 `neutralize`，legacy 缺失值也会被错误写成 `neutralize`。这会污染 Phase 5 execution report 的数据血缘。O1-O4 都是低成本的 contract hygiene 和测试加固，接受后不扩大 simulator scope。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_backtest_execution tests.schema.test_execution_backtest_report_schema -v
```

### 验证结果

- `tests.execution.test_backtest_execution`：5 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- 总计 8 tests passed，smoke report 继续通过 `execution_backtest_report.schema.json` v1.0.0 校验。

### 失效旧结论

- `normalized_l3_mode()` 不再接受或转换 `"historical_replay"`；该值不属于 `analysis_input.schema.json` 的合法 enum。
- 当前 skeleton 不再重复执行 analyzer replay；后续若 `run_veto()` 有副作用或成本上升，这一路径已规避重复调用。

### 下一步注意事项

1. 让 Claude 复审本轮 repair diff，尤其确认 R1 lineage invariant 和 Optional disposition 记录是否完整。
2. 复审 Pass 并提交前，不继续实现真实 price simulation / fill logic。
3. 下一轮实现 fill logic 前，先明确 `inputs.price_data.path` 指向的真实 OHLC 数据来源与最小字段契约。

## 2026-05-26 追加：execution price data input contract

### 改了什么

- 新增 `schemas/execution_price_data.schema.json` v1.0.0，定义 Phase 5 `execution_report.inputs.price_data.path` 未来指向的真实 OHLC 输入文件契约。
- 新增 `tests/schema/test_execution_price_data_schema.py`，覆盖 schema meta-validation、API family 最小要求、qfq OHLC + limit 字段契约、最小合法实例。
- 补齐 `docs/SESSION_LOG.md` 的 post-commit reconstructed entry，记录 commit `8488427` 已完成，避免下一位 LLM 误判 runner skeleton 仍待提交。
- 更新 `docs/CURRENT.md`，把当前 P0 从 runner skeleton 复审切换为 price data input contract 复审。

### 为什么改

Phase 5 runner skeleton 已提交，但 `inputs.price_data.path` 仍只是占位字符串。进入真实 fill logic 前，必须先明确执行级价格输入的最小字段、数据来源和 lineage，否则后续撮合会把 rank backtest 的 `ret_*` 或其他聚合收益误用为逐日成交价格。

本轮只定义契约，不实现 provider fetch、缓存生成、撮合、止损止盈、时间止损、组合记账或真实交易事件。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema tests.execution.test_backtest_execution -v
```

### 验证结果

- `tests.schema.test_execution_price_data_schema`：4 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- `tests.execution.test_backtest_execution`：5 tests passed。
- 总计 12 tests passed；现有 runner skeleton 继续通过 schema-valid smoke path。

### 失效旧结论

- “下一步是 Claude 复审 runner skeleton 修复”已失效；runner skeleton 修复已通过 review 并提交为 `8488427`。
- “`inputs.price_data.path` 暂无明确文件契约”已失效；当前契约为 `execution_price_data` v1.0.0。

### 下一步注意事项

1. 先让 Claude 审查本轮 schema/doc diff。
2. 通过并提交前，不实现 provider fetch 或 fill simulation。
3. 后续 loader 必须生成满足 `execution_price_data` 的文件，并把 execution report 的 `inputs.price_data.path` 从 placeholder 改成真实路径。

## 2026-05-26 追加：execution price data contract review fixes

### 改了什么

- 处理 Claude 对 `execution_price_data` v1.0.0 的 3 条 Optional suggestion。
- `source.api_families.items` 从封闭 enum 改为非空字符串，同时保留 `minItems: 4`、`uniqueItems: true` 和四个 required `contains`，允许后续 loader 声明额外 provider family。
- `rows` 增加 `minItems: 1`，避免空 price file schema-valid。
- `priceRow.is_trade_day` 改为 `const: true`，明确 rows 只表达交易日价格观测；非交易日由 `trade_cal` lineage 表达，不用空 OHLC row 表达。
- `tests/schema/test_execution_price_data_schema.py` 增加空 rows 与非交易日 row 的拒绝测试。

### 为什么改

Claude review 指出初版契约存在三个可读性/下游风险点：API family 同时用 enum 与 contains 过度约束；空 rows 会让未来 fill simulator 在更深层报错；`is_trade_day` 与必填正数 OHLC 的语义有冲突。本轮选择把 price rows 定义为“实际交易日价格观测”，保留 OHLC 必填正数，日历缺口交给 `trade_cal`。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema tests.execution.test_backtest_execution -v
```

### 验证结果

- `tests.schema.test_execution_price_data_schema`：5 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- `tests.execution.test_backtest_execution`：5 tests passed。
- 总计 13 tests passed；现有 runner skeleton 继续通过 schema-valid smoke path。

### 失效旧结论

- “`api_families` 只能包含四个固定 family”已失效；现在必须包含四个 minimum family，但可声明额外非空 family。
- “`rows: []` schema-valid”已失效；price data file 必须至少包含一行。
- “`is_trade_day` 是任意 boolean”已失效；price row 只允许 `is_trade_day: true`。

### 下一步注意事项

1. 让 Claude 复审 Optional disposition 是否合理。
2. 通过并提交前，仍不实现 provider fetch 或 fill simulation。
3. 后续 loader 若遇到停牌或非交易日，应通过缺失 price row / `trade_cal` / downstream skip 处理，不要伪造 OHLC。

## 2026-05-26 追加：execution price data loader wiring

### 改了什么

- `runners/backtest_execution.py` 新增 `--price-data` 参数，读取并校验一个既有 `execution_price_data` JSON 文件。
- 新增 `load_execution_price_data()`，复用 JSON Schema 校验工具，校验 `schemas/execution_price_data.schema.json`。
- 新增 price-data 语义校验：
  - `date_range.start_date <= --as-of <= date_range.end_date`
  - `symbols` 必须覆盖 `analysis_input.candidates` 中的全部 candidate code
- `execution_report.inputs.price_data` 在传入 `--price-data` 时写入真实路径、date range、adjustment mode；未传入时保留 skeleton 占位值。
- `data_lineage.api_families.execution_price` 在传入 `--price-data` 时来自 price-data source；未传入时保留 `not_implemented_phase5_skeleton`。
- 新增 `tests/fixtures/execution_price_data_minimal.json` 与 3 条 execution runner 测试，覆盖正常引用、date range mismatch、symbol coverage mismatch。

### 为什么改

`execution_price_data` 契约已经提交为 `ad4068f`。下一条最小实现不是直接抓 Tushare 或撮合，而是先让 runner 消费这个契约，确保 `inputs.price_data.path` 能从占位字符串过渡为 schema-validated 的真实文件引用。这样后续 provider materialization 和 fill simulation 可以分别审查，不把数据输入边界和交易逻辑混在同一轮。

本轮仍不实现 provider fetch、缓存生成、limit-up matching、order fill、stop/take-profit/time-stop execution 或 portfolio accounting。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_backtest_execution tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
```

### 验证结果

- `tests.execution.test_backtest_execution`：8 tests passed。
- `tests.schema.test_execution_price_data_schema`：5 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- 总计 16 tests passed；runner 在有/无 `--price-data` 两条路径都继续输出 schema-valid report。

### 失效旧结论

- “`inputs.price_data.path` 只能是 `not_available_phase5_skeleton` 占位值”已失效；传入 `--price-data` 时可写入真实 schema-validated 文件引用。
- “runner 完全不消费 `execution_price_data` 契约”已失效；当前已做契约读取、schema 校验和最小语义校验。

### 下一步注意事项

1. 让 Claude 审查本轮 loader wiring diff。
2. 通过并提交前，不实现 provider fetch 或 fill simulation。
3. 后续 provider materialization 应生成满足 `execution_price_data` 的真实文件；fill simulation 应在其后单独实现 entry/exit 事件、涨停不可买、止损、时间止损和组合约束。

## 2026-05-26 追加：execution price data loader review fix

### 改了什么

- 处理 Claude 对 loader wiring 的 1 条 Optional suggestion。
- `validate_price_data_semantics()` 新增 row-level coverage 校验：`execution_price_data.rows` 必须包含每个 `analysis_input` candidate 在 `--as-of` 当天的 `(ts_code, trade_date)` 行。
- `tests/execution/test_backtest_execution.py` 新增 `test_price_data_rows_must_cover_candidates_on_as_of`，覆盖 `symbols` 完整但 `rows` 缺失某 candidate 的错误路径。

### 为什么改

只检查 `symbols` 和 `date_range` 不足以保证 loader 边界完整：一个 price file 可以声明覆盖某股票和日期范围，但实际 `rows` 缺失该股票在 `--as-of` 的价格观测。若推迟到 fill stage 才报错，会把数据缺失误诊为撮合逻辑问题。本轮把该错误提前收敛到 loader。

本轮仍不实现 provider fetch、缓存生成、fill simulation、止损止盈、时间止损或组合记账。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_backtest_execution tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
```

### 验证结果

- `tests.execution.test_backtest_execution`：9 tests passed。
- `tests.schema.test_execution_price_data_schema`：5 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- 总计 17 tests passed。

### 失效旧结论

- “loader 只检查 date_range + symbols 覆盖”已失效；现在还检查每个候选在 `--as-of` 的 row-level 覆盖。

### 下一步注意事项

1. 让 Claude 复审本轮 Optional disposition。
2. 通过并提交前，仍不实现 provider fetch 或 fill simulation。
3. 后续 provider materialization 必须生成 candidate/as_of 可用的 row-level price observations。

## 2026-05-26 追加：execution price data CSV materializer

### 改了什么

- 新增 `runners/materialize_execution_price_data.py`，把本地 OHLC CSV 转成 schema-valid `execution_price_data` JSON。
- CSV 输入要求包含 `ts_code`、`trade_date`、qfq OHLC、`pre_close_qfq`、`adj_factor`、`up_limit`、`down_limit`；`source_flags` 可选，缺省为 `daily,adj_factor,stk_limit`。
- 输出默认落到 `result/a_short/backtest/execution/price_data/execution_price_data_<as_of>.json`，也可用 `--out-path` 指定。
- 新增 `tests/execution/test_materialize_execution_price_data.py`，覆盖 schema-valid 输出、symbol filter、缺必填 CSV 列错误。
- 更新 `docs/CURRENT.md` 与 `runners/README.md`，把当前 P0 切到 CSV materializer 审查。

### 为什么改

`be68abe` 已让 execution runner 能消费 `execution_price_data` JSON。下一步不应直接混入真实 Tushare fetch 或 fill simulator，而是先建立一个可审查的 provider-boundary materializer：后续真实 provider 只要产出同一契约，runner 和 fill 阶段就不用关心数据来源。

本轮仍不实现 Tushare fetch、缓存生成、limit-up matching、order fill、stop/take-profit/time-stop execution 或 portfolio accounting。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_materialize_execution_price_data tests.execution.test_backtest_execution tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
git diff --check
```

### 验证结果

- `tests.execution.test_materialize_execution_price_data`：5 tests passed。
- `tests.execution.test_backtest_execution`：9 tests passed。
- `tests.schema.test_execution_price_data_schema`：5 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- 总计 22 tests passed。
- `git diff --check` 通过。

### 失效旧结论

- “下一步是 provider materialization 或 fill simulation 二选一”需要细化：当前已先落地 local CSV materializer 作为 provider-boundary step；真实 Tushare fetch 和 fill simulation 仍未开始。
- “没有工具能生成 `execution_price_data` JSON”已失效；现在可由本地 CSV materializer 生成并交给 `backtest_execution.py --price-data` 验证引用。

### 下一步注意事项

1. 让 Claude 审查本轮 materializer diff。
2. 通过并提交前，不实现真实 Tushare fetch 或 fill simulation。
3. 后续真实 provider materialization 应复用同一 `execution_price_data` 契约；fill simulation 再单独实现 entry/exit、涨停不可买、止损、时间止损和组合约束。

## 2026-05-26 追加：execution price data CSV materializer review fixes

### 改了什么

- 处理 Claude 对 CSV materializer 的 5 条 active Optional suggestion。
- O1：`is_trade_day=false` 现在在 materializer 层抛出明确 `ValueError`，说明 `execution_price_data` rows 只允许交易日价格观测，非交易日由 `trade_cal` lineage 表达。
- O2：补充 `parse_symbols()` 和默认 `output_path()` 测试，覆盖 CLI-facing 的 symbol 去重/空值处理和默认输出路径。
- O3：`materialize_payload()` 新增 `source_csv_path`，CLI 输出的 `limitations` 会记录源 CSV 路径，便于 audit 追溯。
- O4：先按 raw `ts_code` 过滤 selected symbols，再做 float/flag/trade-day build，避免 `--symbols` 只选少数标的时无谓解析整表。
- O5：新增 `CSV_API_FAMILIES` 常量，避免 `source.api_families` 与 `DEFAULT_SOURCE_FLAGS` 风格不一致。
- O6 仍按 Claude review 结论保留为 `docs/CURRENT.md §P2` 后续 cleanup，本轮不做 shared util 重构。

### 为什么改

这些 Optional 都是 materializer 边界内的低成本加固：让坏 CSV 更早给出可读错误，让输出文件有源 CSV 追溯，让 CLI 行为被测试锁住，并减少后续 provider materializer 扩大输入规模时的无谓解析。O6 涉及跨 runner helper 抽取，属于更大重构，继续留到后续 cleanup。

本轮仍不实现真实 Tushare fetch、缓存生成、fill simulation、止损止盈、时间止损或组合记账。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_materialize_execution_price_data tests.execution.test_backtest_execution tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
git diff --check
```

### 验证结果

- `tests.execution.test_materialize_execution_price_data`：9 tests passed。
- `tests.execution.test_backtest_execution`：9 tests passed。
- `tests.schema.test_execution_price_data_schema`：5 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- 总计 26 tests passed。
- `git diff --check` 通过。

### 失效旧结论

- “CSV materializer Optional O1-O5 pending”已失效；当前已由 Codex 全部处理。
- “`is_trade_day=false` 只能由 JSON Schema 报 const 错”已失效；现在 materializer 会给出 CSV 语义错误。
- “materialized JSON 无源 CSV 路径追溯”已失效；CLI 现在写入 `limitations`。

### 下一步注意事项

1. 让 Claude 复审本轮 Optional disposition diff。
2. 通过并提交前，不实现真实 Tushare fetch 或 fill simulation。
3. 后续若处理 O6，应单独做 shared util cleanup，不要混入 provider fetch 或 fill simulator。

## 2026-05-26 追加：execution price data Tushare materializer

### 改了什么

- 新增 `runners/materialize_execution_price_data_tushare.py`，从 Tushare `daily` / `adj_factor` / `stk_limit` / `trade_cal` 生成 schema-valid `execution_price_data` v1.0.0 JSON。
- CLI 支持：
  - `--as-of`
  - `--analysis-input`（默认 `result/a_short/<as-of>/analysis_input.json`，用于推导 symbols）
  - `--symbols`（覆盖 analysis_input symbols）
  - `--start-date` / `--end-date` / `--calendar-days`
  - `--cache-dir` / `--refresh`
  - `--out-path`
- 输出仍默认落到 `result/a_short/backtest/execution/price_data/`；provider cache 默认落到 `result/a_short/backtest/cache/execution_price_data/`。
- 生成的 OHLC 与 limit 字段采用同一口径：raw price × same-day `adj_factor`，保持 qfq 价格与涨跌停价可比较。
- 新增 `tests/execution/test_materialize_execution_price_data_tushare.py`，用 fake Tushare client 覆盖 schema-valid payload、缺 as_of row 错误、analysis_input symbols、date range、cache path、cache roundtrip、cache request-mismatch 校验、CLI cache reuse。
- `.gitignore` 新增 `result/*/backtest/execution/`，避免 provider/materializer 输出被误纳入 GitHub backup。
- 更新 `docs/CURRENT.md` 与 `runners/README.md`，把 P0 切换为 Claude 审查 Tushare provider materializer。

### 为什么改

CSV materializer 已验证 `execution_price_data` 契约和 runner loader 边界。下一步应把 data source 从 CSV fixture 换成真实 Tushare provider，同时继续保持 provider-boundary scope：只产出价格数据契约，不混入 entry/exit、涨停不可买、止损、时间止损或组合记账。这样 fill simulator 后续可以基于稳定、真实来源的价格输入单独审查。

本轮仍不改 `schemas/execution_price_data.schema.json`，不改 `runners/backtest_execution.py` 的撮合逻辑，不实现 fill simulation。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_materialize_execution_price_data_tushare tests.execution.test_materialize_execution_price_data tests.execution.test_backtest_execution tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
git diff --check
```

### 验证结果

- `tests.execution.test_materialize_execution_price_data_tushare`：8 tests passed。
- `tests.execution.test_materialize_execution_price_data`：9 tests passed。
- `tests.execution.test_backtest_execution`：9 tests passed。
- `tests.schema.test_execution_price_data_schema`：5 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- 总计 34 tests passed。
- `git diff --check` 通过。

### 失效旧结论

- “真实 Tushare provider materializer 尚未开始”已失效；当前已实现待审。
- “Phase 5 只能通过 CSV fixture 生成 `execution_price_data`”已失效；现在有 CSV 与 Tushare 两个 materializer，共用同一 schema contract。

### 下一步注意事项

1. 让 Claude 审查本轮 Tushare provider materializer diff。
2. 通过并提交前，不实现 fill simulation。
3. 后续 fill simulation 应消费 schema-valid `execution_price_data`，单独实现 entry/exit、涨停不可买、止损、时间止损和组合约束。

## 2026-05-26 追加：execution price data Tushare materializer review fixes

### 改了什么

- 处理 Claude 对 Tushare materializer 的 6 条 active Optional suggestion。
- O1 accept：`build_payload_from_tushare()` 在读取 `trade_cal` 后先检查 `--as-of` 是否为交易日；非交易日现在抛出明确错误，而不是退化成“缺 as_of price row”。
- O2 accept：`_pin_tushare_base_url()` 无法设置 Tushare client 私有 URL 属性时改为 hard fail，避免用户配置 `TUSHARE_BASE_URL` 后静默打到默认公网 endpoint。
- O3 accept：Tushare materializer 的 row-level `source_flags` 固定包含 `daily` / `adj_factor` / `stk_limit`，表示已调用 API family lineage；即使具体行没有涨跌停字段，也不把 lineage 解释成字段非空状态。
- O4 accept：删除 `getattr(row, "up_limit", None)` 式冗余防御，直接使用 merge 后保证存在的 `row.up_limit` / `row.down_limit`。
- O5 accept with modification：新增缺 `TUSHARE_TOKEN`、`--refresh` 绕过 cache、`--symbols` 覆盖 analysis_input、跨月/跨年 `add_calendar_days()`、非交易日 as_of 的测试；未覆盖 `ts_call` retry path，因为该路径保留为环境绑定防御分支。
- O6 accept：把 `FakeTusharePro` 改成 dict-backed fixture，降低测试读者理解成本。
- `docs/CURRENT.md §P2` 的 shared-util cleanup followup 补入本轮 archived A1-A3 范围：materializer 重复 helper、Tushare retry helper、Tushare client 初始化/base URL pinning。

### 为什么改

这些修改都在 provider-boundary scope 内：让错误更早、更可读，并把 lineage 语义固定为“调用过哪些 API family”，而不是“某行哪些字段非空”。同时补齐 CLI/cache/token 关键路径测试，为后续真实运行和 fill simulator 消费 price data 降低误诊风险。

本轮仍不改 `schemas/execution_price_data.schema.json`，不改 `runners/backtest_execution.py`，不实现 fill simulation、止损止盈、时间止损或组合记账。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_materialize_execution_price_data_tushare tests.execution.test_materialize_execution_price_data tests.execution.test_backtest_execution tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
git diff --check
```

### 验证结果

- `tests.execution.test_materialize_execution_price_data_tushare`：12 tests passed。
- `tests.execution.test_materialize_execution_price_data`：9 tests passed。
- `tests.execution.test_backtest_execution`：9 tests passed。
- `tests.schema.test_execution_price_data_schema`：5 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：3 tests passed。
- 总计 38 tests passed。
- `git diff --check` 通过。

### 失效旧结论

- “Tushare provider materializer initial review Optional O1-O6 pending”已失效；当前已由 Codex disposition 并落地。
- “Tushare row `source_flags` 可根据涨跌停字段是否非空省略 `stk_limit`”已失效；当前语义按 API family lineage 处理。
- “缺 token path 未测试 / `--refresh` 未测试 / `--symbols` override 未测试”已失效；当前已有单测覆盖。

### 下一步注意事项

1. 让 Claude 复审本轮 Optional disposition diff。
2. 通过并提交前，不实现 fill simulation。
3. 提交后下一条大 scope 才是 fill simulation 起步：entry/exit、涨停不可买、止损、时间止损和组合约束。

## 2026-05-26 追加：capital allocation preflight

### 改了什么

- 新增 `docs/portfolio_allocation_policy.md`，作为 P0c 资金分配与流动资金使用规则草案。
- 将 Phase 5 下一步从“直接起步 fill simulation”改为“先解决或显式编码 P0c 决策，再做 P0a capital context contracts”。
- 更新 `docs/CURRENT.md`，让后续 LLM 明确：fill simulation 不能基于单一总账户 `initial_capital` 直接开写。

### 为什么改

用户已明确每个市场内部采用 `1/3 长线 + 1/3 短线 + 1/3 流动资金`。现有 `execution_backtest_report` v1.0.0 和 `backtest_execution.py` 仍主要围绕 run-level `initial_capital` 和普通 `position_sizing` 表达资金。若先写 fill simulation，会把“单账户本金”假设锁进执行回测，后续再接长短线 bucket、流动资金和跨市场资金规则时需要返工。

本次只落地决策草案，不写 schema、不改 runner、不实现撮合，避免把尚未确认的投资政策误编码为运行时默认值。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['docs/portfolio_allocation_policy.md','docs/CURRENT.md','docs/handoff/2026-05-25_phase5_kickoff_spec_handoff.md','docs/SESSION_LOG.md']; [Path(f).read_text(encoding='utf-8') for f in files]; print('utf8 ok')"
git diff --check
git status --short
```

### 验证结果

- `utf8 ok`
- `git diff --check` 通过
- `git status --short` 只显示本次文档 scope 相关文件

### 失效旧结论

- `docs/CURRENT.md` 旧口径“Next P0: start fill simulation as a separate Phase 5 scope”失效。
- Phase 5 fill simulation 仍是核心目标，但必须排在 P0a capital context contracts 之后。

### 下一步注意事项

1. 不要在 P0a 前实现 fill simulation。
2. P0a 应拆清静态政策、动态 cash state、execution report runtime snapshot，不能把 `capital_context` 当成政策源头。
3. `A = 50% / US = 50%` 只能作为待确认的中性规划假设，不能无声写成代码默认值。
4. 后续 schema 和 runner 需要显式 capital input path，否则 report 中的 `capital_context` 不可复现。
5. P0a 可先把 liquidity strictness 设为 `hard_floor` 起步默认；长线调用 liquidity 条件先 reserve 字段，等长线 spec 建立后再补 enum 值。

## 2026-05-26 追加：P0c user-confirmed capital decisions

### 改了什么

- `docs/portfolio_allocation_policy.md` 从 P0c 决策草案更新为用户确认决策。
- `AGENTS.md` 记录顶层资金比例、跨市场 cash 默认不互通、多 metric AND ship gate，以及“分析筛选 + 手动下单、不做自动下单”的执行边界。
- `docs/CURRENT.md` 更新当前目标：P0c 用户决策已确认，下一步是 P0a capital context contracts。

### 为什么改

用户确认了 P0a 需要的关键资金政策：

- 顶层市场资金比例：`A = 35%`、`US = 65%`。
- A 股 cash 与美股 cash 默认不互通。
- full-size 手动实盘使用采用多 metric AND ship gate：monthly alpha t-stat ≥ 2.0、Sharpe ≥ 1.0、max drawdown ≤ 15%、forward live data ≥ 12 个月。
- 系统只用于分析筛选、回测复盘和报告；用户手动下单，不接券商、操作系统或自动化工具自动下单。

这使 P0a 可以不再用 `50/50` 占位，也不需要在跨市场 cash 和 ship gate 上继续 pending。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['AGENTS.md','docs/portfolio_allocation_policy.md','docs/CURRENT.md','docs/handoff/2026-05-25_phase5_kickoff_spec_handoff.md','docs/SESSION_LOG.md']; [Path(f).read_text(encoding='utf-8') for f in files]; print('utf8 ok')"
git diff --check
git status --short
```

### 验证结果

- `utf8 ok`
- `git diff --check` 通过
- `git status --short` 只显示本次文档 scope 相关文件

### 失效旧结论

- “`A = 50% / US = 50%` 是中性规划假设”已失效；用户确认 `A = 35% / US = 65%`。
- “A/US cash 互通仍待确认”已失效；用户确认默认不互通。
- “ship gate 阈值仍待确认”已失效；用户确认多 metric AND gate。
- 任何把 Phase 5 解释为自动下单或 live order execution engine 的方向均失效。

### 下一步注意事项

1. P0a 可以开始设计 `portfolio_allocation` / `cash_buffer_state` / `execution_report.capital_context` 契约。
2. P0a 必须保留 manual-order boundary；不得新增 broker / OS 自动下单接口。
3. Execution backtest 输出用于评估手动交易计划、风险约束和 full-size gate，不用于自动执行交易。

## 2026-05-26 追加：P0c user-confirmed decisions optional disposition

### 改了什么

- 修正 `AGENTS.md` 中 Phase 6 口径：一个季度 closed-loop 是 forward/paper 或 minimal-size 手动观察，不等于 full-size ship gate。
- 在 `docs/portfolio_allocation_policy.md` 明确 bucket 比例是 within-market percentage，并补充 A 股 long bucket 的 total portfolio 示例。
- 在 `docs/portfolio_allocation_policy.md` 明确实际 cash 调拨由用户手动执行，系统只生成 signal / recommendation。
- 在 `docs/CURRENT.md` 标注 Phase roadmap 是否重排是单独用户决策；P0a 仍应一次性设计四个 preset 的 capital/bucket 契约。

### 为什么改

Claude review 指出 4 条 Optional 文档风险：

- Phase 6 “实盘一个季度”会与 full-size ship gate 的 ≥12 个月 forward data 冲突。
- “申请 liquidity”容易被误读成系统自动调拨资金。
- `33.3333%` bucket target 未明说是市场内部比例，P0a schema 设计时可能误当 total portfolio 比例。
- 已固化决策 #10 的“四套子系统同等重要”与旧 Phase 表中长线最后实现有潜在冲突，但路线图重排超出本轮 decision-recording scope。

本轮处理前三条为文档修复；第四条只记录为待用户决策，不直接重排 Phase 表。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['AGENTS.md','docs/portfolio_allocation_policy.md','docs/CURRENT.md','docs/handoff/2026-05-25_phase5_kickoff_spec_handoff.md','docs/SESSION_LOG.md']; [Path(f).read_text(encoding='utf-8') for f in files]; print('utf8 ok')"
git diff --check
git status --short
```

### 验证结果

- `utf8 ok`
- `git diff --check` 通过
- `git status --short` 只显示本次文档 scope 相关文件

### 失效旧结论

- “Phase 6 一季度实盘 = full-size ship 放行”失效；Phase 6 只是工程闭环 / paper / minimal-size 手动观察。
- “系统可以自动调拨 cash bucket”失效；系统只生成建议，实际资金调拨由用户手动执行。
- “bucket target 可能是 total portfolio percentage”失效；bucket target 是 within-market percentage。

### 下一步注意事项

1. P0a 设计四个 preset 的 bucket/capital ceiling 字段，避免未来长线接入时 schema breaking。
2. Phase 路线图是否重排仍需用户单独决定；本轮未改 AGENTS.md Phase 表顺序。
3. 不要把 manual-order boundary 误解为 live order execution engine。

## 2026-05-26 追加：roadmap B semi-reorder

### 改了什么

- `AGENTS.md` 执行路线图改为用户采纳的 B 半重排：
  - Phase 5 = P0a capital context contract + A 股短线 execution/fill 回测。
  - Phase 5b = ship gate policy + preliminary gate status；full-size 仍需 ≥12 个月 forward live data。
  - Phase 6 = A 股短线一季度 forward/paper 或 minimal-size 手动观察，同时产出 A 股长线 spec、美股长线 spec，并规范化美股短线 spec。
  - Phase 7 = DataHub / engine 模块化重构，以 4 套 spec 划分共享层与独立 rule pack。
  - Phase 8 = 美股短线 implementation + 美股长线 implementation skeleton。
  - Phase 9 = A 股长线 implementation；可按数据准备度与 Phase 8 子项交换顺序。
- `AGENTS.md` 已固化决策新增路线图决策 #12。
- `docs/CURRENT.md` 删除“路线图是否重排待决策”的旧状态，改为“B 半重排已固化；P0a 仍只做 capital context contract，但必须覆盖四个 preset”。

### 为什么改

用户在 P0c 之后确认：A 股和美股都采用长线 1/3、短线 1/3、流动资金 1/3 的市场内 bucket 结构，且四套子系统都是真实需求。旧路线图把长线整体推到 Phase 9，容易让 Phase 7 引擎重构在缺少长线 spec 的情况下短线化。

B 半重排保留两条既定约束：A 股短线仍先完成 Phase 6 一季度观察，Phase 7 仍是美股扩展和共享引擎的硬前置；同时提前输出长线 spec，让 Phase 7 的共享层 / 独立层划分有依据。

本轮只落文档，不写 schema、不改 runner、不提前实现长线。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['AGENTS.md','docs/CURRENT.md','docs/handoff/2026-05-25_phase5_kickoff_spec_handoff.md','docs/SESSION_LOG.md']; [Path(f).read_text(encoding='utf-8') for f in files]; print('utf8 ok')"
git diff --check
git status --short
```

### 验证结果

- `utf8 ok`
- `git diff --check` 通过
- `git status --short` 只显示本次 roadmap 文档 scope 相关文件

### 失效旧结论

- “Phase roadmap follow-up 仍待用户决策”失效；用户已采纳 B 半重排。
- “Phase 7 可以只基于 A 股短线 / 美股短线视角拆 shared engine”失效；Phase 7 应以 4 套 spec 作为共享层与独立 rule pack 的划分依据。
- “长线只有到 Phase 9 才开始任何设计”失效；长线 implementation 仍在后面，但 A 股长线 / 美股长线 spec 应在 Phase 6 与 A 股短线观察并行输出。

### 下一步注意事项

1. 下一条执行仍是 P0a capital context contracts，不是长线 spec，也不是 fill simulation。
2. P0a 应一次性覆盖 `a_short` / `us_short` / `a_long` / `us_long` 的 capital/bucket contract；但可以把长线策略细节 enum 保留为空数组或 reserved 字段，等长线 spec 完成后填充。
3. Phase 5b 的 ship gate status 只能给 preliminary gate status；full-size manual use 仍必须满足 ≥12 个月 forward live data。

## 2026-05-26 追加：roadmap data-readiness example

### 改了什么

- 处理 Claude 对 roadmap B semi-reorder 的 O1 Optional。
- `AGENTS.md` 决策 #12 补充“数据准备度”的非硬性示例：若 US provider 已能稳定提供 10-K、FCF、guidance、估值等长线维度，可优先推进 US 长线 skeleton / implementation；否则按默认顺序先做 US 短线。
- `docs/CURRENT.md` 增加交叉引用，提示 Phase 8/9 子项交换看 `AGENTS.md` #12 的示例，不把它误读成严格门槛。

### 为什么改

原路线图允许 Phase 8 子项与 Phase 9 按“数据准备度”交换顺序，但没有说明数据准备度的判断维度。这样会让后续 LLM 不确定是看 US provider 长线数据能力、A 股短线 forward 样本量，还是其他条件。

本轮选择接受 Claude O1，但只给示例，不写 strict criteria。原因是当前还没有长线 spec，也没有 US provider 首版；硬编码门槛会过早约束 Phase 8/9 的实际排序。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['AGENTS.md','docs/CURRENT.md','docs/handoff/2026-05-25_phase5_kickoff_spec_handoff.md','docs/SESSION_LOG.md']; [Path(f).read_text(encoding='utf-8') for f in files]; print('utf8 ok')"
git diff --check
git status --short
```

### 验证结果

- `utf8 ok`
- `git diff --check` 通过
- `git status --short` 只显示本次 roadmap 文档 scope 相关文件

### 失效旧结论

- “数据准备度可以完全留空解释”失效；现在至少有 US 长线 provider 维度作为示例。
- “数据准备度需要在当前阶段写成 strict criteria”不成立；当前只保留示例，具体门槛等 US provider / 长线 spec 明确后再定。

### 下一步注意事项

1. 让 Claude 复查 O1 disposition。
2. 本轮仍不写 schema、不改 runner、不启动长线 spec。
3. 通过并提交后，下一步仍是 P0a capital context contracts。

## 2026-05-26 追加：P0a capital context contracts

### 改了什么

- 新增 `schemas/portfolio_allocation.schema.json` v1.0.0，作为静态资金政策源头：
  - A 股 / 美股顶层比例固定为 `35% / 65%`。
  - 每个市场内部 long / short / liquidity bucket 固定为 `0.333333 / 0.333333 / 0.333333`。
  - A/US cash 默认不互通，跨市场转移为 `manual_only_non_fungible`。
  - ship gate 固定为多 metric AND：monthly alpha t-stat ≥ 2.0、Sharpe ≥ 1.0、max drawdown ≤ 15%、forward live data ≥ 12 个月。
  - execution boundary 固定为 manual-order-only，不允许 broker / OS automation。
- 新增 `schemas/cash_buffer_state.schema.json` v1.0.0，作为动态 per-market cash/bucket state：
  - `portfolio_policy_ref` 指向静态政策。
  - A/US 各自记录 market capital、long/short/liquidity bucket capital、cash buffer、drawdown state、rebalance metadata。
  - `state_management.atomic_write_required = true`，writer 指向 `engine.analyzer.state_manager.atomic_write_json`。
- `schemas/execution_backtest_report.schema.json` 升级 v1.0.0 -> v1.1.0：
  - 新增 required `capital_context` runtime snapshot。
  - `settings.initial_capital` 的语义改为 selected bucket capital，不再是 total account capital。
  - `execution_assumptions.position_sizing` 新增 `capital_basis = bucket_capital` 和 `bucket_ceiling_pct`。
- `runners/backtest_execution.py` 新增：
  - `--portfolio-allocation` required input。
  - `--cash-buffer-state` required input。
  - schema validation for both inputs。
  - `build_capital_context()`，从 policy + cash state 生成 A-short bucket-aware capital context。
  - `--initial-capital` 变为 optional guard；如果传入，必须等于 selected bucket capital。
- 4 个 preset 同步新增 `capital` block：`market` / `horizon` / `bucket` / `capital_basis` / `bucket_target_pct` / `bucket_ceiling_pct` / `portfolio_allocation_policy`。
- 新增 fixtures 和测试：
  - `tests/fixtures/portfolio_allocation_minimal.json`
  - `tests/fixtures/cash_buffer_state_minimal.json`
  - `tests/schema/test_capital_context_schemas.py`
  - 扩展 `tests/schema/test_execution_backtest_report_schema.py`
  - 扩展 `tests/execution/test_backtest_execution.py`

### 为什么改

P0a 是 fill simulation 的硬前置。没有静态资金政策、动态 cash state 和 execution report 的 runtime capital snapshot，fill simulator 会继续把单一 `initial_capital` 当作总账户本金，从而把错误资金模型锁进执行回测。

本轮把资金契约拆成三层：

- `portfolio_allocation` = 静态政策源头。
- `cash_buffer_state` = 动态状态源头。
- `execution_backtest_report.capital_context` = 本次 run 的可复现快照，不是政策源头。

同时保留 scope 边界：本轮不实现 entry/exit 撮合、涨停不可买、止损、时间止损、组合 accounting、长线 spec 或 Phase 7 DataHub 重构。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_capital_context_schemas tests.schema.test_execution_backtest_report_schema tests.execution.test_backtest_execution -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_materialize_execution_price_data_tushare tests.execution.test_materialize_execution_price_data tests.execution.test_backtest_execution tests.schema.test_capital_context_schemas tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -v
git diff --check
```

### 验证结果

- `tests.schema.test_capital_context_schemas`：2 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：4 tests passed。
- `tests.execution.test_backtest_execution`：11 tests passed。
- P0a focused total：17 tests passed。
- Broader Phase 5 suite：43 tests passed。
- Full unittest discover：78 tests passed。
- `git diff --check`：通过。

### 失效旧结论

- “`execution_backtest_report` 当前版本为 v1.0.0”失效；当前 contract 为 v1.1.0。
- “runner 可只用 run-level `--initial-capital` 生成 execution report”失效；现在必须显式传入 `--portfolio-allocation` 和 `--cash-buffer-state`。
- “`position_sizing` 只需要 max_position_pct / max_positions / cash_constrained”失效；现在还必须声明 `capital_basis = bucket_capital` 与 `bucket_ceiling_pct`。
- “4 个 preset 还没有 capital/bucket 契约字段”失效；当前已同步声明。

### 下一步注意事项

1. 让 Claude 审查 P0a contract diff，重点看三层资金契约是否职责分明、runner 是否仍未实现 fill simulation、`settings.initial_capital` 是否会被误读。
2. 通过并提交后，下一步才是 Phase 5 fill simulation：entry/exit、涨停不可买、止损、时间止损、组合约束。
3. 后续若处理真实 cash state 写入，应复用 `engine.analyzer.state_manager.atomic_write_json`，不要直接写文件。

## 2026-05-26 追加：P0a Optional disposition O1-O3

### 改了什么

- O1 accepted：`runners/backtest_execution.py` 不再使用 hardcoded `PRESET_CAPITAL_PROFILES`。
  - 新增 `--preset-path`，默认读取 `presets/a_short.yaml`。
  - runner 从 preset YAML 的 `capital` block 读取 `preset` / `market` / `horizon` / `bucket` / `bucket_target_pct` / `bucket_ceiling_pct` / `portfolio_allocation_policy`。
  - runner 将 preset YAML 与 `portfolio_allocation` / `cash_buffer_state` 做 cross-validation，防止 preset、policy、state 三者漂移。
- O2 accepted：删除 `schemas/portfolio_allocation.schema.json` 中 `bucketAllocation.horizon`，并从 `tests/fixtures/portfolio_allocation_minimal.json` 删除对应字段。
- O3 accepted：`portfolio_allocation` 里的单值 policy enum 改为 `const`：
  - `cross_market_transfer_policy`
  - `capital_basis`
  - `floor_policy`
  - `cross_market_cash_default`
  - `short_circuit_breaker_liquidity_use`
  - `logic`
  - `failure_mode`
- 新增/更新 regression：
  - `tests.execution.test_backtest_execution.test_preset_yaml_drives_capital_profile`
  - `tests.schema.test_capital_context_schemas` 检查 `bucketAllocation.horizon` 已移除、单值 policy 使用 `const`。

### 为什么改

Claude 首轮审查已 Pass，但指出 3 个 schema/contract hygiene 风险：

- hardcoded preset map 与 preset YAML 双源会在未来 preset 调整时 drift。
- `bucketAllocation.horizon` 与 `bucket` 完全同义，且 schema 无法保证一致。
- 单值 enum 看起来像可扩展枚举，但当前政策是明确锁死，`const` 更清晰。

本轮只做 Optional disposition，不实现 fill simulation，不改 provider materializer，不改 EGS/analyzer，不启动长线 spec。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.schema.test_capital_context_schemas tests.schema.test_execution_backtest_report_schema tests.execution.test_backtest_execution -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_materialize_execution_price_data_tushare tests.execution.test_materialize_execution_price_data tests.execution.test_backtest_execution tests.schema.test_capital_context_schemas tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -v
git diff --check
```

### 验证结果

- P0a focused total：18 tests passed。
- Broader Phase 5 suite：44 tests passed。
- Full unittest discover：79 tests passed。
- `git diff --check`：通过。

### 失效旧结论

- “runner 依赖 `PRESET_CAPITAL_PROFILES` 映射 4 套 preset”失效；当前 runner 从 `--preset-path` 读取 preset YAML。
- “`portfolio_allocation` bucket row 同时需要 `bucket` 和 `horizon`”失效；当前静态政策只保留 `bucket`，horizon 属于 preset/report 身份字段。
- “单值 enum 可继续作为锁死 policy 表达”失效；当前锁死 policy 统一使用 `const`。

### 下一步注意事项

1. 让 Claude 复审 O1-O3 disposition，重点看 preset YAML parser 与 cross-validation 是否足够窄、`horizon` 删除是否未破坏 report `capital_context.horizon`。
2. 通过并提交后，下一步才是 Phase 5 fill simulation。
3. 不要把 `--preset-path` 理解成多 preset 批量执行；当前 runner 默认仍是 A-short skeleton，只是把 capital profile source of truth 移到 preset YAML。

## 2026-05-26 追加：Phase 5 minimal fill simulation

### 改了什么

- `runners/backtest_execution.py` 在传入 `--price-data` 时不再只引用价格文件，而是执行最小 daily-OHLC fill simulation：
  - candidate 先过 Phase 3 Rule 6 analyzer hard veto replay。
  - 入场使用 T+1 `open_qfq`。
  - 若 T+1 `open_qfq` 接近/等于 `up_limit`，记为 `entry_unbuyable` 并跳过。
  - stop-loss 从 deterministic candidate 字段读取，当前 fallback 到 `technical.support.price`。
  - stop-loss 优先于 time-stop；后续交易日若 `open_qfq <= stop_loss`，按 open 出场，否则 daily `low_qfq <= stop_loss` 时按 stop price 退出。
  - time-stop 使用 `close_qfq` 退出。
  - 仓位按 `capital_context.bucket_capital`、`max_position_pct`、`max_positions`、现金约束和 A 股 100 股 lot sizing 计算。
  - entry/exit 均扣 `cost_pct`。
- `execution_report.json` 的 metrics / warnings / limitations 改为来自模拟结果。
- `trades.csv` / `daily_equity.csv` / `order_events.csv` / `skipped_candidates.csv` 写出真实模拟结果；不传 `--price-data` 时保留 skeleton skip 行为。
- `schemas/execution_backtest_report.schema.json` 的 event enum 补 `missing_price_data` 和 `cash_constrained`。
- `tests/fixtures/execution_price_data_minimal.json` 增加 T+1 价格行。
- 新增 regression 覆盖：
  - time-stop 正常成交且按 bucket sizing 买入 800 股。
  - stop-loss 优先于 time-stop。
  - 涨停开盘不可买。

### 为什么改

P0a 已把资金模型锁到 bucket capital；下一步必须让 execution backtest 从“契约 shell”前进到“最小可解释撮合”。本轮只做最小 daily-OHLC 模拟，确保后续扩展真实样本、组合持仓和 ship gate metrics 时不会回到 total-account `initial_capital` 假设。

本轮刻意不实现 provider fetch、Tushare materializer 修改、长线 spec、Phase 7 DataHub、券商/OS 自动下单。用户已确认系统只做分析筛选，后续交易仍手动执行。

另一个刻意保留的边界：这不是 full concurrent multi-position portfolio engine。第一版按候选顺序模拟、执行 bucket cash / 单票 sizing 约束，daily equity 只记录起点和已实现 exit 日期；持仓期间 mark-to-market 和并发持仓 accounting 留给后续 scope。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_backtest_execution tests.schema.test_execution_backtest_report_schema tests.schema.test_execution_price_data_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_materialize_execution_price_data_tushare tests.execution.test_materialize_execution_price_data tests.execution.test_backtest_execution tests.schema.test_capital_context_schemas tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -v
git diff --check
```

### 验证结果

- `tests.execution.test_backtest_execution`：15 tests passed。
- `tests.schema.test_execution_backtest_report_schema`：4 tests passed。
- `tests.schema.test_execution_price_data_schema`：5 tests passed。
- Targeted total：24 tests passed。
- Broader Phase 5 suite：47 tests passed。
- Full unittest discover：82 tests passed。
- `git diff --check`：通过。

### 失效旧结论

- “`--price-data` 只做 schema validate + report reference，不用于 fills”失效；当前传入 `--price-data` 会触发 minimal fill simulation。
- “`trades.csv` / `daily_equity.csv` / `order_events.csv` 只是 shell”部分失效；price-data path 下它们写真实模拟结果。无 price-data path 仍保留 skeleton skip 行为。
- “execution report limitations 可写 no fill simulation”失效；当前 price-data path limitations 必须说明 daily-OHLC 模拟边界，而不是说未实现撮合。

### 下一步注意事项

1. 让 Claude 审查本轮 minimal fill simulation + Optional disposition，重点看撮合顺序、stop-loss 优先级、bucket sizing、schema event enum 和 no-price-data fallback 是否一致。
2. 若 Pass，再提交；若 Required fixes 出现，只修用户批准的 Required items。
3. 下一轮不要马上做 full portfolio engine。更自然的下一个小 scope 是把真实 Tushare materializer 输出接到一个小样本 execution run，并补 execution-level ship-gate metric 输出字段。

## 2026-05-26 追加：Phase 5 minimal fill simulation Optional disposition O1-O5

### 改了什么

- O1 accepted with modification：修正 gap-down stop fill。
  - 若后续持仓日 `open_qfq <= stop_loss`，stop-loss 出场价用当日 open。
  - 若当日 open 仍高于 stop，但 `low_qfq <= stop_loss`，按 stop price 出场。
  - 没有采用“所有 low 触及都按 low 出场”，因为 daily OHLC 无法证明日内穿 stop 后一定成交在 low；用 open 处理真正 gap-down，用 stop 处理日内触发，更符合当前数据粒度。
- O2 accepted：stop 先独立解析，再显式要求 `stop_loss < entry_price`；若 T+1 open 已低于/等于 stop，跳过该 candidate，不产生 entry artifact。
- O3 accepted with modification：
  - 新增 `test_gap_down_stop_loss_fills_at_open`。
  - 新增 `test_entry_open_at_or_below_stop_is_skipped`。
  - 新增 `test_cash_constrained_candidate_is_skipped` 覆盖 cash-constrained event path。
  - 未实现“多候选并发持仓竞争”测试，因为当前 minimal fill scope 明确不建 concurrent multi-position accounting；这个点留给 full portfolio engine 阶段。
- O4 accepted：`limitations` 增加 `total_return = realized total_pnl / initial bucket_capital` 的说明，不新增 metric。
- O5 accepted：`execution_backtest_report.schema.json` 描述中明确 `event_log.event_codes` 是 v1.x grow-only，consumer 应 graceful handle unknown event codes，不升 schema version。

### 为什么改

Claude review 虽然 Pass，但 O1/O2 指向 stop-loss 价格和 entry pre-check 的 correctness 风险，会直接影响后续 ship gate 的 alpha / Sharpe / drawdown 可信度。本轮修正这些数值偏差，同时把 O4/O5 两个 contract 解释问题文档化。

本轮仍不改 provider materializer、不接真实 Tushare run、不做长线 spec、不做 Phase 7 DataHub、不做并发持仓 portfolio engine。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_backtest_execution tests.schema.test_execution_backtest_report_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.execution.test_materialize_execution_price_data_tushare tests.execution.test_materialize_execution_price_data tests.execution.test_backtest_execution tests.schema.test_capital_context_schemas tests.schema.test_execution_price_data_schema tests.schema.test_execution_backtest_report_schema -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -v
git diff --check
```

### 验证结果

- Execution + report schema subset：22 tests passed。
- Broader Phase 5 suite：50 tests passed。
- Full unittest discover：85 tests passed。
- `git diff --check`：通过。

### 失效旧结论

- “stop-loss 出场只要 low 触及就总是按 stop price”失效；后续持仓日若 open 已低于 stop，按 open 出场。
- “T+1 open 低于/等于 stop 可能进入再同日止损”失效；当前直接跳过，计入 missing_stop。
- “event enum 扩展是否应升 schema version 仍未说明”失效；当前已文档化 grow-only 策略。

### 下一步注意事项

1. 让 Claude 复审 O1-O5 disposition。
2. 若 Pass，用户可 `提交`。
3. 下一条 `执行` 仍应保持小 scope：优先把 Tushare materializer 输出接到一个小样本 execution run，并补 ship-gate metric 输出字段；不要直接启动 full portfolio engine。
