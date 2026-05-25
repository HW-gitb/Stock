# 股票分析系统项目 — AI 协作说明

> 本文件是项目的 AI 协作根入口。**所有 AI 协作者**（Claude Code / Codex CLI / ChatGPT / Cursor / Cline / Aider / 其他 LLM）进入此项目时**必读**。
> Claude Code 用户通过根目录的 `CLAUDE.md` 自动转入本文件；Codex CLI 自动加载本文件；其他工具请用户手动告知。

## 项目背景

构建 4 套股票分析系统：A 股短线、美股短线、A 股长线、美股长线。每套包含筛选、分析、回测、复盘四组件，共享同一套 engine，通过 preset 配置区分市场和周期。

## 当前进度

- ✅ A 股短线筛选脚本：`A-EGS/egs_main.py` v7.10 已支持 `--as-of` 历史日期运行
- ✅ A 股短线分析框架：`skills/a_short_analysis/reference/v14.2_spec.md` 已定位为规格说明书，不作为运行时提示词
- ✅ 美股短线资料：已整理到 `skills/us_short_analysis/reference/`
- ✅ Phase 1a：`schemas/analysis_input.schema.json` 已完成，当前输出 schema 版本 `1.1.0`
- ✅ Phase 1b：`egs_main.py` 已接入 `analysis_input.json`、`snapshot.json`、`candidates.csv` 导出器
- ✅ 项目目录：已按 engine/shared + preset/state/skill/result 分离原则建立骨架
- ✅ Phase 2：`runners/backtest_rank.py` 已跑通 24 期 production rank 回测；工程链路通过，策略优化继续推进
- ✅ L3 概念缓存：正式运行默认刷新 L3；搭建/测试阶段可用 `--reuse-l3-cache` 复用共享缓存加速
- ✅ Phase 4 schema-first：`schemas/deterministic_report.schema.json` v1.0.0 已落地；`runners/run_analysis_report.py` 纯 Python runner 已可生成 schema-validated JSON + Markdown

## 三条不可动摇的原则

1. **v14.2 是规格说明书，不是运行时提示词。** 所有规则拆到代码、配置、状态、Skill、提示词五个介质。
2. **先把 A 股短线做成完整可复用样板**，即 Phase 1-6 全跑通并实盘一个季度，再扩展其他市场。
3. **回测分两层。** rank 回测先做，execution 回测后做。

## 目标架构

```text
Stock/
├── engine/
│   ├── data/
│   │   ├── tushare_provider.py
│   │   └── us_provider.py
│   ├── factors/
│   │   ├── momentum.py
│   │   ├── quality.py
│   │   ├── catalyst.py
│   │   └── expectation.py
│   ├── scoring/scorer.py
│   ├── analyzer/
│   │   ├── rule6_hard_veto.py
│   │   ├── technical.py
│   │   ├── position_sizing.py
│   │   ├── stop_loss.py
│   │   └── state_manager.py
│   └── backtest/
│       ├── rank_backtest.py
│       └── execution_backtest.py
├── schemas/
│   ├── analysis_input.schema.json
│   └── deterministic_report.schema.json
├── presets/
│   ├── a_short.yaml
│   ├── us_short.yaml
│   ├── a_long.yaml
│   └── us_long.yaml
├── skills/
│   ├── a_short_analysis/
│   │   ├── SKILL.md
│   │   ├── prompts/
│   │   └── reference/
│   │       ├── v14.2_spec.md
│   │       └── a_short_workflow_legacy.txt
│   ├── us_short_analysis/
│   │   ├── SKILL.md
│   │   ├── prompts/
│   │   └── reference/
│   │       ├── us_short_analysis_spec.md
│   │       └── us_short_screening_spec.md
│   ├── a_long_analysis/
│   └── us_long_analysis/
├── state/
│   ├── a_short/
│   │   ├── positions.json
│   │   ├── veto_log.json
│   │   ├── circuit_breaker.json
│   │   └── execution_log.csv
│   ├── us_short/
│   ├── a_long/
│   └── us_long/
├── runners/
├── result/
│   └── a_short/YYYYMMDD/
│       ├── candidates.csv
│       ├── analysis_input.json
│       └── snapshot.json
├── A-EGS/
│   └── egs_main.py
└── docs/
    ├── archive/
    └── handoff/
```

