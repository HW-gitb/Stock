# Phase 4 kickoff spec handoff

**日期**：2026-05-25
**范围**：Phase 4 minimal Skill 启动规格
**状态**：实施中。schema v1.0.0、runner v1、coverage doc、Skill 使用文档、prompt 骨架、LLM enrichment patch schema 已落地；真实样本 smoke 待补。
**前置 handoff**：`docs/handoff/2026-05-24_phase3_kickoff_spec_handoff.md`（Phase 3 完整实施记录，含 audit fixes / 3.3 / 3.4 / 3.5）

---

## 1. 背景

Phase 3 全部子阶段完成：minimal analyzer + 4 条 hard veto + state stub + audit fixes + 比较口径修正 + 子分数预测力分析 + ESP 反向 PIT 调查 + 实盘 forward tracker。工程层 7/7 spec 完成线满足；策略层在 backtest 范围内能查的都查完了，剩下需要时间累积（实盘 12 期 / L3 PIT 6 月）。

Phase 4 启动决策：**不等数据累积**。理由：
- forward tracker（Phase 3.5）已自动后台累积，不需要主线等待
- Phase 4 minimal Skill 是 v14.2 内容首次工程化落地（30-40% 覆盖率），是 Phase 5/6 的 contract 基础
- AGENTS.md 已固化决策 #7："Skill 走渐进路线，第一版只做读 input、调 analyzer、出 M6.7，不追求自动批量"

---

## 2. 关键边界（用前一轮 reviewer 收紧后的版本，否决了一版较松的初稿）

### 2.1 Skill 不是执行入口，runner 才是

否决的初稿框架（**不要这样做**）：
- ❌ Skill 直接驱动 LLM 做单股分析、调 analyzer、出报告
- ❌ M6.7 输出是 LLM 自由文本格式
- ❌ Skill 作为唯一执行路径

正确框架：
- ✅ `runners/run_analysis_report.py` 是执行入口，**纯 Python**，不调 LLM
- ✅ Runner 读 `analysis_input.json` + 调 analyzer + 查 state，写 schema-validated JSON 报告
- ✅ Skill (`skills/a_short_analysis/SKILL.md`) 是 **使用文档**：告诉 AI 协作者如何 (a) 调 runner (b) 读输出 (c) 在哪些字段做 LLM enrich (d) enrich 结果如何合并回报告
- ✅ LLM enrich 是 **可选 enrichment 层**，不在 minimal v1

### 2.2 v1 必须本地可复现，无 LLM 也能跑

最小闭环 = `analysis_input.json` + analyzer + state + schema + JSON/Markdown 渲染。

LLM 判断（行业景气 / 48h 监管 / 政策解读 / 季报"无利好修复" / 隐蔽风险）作为 prompt section 提供，但 v1 runner 不调用它们。这些字段在报告里标 `unknown + requires_llm`，**绝不硬编默认值**。

为什么这一条这么硬：Phase 5 execution 回测要复现 Phase 4 输出来 simulate；如果 v1 就依赖 LLM，Phase 5 无法 deterministic 回放。

### 2.3 Phase 5 真正的 prerequisite 是 schema，不是 Skill

把这条写清楚是因为之前的初稿混淆了"phase 时序"和"contract 依赖"：

| 错误说法 | 准确说法 |
|---|---|
| Skill 是 Phase 5 prereq | **deterministic report schema** 是 Phase 5 prereq |
| Skill 写 M6.7 报告 | Runner 写 schema-validated 报告；Skill 描述怎么读它 |

Phase 5 execution 回测要拿 schema 字段做 deterministic simulate：从 `entry_plan.price` + `exit_plan.stop_loss` + `position_size.pct` 这些结构化字段读决策，不能从 LLM 自由文本提取。

---

## 3. M6.7 数据模型 vs 渲染层

v14.2 的 M6.7 是**渲染层**（人读的表格：标的/操作/股数/入盈一盈二损/类型/星级/触发条件）。Phase 4 需要**先建数据模型**，再从数据模型映射到 v14.2 表格。两层都要有。

### 3.1 数据模型（schema 核心字段）

