# 股票分析系统项目 — AI 协作说明

> 本文件是项目的 AI 协作根入口。**所有 AI 协作者**（Claude Code / Codex CLI / ChatGPT / Cursor / Cline / Aider / 其他 LLM）进入此项目时**必读**。
> Claude Code 用户通过根目录的 `CLAUDE.md` 自动转入本文件；Codex CLI 自动加载本文件；其他工具请用户手动告知。

## 文档路由

先读本文件，再按任务查 `docs/README.md` 的完整 routing table。`AGENTS.md` 只维护最高规则、固化决策、启动顺序和强制流程；不要在这里复制完整文档索引。

常规启动至少读取：

- `docs/README.md`：完整文档路由。
- `docs/CURRENT.md`：当前状态 / 下一步。
- `docs/system_risk_register.md`：未修复的数据 / PIT / schema / execution / security 风险队列；`执行` / `审查` 不得绕过 open P0。
- `docs/SESSION_LOG.md` 顶部 1-3 条：最新跨 LLM 交接、review verdict、pending Optional。
- `docs/AI_REVIEW_PROTOCOL.md`：review 流程和短命令。

## 项目背景

构建 4 套股票分析系统：A 股短线、美股短线、A 股长线、美股长线。每套包含筛选、分析、回测、复盘四组件，共享同一套 engine，通过 preset 配置区分市场和周期。

**资金分布与设计目标**（2026-05-26 用户明确）：

- 顶层市场资金比例 = **A 股 35% / 美股 65%**。
- each market = **1/3 长线 + 1/3 短线 + 1/3 流动资金**（A 股内部 1/3+1/3+1/3，美股内部 1/3+1/3+1/3）。
- A 股 cash 与美股 cash 默认**不互通**；跨市场资金转移必须是显式人工决策或后续 coordinator 规则，不能隐式混池。
- 长线和短线**同等重要**；4 套子系统**全部都是真实需求**，phase 路线图不能让任何一套被长期搁置。
- 跨子系统的 portfolio coordination 是真需求：长短可以共享 cash buffer，但触发规则需明确（如短线熔断时 cash 默认转向长线 averaging-down 而非 short re-entry）。每个 runner 启动前必须能拿到自己 preset 的 capital ceiling，不超过所属 bucket 的 1/3。
- **Ship gate**：每套子系统支持 full-size 手动实盘使用前，必须同时满足多 metric AND：monthly alpha t-stat ≥ 2.0、Sharpe ≥ 1.0、max drawdown ≤ 15%、forward live data ≥ 12 个月。任一不达标时定位为"风控 filter"（仍可 ship 但 sizing 缩到 minimal 或仅跑 paper trade），不能 silent 走 full-size 手动实盘。
- **执行边界**：本系统只做分析、筛选、回测、复盘和报告；用户之后**手动下单**。不得接入券商、操作系统或自动化工具执行自动下单。Phase 5 execution backtest 只模拟交易规则和风控结果，不是 live trading/order execution engine。

## 当前进度