## v14.2 五段拆解映射

| v14.2 内容 | 去处 | 介质 |
|---|---|---|
| Rule 6 阈值检查、M2.7 粗筛、M3.2 技术指标、M3.3B IV/HV、M3.6 止损止盈、M5.5B 多因子、M6.3 仓位公式、Rule 8/9 检查 | `engine/analyzer/*.py` | Python |
| Rule 12 熔断、Rule 13 冷静期、M0.5 觉醒、M3.5 持仓追踪 | `state/a_short/*.json` + `state_manager.py` | 状态文件 + 操作类 |
| 所有阈值，如 ATR 系数、IV 分位、仓位上限、盈亏比、时间止损天数 | `presets/a_short.yaml` | YAML 配置 |
| 行业景气判断、48h 监管识别、政策新闻解读、季报“无利好修复”判断、跨市场联动、隐蔽风险事件理解 | `skills/a_short_analysis/prompts/*.md` | LLM 提示词 |
| M0-M6 编排、何时调脚本、何时联网、何时合成报告 | `skills/a_short_analysis/SKILL.md` | Skill 主体 |

## 执行路线图

| Phase | 内容 | 工作量 | 状态 |
|---|---|---|---|
| 0 | 维持 `egs_main.py` 当前可用 | — | ✅ |
| 1a | 设计 `analysis_input.schema.json` | 0.5-1 天 | ✅ |
| 1b | `egs_main.py` 输出 `analysis_input` + 历史快照 | 1-2 天 | ✅ |
| 2 | rank 回测 + Rule 6 规则有效性统计 | 3-5 天 | ✅ 工程链路通过，策略优化继续 |
| 3+ | minimal analyzer + state 接口同步建立 | 1-2 周 | ⬜ |
| 4 | minimal Skill：读 input，调 analyzer，出 M6.7 | 3-5 天 | ⬜ |
| 5 | execution 回测 | 1-2 周 | ⬜ |
| 6 | A 股短线完整闭环跑一个季度 | 实盘期 | ⬜ |
| 7 | 引擎模块化重构，美股扩展硬前置 | 1-2 周 | ⬜ |
| 8 | 美股短线：data provider + preset + skill | 1-2 周 | ⬜ |
| 9 | 长线系统：架构复用，规则全新设计 | 2-4 周 | ⬜ |

## 已固化决策

1. 架构走 engine 共享 + preset 分离，不走每市场一个独立目录。
2. state 用 JSON，不用 Excel。
3. `analysis_input.json` 是契约文件，schema 版本使用 SemVer，当前输出版本为 `1.1.0`。
4. state 接口必须跟 analyzer Phase 3 同步建立，即使初版返回空或 False。
5. 引擎重构 Phase 7 是美股扩展 Phase 8 的硬前置红线。
6. 长线分析框架不复用短线 v14.2，从头设计。
7. Skill 走渐进路线，第一版只做读 input、调 analyzer、出 M6.7，不追求自动批量。
8. v14.2.md 不废弃，已移到 `skills/a_short_analysis/reference/v14.2_spec.md` 作设计文档。
9. `A-EGS/egs_main.py` 当前不移动，等 Phase 7 再拆进 `engine/`。

## AI 协作者在本项目中的工作守则

## 交接记录

任何 AI 助手，包括 ChatGPT、Codex 或其他 LLM，继续 Phase 2 / Phase 3、A 股短线筛选、rank 回测、analyzer、state、`A-EGS/egs_main.py`、`runners/backtest_rank.py`、`analysis_input.json` 或 findings 相关工作前，**按时间顺序读取以下 handoff**：