报告对象顶级字段（命名向 Phase 2 backtest_report schema 看齐）：

```
schema_name: "deterministic_report"
schema_version: "1.0.0"          # SemVer; Phase 5 演进时升 minor
generated_at: ISO8601
preset: "a_short"
as_of: YYYYMMDD
ts_code: "600519.SH"
name: "贵州茅台"

# 核心决策结构
decision: {
  action: "buy" | "skip" | "watch" | "sell" | "reduce"
  reason_code: str               # 主要决策依据 code
  confidence: "high" | "medium" | "low" | "unknown"
}

# Phase 3 analyzer 输出原样写入
veto: {
  vetoed: bool
  reasons: [ ... ]                # run_veto 返回的 reasons 列表
  diagnostics: [ ... ]            # run_veto 返回的 diagnostics
  enabled_rules: [ ... ]
}

# 入场/出场计划（结构化、可被 Phase 5 simulate）
entry_plan: {
  price: float | null              # 建仓价
  condition: str                   # 入场条件描述
  type: "breakout" | "pullback" | "absorb" | "..."
  requires_llm: bool               # true = 需要 LLM enrich 才能给数值
}
exit_plan: {
  stop_loss: float | null
  take_profit_1: float | null
  take_profit_2: float | null
  time_stop_days: int | null
  requires_llm: bool
}
position_size: {
  shares: int | null
  pct_of_capital: float | null
  rationale: str
  requires_llm: bool               # M6.3 仓位公式在 Phase 5 才完整实现
}

# 风险与证据
risk_flags: [
  { code: str, severity: "info" | "warn" | "critical", source: "analyzer" | "egs" | "state" | "llm", detail: dict }
]
evidence: [
  { field_path: str, value: any, source: str }   # 报告关键判断的依据
]

# 显式未知项（v1 关键设计）
unknowns: [
  { field: str, reason: "requires_llm" | "requires_external" | "data_missing" | "not_implemented_phase4", note: str }
]

# LLM 自由文本（与 deterministic 部分严格分离）
llm_notes: {
  enabled: bool                    # v1 总是 false
  sections: [ ... ]                # M2.1 板块/M2.4 跨市场/M2.5 隐蔽风险 等
}

# Phase 2 工程纪律双件套
data_lineage: {
  egs_version: str                 # 来自 source.egs_version
  analyzer_rules: [ { code: str, version: int } ]
  state_snapshot_ref: str          # state/*.json 的 hash 或 timestamp
  analysis_input_schema_version: str
  generated_at: ISO8601
}
analyzer_invocations: [
  { code: str, version: int, status: "fired" | "passed" | "diagnostic", detail: dict }
]
```

### 3.2 渲染层（v14.2 M6.7 表格）

Runner 同时输出 Markdown，从数据模型字段映射到 v14.2 M6.7 表格列：

| 标的 | 操作 | 股数 | 入 / 盈一 / 盈二 / 损 | 类型 | 优先级 | 触发条件 |

- 标的 ← `ts_code + name`
- 操作 ← `decision.action`
- 股数 ← `position_size.shares` 或 `"待 Phase 5 仓位公式"` 若 requires_llm
- 入/盈一/盈二/损 ← `entry_plan.price / exit_plan.take_profit_1 / take_profit_2 / stop_loss`，缺数据标 `unknown`
- 类型 ← `entry_plan.type`
- 优先级 ← Phase 4 minimal 不计算星级（M5.4 LLM 判断），标 `"待 LLM enrich"`
- 触发条件 ← 从 `risk_flags + decision.reason_code + entry_plan.condition` 汇编

Markdown 报告还要包含 v14.2 §6.7 "精简结论区"（当前环境 / 波动率状态 / 现价与成本 / 否决审查触发 / 板块资金事件 / M6.6 风控触发 / 操作建议）以及 §6.5 风险提示清单。这些 v1 大多是 `unknown` 或从 analyzer 已知字段填，要诚实标记。

---

## 4. 启动顺序（schema first）