- ✅ A 股短线筛选脚本：`A-EGS/egs_main.py` v7.10 已支持 `--as-of` 历史日期运行
- ✅ A 股短线分析框架：`skills/a_short_analysis/reference/v14.2_spec.md` 已定位为规格说明书，不作为运行时提示词
- ✅ 美股短线资料：已整理到 `skills/us_short_analysis/reference/`
- ✅ 策略设计综合版：`docs/strategy_design_synthesis.md` 已固化为短线双通道 + 长线 alpha 主系统 + research / coordinator 的设计入口
- ✅ Phase 6c burst lane 规格：`docs/burst_lane_spec.md` 已建立 A / US 短线 burst lane docs-only baseline（独立 signal / risk / sizing / ship gate；provider/data audit baseline 已补；provider 选择仍未锁）
- ✅ Phase 6d 长线规格：`docs/long_alpha_spec.md` 已建立长线 alpha 共同规格、US 长线 skeleton、A 股长线 skeleton（docs-only；provider/data audit baseline 已补；provider 选择仍未锁）
- ✅ Phase 6d US-short 规格：`docs/us_short_spec.md` 已把 `skills/us_short_analysis/reference/` 资料规范成 production-facing docs-only baseline（provider / DataHub / runner / Skill 尚待后续）
- ✅ Phase 6e provider/data requirements audit：`docs/provider_data_requirements_audit.md` 已汇总 4 套系统字段、PIT、频率、lineage、授权/成本、稳定性和 fallback 要求（docs-only；不锁最终 provider）
- ✅ Phase 7 provider capability / field catalog contract：`schemas/provider_capability_catalog.schema.json` v1.0.0 已建立 schema-first contract（不选 provider、不抓数据、不建 adapter / DataHub table）
- ✅ Phase 7a alpha-validation route：`docs/alpha_plausibility_audit.md` 与 `docs/evidence_capital_policy.md` 已建立设计路由；后续在大规模 DataHub / runner implementation 前，先用 schema-first alpha audit 判断 lane objective / provider priority / evidence horizon，并用 paper vs live-normalized evidence policy 约束 ship-gate 证据
- ✅ Phase 7a+ alpha reality action guide：`docs/ALPHA_VALIDATION_ACTION_GUIDE.md` 已固化为当前最高行动指南；Phase 7a-1 必须把 survivorship / multiple testing / statistical power / regime / factor exposure / execution-cost feasibility / risk-filter evidence / decision effect 写进 schema-first audit
- ✅ Phase 7a-3 provider priority / provisional benchmark contract：`docs/provider_priority_benchmark_contract.md` 已把 provider evidence queue 与 provisional evidence benchmark 固化为 docs-only contract（不选 provider、不抓数据、不建 adapter / DataHub table、不锁最终 ship-gate benchmark）
- ✅ Phase 7a-4 evidence feasibility controls：`docs/evidence_feasibility_controls.md` 与 `schemas/evidence_feasibility_controls.schema.json` 已固化 burst minimal-to-full promotion、evidence capital、concentration / liquidity / ADV、slippage / borrow / limit-risk、circuit-breaker playbook contract（不选 provider、不抓数据、不改 runner）
- ✅ Phase 7a-5 evidence report schema contract：`docs/evidence_report_schema_contract.md` 与 `schemas/evidence_report.schema.json` 已固化 immutable decision packet、cost-adjusted return、cash drag、manual override、minimal reconciliation、thesis outcome log、research experiment log contract（不选 provider、不抓数据、不改 runner）
- ✅ Phase 7b-1 provider evidence / drift monitor schema-first contract：`docs/provider_evidence_drift_monitor.md` 与 `schemas/provider_evidence_drift_monitor.schema.json` 已把 P1-P4 provider evidence queue、provider readiness rollup 与 drift-monitor dimensions/action set 固化为 contract（不选 provider、不抓数据、不建 adapter / DataHub table）
- 🟡 Phase 7b-2 P1 US evidence snapshots + readiness review matrix + access/sample plan：六份 P1 snapshot 已基于官方 SEC / Nasdaq / MSCI / S&P DJI / S&P Global / LSEG / Massive / Polygon / Norgate / Intrinio / FMP 文档记录 candidate evidence；`schemas/provider_p1_readiness_review.schema.json` / `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json` 已固化 field-by-field blocker disposition；`schemas/provider_p1_access_decision_plan.schema.json` / `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` 已把 cost ceiling、access path、license / storage、sample rows、coverage counts、fallback / incident gate 固化为 plan-only artifact。Approved spend = 0；仍不授权 provider selection / contact / token / trial / paid access / sample fetch / data fetch / Phase 7c；A-share `minimal_data_burst` 原 preregistration 继续 `BLOCKED_DO_NOT_RUN`，corrected-basis supersession 已因 `valid_signal_events = 0` 不得 outcome-run，full-universe redesign preflight 已过 event-count（134）但未算 outcome / excess；`SR-DATA-003` benchmark-open input 已由 benchmark-only local cache patch 补齐，下一步 outcome / excess 仍必须单独 reviewed slice。
- ✅ Phase 1a：`schemas/analysis_input.schema.json` 已完成，当前输出 schema 版本 `1.1.0`
- ✅ Phase 1b：`egs_main.py` 已接入 `analysis_input.json`、`snapshot.json`、`candidates.csv` 导出器
- ✅ 项目目录：已按 engine/shared + preset/state/skill/result 分离原则建立骨架
- ✅ Phase 2：`runners/backtest_rank.py` 已跑通 24 期 production rank 回测；工程链路通过，策略优化继续推进
- ✅ L3 概念缓存：正式运行默认刷新 L3；搭建/测试阶段可用 `--reuse-l3-cache` 复用共享缓存加速
- ✅ Phase 4 minimal：`deterministic_report` schema、纯 Python runner、coverage doc、Skill 使用文档、prompts 骨架、LLM enrichment patch schema/example 已落地