1. `docs/handoff/2026-05-24_phase2_v7.9_handoff.md` — EGS v7.8/v7.9 的脚本修改、正式周五实盘重跑、24 期 production 回测验收、当前有效 findings、下一步策略优化优先级
2. `docs/handoff/2026-05-24_phase2_tier1only_subset_handoff.md` — Tier1-only 主口径切片实施、stats CSV 加 `subset` 列、schema 升 1.6.0、settings.primary_subset 字段
3. `docs/handoff/2026-05-24_phase2_git_init_handoff.md` — **项目首次进入 git 管理**（私密本地仓库，不可 push / 不可 add remote）、`.gitignore` 排除清单、commit hash `dca8367`、git 私密性约束
4. `docs/handoff/2026-05-24_phase2_validation_tooling_handoff.md` — EGS v7.10、rank backtest schema 1.8.0、split/variant/eligible benchmark/T+1 不可买/portfolio stats/reason observability
5. `docs/handoff/2026-05-24_phase2_6_datahub_guardrail_handoff.md` — Phase 2.6 DataHub guardrail，固定“先补 lineage、不做大重构”的边界
6. `docs/handoff/2026-05-24_phase2_24p_v710_results_handoff.md` — v7.10 24 期 production 实跑结果、schema 校验、核心 findings 和结论边界
7. `docs/handoff/2026-05-24_phase2_tier1_count_warning_handoff.md` — rank backtest schema 1.9.0，report 增加日期级 Tier1-count 告警
8. `docs/handoff/2026-05-24_phase2_data_lineage_handoff.md` — rank backtest schema 1.10.0，新增 `data_lineage` 对象，Phase 2.6 lineage 闭环
9. `docs/handoff/2026-05-24_phase3_kickoff_spec_handoff.md` — Phase 3 开工规格：minimal veto analyzer + JSON state + replay/ablation 完成线（含 3.3 子分数预测力 + 3.4 ESP 反向 PIT 调查 + 3.5 实盘 forward tracker）
10. `docs/handoff/2026-05-25_phase4_kickoff_spec_handoff.md` — Phase 4 开工规格：deterministic_report schema first + runner 纯 Python + Skill 是使用文档（非执行入口）

完成一轮重要修改后，收尾时必须同步更新 handoff。**默认追加到同 phase 主 handoff，不要轻易新建文件**（2026-05-24 当天 8 个 handoff 是历史教训：碎片化让接手者读到第 5 个就开始跳读）。

**何时新建独立 handoff**（高门槛，只有以下情况）：

- 跨 phase 转换（Phase 2 → Phase 3、Phase 6 → Phase 7 等）
- breaking change：schema major 升级（1.x → 2.0）、数据口径反转、findings 整体 INVALIDATED、移除 / 重命名公共字段
- 接入新数据源或新模块（美股 provider、analyzer 首版、execution 回测首版）
- 一次性强约束事件（git init、私密性规则、安全口径变化）

**何时追加到同 phase 主 handoff**（默认）：

- schema minor / patch 升级（纯加可选字段、加 warning 数组、加 lineage 元数据）
- 同主题的迭代改动（同一周里多次报告增强 / 多次过滤器调优 / 多次 EGS 小版本）
- 验证工具、CSV 列、日志改进等"工程增量"

**追加格式**：在主 handoff 末尾加 `## YYYY-MM-DD 追加：<short topic>` 小节，沿用同一份"改了什么 / 为什么 / 验证命令 / 验证结果 / 失效旧结论"结构。schema 演进链一并在该节展开（1.8.0 → 1.9.0 → 1.10.0 写在一处更清楚）。

**何时不写 handoff**：错别字、注释、文档解释、临时探索、CURRENT.md 文案微调。

**通用要求**：所有 handoff（无论新建或追加）必须记录改了什么、为什么改、验证命令、验证结果、失效旧结论、下一步注意事项。旧 handoff 不重组（git 历史已固化）。

## Session log discipline

**目的**：commit message 记录"改了什么 / 为什么改"，handoff 记录 phase 级设计决定；但都不记录"试过什么没成 / 试过的方案为什么被否决 / 当前 LLM 的纠结点 / 下一步该做什么的判断"。**这一层认知信息在跨 LLM 协作时最容易丢失**，所以单独用 `docs/SESSION_LOG.md` 累积。

**所有 AI 协作者（Codex / Claude / 其他 LLM）均适用**。

### 何时写 session log entry

满足以下**任一**条件时，session 收尾前必须 append 一条 entry 到 `docs/SESSION_LOG.md`：