1. **`schemas/deterministic_report.schema.json` v1.0.0** — JSON Schema Draft 7；schema first
2. ✅ **`runners/run_analysis_report.py`** — CLI 入口
   - 参数：`--as-of YYYYMMDD --ts-code CODE [--out-dir]`
   - 读 `result/a_short/<as_of>/analysis_input.json` 找 candidate
   - 调 `engine.analyzer.rule6_hard_veto.run_veto(candidate)` 得 veto 决策
   - 调 `engine.analyzer.state_manager.has_position(ts_code) / is_circuit_breaker_active()` 查 state
   - 决定 `decision.action`：
     - vetoed → `skip`
     - circuit_breaker_active → `skip`
     - has_position → `watch`
     - 其它 → `watch`（v1 不做 `buy` 决策；buy 需要 Phase 5 的仓位公式 + 入场价计算）
   - 缺 LLM 判断的字段全标 `unknown + requires_llm`
   - 落盘前 JSON Schema 校验通过
3. ✅ **`schemas/deterministic_report_coverage.md`** — 类比 `schemas/analysis_input_coverage.md`，记录 v14.2 五段拆解里哪些已实现、哪些 `requires_llm` / `requires_external` / `not_implemented_phase4`
4. ✅ **`skills/a_short_analysis/SKILL.md`** — AI 协作者**使用文档**：
   - 怎么调 runner
   - 怎么读 JSON / Markdown
   - 哪些字段需要 LLM enrich + 如何调 prompts/
   - enrich 后如何把结果合并回报告（重新跑 runner + 提供 enrich JSON 作为补充输入）
5. ✅ **`skills/a_short_analysis/prompts/*.md`** — v14.2 各 LLM 判断子任务的 prompt 文件（M2.1 板块联动 / M2.4 跨市场 / M2.5 隐蔽风险 / 行业景气 / 48h 监管识别 / 政策新闻解读 / 季报"无利好修复"判断）。**v1 这些 prompt 文件可以先写骨架占位，不强制实现内容**——只要 SKILL.md 知道每个 LLM 子任务对应哪个 prompt 文件即可
6. **`tests/skill/test_run_analysis_report.py`** — at least one fixture end-to-end：
   - 拿 24p 里某个 as_of + ts_code 跑 runner
   - 验证 JSON 输出过 schema 校验
   - 验证 veto 字段与 `run_veto` 直接调用一致
   - 验证 Markdown 渲染含必要 sections

---

## 5. 输出位置（开工前需用户确认）

候选：
- `result/a_short/<as_of>/reports/<ts_code>.json` 和 `.md`
- `result/a_short/<as_of>/skill_reports/<ts_code>.json` 和 `.md`

AGENTS.md 现有边界："不写 `result/a_short/<YYYYMMDD>/`" 原意是不让回测产物污染实盘目录。Skill 输出是实盘 workflow 的一部分，应该可以放进实盘 as_of 目录。建议用 `reports/` 子目录避免与 EGS 已有的 `candidates.csv` / `analysis_input.json` / `snapshot.json` 混淆。

**开工前必须用户拍板**。

---

## 6. 明确排除（Phase 4 minimal 不做）

- LLM 自动联网搜索 / 新闻 / 监管识别 / 政策解读
- M0.5 觉醒检查的真实逻辑（state 仍是 stub）
- M3.3B IV/HV 偏离（Tushare 已知限制）
- M3.6 ATR-based 止损止盈位计算
- M6.3 完整仓位公式（5 日均分钟量 / 昨日量 / 单只 40% / 共振扣减）
- Rule 12 组合熔断的真实触发逻辑
- Rule 13 再入场冷静期的真实状态机
- M5.4 星级排序（防御期降星 / 突破型降星等）
- M5.5B 多因子风险模型（北向 / 融资 / 50ETF / 小市值四因子）
- 批量分析（v1 一次只跑一只票）

所有这些在数据模型里都有对应字段，v1 标 `unknown` + `not_implemented_phase4` 或 `requires_llm`，不硬编默认值。

---

## 7. Phase 5 / 6 依赖契约

Phase 5 execution 回测启动时，需要：
- 数据模型字段 `decision.action / entry_plan / exit_plan / position_size` 都已 schema 化、可直接读
- `analyzer_invocations` 可重放 audit 决策路径
- `data_lineage` 可验证报告生成时的 EGS / analyzer 版本

