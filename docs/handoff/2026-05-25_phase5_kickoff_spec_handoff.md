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