## 三条不可动摇的原则

1. **v14.2 是规格说明书，不是运行时提示词。** 所有规则拆到代码、配置、状态、Skill、提示词五个介质。
2. **先把 A 股短线做成完整可复用样板**，即 Phase 1-6 全跑通并完成一个季度 forward/paper 或 minimal-size 手动观察；full-size 手动实盘使用仍必须满足 Ship gate（含 ≥12 个月 forward live data），不能把一季度工程闭环误读为 full-size 放行。
3. **回测分两层。** rank 回测先做，execution 回测后做。

## Reference framework policy

- `skills/a_short_analysis/reference/` 下的 Markdown 是 **A 股短线分析框架参考源**，其中 `v14.2_spec.md` 是规格说明书，不是运行时提示词。
- `skills/us_short_analysis/reference/` 下的两个 Markdown 是 **美股短线选股框架** 与 **美股短线分析框架参考源**。
- A 股短线框架与美股短线框架虽然都可能使用 `v14.x` 版本号，但它们是两套独立框架；不是前后版本关系，也不能把一个市场的 v14.x 当作另一个市场的升级版或替代版。
- 这些 reference 文档原始目标是 AI chatbox 工作流。后续做 schema、runner、analyzer、Skill、prompt 或 preset 设计时，必须参考其业务逻辑、流程结构和判断维度，但不能机械照搬为运行时提示词或代码规则。
- US-short normalized spec 已在 `docs/us_short_spec.md` 建立；reference docs 继续作为源资料归档，`skills/us_short_analysis/SKILL.md` 在 Phase 7 / Phase 8 前仍保持 reserved。
- 可确定、可回测、可结构化的规则应拆入 Python / schema / config / state；需要语义判断、新闻理解、行业判断的部分才进入 Skill prompts。
- 长线共同规格、US 长线 skeleton、A 股长线 skeleton 已在 `docs/long_alpha_spec.md` 建立；provider/data audit baseline 已在 `docs/provider_data_requirements_audit.md` 建立；后续 provider 选择、schema 和 implementation 仍待后续 Phase。不得用短线框架硬套长线系统。

## Strategy design synthesis policy