Phase 6 实盘 1 季度需要：
- M6.7 表格 Markdown 渲染可读（v14.2 §6.7 格式）
- `risk_flags + unknowns` 让人工 review 时清楚哪些维度 AI 没判断
- LLM enrich 路径已通（v1 可以不实现，但 SKILL.md 文档要明确路径）

---

## 8. 开工前必须用户确认的两件事

1. **数据模型字段范围**：上面 §3.1 列的字段是否够 minimal？是否漏关键字段（如盈亏比、持仓周期等）？
2. **输出目录**：`result/a_short/<as_of>/reports/` 还是别处？

确认后开工顺序按 §4 走，schema first，6 步落地，预估 3-5 天。

---

## 9. 跨 LLM 协作约定

本 handoff 是 Phase 3 → Phase 4 的转换 spec，进入 AGENTS.md `§交接记录` 的高门槛新建独立 handoff 范畴。

任何 AI 协作者（Codex / Claude / 其他）启动 Phase 4 实施前必读：

1. `AGENTS.md` — 项目不变约定
2. `docs/CURRENT.md` — 当前动态状态
3. `docs/handoff/2026-05-24_phase3_kickoff_spec_handoff.md` — Phase 3 完整实施记录
4. **本文件**（Phase 4 启动规格）
5. `skills/a_short_analysis/reference/v14.2_spec.md` — Phase 4 内容映射来源

实施过程产生的 schema / runner / Skill / prompts / tests 改动按 AGENTS.md §交接记录约定记录：默认追加到 phase 主 handoff（本文件）末尾 `## YYYY-MM-DD 追加：<topic>` 小节，不轻易新建独立 handoff。


---

## 2026-05-25 追加：Validation 依赖声明

### 改了什么

- 新增 `requirements-dev.txt`。
  - 当前只声明 validation/test 层必须的 `jsonschema>=4.0`。
  - 不在本轮整理完整运行期依赖（pandas / tushare / numpy 等仍来自用户本机数据环境），避免把小修扩大成环境重构。
- 更新 `runners/README.md`。
  - 明确 schema-validating 命令应使用项目/本机 Python（当前常用 `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`）。
  - 明确安装命令：`python -m pip install -r requirements-dev.txt`。
  - 明确 Codex bundled Python 可用于 compile / unit tests，但不作为项目依赖来源。
- 更新 `docs/CURRENT.md`，把 validation 依赖声明加入当前状态和关键文件。

### 为什么改

Phase 3.6 stats-only 复核时，Codex bundled Python 可以跑 compile / unittest，但缺 `jsonschema`，导致 `backtest_rank.py` 在最终 `backtest_report.json` schema 校验处失败。项目此前一直用本机 Python 3.13 完成 schema 校验，但依赖没有 repo-visible 声明。