- 本次 session 有 ≥1 个 non-trivial commit（不含纯错别字、纯注释格式调整等微改）
- 即使无 commit，但做出了实质性设计决定 / 排除了某个方案 / 留下了开放问题给下一 LLM
- 用户明确说要切换话题或下次再聊

**何时不写**：纯问答会话（没有任何文件改动、没有设计决定）；纯探索式 grep / read 而无任何结论；用户主动说"这次不用记"。

### Entry 格式（七节）

reverse-chronological：**新 entry 永远 prepend 到文件顶部**，紧跟 H1 header 之后。

```markdown
## YYYY-MM-DD — <LLM 名> (<本次 session 主题简述>)

**Commits**: <hash1>, <hash2>, ...

**Relationship to prior session(s)**:
- Builds on <date> <LLM> (<topic>) §<section>
- **Reverses**: <prior decision> → <new decision>. Reason: <why>
- **Refines**: <prior decision>. Adjustment: <what changed>
（无关联可只写 "Initial session for <topic>"）

**Worked on**:
1. <item> ...
2. <item> ...

**Key decisions**:
- <decision> — <reasoning>
- ...

**Alternatives considered and rejected**:
- "<alternative>" — 否决。<reason>
- ...

**Open questions handed off**:
- <question>
- ...

**Next natural step from my view**:
1. <step>
2. <step>
```

`LLM 名` 用 `Claude` / `Codex` / `ChatGPT` 等明显标识。

### 三层保险机制

1. **机制层**：本规则写进 AGENTS.md（你正在读的这节），所有 LLM 进项目时自动加载到 context
2. **行为层**：Claude 通过 `~/.claude/projects/D--cnhea-Stock/memory/feedback_session_log.md` 自我约束；Codex 通过 AGENTS.md auto-load 约束
3. **fallback 层**：**下一个进场的 LLM 第一件事就是检查 SESSION_LOG 末次 entry 之后的 git log 有没有 commit**。如果有 commit 但没对应 entry，必须立刻补一条"reconstructed from commit messages"的 entry，重建上一 session 的认知交接

### 与 commit message / handoff 的关系

- **不重复 commit message 的内容**。entry 的 "Worked on" 节用 1-2 行高层概述，不抄 commit 详情。读者要详情自己 git show
- **不重复 phase handoff 的内容**。handoff 是项目级设计文档，session log 是 LLM 思维流水账
- **重叠的部分有意保留**：commits 列表可以让接手 LLM 快速回看；"Key decisions" 概要可与 handoff "为什么改"节重叠，目的是让 SESSION_LOG 单独可读不需要打开 handoff

### 单文件 vs 多文件

刻意选择**单文件 `docs/SESSION_LOG.md`** 而非 `docs/sessions/<date>.md` 一篇一文件，因为：
- 文件多了又会重蹈 2026-05-24 当天 8 个 handoff 碎片化的覆辙
- 单文件 reverse-chrono 让接手 LLM 一次性看到最近 N 次 session 的认知线索
- 文件无限增长不是问题：只读最近 3-5 条 entry，更老的当历史档案

### 与 Phase 7 DataHub 的关系

未来 Phase 7 引擎重构若有显著架构决策，主线决定走 handoff（仍是 phase 级文档），认知过程（rejected 方向 / 纠结点）继续走 SESSION_LOG。两个层级互补。

**用户身份**：Python 熟手，AI 工具链如 Skill、Codex、MCP 入门。代码细节可以放心讨论，AI 工具链概念按需展开。

**沟通风格**：直接给判断，不堆选项让用户选。有理据时主动指出用户方案的问题，不必要的礼貌让位于决策效率。

**重要边界**：设计阶段已结束，不再开新的架构讨论。所有“要不要重新考虑 X”类问题，先指向“已固化决策”；只有遇到本说明明显未覆盖的新问题才展开。

**身份定位**：AI 协作者在本项目中是建造者，不是顾问。优先输出代码、schema、测试，而不是讨论方案。除非用户明确问意见，默认动手。

**代码改动前必先 view**：改 `egs_main.py` 之前先查看当前状态，不基于记忆假设。`egs_main.py` 当前版本以文件为准，不按旧版本提建议。