- 详细设计入口是 `docs/strategy_design_synthesis.md`；本节只保留所有 LLM 必须遵守的摘要。
- 当前 Phase 7a+ 执行以 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` 为最高行动指南；若旧 roadmap / handoff / design note 与该指南冲突，除 `AGENTS.md` 固化治理规则外，以该指南为准，除非用户明确批准更新的反转。
- 短线系统不再被定义为 alpha 主引擎；短线 = 稳健风控过滤 + bounded variants + 独立 `burst_lane`。A 短现有主通道不得为追爆发力而整体放松风控。
- A 短优化先走有限 variants：追高 veto、OVERHEAT veto、Tier1-only trading、ESP cap/winsorize、rank bucket split、exit policy variants。variant promote 必须有 forward evidence，不得凭单次回测直接替换主策略。
- `burst_lane` 是独立爆发力通道，必须有自己的 signal spec、risk lock、sizing gate 和 ship gate。详细 baseline 在 `docs/burst_lane_spec.md`。Production sizing 按阶段推进：paper 可模拟 30% of relevant short bucket；minimal live <=10%；6 个月 preliminary pass <=20%；12 个月独立 ship gate pass 后才可到 30%。
- 长线系统是 push alpha 的主战场。A 长 / US 长从头设计为 `core quality compounding` + `re-rating / catalyst long` 两层，不复用短线 v14.x 规则。
- 长线阈值必须行业归一化：A 股默认 SW L2 + 5 年滚动，样本 <20 回退 SW L1；美股默认 GICS industry + 5 年滚动，样本 <20 回退 GICS industry group。
- `research/` 允许更快实验，但必须记录 data lineage / parameters / seed / experiment log。Research 输出不得直接喂 production runner；进主线必须 schema-first + tests + review。
- Cross-system coordinator 先写 spec 后实现，只生成手动建议，不自动调仓、不接券商、不混池 A/US cash。
- Phase 7 broad implementation 前必须先做 alpha plausibility audit：每条 lane 需明确 alpha source、expected excess / vol / drawdown、data/PIT/provider blockers、detectability horizon、portfolio contribution 和 continue / risk-filter / redesign / defer / do-not-implement verdict。Audit 结果必须 schema-first，不得只是主观 Markdown 判断。
- Phase 7a-1 audit schema 必须覆盖 alpha 真实性护栏：provider status snapshot、parent aggregation、risk-filter effectiveness、correlation basis、hypothesis registration、multiple testing、statistical power、PIT/survivorship/security master、fraud/accounting red flags（长线必填）、regime sensitivity、factor framework、gross vs net alpha、execution-cost feasibility、decision effect / bucket deployment interface。
- A-short steady 默认永久定位为 risk filter / evidence loop；A-short variants 主要用于 bad-ticket / drawdown / execution-quality 改善。短线 alpha 期望主要由 A/US burst lanes 承担，且 burst 分 minimal-data paper tier 与 full-data live-eligible tier。
- Evidence capital 不改变资金政策：禁止 temporary global AUM pool、禁止自动跨市场/跨 bucket pooling。Paper evidence 只能做设计迭代 / preliminary comparison；full-size ship gate 只能接受稳定流程下的 live-normalized forward evidence，并记录 capacity / slippage / scaling validity。
- 后续 implementation / operation 漏洞不再开新 design loop，直接挂到既有 phase：data quality / provider drift 进 Phase 7b/7c；immutable decision packet、cost-adjusted return、cash drag、manual override、minimal reconciliation、thesis outcome log 进 Phase 7a-5；production monitoring / kill switch 进 Phase 8；coordinator、unified report、cross-lane conflict、alert priority 进 Phase 9。

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
| 3+ | minimal analyzer + state 接口同步建立 | 1-2 周 | ✅ |
| 4 | minimal Skill：读 input，调 analyzer，出 M6.7 | 3-5 天 | ✅ minimal 完成 |
| 5 | P0a capital context contract + A 股短线 execution/fill 回测 | 1-2 周 | ✅ minimal 完成 |
| 5b | Ship gate policy + preliminary gate status（非 full-size 最终放行；full-size 仍需 ≥12 个月 forward live data） | 1-2 天 | ✅ preliminary 完成 |
| 6a | Phase 6 boundary kickoff：forward evidence、benchmark、记录格式、steady/variant/burst/long-spec 边界 | 1-2 天 | ✅ |
| 6b | A 股短线 maintenance / evidence line：weekly forward capture、comparison-track accumulator、forward evidence accumulation；不扩新小工具，除非直接服务 evidence clock | 观察期 | ⬜ |
| 6c | A / US 短线 `burst_lane` spec：共用 signal family、市场字段差异、独立 risk lock / sizing gate / ship gate | 2-4 天 | ✅ docs-only baseline |
| 6d | 长线 alpha spec pack：long alpha common spec + A-long annex + US-long annex + US-short spec normalization | spec 设计 | ✅ docs-only baselines |
| 6e | Provider / fundamentals data requirements audit：列出 A/US long、A/US burst、US-short 所需字段、PIT、频率、lineage、授权/成本/稳定性要求；不在本步锁最终 provider | 2-4 天 | ✅ docs-only baseline |
| 7a-1 | Alpha plausibility audit schema / example / tests + lightweight provider status snapshot + first audit；按 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` 写入 alpha 真实性护栏 | 2-4 天 | ✅ |
| 7a-2 | 根据 audit 修订 long / short specs；补 US microstructure、monitoring contract、calendar / timezone semantics | 1-3 天 | ✅ |
| 7a-3 | Provider priority reorder + provisional benchmark contract | 1-2 天 | ✅ docs-only baseline |
| 7a-4 | Burst minimal→full promotion criteria + evidence capital schema + concentration / liquidity / ADV sizing + slippage constraints + drawdown / circuit-breaker playbook | 2-4 天 | ✅ schema-first baseline |
| 7a-5 | Evidence report schemas：immutable decision packet、cost-adjusted return、cash drag、manual override、minimal reconciliation、thesis outcome log、research experiment log | 2-4 天 | ✅ schema-first baseline |
| 7b-1 | Provider evidence / drift monitor schema-first contract（P1-P4 queue、readiness rollup、drift dimensions/actions；不抓真实 provider data） | 1-2 天 | ✅ schema-first baseline |
| 7b-2 | Provider capability evidence population：按 P1-P4 读取/核验 provider 文档、字段、PIT、coverage、cost、fallback、stability 证据；不默认选择 provider、不建 adapter / DataHub table | 1-2 周 | 🟡 P1 six snapshots + readiness matrix + access/sample plan complete；provider access still needs explicit user-approved cost / license boundary |
| 7c | DataHub shared layer / report contracts / reproducibility plumbing：先写 schema-first contract；implementation 另起 reviewed slice | 1-2 周 | ⬜ |
| 8 | 四套子系统 implementation wave：按资金权重 × alpha leverage × data readiness 排序；每条 lane 配 production monitoring / kill switch | 2-4 周 | ⬜ |
| 9 | Cross-system coordinator：unified daily / weekly report、cross-lane conflict resolution、full position reconciliation、alert priority | 2-4 周 | ⬜ |

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
10. 资金分布固化为 A 股 35% / 美股 65%；each market = 1/3 长线 + 1/3 短线 + 1/3 流动资金；A 股 cash 与美股 cash 默认不互通。4 套子系统同等重要；phase 路线图不能让任何一套被长期搁置；每套支持 full-size 手动实盘使用前必须通过多 metric AND ship gate，alpha 不足则定位为风控 filter。详 §项目背景。
11. 系统执行边界固化为分析筛选 + 回测复盘 + 报告输出；用户手动下单。不得接入券商、操作系统或自动化工具做自动下单；execution backtest 只是模拟规则，不是 live trading/order execution engine。
12. 路线图采用 B 半重排的修订版：Phase 6 采用 **spec 层并行 + implementation 层串行受控**。A 股短线 Phase 6b 不停止，但降为 maintenance / evidence line（weekly forward capture、comparison-track accumulator、forward evidence accumulation）；同时前置 A/US `burst_lane` spec、long alpha common spec、A-long annex、US-long annex、US-short spec normalization、provider/data requirements audit。Phase 7 DataHub / engine 重构必须以 4 套 spec + provider/data requirements audit 为依据。Phase 8/9 implementation 不再按原固定顺序推进，而按 `资金权重 × alpha leverage × data readiness` 排序：默认倾向 US-long 优先；若 US provider / fundamentals readiness 不足，A-long 或 US-short burst 可前置。数据准备度只作触发条件，不写死门槛；不得因 spec 并行而启动 implementation 层并行、降低 ship gate、跳过 A-short forward evidence，或把 DataHub 工程误读为 alpha 本身。
13. 策略设计综合版采用 `docs/strategy_design_synthesis.md`：短线 = 稳健通道 + 有限 variants + 独立 `burst_lane`；长线 = `core quality compounding` + `re-rating / catalyst long` 的 alpha 主系统；research 快迭代但不可直连 production；coordinator 只给手动建议。
14. Phase 7 implementation 顺序采用 alpha-leverage-first，不再默认从已证明的 A-share EOD / benchmark surface 消耗下一刀资源；Phase 7a schema-first audit / routing / feasibility / report contracts 与 Phase 7b-1 provider evidence / drift monitor contract 已建立。Phase 7b-2 已有 P1 US public-source、market-data-candidate、authorization / cost / stability、benchmark / GICS、fundamentals observed-date、coverage / fallback / incident candidate evidence snapshots，并已由 P1 readiness review matrix 做 field-by-field blocker disposition；P1 access-decision / sample-validation plan 只定义 cost / access / license / sample / coverage / fallback gates，approved spend = 0，且不授权 provider contact、token、trial、paid access、sample fetch、data fetch、provider selection 或 Phase 7c。SEC / Nasdaq / MSCI / S&P DJI / S&P Global / LSEG / Massive / Polygon / Norgate / Intrinio / FMP docs 不等于完整 provider selection、PIT security master、licensed benchmark return feed、field-level fundamentals PIT construction、sample-row validation、fallback playbook、incident-stability 或 production readiness。后续 Phase 7c DataHub / report / reproducibility work 必须消费 reviewed P1-P4 provider evidence 与 drift-monitor contract，不能把 P4 ready helper surface 当作 broad implementation 起点。
15. Phase 7a+ 最高行动指南采用 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`：所有后续 schema / provider / DataHub / runner / report / live evidence 工作必须先证明 alpha 真实性边界，不得跳过 survivorship、multiple testing、statistical power、PIT/security master、fraud red flags、regime sensitivity、factor exposure、execution cost、decision reproducibility、position reconciliation 和 production monitoring 等护栏。

## AI 协作者在本项目中的工作守则

## System risk register discipline

`docs/system_risk_register.md` 是所有未修复系统风险的 durable queue。任何 LLM 发现影响 data integrity、PIT safety、schema contract、execution simulation、security、ship-gate evidence 或 cross-LLM continuity 的实质问题时，必须在同一轮内二选一：修复并验证，或写入该 register。不得只把发现留在 chat / SESSION_LOG / 临时审查文字里。

`执行` 前必须检查 register；open P0 风险默认优先于普通 roadmap work，除非用户明确批准更窄的 override。`审查` 必须确认新发现已被修复或入 register；若漏记 material finding，审查不能给 clean Pass。

## Multi-LLM Review Protocol

Codex acts as the Designer + Implementer.

Claude acts as the Independent Reviewer.

The user remains the Final Approver.

Detailed review workflow is defined in `docs/AI_REVIEW_PROTOCOL.md`.

Codex-to-Claude review handoff lives in the top SESSION_LOG entry written by Codex after each `执行` / `修复`; no separate review packet file (as of 2026-05-25).

`AGENTS.md` remains the highest-level project rule. If `docs/AI_REVIEW_PROTOCOL.md` conflicts with this file, `AGENTS.md` wins.

## Short Command Aliases

This project supports short command aliases defined in `docs/AI_REVIEW_PROTOCOL.md`.
Detailed command expansions live only in `docs/AI_REVIEW_PROTOCOL.md` to avoid drift.

Common aliases:
- `执行` = Codex executes the next approved smallest task and prepends a SESSION_LOG entry. Does not commit.
- `审查` = Claude reviews the current uncommitted working tree using the top SESSION_LOG entry plus `docs/AI_REVIEW_PROTOCOL.md` mandatory fast path; Claude must not directly modify business code.
- `批准修改` = User approves pending Required fixes only. Optional suggestions are not user-approved — Codex disposes of them during `修复` (see `docs/AI_REVIEW_PROTOCOL.md` §修复).
- `修复` = Codex repairs user-approved Required fixes + disposes of each Optional suggestion from the latest Claude review (accept / accept with modification / reject + reason). Records dispositions in SESSION_LOG. Does not commit.
- `提交` = Codex commits the reviewed working tree as a single coherent commit after Claude `审查` returns Pass. Not used during `执行` / `修复`. See `docs/AI_REVIEW_PROTOCOL.md` §Commit Timing Rule.

Claude 审查 fast path lives in `docs/AI_REVIEW_PROTOCOL.md §Review Continuity Without Packet` / `§Working Tree Completeness Guard`: before any verdict, Claude must run `git status --short`, inspect `git diff`, read every `??` untracked file body, and read `docs/SESSION_LOG.md` top 1-3 entries. `docs/AI_REVIEW_PROTOCOL.md` owns the full mandatory steps and staged-change add-on.

`AGENTS.md` remains the highest-level project rule. If any alias conflicts with `AGENTS.md`, `AGENTS.md` wins.

## 交接记录

任何 AI 助手，包括 ChatGPT、Codex 或其他 LLM，继续 Phase 2 / Phase 3、A 股短线筛选、rank 回测、analyzer、state、`A-EGS/egs_main.py`、`runners/backtest_rank.py`、`analysis_input.json` 或 findings 相关工作前，**按时间顺序读取以下 handoff**：

1. `docs/handoff/2026-05-24_phase2_v7.9_handoff.md` — EGS v7.8/v7.9 的脚本修改、正式周五实盘重跑、24 期 production 回测验收、当前有效 findings、下一步策略优化优先级
2. `docs/handoff/2026-05-24_phase2_tier1only_subset_handoff.md` — Tier1-only 主口径切片实施、stats CSV 加 `subset` 列、schema 升 1.6.0、settings.primary_subset 字段
3. `docs/handoff/2026-05-24_phase2_git_init_handoff.md` — **项目首次进入 git 管理**（初始为私密本地仓库；2026-05-26 起允许受约束 private remote）、`.gitignore` 排除清单、commit hash `dca8367`、git 私密性约束
4. `docs/handoff/2026-05-24_phase2_validation_tooling_handoff.md` — EGS v7.10、rank backtest schema 1.8.0、split/variant/eligible benchmark/T+1 不可买/portfolio stats/reason observability
5. `docs/handoff/2026-05-24_phase2_6_datahub_guardrail_handoff.md` — Phase 2.6 DataHub guardrail，固定“先补 lineage、不做大重构”的边界
6. `docs/handoff/2026-05-24_phase2_24p_v710_results_handoff.md` — v7.10 24 期 production 实跑结果、schema 校验、核心 findings 和结论边界
7. `docs/handoff/2026-05-24_phase2_tier1_count_warning_handoff.md` — rank backtest schema 1.9.0，report 增加日期级 Tier1-count 告警
8. `docs/handoff/2026-05-24_phase2_data_lineage_handoff.md` — rank backtest schema 1.10.0，新增 `data_lineage` 对象，Phase 2.6 lineage 闭环
9. `docs/handoff/2026-05-24_phase3_kickoff_spec_handoff.md` — Phase 3 开工规格：minimal veto analyzer + JSON state + replay/ablation 完成线（含 3.3 子分数预测力 + 3.4 ESP 反向 PIT 调查 + 3.5 实盘 forward tracker）
10. `docs/handoff/2026-05-25_phase4_kickoff_spec_handoff.md` — Phase 4 开工规格：deterministic_report schema first + runner 纯 Python + Skill 是使用文档（非执行入口）
11. `docs/handoff/2026-05-25_phase5_kickoff_spec_handoff.md` — Phase 5 kickoff 规格：execution backtest contract 边界；schema / runner / simulator 代码尚未开始
12. `docs/handoff/2026-05-26_phase6a_kickoff_spec_handoff.md` — Phase 6a 开工边界：forward evidence、A 短 benchmark sensitivity、forward tracker → aggregate evidence flow、steady/variant/burst/long-spec 边界
13. `docs/handoff/2026-05-27_phase7_kickoff_spec_handoff.md` — Phase 7 开工边界：provider capability / field catalog contract v1.0.0；schema-first，不选 provider、不抓数据、不建 adapter / DataHub table

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

## Git remote privacy policy

本项目允许推送到用户本人控制的 **private** Git remote，但必须满足以下硬约束：

- 默认仍按本地仓库处理；只有用户明确要求添加 remote 或 push 时，AI 协作者才可执行相关 git remote 操作。
- 远程仓库必须是 private；禁止 public / internal 公开范围不明的仓库，禁止添加 collaborator，除非用户另行明确授权。
- 允许的用途是私密备份、跨设备同步和用户个人版本管理；不得把 private remote 当作共享发布渠道。
- 添加 remote 或 push 前必须先检查：`git status --short`、`git remote -v`、`.gitignore` 覆盖范围，以及 staged / tracked 文件中是否有 token、secret、credentials、日志、缓存、实盘状态或大体量结果产物。
- 禁止上传：`TUSHARE_TOKEN` 或其他 API key / token / credentials、`.env*`、`logs/`、可再生缓存、`state/*/l3_snapshots/`、未脱敏实盘状态、个人账户信息、以及 `.gitignore` 已排除的结果或临时文件。
- `git remote add` / `git push` 仍属于高风险操作；AI 协作者执行前必须得到用户明确指令，并遵守当前工具环境的审批机制。

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
- `docs/us_short_spec.md` — Phase 6d US-short steady-lane normalized spec（docs-only；不锁 provider / runner / schema / Skill）
- `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` — Phase 7a+ 最高行动指南（alpha 真实性、业务漏洞、执行路线和后续 phase 挂载）
- `docs/alpha_plausibility_audit.md` — Phase 7a alpha plausibility / lane objective owner（schema-first audit route；决定 continue / risk-filter / redesign / defer / do-not-implement）
- `docs/evidence_capital_policy.md` — Phase 7a paper vs live-normalized evidence owner（不改变资金政策；ship gate 证据必须区分 paper / live_normalized）
- `docs/provider_priority_benchmark_contract.md` — Phase 7a-3 provider evidence priority / provisional benchmark owner（不选 provider；不锁最终 ship-gate benchmark）
- `docs/evidence_feasibility_controls.md` — Phase 7a-4 burst promotion / concentration / liquidity / slippage / circuit-breaker owner
- `schemas/evidence_feasibility_controls.schema.json` — Phase 7a-4 evidence feasibility controls 契约，当前 `1.0.0`
- `docs/evidence_report_schema_contract.md` — Phase 7a-5 evidence report schema owner
- `schemas/evidence_report.schema.json` — Phase 7a-5 evidence report 契约，当前 `1.0.0`
- `docs/provider_evidence_drift_monitor.md` — Phase 7b-1 provider evidence / drift monitor contract owner；Phase 7b-2 evidence population 需消费它
- `schemas/provider_evidence_drift_monitor.schema.json` — Phase 7b provider evidence / drift monitor 契约，当前 `1.1.0`
- `docs/provider_evidence_p1_us_public_sources_20260528.json` — Phase 7b-2 P1 US public-source provider evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_market_data_candidates_20260528.json` — Phase 7b-2 P1 US market-data-candidate provider evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json` — Phase 7b-2 P1 US authorization / cost / stability provider evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json` — Phase 7b-2 P1 US benchmark / GICS candidate evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json` — Phase 7b-2 P1 US fundamentals observed-date candidate evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json` — Phase 7b-2 P1 US coverage / fallback / incident candidate evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `schemas/provider_p1_readiness_review.schema.json` / `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json` — Phase 7b-2 P1 readiness review matrix（collection complete；Phase 7c / provider selection / data fetch blocked）
- `schemas/provider_p1_access_decision_plan.schema.json` / `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` — Phase 7b-2 P1 access-decision / sample-validation plan（plan-only；approved spend = 0；provider access / sample / data / Phase 7c blocked）
- `schemas/research_preregistration.schema.json` / `schemas/research_preflight_result.schema.json` / `schemas/program_test_budget_ledger.schema.json` / `research/preregistrations/a_share_minimal_data_burst_20260531.json` / `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json` / `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json` / `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json` / `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json` / `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` — research-only preregistration, preflight, and ledger artifacts（不进 production、不声称 ship-gate evidence；outcome / excess 必须单独 reviewed slice）
- `schemas/analysis_input.schema.json` — analysis_input 契约，当前 `1.1.0`，JSON Schema Draft 7
- `schemas/deterministic_report.schema.json` — deterministic report 契约，当前 `1.0.0`，Phase 4 runner 输出 JSON 必须通过该 schema
- `schemas/rank_backtest_report.schema.json` — backtest_report 契约，当前 `1.11.0`（含 date_warnings + data_lineage + analyzer veto replay）
- `schemas/provider_capability_catalog.schema.json` — Phase 7 provider capability / field catalog 契约，当前 `1.0.0`（schema-first；不锁最终 provider / adapter / DataHub table）
- `schemas/examples/provider_capability_catalog.example.json` — Phase 7 provider capability catalog 示例（验证 schema；不是生产 provider registry）
- `schemas/analysis_input_coverage.md` — schema 覆盖率与修复记录
- `docs/burst_lane_spec.md` — Phase 6c A / US 短线 burst lane docs-only baseline（独立 signal / risk / sizing / ship gate；不继承 steady lane gate）
- `docs/long_alpha_spec.md` — Phase 6d 长线 alpha 共同规格与 A / US 长线 skeleton（docs-only；不锁 provider / runner / schema）
- `docs/provider_data_requirements_audit.md` — Phase 6e provider / data requirements audit（docs-only；不锁最终 provider / schema / DataHub implementation）
- `docs/handoff/2026-05-24_phase2_v7.9_handoff.md` — Phase 2 v7.9 交接记录
- `docs/handoff/2026-05-24_phase2_tier1only_subset_handoff.md` — Phase 2 Tier1-only 主口径切片交接记录
- `docs/handoff/2026-05-24_phase2_git_init_handoff.md` — Phase 2 git init 交接记录（初始 local-only；2026-05-26 amendment 允许受约束 private remote）
- `docs/handoff/2026-05-24_phase2_validation_tooling_handoff.md` — Phase 2 验证工具升级交接记录
- `docs/handoff/2026-05-24_phase2_6_datahub_guardrail_handoff.md` — Phase 2.6 DataHub guardrail 交接记录
- `docs/handoff/2026-05-24_phase2_24p_v710_results_handoff.md` — Phase 2 v7.10 24 期 production 实跑交接记录
- `docs/handoff/2026-05-24_phase2_tier1_count_warning_handoff.md` — Phase 2 Tier1-count 日期告警交接记录
- `docs/handoff/2026-05-24_phase2_data_lineage_handoff.md` — Phase 2 data_lineage 交接记录（schema 1.10.0，Phase 2.6 闭环）
- `docs/handoff/2026-05-24_phase3_kickoff_spec_handoff.md` — Phase 3 开工规格交接记录（minimal veto analyzer + JSON state + replay/ablation）
- `docs/handoff/2026-05-25_phase4_kickoff_spec_handoff.md` — Phase 4 开工规格交接记录（deterministic_report schema first + runner-as-executor + Skill-as-doc）
- `docs/handoff/2026-05-25_phase5_kickoff_spec_handoff.md` — Phase 5 kickoff 规格交接记录（execution backtest contract 边界；代码未开始）
- `docs/handoff/2026-05-27_phase7_kickoff_spec_handoff.md` — Phase 7 kickoff 规格交接记录（provider capability / field catalog contract）
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