Phase 4 会新增 `deterministic_report.schema.json`，schema 校验频率会更高。把 `jsonschema` 明确写入项目依赖声明，可以避免后续 LLM 或新终端把"本机刚好装了 jsonschema"误当作项目契约。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests -p "test_*.py" -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['runners/backtest_rank.py','engine/analyzer/state_manager.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]; print('compile ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "from importlib.metadata import version; print(version('jsonschema'))"
```

### 验证结果

- Unit tests：21 tests passed。
- Compile：`compile ok`。
- 本机 Python 3.13 可 import `jsonschema`。

### 失效旧结论

无。此改动不改变 Phase 3 / Phase 4 设计结论，也不改变任何回测结果。

### 下一步注意事项

1. 后续 schema-validating 命令统一使用项目/本机 Python，或先确保当前 Python 已安装 `requirements-dev.txt`。
2. 不要往 Codex bundled Python 里安装项目依赖；它只作为工具运行时。
3. 如果 Phase 4 增加新的 validation-only 依赖，追加到 `requirements-dev.txt`，不要散落在 handoff 的命令说明里。


---

## 2026-05-25 追加：deterministic_report schema v1.0.0

### 改了什么

- 新增 `schemas/deterministic_report.schema.json`，JSON Schema Draft 7，schema id:
  `https://stock.local/schemas/deterministic_report/1.0.0/schema.json`。
- 顶级字段按 §3.1 已拍板的 minimal 范围实现：
  - `decision`
  - `veto`
  - `entry_plan`
  - `exit_plan`
  - `position_size`
  - `risk_flags`
  - `evidence`
  - `unknowns`
  - `llm_notes`
  - `data_lineage`
  - `analyzer_invocations`
- `schema_name` 固定为 `deterministic_report`，`schema_version` 固定为 `1.0.0`。
- `decision.action` enum 保留 `buy/skip/watch/sell/reduce`，但 schema description 明确 Phase 4 v1 runner 应只输出 `skip/watch`；`buy/sell/reduce` 留给后续 deterministic enrich。
- `veto.reasons/diagnostics/enabled_rules` 对齐 Phase 3 `run_veto()` 输出结构；reason code enum 为当前四条 analyzer rule。
- `llm_notes.enabled` 与 `llm_notes.sections` 明确把 LLM enrich 和 deterministic 字段分离；v1 runner 应输出 `enabled=false`。
- `unknowns.reason` enum 固定为 `requires_llm / requires_external / data_missing / not_implemented_phase4`，承接 Phase 4 v1 "诚实标 unknown"边界。
- 用户已拍板 §8：
  - 数据模型字段范围足够 minimal，不额外加字段。
  - 输出目录用 `result/a_short/<as_of>/reports/`。
- 更新 `AGENTS.md` 与 `docs/CURRENT.md` 指向新 schema。

### 为什么改

Phase 5 execution 回测需要消费机器可读决策字段，不能从 LLM 自由文本里抽取入场、止损、仓位等信息。Phase 4 第一刀必须先把 deterministic report contract 固化，再写 runner 和 Skill 文档。

本轮刻意没有加入盈亏比、持仓周期、ATR 止损细节等字段；这些属于 Phase 5/后续 analyzer enrich 的 schema minor 升级，不进入 v1.0.0 minimal contract，避免 schema-first 变成大而全设计。

### 验证命令

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/deterministic_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; import json; json.load(open('schemas/deterministic_report.schema.json',encoding='utf-8')); print('json parse ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "<minimal sample validation>"
```

### 验证结果

- Schema meta-validation：`schema ok`。
- Bundled Python JSON parse：`json parse ok`。
- 最小 `watch` 样例 report 校验：`sample_errors 0`。

### 失效旧结论

无。此改动是 Phase 4 schema-first 首次落地，不改变 Phase 3/Phase 4 既有设计边界。

### 下一步注意事项

1. 下一步写 `runners/run_analysis_report.py`。
2. Runner 必须在落盘前校验输出符合 `schemas/deterministic_report.schema.json`。
3. Runner v1 的 `decision.action` 只应输出 `skip/watch`；不要在 Phase 4 v1 里硬做 `buy`。
4. 输出目录固定为 `result/a_short/<as_of>/reports/<ts_code>.json` 和 `.md`。


---

## 2026-05-25 追加：run_analysis_report runner v1

### 改了什么

- 新增 `runners/run_analysis_report.py`。
  - CLI：`--as-of YYYYMMDD --ts-code CODE [--input-path] [--out-dir]`。
  - 默认读取 `result/a_short/<as_of>/analysis_input.json`，按 `ts_code` 找单个 candidate。
  - 调用 Phase 3 `engine.analyzer.rule6_hard_veto.run_veto(candidate)`，并读取 `state_manager.has_position()` / `is_circuit_breaker_active()`。
  - 落盘前调用 `schemas/deterministic_report.schema.json` 校验，输出 JSON + Markdown。
  - 默认输出目录固定为 `result/a_short/<as_of>/reports/`。
- 新增 `tests/skill/test_run_analysis_report.py`。
  - 验证 runner 构造的 `veto` 与直接 `run_veto(candidate)` 一致。
  - 验证 Markdown 包含 M6.7 table。
  - 若当前 interpreter 安装了 `jsonschema`，验证 `write_report()` 的 schema 校验 + 文件输出；bundled Python 缺依赖时该项 skip。
- 更新 `runners/README.md`、`AGENTS.md`、`docs/CURRENT.md` 指向 runner v1 状态。

### 为什么改

Phase 4 schema-first 已经固定 contract；下一步必须有纯 Python、可复现的执行入口，把 `analysis_input.json + analyzer + state` 合成为机器可读报告。Skill 仍保持使用文档定位，不作为执行入口；LLM enrich 仍为后续可选层，不进入 v1 runner。

本轮没有实现 `buy`、仓位公式、ATR 止损、止盈位、联网新闻/监管判断。对应字段继续输出 `unknown` / `requires_llm` / `not_implemented_phase4`，避免 Phase 4 v1 硬编不可回测的默认值。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['runners/run_analysis_report.py','tests/skill/test_run_analysis_report.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]; print('compile ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests -p "test_*.py" -v
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import tempfile; from pathlib import Path; from runners.run_analysis_report import main; d=tempfile.mkdtemp(prefix='phase4_report_'); rc=main(['--as-of','20260522','--ts-code','600415.SH','--out-dir',d]); print('rc', rc); print(sorted(p.name for p in Path(d).iterdir()))"
```

### 验证结果

- Compile：`compile ok`。
- Unit tests：24 tests passed，1 skipped（bundled Python 缺 `jsonschema`，schema 写入测试按设计 skip）。
- 本机 Python 3.13 E2E：`20260522 / 600415.SH` 成功生成 `600415.SH.json` 和 `600415.SH.md`，返回码 `0`，schema 校验通过。

### 失效旧结论

无。此改动不改变 Phase 3 analyzer 规则、不改变 rank 回测结论、不改变 Phase 4 schema v1.0.0。

### 下一步注意事项

1. 写 `schemas/deterministic_report_coverage.md`，明确 v14.2 覆盖率和 unknown 原因分布。
2. 写 `skills/a_short_analysis/SKILL.md`，把 runner 调用、报告读取、LLM enrich 边界写成 AI 协作者使用文档。
3. Runner v1 继续只输出 `skip/watch`；Phase 5 前不要把 `buy` 逻辑塞进 Skill 自由文本。


---

## 2026-05-25 追加：coverage doc + Skill 使用文档

### 改了什么

- 新增 `schemas/deterministic_report_coverage.md`。
  - 记录 `deterministic_report` v1.0.0 顶级字段的来源和状态。
  - 按 v14.2 Rule/M0-M6 映射 Phase 4 v1 已实现、`requires_llm`、`requires_external`、`data_missing`、`not_implemented_phase4`。
  - 明确 v1 验收线：schema meta-validation、runner 落盘前校验、真实样本可生成、v1 不输出 `buy`。
- 更新 `skills/a_short_analysis/SKILL.md`。
  - 加 YAML frontmatter，定位为 A 股短线单票分析 Skill。
  - 明确 executor 是 `runners/run_analysis_report.py`，Skill 只负责调用、阅读和可选 LLM enrich 指引。
  - 明确 deterministic 字段不得手改，LLM enrich 不得覆盖 analyzer veto，也不得把解释变成 `decision.action=buy`。
- 新增 6 个 prompt 骨架：
  - `industry_trend.md`
  - `regulatory_48h.md`
  - `policy_news.md`
  - `earnings_no_good_repair.md`
  - `cross_market_linkage.md`
  - `hidden_risk.md`
- 更新 `AGENTS.md` 与 `docs/CURRENT.md`，把下一步从 coverage/Skill 推进到 enrich contract 收口和 smoke 样例。

### 为什么改

Runner 和 schema 已经提供 deterministic contract，但接手者还需要知道 v14.2 哪些部分在 v1 已覆盖、哪些部分仍是未知项，以及 Skill 应该如何安全使用 runner 输出。否则后续 LLM 很容易把 Skill 写成自由文本执行入口，或把未验证的新闻/行业判断写进 deterministic 决策字段。

Prompt 骨架本轮只做最小占位，是为了让 `SKILL.md` 的 enrichment 引用不指向空目录；它们不接入 runner，不改变 JSON schema，也不改变 Phase 3 analyzer 规则。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests -p "test_*.py" -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['skills/a_short_analysis/SKILL.md','schemas/deterministic_report_coverage.md']; [Path(f).read_text(encoding='utf-8') for f in files]; print('docs utf8 ok')"
```

### 验证结果

- Unit tests：24 tests passed，1 skipped（bundled Python 缺 `jsonschema`，schema 写入测试按设计 skip）。
- Docs UTF-8 read：`docs utf8 ok`。

### 失效旧结论

无。此改动不改变 Phase 4 schema v1.0.0、不改变 runner 输出字段、不改变 analyzer 决策。

### 下一步注意事项

1. 如果要把 LLM enrich 写回 JSON，先定义补充输入/patch 文件格式，不能手工覆盖 deterministic 字段。
2. 用 1-2 只不同 veto 状态股票跑 smoke，检查 Markdown 和 `unknowns` 对人工 review 是否足够清楚。
3. Phase 4 v1 仍保持 `skip/watch`，不要把 prompt 输出升级成买入决策。


---

## 2026-05-25 追加：LLM enrichment patch contract

### 改了什么

- 新增 `schemas/deterministic_report_enrichment.schema.json` v1.0.0。
  - 只定义可选 LLM notes patch，不承载 deterministic 决策。
  - 必须声明 `target.as_of`、`target.ts_code`、`target.report_schema_version`，以及 `source.kind` / `source.prompt_refs`。
  - 只允许写 `llm_notes.enabled=true` 和 `llm_notes.sections[]`。
- 更新 `runners/run_analysis_report.py`。
  - 新增 `--enrichment-path` 参数。
  - 读取并校验 enrichment patch 后，先核对 target 与新生成 report 是否一致，再只合并 `llm_notes`。
  - Markdown 的 `## LLM Notes` 会反映 `enabled=true/false` 和 section 状态。
- 更新 `tests/skill/test_run_analysis_report.py`。
  - 覆盖 enrichment 合并后 deterministic `decision` 不变。
  - 覆盖 target mismatch 会拒绝。
- 更新 `schemas/deterministic_report_coverage.md`、`skills/a_short_analysis/SKILL.md`、`AGENTS.md`、`docs/CURRENT.md`。

### 为什么改

上一轮已经明确 Skill 可以做可选 LLM enrich，但没有定义 enrich 如何写回 JSON。没有 patch contract 的情况下，后续 LLM 很容易直接手改 report JSON，误伤 `decision/veto/risk_flags/entry_plan/exit_plan/position_size` 等 deterministic 字段。

本轮把写回面压缩到 `llm_notes`，让 runner 仍然是唯一合并入口，并让 schema 拒绝任何多余字段。这样 Phase 4 能保留 LLM notes，同时不破坏 Phase 5 execution 回测所需的 deterministic contract。

### 验证命令

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['runners/run_analysis_report.py','tests/skill/test_run_analysis_report.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]; print('compile ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests -p "test_*.py" -v
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['skills/a_short_analysis/SKILL.md','schemas/deterministic_report_coverage.md','schemas/deterministic_report_enrichment.schema.json']; [Path(f).read_text(encoding='utf-8') for f in files]; print('docs utf8 ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "<enrichment schema meta-validation + runner --enrichment-path E2E sample>"
```

### 验证结果

- Compile：`compile ok`。
- Unit tests：26 tests passed，1 skipped（bundled Python 缺 `jsonschema`，schema 写入测试按设计 skip）。
- Docs/schema UTF-8 read：`docs utf8 ok`。
- 本机 Python 3.13 enrichment E2E：
  - enrichment schema meta-validation：`schema ok`
  - runner `--enrichment-path` 生成 `600415.SH.json` 和 `600415.SH.md`
  - 输出 JSON 中 `llm_notes.enabled=True`，section code=`industry_trend`

### 失效旧结论

无。此改动不改变 deterministic report schema v1.0.0，不改变 analyzer 规则，不改变 runner 默认无 enrichment 输出。

### 下一步注意事项

1. 补真实样本 enrichment E2E 验证结果。
2. 用 1-2 只不同 veto 状态股票做 Phase 4 smoke，检查 Markdown 可读性。
