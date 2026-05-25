# Phase 4 kickoff spec handoff

**日期**：2026-05-25
**范围**：Phase 4 minimal Skill 启动规格
**状态**：待开工。本文是 Phase 4 开工边界，不是实现记录。
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
2. **`runners/run_analysis_report.py`** — CLI 入口
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
3. **`schemas/deterministic_report_coverage.md`** — 类比 `schemas/analysis_input_coverage.md`，记录 v14.2 五段拆解里哪些已实现、哪些 `requires_llm` / `requires_external` / `not_implemented_phase4`
4. **`skills/a_short_analysis/SKILL.md`** — AI 协作者**使用文档**：
   - 怎么调 runner
   - 怎么读 JSON / Markdown
   - 哪些字段需要 LLM enrich + 如何调 prompts/
   - enrich 后如何把结果合并回报告（重新跑 runner + 提供 enrich JSON 作为补充输入）
5. **`skills/a_short_analysis/prompts/*.md`** — v14.2 各 LLM 判断子任务的 prompt 文件（M2.1 板块联动 / M2.4 跨市场 / M2.5 隐蔽风险 / 行业景气 / 48h 监管识别 / 政策新闻解读 / 季报"无利好修复"判断）。**v1 这些 prompt 文件可以先写骨架占位，不强制实现内容**——只要 SKILL.md 知道每个 LLM 子任务对应哪个 prompt 文件即可
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