**v14.2 规则定位**：用户提到任何 v14.2 规则时，先识别该规则属于五段拆解的哪一段，在对应介质里讨论实现，不在原 Markdown 框架里叠加。

**Tushare 已知限制**：当前版本继承的无解限制清单包括 L6 盘中动态止损、调研次数、L1 行业毛利率趋势。不反复提“是否实现”，直接跳过或标记低置信度。

**schema 优先**：任何跨模块传递数据的场合，如 `analysis_input`、`deterministic_report`、state 文件，讨论实现前先讨论字段定义。schema 改动是 breaking change，需明确版本升级。

**回测覆盖要求**：rank 回测必须包含 Rule 6 各项的历史预测力分析。execution 回测必须完整模拟止损、时间止损、熔断、仓位限制、冷静期。

**版本对齐**：项目内所有版本号引用必须以 `egs_main.py` 当前版本为准。旧文档中的旧 EGS 引用，在改动相关文档时顺手更新。

**Phase 完成判定**：每个 Phase 必须有明确完成判定。Phase 1a 完成 = `schemas/analysis_input.schema.json` 通过 JSON Schema 校验且对 v14.2 M0-M6 字段覆盖率 ≥ 90%。

## Phase 3 开工边界

- Phase 3 = minimal veto analyzer + JSON state 接口 + rank 回测 replay；不是完整 analyzer，也不是 Phase 7 DataHub 重构。
- 新 analyzer 直接放 `engine/analyzer/`，不要放进 `A-EGS/`；不得反向 import `A-EGS/egs_main.py`。
- `rule6_hard_veto.py` 必须真实返回 veto decision；state manager 初版可以返回空 dict / False。
- 第一批 hard veto：`chasing_high`、`overheat`、`l2_unknown`、`esp_non_positive`。四条都 hard veto，且各自独立 reason code + version。`esp_non_positive` 已升 v2：只对明确负 `esp_raw < 0` hard veto；`esp_raw == 0` 视为中性/数据不足诊断，不再 hard veto。
- missing 不等于 negative：字段缺失、空值、不可解析不自动触发 hard veto，除非 EGS 当前逻辑已明确把该缺失当作降级原因。
- `LOCK` 暂不 hard veto，只做辅助 flag；扩样本到 N≥15 后再决策。
- 回测已新增 `tier1_veto_passed` subset，保留 `all` / `tier1_only` baseline；schema 已升到 `1.11.0`，并加入 `low_tier1_veto_passed_count` date warning。
- Phase 3 详细完成线见 `docs/handoff/2026-05-24_phase3_kickoff_spec_handoff.md`。

## Phase 2 特别待办

- rank 回测必须单独统计 Rule 6 各否决项的历史预测力。
- 专门检验 `q0_dt_yoy > 200%`、`q1_dt_yoy > 200%`、`esp_raw` 极端值分组的未来 20 日收益。
- 如果低基数高增长标的没有稳定超额收益，在 `esp_raw` 计算中加入 winsorize 或低基数惩罚。
- 统计 `data_quality.completeness_score` 与后验收益的关系，决定低完整度样本是否退出 rank 回测。
- 正式运行无论每周五选股还是正式回测验证，都应刷新 L3；只有搭建/测试阶段可用 `--reuse-l3-cache` 复用共享缓存。
- EGS v7.9 后 `data_quality.completeness_score` 已改为动态计算；v7.9 之前的完整度分组结论不可用。
- 24 期 v7.10 production 回测显示：追高风险、OVERHEAT/LOCK、ESP 低基数、Tier2 filler 和低 Tier1-count 日期是下一批优先优化点。

## 文件参考

