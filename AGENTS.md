# 股票分析系统项目 - ChatGPT 工作说明

## 项目背景

构建 4 套股票分析系统：A 股短线、美股短线、A 股长线、美股长线。每套包含筛选、分析、回测、复盘四组件，共享同一套 engine，通过 preset 配置区分市场和周期。

## 当前进度

- ✅ A 股短线筛选脚本：`A-EGS/egs_main.py` v7.9 已支持 `--as-of` 历史日期运行
- ✅ A 股短线分析框架：`skills/a_short_analysis/reference/v14.2_spec.md` 已定位为规格说明书，不作为运行时提示词
- ✅ 美股短线资料：已整理到 `skills/us_short_analysis/reference/`
- ✅ Phase 1a：`schemas/analysis_input.schema.json` 已完成，当前输出 schema 版本 `1.1.0`
- ✅ Phase 1b：`egs_main.py` 已接入 `analysis_input.json`、`snapshot.json`、`candidates.csv` 导出器
- ✅ 项目目录：已按 engine/shared + preset/state/skill/result 分离原则建立骨架
- ✅ Phase 2：`runners/backtest_rank.py` 已跑通 24 期 production rank 回测；工程链路通过，策略优化继续推进
- ✅ L3 概念缓存：正式运行默认刷新 L3；搭建/测试阶段可用 `--reuse-l3-cache` 复用共享缓存加速

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

## ChatGPT 在本项目中的工作守则

## 交接记录

任何 AI 助手，包括 ChatGPT、Codex 或其他 LLM，继续 Phase 2、A 股短线筛选、rank 回测、`A-EGS/egs_main.py`、`runners/backtest_rank.py`、`analysis_input.json` 或 findings 相关工作前，**按时间顺序读取以下两份 handoff**：

1. `docs/handoff/2026-05-24_phase2_v7.9_handoff.md` — EGS v7.8/v7.9 的脚本修改、正式周五实盘重跑、24 期 production 回测验收、当前有效 findings、下一步策略优化优先级
2. `docs/handoff/2026-05-24_phase2_tier1only_subset_handoff.md` — Tier1-only 主口径切片实施、stats CSV 加 `subset` 列、schema 升 1.6.0、settings.primary_subset 字段

完成一轮重要修改后，收尾时必须同步更新 handoff：

- 小修改：更新当前最新 handoff 文件。
- 阶段性或重要修改：新建新的 handoff 文件，命名格式为 `docs/handoff/YYYY-MM-DD_short-topic_handoff.md`。
- 涉及版本升级、回测重跑、schema 改动、策略结论变化、数据口径变化时，必须写 handoff。
- 只改错别字、解释文档、临时检查时，可以不写 handoff。
- handoff 必须记录：改了什么、为什么改、验证命令、验证结果、失效旧结论、下一步注意事项。

**用户身份**：Python 熟手，AI 工具链如 Skill、Codex、MCP 入门。代码细节可以放心讨论，AI 工具链概念按需展开。

**沟通风格**：直接给判断，不堆选项让用户选。有理据时主动指出用户方案的问题，不必要的礼貌让位于决策效率。

**重要边界**：设计阶段已结束，不再开新的架构讨论。所有“要不要重新考虑 X”类问题，先指向“已固化决策”；只有遇到本说明明显未覆盖的新问题才展开。

**身份定位**：在本项目中 ChatGPT 是建造者，不是顾问。优先输出代码、schema、测试，而不是讨论方案。除非用户明确问意见，默认动手。

**代码改动前必先 view**：改 `egs_main.py` 之前先查看当前状态，不基于记忆假设。`egs_main.py` 当前版本以文件为准，不按旧版本提建议。

**v14.2 规则定位**：用户提到任何 v14.2 规则时，先识别该规则属于五段拆解的哪一段，在对应介质里讨论实现，不在原 Markdown 框架里叠加。

**Tushare 已知限制**：当前版本继承的无解限制清单包括 L6 盘中动态止损、调研次数、L1 行业毛利率趋势。不反复提“是否实现”，直接跳过或标记低置信度。

**schema 优先**：任何跨模块传递数据的场合，如 `analysis_input`、`deterministic_report`、state 文件，讨论实现前先讨论字段定义。schema 改动是 breaking change，需明确版本升级。

**回测覆盖要求**：rank 回测必须包含 Rule 6 各项的历史预测力分析。execution 回测必须完整模拟止损、时间止损、熔断、仓位限制、冷静期。

**版本对齐**：项目内所有版本号引用必须以 `egs_main.py` 当前版本为准。旧文档中的旧 EGS 引用，在改动相关文档时顺手更新。

**Phase 完成判定**：每个 Phase 必须有明确完成判定。Phase 1a 完成 = `schemas/analysis_input.schema.json` 通过 JSON Schema 校验且对 v14.2 M0-M6 字段覆盖率 ≥ 90%。

## Phase 2 特别待办

- rank 回测必须单独统计 Rule 6 各否决项的历史预测力。
- 专门检验 `q0_dt_yoy > 200%`、`q1_dt_yoy > 200%`、`esp_raw` 极端值分组的未来 20 日收益。
- 如果低基数高增长标的没有稳定超额收益，在 `esp_raw` 计算中加入 winsorize 或低基数惩罚。
- 统计 `data_quality.completeness_score` 与后验收益的关系，决定低完整度样本是否退出 rank 回测。
- 正式运行无论每周五选股还是正式回测验证，都应刷新 L3；只有搭建/测试阶段可用 `--reuse-l3-cache` 复用共享缓存。
- EGS v7.9 后 `data_quality.completeness_score` 已改为动态计算；v7.9 之前的完整度分组结论不可用。
- 24 期 v7.9 production 回测显示：追高风险、OVERHEAT/LOCK、ESP 低基数、Tier2 filler 是下一批优先优化点。

## 文件参考

- `A-EGS/egs_main.py` — A 股短线筛选引擎，当前 v7.9
- `runners/backtest_rank.py` — Phase 2 rank 回测入口
- `skills/a_short_analysis/reference/v14.2_spec.md` — A 股短线分析框架规格说明书
- `skills/us_short_analysis/reference/us_short_analysis_spec.md` — 美股短线分析框架资料
- `skills/us_short_analysis/reference/us_short_screening_spec.md` — 美股短线预测/筛选框架资料
- `schemas/analysis_input.schema.json` — analysis_input 契约，当前 `1.1.0`，JSON Schema Draft 7
- `schemas/rank_backtest_report.schema.json` — backtest_report 契约，当前 `1.6.0`（Tier1-only 主口径切片）
- `schemas/analysis_input_coverage.md` — schema 覆盖率与修复记录
- `docs/handoff/2026-05-24_phase2_v7.9_handoff.md` — Phase 2 v7.9 交接记录
- `docs/handoff/2026-05-24_phase2_tier1only_subset_handoff.md` — Phase 2 Tier1-only 主口径切片交接记录
- `result/a_short/backtest/Phase2_rank_backtest_findings_codex.md` — 当前有效 Phase 2 findings（codex 视角）
- `result/a_short/backtest/Phase2_rank_backtest_findings_cc_24p.md` — 当前有效 Phase 2 findings（cc 互补合并版，含 OVERHEAT/entry_flag/LOCK 三个负信号 + 2024 vs 2025 regime 拆分）