- `A-EGS/egs_main.py` — A 股短线筛选引擎，当前 v7.10
- `runners/backtest_rank.py` — Phase 2 rank 回测入口
- `runners/diagnose_tier1_bad_signals.py` — Phase 3.2 Tier1 坏票特征诊断，仅读取现有回测输出，不重跑 EGS
- `runners/data_canary.py` — Phase 2.6 旁路数据对账（Tushare vs akshare），不阻断选股，输出 `logs/data_canary_<as_of>.json`
- `skills/a_short_analysis/reference/v14.2_spec.md` — A 股短线分析框架规格说明书
- `skills/us_short_analysis/reference/us_short_analysis_spec.md` — 美股短线分析框架资料
- `skills/us_short_analysis/reference/us_short_screening_spec.md` — 美股短线预测/筛选框架资料
- `schemas/analysis_input.schema.json` — analysis_input 契约，当前 `1.1.0`，JSON Schema Draft 7
- `schemas/deterministic_report.schema.json` — deterministic report 契约，当前 `1.0.0`，Phase 4 runner 输出 JSON 必须通过该 schema
- `schemas/rank_backtest_report.schema.json` — backtest_report 契约，当前 `1.11.0`（含 date_warnings + data_lineage + analyzer veto replay）
- `schemas/analysis_input_coverage.md` — schema 覆盖率与修复记录
- `docs/handoff/2026-05-24_phase2_v7.9_handoff.md` — Phase 2 v7.9 交接记录
- `docs/handoff/2026-05-24_phase2_tier1only_subset_handoff.md` — Phase 2 Tier1-only 主口径切片交接记录
- `docs/handoff/2026-05-24_phase2_git_init_handoff.md` — Phase 2 git init 交接记录（私密本地仓库约束）
- `docs/handoff/2026-05-24_phase2_validation_tooling_handoff.md` — Phase 2 验证工具升级交接记录
- `docs/handoff/2026-05-24_phase2_6_datahub_guardrail_handoff.md` — Phase 2.6 DataHub guardrail 交接记录
- `docs/handoff/2026-05-24_phase2_24p_v710_results_handoff.md` — Phase 2 v7.10 24 期 production 实跑交接记录
- `docs/handoff/2026-05-24_phase2_tier1_count_warning_handoff.md` — Phase 2 Tier1-count 日期告警交接记录
- `docs/handoff/2026-05-24_phase2_data_lineage_handoff.md` — Phase 2 data_lineage 交接记录（schema 1.10.0，Phase 2.6 闭环）
- `docs/handoff/2026-05-24_phase3_kickoff_spec_handoff.md` — Phase 3 开工规格交接记录（minimal veto analyzer + JSON state + replay/ablation）
- `docs/handoff/2026-05-25_phase4_kickoff_spec_handoff.md` — Phase 4 开工规格交接记录（deterministic_report schema first + runner-as-executor + Skill-as-doc）
- `result/a_short/backtest/Phase2_rank_backtest_findings_codex_24p_v7.10.md` — 当前有效 Phase 2 findings（Codex 24p v7.10 视角）
- `result/a_short/backtest/Phase2_rank_backtest_findings_cc_24p.md` — 当前有效 Phase 2 findings（cc 互补合并版，含 OVERHEAT/entry_flag/LOCK 三个负信号 + 2024 vs 2025 regime 拆分）
## DataHub / Data Middle Platform Guardrail

The DataHub direction is accepted and fixed as a staged roadmap item.

**Phase 2.6 = DataHub design and data-lineage hardening.**

- Add and maintain `docs/datahub_design.md`.
- Strengthen report metadata so future readers can see provider, API families, date ranges, L3 mode, PIT limitations, adjustment mode, and benchmark sources.
- Do not rewrite `A-EGS/egs_main.py` into a full data middle platform during Phase 2.6.
- Phase 2.6 completion = design doc exists, AGENTS roadmap names the guardrail, and backtest/report lineage gaps are identified or filled.

**Phase 3-6 = continue A-share short-term closed-loop build.**

- Keep `A-EGS/egs_main.py` stable unless fixing concrete correctness bugs.
- Do not start broad ODS/DWD/DWS refactors while analyzer/state/Skill/execution loop is incomplete.

**Phase 7 = formal DataHub and engine modularization.**

- Implement ODS raw layer, DWD standardized detail layer, DWS/factor layer, and shared provider access under `engine/data/` and `engine/factors/`.
- Production screening and rank/execution backtests must consume the same standardized data/factor definitions.
- Phase 7 is the hard prerequisite before US-short expansion.

Reference document: `docs/datahub_design.md`.

Related handoff: `docs/handoff/2026-05-24_phase2_6_datahub_guardrail_handoff.md`.
