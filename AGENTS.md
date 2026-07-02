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

## 审查输出/落盘短入口（Codex 必读）

用户下达 `审查` 或要求按审查流程收口时，Codex 在发送最终回复前必须先完成落盘：把 `docs/SESSION_LOG.md` 顶部、`REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER` 之上 prepend 一条极简 review-cycle entry（`Verdict/Action` / `Required` / `Verify` / `Next`）；material Required 的完整细节只写 `docs/system_risk_register.md`。

屏幕最终回复固定三段且只用这三段：`Verdict`、`Required / Optional / Options`、`下一步`。不再输出 `Findings` 段，也不单列“已验证 / Verify / 验证”项；无内容写“无”；不要另起“覆盖范围 / 验证 / 结论边界 / Findings”等额外栏目。**大白话只放在前两段**：`Verdict` 用单独一行 `大白话：…` 说明能不能过；`Required / Optional / Options` 下每条具体项都带单独一行 `大白话：…` 说清后果或怎么选；`下一步` 只写一行最简单给另一个 LLM 的命令，如 `Claude Code：Pass`、`Claude Code：修复`、`Claude Code：执行`，不写 `大白话`、不写解释，具体指示放 `docs/SESSION_LOG.md` / `docs/system_risk_register.md`。`审查` PASS 后 Codex 自动提交已审查工作树，`下一步` 不再指示 Claude `提交`；Claude 只实现/修复。任何 `FAIL` / `Required` 用「技术标识 + 技术现状 + 大白话」三件套。完整规则见 `## 输出结论规则`。

若没有写入 SESSION_LOG 极简 entry，Codex 不得发送 `审查` 最终回复。详细规则见 `### Codex review closeout gate` 与 `### 评审循环 entry 极简模板`；本短入口只防漏读，不另立第二套规则。

**Route-doc 稳定性约定 (v3)**：**单一 live-state 真相源 = `docs/SESSION_LOG.md` 顶部最新 verdict + artifact 本身**(ledger 的 `tests_spent_count`、`research/results/.../execution_summary.json`)。

- `docs/CURRENT.md` **§0 Latest Delta** 是**唯一**允许重述当前态的短摘要(每轮更新),但**只放已 settled 的事实**(verdict / 度量 / ledger 已花 / 线已关闭 / 下一步目标);**实时 review/commit-cycle gate(pending review / before commit / 谁审谁提交 / routed-to / uncommitted / 在飞的 PASS·FAIL)绝不进 `CURRENT` 任何位置(含 §0 与 header)——只进 `docs/SESSION_LOG.md` 顶部**。这是 v2 的修正:v2 曾允许 §0 含 pending / 下一步周期词,导致 `result-closeout 待 Codex 审查` 这类 gate 词在 commit 后立即陈旧(`R-EP-CURRENT-TRANSIENT-GATE-WORDING`)。"下一步目标"指 settled 的研究方向(如"下一步 batch+FDR"),不是"下一条命令是谁的 `审查`/`提交`"。
- 其余 durable 路由(`docs/README.md`、`research/README.md`、`docs/CURRENT.md` §1/§5)只写**稳定身份 + 指针**——存在什么 artifact、什么设计、文件在哪、anti-rescue / singleton 等不变规则——并指向真相源。
- **README route row = 薄指针(机器焊死,反膨胀)**:`docs/README.md` 每条路由行的描述列(col1)只写 `主题 + 一句话 + 关键不变式`;**契约细节去 module docstring、设计/边界去 owner doc(如 `docs/us_short_system_design.md`)+ register、测试枚举去 test 文件**——README 不当第二份契约书。光靠本规范必逐刀重新膨胀(实证多次),故由 `tests/test_readme_route_row_length.py` 机器 enforce:任何路由行 col1 超 cap(350 字)即 FAIL;当前已存在的 over-cap **稳定历史行**(a_short / a_long / Phase / Production)经整行 sha256 grandfather 放行(原样不动即过,一旦改它即须压到 cap);新增行 / US-short·US-long 已压行 / 任何非 grandfather 行都吃 cap。col2 文件列**不**限长。
- **禁止**在这些 durable 行重述会漂移的状态:瞬态周期词(`UNCOMMITTED` / `in re-review` / "下一步是 `审查`" / 在飞的 `PASS`·`FAIL`)、ledger 计数、pending gate、verdict 度量(t 值 / drawdown / cohort 数)。
- **terminal 终态可留,但低频 + 指针化**:不会再变的事实(路径已关闭、singleton 已花、最终 verdict 已定)可写**一行指针**(例:"`cash_conversion` 已执行 → `statistical_alpha_clue`(非 tradeable),见 `research/results/.../execution_summary.json`"),但**绝不**把度量 / pending 在三处重复。
- **漂移自检**:写每句 durable 路由前问"这句在下一次 commit / execute 之后还成立吗?"——**不成立的 review/commit-cycle gate(谁审 / 谁提交 / 下一条命令 / pending / before-commit / uncommitted,及其同义改写)只进 `docs/SESSION_LOG.md` 顶部,绝不进 `CURRENT`(含 §0)**;只有"已 settled 且值得重复"的短事实(verdict / 已花 / 已关闭)才可进 `CURRENT §0`。(与 §20、§28 一致;旧版"→ SESSION_LOG + CURRENT §0"的写法已废,它正是 `R-EP-CURRENT-GATE-SYNONYM-GUARD-GAP` 的矛盾源。)
- **状态转变过时是真正的复发根因**:此类 drift 已被 Codex 抓 ≥5 次(`R-CURRENT-POST-COMMIT-ROUTE` → `R-CASH-*-ROUTE-*` → `R-LOWVOL-ROUTE-LEDGER-STATUS-DRIFT`)。机制不是"复审周期瞬态词",而是:一行**写时正确**,但它描述的线**后来执行/花掉 ledger**,该行没被回扫就变错;且每轮只更新"当前线",**兄弟行的过时悄悄累积**。`research/README.md` 的 "Current result / ledger status" 节最易中招。
- **机器强制 (v2.2)**:仅靠"记得遵守"在多 LLM / 跨会话下必然失守,所以必须跑机器校验——`tests/test_route_doc_ledger_status_consistency.py` 读每个 `*_program_test_budget_ledger_*.json` 的真实 `tests_spent_count`,若已花(>0)而任一 route-doc 行(`research/README.md` / `docs/README.md` / `docs/CURRENT.md`)仍以 "zero spent / one pending / planned not-reviewed / spends this singleton once / no valid … result" 等未花措辞引用该已花线,则 FAIL。引用不只按 ledger 文件名判断,还必须覆盖该线的 preregistration / result / runner / schema / packet aliases,否则 contract 行、runner 行、兄弟行会逃过检查。**每次 `执行` / 收尾、以及改任何 route-doc 行后必跑此测试再交 `审查` / `提交`**;它把"状态转变过时"从事后人肉抓变成过不了测试。**(v2.3)** 同测试再加两道**与位置无关**的 `CURRENT` 扫描:(a) §1/§5 durable 指针区出现 verdict 度量(backtick 小数 / `HAC t` / `mean net excess` / cohort 数)即 FAIL;(b) **整篇 `CURRENT`(header / preamble / §0 / 任意节)**出现 review/commit-cycle gate 词(`待 Codex` / `待审查` / `pending` / `awaiting` / `routed to Codex` / `result-closeout` / `before … commit` / `uncommitted`)即 FAIL。早先的 guard 都是**按节 / 按 ledger 文件名**作用域,所以同类 drift 每轮换个未覆盖的位置就逃掉(`research/README` → contract 行 → §1/§5 → header/§0);**整篇扫描是位置无关的根治**——drift 无处可搬。**(v2.4)** 整篇 `CURRENT` gate 扫描再加**同义改写**(`下一条命令` / `谁审` / `谁提交` / `谁执行` / `由 Codex 审` / `Claude 提交` / `Claude 执行` 等,堵 `R-EP-CURRENT-GATE-SYNONYM-GUARD-GAP` —— 词表 ≠ 概念,旧 guard 只抓字面,概念级仍靠 Codex + 本约定兜底)。**README 不做整篇扫描**(它合法描述 review 流程,会误报如"pending Optional disposition");README 的 transient drift 改由 **alias-scoped** 扫描覆盖——只在引用**已花线 alias** 的行上应用**与 `CURRENT` 相同的 strict+synonym regex**(含无空格 `待Codex`、`谁审`/`谁提交`/`谁执行`/`由 Codex 审`/`Claude 提交`/`Claude 执行` 等同义词,堵 `R-ROUTEDOC-README-SYNONYM-GUARD`),流程说明 prose(不含已花 alias)不受影响。防护层级:**① tracked 测试 = 主防线(`提交` / `审查` 前必跑);② `.githooks/pre-commit`(`git config core.hooksPath .githooks` 启用,新克隆各自跑一次)= 本机第二道门:先按 PATH 找 `python/python3/py`,找不到再回退到 Windows 安装位(`$HOME`/`$LOCALAPPDATA` 下 `Programs/Python/Python*/python.exe`——Git hook PATH 极简、常无 python,堵 `R-ROUTEDOC-PRECOMMIT-PYTHON-DISCOVERY`),仍找不到则**告警放行、不 brick commit**(主防线是 tracked 测试);guard FAIL 才 exit 1 挡 commit。Git hook 跨环境不保证自动生效,故不是唯一保障;③ 本约定 + Codex 复核 = 概念级人/规则兜底**。紧急绕过 `--no-verify` 需用户批准。

这样**唯一会过时的只有 `SESSION_LOG` 顶部一处**(reverse-chrono,设计上每轮新增即新鲜);`CURRENT §0` 只放 settled 事实(falsified 永远 falsified,不会变错),不放在飞的 review/commit gate;其余路由对状态转变天然免疫。三道机器扫描(spent-ledger alias + §1/§5 度量 + 整篇 gate 词含同义,后两道覆盖 `CURRENT`,gate 词另扫两个 README)+ `.githooks/pre-commit` 自动兜底。作者(implementer)按此写、审查者(Codex)按此核。

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
- ✅ Phase 6d US-short 规格：US-short 设计权威已升级为 `docs/us_short_system_design.md`（单一权威，2026-06-20 docs-only 写入 repo，移植桌面定稿 `us_short_designs_final.md`：安全闸 + 两遍打分 + 赛道生命周期 + 两轴环境 + theme_probe 成本地板 + paper/live_normalized 双轨 + 比较轨 shadow + §18.0 7 道 P0 硬门）；旧 `docs/us_short_spec.md` 已降级为归档指针（不两个权威并存）。design-only / 实现 gated（须单独授权 + schema-first + tests + 审查 + 串行、不交叉 A 股）；provider / DataHub / runner / Skill 仍待后续
- ✅ Phase 6e provider/data requirements audit：`docs/provider_data_requirements_audit.md` 已汇总 4 套系统字段、PIT、频率、lineage、授权/成本、稳定性和 fallback 要求（docs-only；不锁最终 provider）
- ✅ Phase 7 provider capability / field catalog contract：`schemas/provider_capability_catalog.schema.json` v1.0.0 已建立 schema-first contract（不选 provider、不抓数据、不建 adapter / DataHub table）
- ✅ Phase 7a alpha-validation route：`docs/alpha_plausibility_audit.md` 与 `docs/evidence_capital_policy.md` 已建立设计路由；后续在大规模 DataHub / runner implementation 前，先用 schema-first alpha audit 判断 lane objective / provider priority / evidence horizon，并用 paper vs live-normalized evidence policy 约束 ship-gate 证据
- ✅ Phase 7a+ alpha reality action guide：`docs/ALPHA_VALIDATION_ACTION_GUIDE.md` 已固化为当前最高行动指南；Phase 7a-1 必须把 survivorship / multiple testing / statistical power / regime / factor exposure / execution-cost feasibility / risk-filter evidence / decision effect 写进 schema-first audit
- ✅ Phase 7a-3 provider priority / provisional benchmark contract：`docs/provider_priority_benchmark_contract.md` 已把 provider evidence queue 与 provisional evidence benchmark 固化为 docs-only contract（不选 provider、不抓数据、不建 adapter / DataHub table、不锁最终 ship-gate benchmark）
- ✅ Phase 7a-4 evidence feasibility controls：`docs/evidence_feasibility_controls.md` 与 `schemas/evidence_feasibility_controls.schema.json` 已固化 burst minimal-to-full promotion、evidence capital、concentration / liquidity / ADV、slippage / borrow / limit-risk、circuit-breaker playbook contract（不选 provider、不抓数据、不改 runner）
- ✅ Phase 7a-5 evidence report schema contract：`docs/evidence_report_schema_contract.md` 与 `schemas/evidence_report.schema.json` 已固化 immutable decision packet、cost-adjusted return、cash drag、manual override、minimal reconciliation、thesis outcome log、research experiment log contract（不选 provider、不抓数据、不改 runner）
- ✅ Phase 7b-1 provider evidence / drift monitor schema-first contract：`docs/provider_evidence_drift_monitor.md` 与 `schemas/provider_evidence_drift_monitor.schema.json` 已把 P1-P4 provider evidence queue、provider readiness rollup 与 drift-monitor dimensions/action set 固化为 contract（不选 provider、不抓数据、不建 adapter / DataHub table）
- 🟡 Phase 7b-2 P1 US evidence snapshots + readiness review matrix + access/sample plan：六份 P1 snapshot 已基于官方 SEC / Nasdaq / MSCI / S&P DJI / S&P Global / LSEG / Massive / Polygon / Norgate / Intrinio / FMP 文档记录 candidate evidence；`schemas/provider_p1_readiness_review.schema.json` / `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json` 已固化 field-by-field blocker disposition；`schemas/provider_p1_access_decision_plan.schema.json` / `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` 已把 cost ceiling、access path、license / storage、sample rows、coverage counts、fallback / incident gate 固化为 plan-only artifact。用户已接受 US EGS 数据源方向：FMP 作为主源候选、SEC EDGAR 作为基本面审计源、`yfinance` 仅可在显式批准后作低信任价格 smoke check；`docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json` 记录 2026-06-02 用户批准的 $0 小样本边界；AAPL / MSFT sample packet 已完成，SEC EDGAR 成功，FMP legacy v3 403；FMP stable retry 已同范围完成 12/12 HTTP 200；`docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json` 已把 coverage、license / storage、PIT、price adjustment、SEC audit、fallback / stability、production-readiness / Phase 7c gate 固化为 plan-only blocker routing；`docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json` 已把 fallback / incident / stability 默认阻断行为固化为 no-access schema-first playbook；`docs/provider_evidence_p1_us_incident_log_contract_20260602.json` 已把未来 incident-log 记录形状固化为 no-access schema-first contract；`docs/provider_evidence_p1_us_license_storage_retention_review_20260602.json` 已用既有 repo evidence 分类 FMP / SEC license-storage-retention blocker（无 current terms web refresh、无法律建议、无 provider call）；`docs/provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json` 已把 SEC EDGAR audit parser scope 固化为 no-access contract（audit-only；无 SEC call、无 raw parse、无 parser implementation）；`docs/provider_evidence_p1_us_sec_edgar_field_family_mapping_contract_20260602.json` 已把 SEC EDGAR audit field-family mapping 固化为 no-access contract（无 SEC call、无 raw parse、无 fixture generation、无 parser / field mapping implementation）；`docs/provider_evidence_p1_us_fmp_pit_observed_date_semantics_contract_20260602.json` 已把 FMP PIT / observed-date semantics 固化为 no-access contract（无 FMP call、无 raw parse、无 field mapping implementation）；`docs/provider_evidence_p1_us_fmp_price_adjustment_corporate_action_semantics_contract_20260602.json` 已把 FMP EOD price adjustment / corporate-action semantics 固化为 no-access contract（无 FMP call、无 raw parse、无 return calculation、无 corporate-action reconciliation、无 field mapping implementation）；`docs/provider_evidence_p1_us_coverage_count_access_packet_plan_20260602.json` 已把 future coverage-count access packet 固化为 no-access contract（无 coverage execution、无 provider call、无 status polling、无 raw parse、无 fixture generation）。仍不授权 provider selection / contact / new token / trial / paid access / `yfinance` / FMP or SEC endpoint call / coverage-count execution / full-market fetch / provider status polling / fallback execution / incident-log writer / production storage / fixture generation / return calculation / corporate-action reconciliation / field-mapping or parser implementation / adapter / DataHub / runner / Phase 7c。A-share `minimal_data_burst` 原 preregistration 继续 `BLOCKED_DO_NOT_RUN`，corrected-basis supersession 已因 `valid_signal_events = 0` 不得 outcome-run，full-universe redesign 已用 patched benchmark-open cache 完成 outcome / excess 并失败（decision = `falsified_or_redesign_required`；mean net CSI1000 excess `-2.8696001309` pp；monthly clustered t `-0.6312965283`）。`docs/phase7a_alpha_plausibility_audit.json` 已将 `a_share_burst_minimal_data` 降为 `redesign_required`；不得 production / live / ship-gate / research-continue；任何 further redesigned A-share burst test 必须新 ledger planned test + reviewed preregistration。
- ✅ Phase 7b-2 approved coverage-count exception：2026-06-02 用户随后批准 exact 5-symbol / 30-call FMP stable coverage-count packet；`runners/us_egs_coverage_count_packet.py` 已执行，`docs/provider_evidence_p1_us_coverage_count_execution_summary_20260602.json` 记录 30/30 HTTP 200、raw payloads 只在 gitignored `provider_samples/us_egs_coverage_count_20260602/fmp_stable/`、tracked summary 无 secret / request URL / raw rows。该结果只证明 bounded active-symbol coverage smoke，仍不证明 inactive / delisted coverage、current terms、production storage、PIT、price adjustment、corporate actions、SEC parser、fallback、stability、provider selection、DataHub、Phase 7c、production readiness 或 ship-gate evidence；未来/更广的 FMP or SEC call / coverage-count execution 仍需 separate explicit approval + reviewed decision。
- ✅ Phase 7b-2 missing key-metrics resolution plan：`schemas/provider_p1_missing_key_metrics_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json` 已把 coverage smoke 中缺失的 `peRatio`、`revenuePerShare`、`netIncomePerShare` 路由为 potentially derivable pending field-presence / lineage review；本 artifact 不读 raw payload、不抓新数据、不实现 derivation / field mapping、不授权 provider selection / DataHub / runner / Phase 7c。
- ✅ Phase 7b-2 provider validation authorization packet：`schemas/provider_p1_validation_authorization_packet.schema.json` / `docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json` 记录用户确认 FMP Basic 并授权未来 reviewed 5-10 symbol / max 60 call validation packet：只允许 existing FMP key + SEC EDGAR public API、$0、gitignored raw payloads、tracked no-secret summary，以及为 PIT row / price adjustment / corporate action / SEC parser / SEC field mapping / field presence 做受限 raw parse；本 slice 不执行 provider call、不读 raw payload、不改 runner、不授权 provider selection / DataHub / Phase 7c / production readiness / ship-gate evidence。
- ✅ Phase 7b-2 provider validation execution / inactive-delisted gap plan / FMP entitlement diagnostic / SIVB re-probe execution：`schemas/provider_p1_validation_execution_packet.schema.json` / `docs/provider_evidence_p1_us_validation_execution_packet_20260603.json` 固化固定 `AAPL` / `MSFT` / `JPM` / `TWTR` / `SIVB`、41 planned calls、zero retry、gitignored raw / tracked no-secret summary 的 execution packet；用户随后触发执行，`runners/us_egs_validation_packet.py` 写入 `docs/provider_evidence_p1_us_validation_execution_summary_20260603.json`（37 actual calls：30 FMP stable + 7 SEC public；32 success / 5 FMP SIVB endpoint errors / 6 skips；raw under gitignored `provider_samples/us_egs_validation_packet_20260603/`；tracked summary no secret / no request URL / no raw rows）。`schemas/provider_p1_inactive_delisted_gap_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_inactive_delisted_gap_resolution_plan_20260603.json` 已把 TWTR / SIVB 缺口路由到 FMP Basic entitlement、SEC historical CIK / symbol lookup、historical security master、alternate-source / paid-access decision tracks。`schemas/provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic.schema.json` / `docs/provider_evidence_p1_us_fmp_entitlement_corporate_action_no_access_diagnostic_20260603.json` 已 docs-only 识别 FMP stable split / dividend endpoint templates，并把 SIVB 402 固化为未决假设集而非 paid-wall / missing-data 结论；`schemas/provider_p1_sivb_reprobe_execution_packet.schema.json` / `docs/provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json` 固化 SIVB-only re-probe packet，用户随后触发执行，`runners/us_egs_sivb_reprobe_packet.py` 写入 `docs/provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json`（5/5 FMP stable calls returned HTTP 402；non-JSON bodies captured only under gitignored `provider_samples/us_egs_sivb_reprobe_20260603/`；tracked summary no body text / request URL / raw rows / secret；category signal = weak `historical_or_delisted_paid_tier`，但 paid-wall / inactive-delisted coverage 均未证明）。该结果只证明 bounded validation response-shape / field-presence / public-doc / SIVB 402 category-signal clues；仍不授权 FMP split/dividend call、provider selection、DataHub、Phase 7c、production readiness 或 ship-gate evidence。
- ✅ Phase 7c schema-first contract baseline：`schemas/datahub_local_resource_budget.schema.json` / `docs/datahub_local_resource_budget_contract_20260602.json` / `schemas/datahub_job_spec.schema.json` / `schemas/examples/datahub_job_spec.example.json` 已固化本机默认 `single_slice_incremental` 运行边界和未来 job spec 最小形状；`engine/datahub/job_spec_contract.py` 已提供未来 executable job 的启动前 enforcement；`schemas/datahub_shared_layer_contract.schema.json` / `docs/datahub_shared_layer_contract_20260603.json`、`schemas/datahub_report_contract.schema.json` / `docs/datahub_report_contract_20260603.json`、`schemas/datahub_reproducibility_manifest.schema.json` / `docs/datahub_reproducibility_manifest_contract_20260603.json`、`schemas/datahub_data_quality_monitor_contract.schema.json` / `docs/datahub_data_quality_monitor_contract_20260603.json`、`schemas/datahub_minimal_a_share_read_path_plan.schema.json` / `docs/datahub_minimal_a_share_read_path_plan_20260603.json` 已固化共享层 / 报告 / 可复现 manifest / 数据质量监控 / 最小 A 股本地 read-path 边界。这些都不抓数据、不建 DataHub table、不改 runner、不授权 Phase 7c implementation。
- ✅ A 股短线阈值治理：`presets/a_short.yaml` 已路由到 `presets/a_short_screening_threshold_governance_20260602.json`；`tests/schema/test_a_short_screening_threshold_governance_schema.py` 以静态 AST 方式校验当前 `A-EGS/egs_main.py::CONF` 与 preset governance artifact 一致（不导入脚本、不改 runtime 行为）。
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
- US-short 设计权威 = `docs/us_short_system_design.md`（单一权威；旧 `docs/us_short_spec.md` 已降级归档指针）；reference docs 继续作为源资料归档，`skills/us_short_analysis/SKILL.md` 在 Phase 7 / Phase 8 前仍保持 reserved。
- US-long 设计权威 = `docs/us_long_system_design.md`（美股中长线 us_long 系统**单一设计权威**；2026-06-24 移植桌面定稿入 repo，桌面稿退役；foundation-first，用户已授权进入 Tier 2；Tier 2-3 只用本地样例数据，真实数据 / provider / DataHub / 联网留 Tier 4+ 单独授权审查；`presets/us_long.yaml` 仍 reserved_phase_9、实现时翻 active；不交叉 A 股、不 auto-push）。`docs/long_alpha_spec.md` 仍是长线**共同**规格 skeleton，本稿是 us_long 的**具体系统**权威，二者不冲突。
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
| 7b-2 | Provider capability evidence population：按 P1-P4 读取/核验 provider 文档、字段、PIT、coverage、cost、fallback、stability 证据；不默认选择 provider、不建 adapter / DataHub table | 1-2 周 | 🟡 P1 six snapshots + readiness matrix + access/sample plan complete；AAPL / MSFT FMP+SEC sample / stable retry plus remaining-blocker / playbook / incident-log / license-storage / SEC parser-scope / SEC field-family mapping / FMP PIT-semantics / FMP price-corporate-action / coverage-count access-packet contracts recorded；approved 5-symbol FMP stable coverage smoke executed；2026-06-03 validation authorization + execution packets recorded；broader access still gated |
| 7c | DataHub shared layer / report contracts / reproducibility plumbing / local resource budget / data-quality monitor / minimal local read-path plan：先写 schema-first contract；implementation 另起 reviewed slice | 1-2 周 | 🟡 resource-budget + job-spec enforcement + shared-layer / report / reproducibility / data-quality / minimal A-share read-path planning contracts complete；implementation not started |
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
14. Phase 7 implementation 顺序采用 alpha-leverage-first，不再默认从已证明的 A-share EOD / benchmark surface 消耗下一刀资源；Phase 7a schema-first audit / routing / feasibility / report contracts 与 Phase 7b-1 provider evidence / drift monitor contract 已建立。Phase 7b-2 已有 P1 US public-source、market-data-candidate、authorization / cost / stability、benchmark / GICS、fundamentals observed-date、coverage / fallback / incident candidate evidence snapshots，并已由 P1 readiness review matrix 做 field-by-field blocker disposition；P1 access-decision / sample-validation plan 只定义 cost / access / license / sample / coverage / fallback gates。US EGS 数据源方向已固化为 FMP 主源候选 + SEC EDGAR 基本面审计；EDGAR 不负责价格，也不能严格审计 free float；`yfinance` 不得替代 EDGAR，只能在显式批准后作为低信任价格 smoke check。2026-06-02 sample-validation approval 只允许 $0、现有 FMP key、SEC EDGAR 公共 API、AAPL / MSFT 小样本、本地 gitignored 原始样本和 tracked no-secret summary；FMP stable retry 的 12/12 HTTP 200 只证明两只股票 endpoint access / response-shape，remaining-blocker plan 只做 blocker routing，fallback / incident / stability playbook 只做默认阻断设计，incident-log contract 只做未来记录形状设计，license-storage-retention review 只用既有 repo evidence 分类 blocker（无 current terms web refresh、无法律建议、无 provider call），SEC parser scope contract 只定义 audit-only scope / lineage gates（无 SEC call、无 raw parse、无 parser implementation），SEC field-family mapping contract 只定义 audit field families / lineage / FMP cross-check gates（无 SEC call、无 raw parse、无 fixture generation、无 parser / field mapping implementation），FMP PIT / observed-date semantics contract 只定义 field-family gates / lineage / no-silent-default policy（无 FMP call、无 raw parse、无 field mapping implementation），FMP price-adjustment / corporate-action semantics contract 只定义 EOD return / liquidity gates、18 个 price lineage requirements 和 no-silent-default policy（无 FMP call、无 raw parse、无 return calculation、无 corporate-action reconciliation、无 field mapping implementation），coverage-count access-packet plan 只定义 future coverage-count request 的 symbol universe / endpoint / call budget / storage / no-secret summary / threshold requirements（无 coverage execution、无 provider call、无 status polling）。这些均不授权 provider contact、new token、trial、paid access、`yfinance`、FMP or SEC endpoint call、coverage-count execution、full-market fetch、provider status polling、fallback execution、incident-log writer、production storage、fixture generation、return calculation、corporate-action reconciliation、field-mapping or parser implementation、provider selection、adapter、DataHub、runner 或 Phase 7c。SEC / Nasdaq / MSCI / S&P DJI / S&P Global / LSEG / Massive / Polygon / Norgate / Intrinio / FMP docs、小样本批准、stable retry、remaining-blocker plan、fallback playbook、incident-log contract、license-storage review、SEC parser scope contract、SEC field-family mapping contract、FMP PIT semantics contract、FMP price/corporate-action semantics contract 和 coverage-count access-packet plan 都不等于完整 provider selection、PIT security master、licensed benchmark return feed、field-level fundamentals PIT construction、coverage validation、current terms / production storage authorization、actual SEC parser feasibility at scale、actual SEC field mapping / fixture set、actual FMP PIT row validation、actual adjusted-return / corporate-action / delisting / missing-session validation、executable fallback、incident-stability evidence 或 production readiness。后续 Phase 7c DataHub / report / reproducibility work 必须消费 reviewed P1-P4 provider evidence 与 drift-monitor contract，不能把 P4 ready helper surface、小样本授权、stable retry、playbook design、incident-log contract、license-storage review、SEC parser scope contract、SEC field-family mapping contract、FMP PIT semantics contract、FMP price/corporate-action semantics contract 或 coverage-count access-packet plan 当作 broad implementation 起点。
15. Phase 7a+ 最高行动指南采用 `docs/ALPHA_VALIDATION_ACTION_GUIDE.md`：所有后续 schema / provider / DataHub / runner / report / live evidence 工作必须先证明 alpha 真实性边界，不得跳过 survivorship、multiple testing、statistical power、PIT/security master、fraud red flags、regime sensitivity、factor exposure、execution cost、decision reproducibility、position reconciliation 和 production monitoring 等护栏。
16. 本机资源边界固化为默认分片 / 增量运行：四套子系统都是真需求，但默认不得一次性全市场、全 lane、full-history、full-refresh 或并行跑完整系统。后续 DataHub / runner / report job 必须先声明 budget profile、market、lane、as_of/date window、provider family、artifact type、预计输入输出、cache policy、checkpoint / abort policy、data boundaries 和 approval gates；heavy run 必须显式用户批准 + reviewed job spec。`schemas/datahub_local_resource_budget.schema.json` / `docs/datahub_local_resource_budget_contract_20260602.json` / `schemas/datahub_job_spec.schema.json` / `schemas/examples/datahub_job_spec.example.json` 与 `engine/datahub/job_spec_contract.py` 只提供启动前预算 / 范围 enforcement，不授权 provider call、DataHub implementation、runner change 或 Phase 7c。
17. 2026-06-02 用户批准并执行的 coverage-count packet 是 item 14 no-access coverage plan 的 exact-scope 例外：只允许 5 个 active symbols、30 次 FMP stable endpoint calls、count-only response inspection、gitignored raw payloads 和 tracked no-secret summary。该 summary 不等于 provider selection、coverage validation、current terms / production storage authorization、PIT / price / corporate-action validation、SEC parser feasibility、fallback / stability evidence、DataHub、runner consumption、Phase 7c、production readiness 或 ship-gate evidence；missing key-metrics resolution plan 只路由 `peRatio` / `revenuePerShare` / `netIncomePerShare` 的后续 field-presence / lineage 审查，不授权 raw-payload parse、derivation 或 field mapping implementation；任何 future / broader FMP or SEC call、coverage-count execution、raw-payload parse、fixture、field mapping、return calculation、adapter 或 DataHub work 仍需 separate explicit approval + reviewed decision。
18. 2026-06-03 用户确认 FMP 是 Basic，并授权一个 future reviewed provider validation packet：existing FMP key + SEC EDGAR public API、$0、5-10 symbols、max 60 calls、active symbols + inactive / delisted candidates if supported、raw payloads only under gitignored `provider_samples/`、tracked no-secret summary，以及为 PIT row / price adjustment / corporate action / SEC parser feasibility / SEC field mapping feasibility / field presence 做受限 raw parse。该授权包本身不执行 provider call、不读 raw payload、不改 runner、不授权 fixture、derivation、field mapping、parser implementation、provider selection、adapter、DataHub、runner consumption、Phase 7c、production readiness 或 ship-gate evidence；实际执行仍必须另有 reviewed execution packet 精确消费该授权，任何超出范围仍需 separate explicit approval + reviewed decision。
19. 2026-06-03 validation execution packet 精确消费 item 18 的授权，但仍是未执行的 review artifact：固定 5 symbols（`AAPL` / `MSFT` / `JPM` / `TWTR` / `SIVB`）、41 planned calls（30 FMP stable + 11 SEC public）、zero retry、environment precheck、gitignored raw storage、tracked no-secret summary、no-new-token / no-paid / no-yfinance / no-full-market guard。它不执行 provider call、不读取 raw、不改 runner、不授权 implementation；FMP split / dividend endpoint family 因仓库内没有 reviewed current template 而保持 zero-call blocked，任何 corporate-action endpoint call 或 reconciliation 仍需 separate reviewed mapping / approval。
20. 2026-06-03 SIVB-only FMP 402 re-probe 已按 reviewed packet 执行但仍只是证据分类，不是 provider 放行：固定 `SIVB` only、5 个失败 FMP endpoint families only、max 5 calls、zero retry、$0、existing FMP key、gitignored raw path `provider_samples/us_egs_sivb_reprobe_20260603/`、tracked summary 禁 body text / request URL / raw rows / secret。执行结果为 5/5 HTTP 402，captured-body category signal 为 weak `historical_or_delisted_paid_tier`；不得写成 paid-wall proven、inactive / delisted coverage proven、provider selected，也不授权 DataHub / runner / Phase 7c / production readiness / ship-gate evidence。
21. 2026-06-03 FMP paid-tier / license public-docs review 只是公开页账本，不是购买或许可结论：FMP public pricing 显示 Basic free / 250 calls/day，Starter $22/mo billed annually，Premium $59/mo billed annually，Ultimate $149/mo billed annually，并列出不同历史深度、fundamentals / ratios、corporate calendars、global / bulk 等 plan signals；public docs 列出 delisted / split / dividend / key-metrics / ratios / historical EOD templates；public Terms 显示 access / storage / deletion / redistribution 仍需按实际 ToS / order form / license 判断。本 review 不调用 API、不注册、不购买、不 trial、不联系 provider、不读 raw、不选 provider、不授权 DataHub / Phase 7c / production readiness / ship-gate evidence；`SR-PROVIDER-001` 继续 open。
22. 2026-06-03 当前临时工作边界（cost-saving working boundary, revisit when a US idea justifies the data cost；非最终决定）：这是当前操作姿态，不是永久承诺；用户可在任何时候改为购买 / 接入专门源（EODHD / Norgate / Sharadar / 付费 FMP 等）。在未补齐 inactive / delisted security master、PIT 财务、price adjustment / corporate actions、license / storage 等 P1 provider blocker 前，美股免费数据路线只能定位为探索、paper、minimal-size 或 live-normalized forward evidence accumulation；FMP Basic / SEC EDGAR 小样本或历史回测不得证明美股 alpha、不得支持 full-size 手动实盘、不得授权 provider selection / DataHub / Phase 7c / production readiness / ship-gate evidence。当某个美股想法在前向实盘里跑出苗头，或用户主动决定时，重新评估是否购买 / 接入专门数据源。A 股 35% / 美股 65% 资金政策不因此自动改写；未验证的美股额度默认留在美股 cash / paper / minimal bucket，不得 silent 转给 A 股，除非用户做出显式人工资金转移决策。
23. 2026-06-03 Phase 7c-a local resource budget code enforcement 已建立：`engine/datahub/job_spec_contract.py` 是未来 DataHub / runner / report executable job spec 的启动前验证入口。任何 Phase 7c DataHub table、adapter、runner、report job 或 broad local job 执行前，必须先通过 `validate_datahub_job_spec_contract` / `validate_datahub_job_spec_file`，验证 resource-budget artifact、budget profile、一市场一 lane、market/lane 一致、bounded as-of/date window、resource estimates、cache / checkpoint / abort policy、approval gates、heavy-run approval 和 no-scope-creep。该 helper 不抓 provider data、不选 provider、不建 DataHub table、不授权 production runner consumption、不放松 ship gate；`SR-RESOURCE-001` 对当前代码级 enforcement 已关闭，但未来 job 若绕过该 helper 仍属新风险。
24. 2026-06-03 Phase 7c schema-first contract batch 已建立：共享层 contract 固化 ODS / DWD / DWS / factor layer 的输入输出、PIT / lineage / no-silent-default / metadata 边界；report contract 固化 screening / evidence / provider-summary / data-quality report 的 plain-result、no-secret、no-raw、no-overclaim 边界；reproducibility manifest contract 固化未来 job 必须记录 job spec validation、resource budget、code/schema refs、input hashes、output refs、environment、dependencies、cache/checkpoint 和 limitations。该批不抓数据、不调用 provider、不建表、不实现 manifest writer、不改 runner、不授权 production consumption、Phase 7c broad implementation、ship-gate evidence 或 full-size。
25. 2026-06-03 Phase 7c data-quality monitor + minimal A-share read-path planning batch 已建立：data-quality monitor contract 固化 coverage、freshness、schema drift、PIT/as-of、survivorship/security master、corporate actions/revisions、calendar/timezone、provider incident/quota、outlier/revision-rate 等未来检查维度，缺失 monitor 结果默认阻断 production / ship-gate claim；minimal A-share read-path plan 只允许未来单日 `market=A` / `lane=a_short` / `provider_family=local_cache` 的 reviewed job-spec 设计。本批不运行 monitor、不读 cache、不调用 Tushare/FMP/SEC、不建 DataHub table、不改 A-EGS 或 runner、不授权 production consumption、Phase 7c broad implementation、ship-gate evidence 或 full-size。
26. 2026-06-03 美股 active-only + forward-live 操作模型已固化，并 supersede item 22 的“临时 / 未决”表述：当前美股 universe 固定为 active only；美股验证只接受 live-normalized forward evidence；美股历史回测只能用于 exploration / idea generation，永不作为 alpha evidence、ship-gate evidence、full-size 依据或 production readiness 依据。美股 forward universe 必须按 forward 起始日 point-in-time 冻结；若 forward 过程中股票停牌、退市、并购、破产或无法交易，必须按实际发生记录和捕获，不得回删。项目暂不购买退市 / 专门源；当某个美股想法有足够前向苗头或用户主动决定时可复议。Ship gate 的 12 个月 forward-live 门槛不变。
27. 2026-06-03 A-short steady alpha re-audit 已执行并花掉唯一 planned test：`research/results/a_short_steady_alpha_reaudit_20260603/evidence_report.json` 结论为 `risk_filter_only`。简单说：旧 5d CSI1000 线索用真正 same-anchor benchmark 修正后不过门槛（corrected mean `0.6158673222` pp，monthly t `1.7623850474`；旧未校正 t `2.8769227582`），不能证明 alpha。A-short steady 只能继续当风控 filter / research reference，不得当 production alpha、ship-gate evidence、full-size 许可、DataHub/runner/provider 授权或参数救援理由；任何新 alpha 搜索 / rerun / deep validation / forward-live follow-up 必须新 reviewed preregistration + 用户批准。固定 12 个月 forward-live ship gate 不变。
28. 2026-06-03 找 alpha 的当前主动路线固化为：只开 A 股长线这一条主动战线；A 股长线必须先通过一次可执行、会产出 hard pass/fail/blocked + usable-window 的数据完整性审计，再允许另起 reviewed signal-search preregistration。审计预注册见 `schemas/a_long_data_integrity_audit_preregistration.schema.json`、`research/preregistrations/a_long_data_integrity_audit_20260603.json`、`research/ledgers/a_long_data_integrity_audit_program_test_budget_ledger_20260603.json`；它冻结 2018-01-31..2025-12-31 月末 as-of schedule、runner planted-violation self-tests、Tushare income / balancesheet / fina_indicator 的 PIT `ann_date`、重述 as-of、PIT universe / survivorship、持有期退市 terminal return、分红 + `adj_factor` 总收益、same-anchor 基准超额和覆盖率可用窗口。`ann_date > as_of`、重述错用、回删退市名、错锚、漏计退市收益是硬失败；缺失/非法 `ann_date` 剔除并报告；早期覆盖率不足用于声明可用起始年，不一票否决。Claude 审查 + 用户 `执行` 后，`runners/a_long_data_integrity_audit.py` 已执行 local-cache-only 审计，`research/results/a_long_data_integrity_audit_20260603/audit_report.json` 结论为 `blocked_missing_required_source`：6 个自检全过，但缺 raw PIT 三大表、完整 PIT universe、分红/总收益和退市 terminal return lineage。A 股长线不得开始信号搜索；先修数据路线，再走新的 reviewed audit。
29. 2026-06-03 A-long 数据路线修复的当前路线固化为：先尝试现有 Tushare 原始 PIT 路线，见 `schemas/a_long_tushare_data_route_repair_plan.schema.json` / `docs/a_long_tushare_data_route_repair_plan_20260603.json`。简单说：路线已定，数据还不能用。该计划要求补 `trade_cal` 月末 schedule、`stock_basic` PIT universe / delist lineage、raw `income` / `balancesheet` / `cashflow` / `fina_indicator` with `ann_date` / `end_date`、重述 as-of、SW L1/L2 历史、`daily` + `adj_factor` + `dividend` + `index_daily` same-anchor 总收益 / 基准、terminal delisting return。它禁止用 A-short derived `financial_*.pkl`、latest-only 基本面、今日 active list、price-only return、close-to-close benchmark 或 AKShare 未审替代。该计划不调用 Tushare、不抓数据、不重跑 audit、不找 signal、不授权 DataHub / production / ship-gate / full-size；下一步只能是 reviewed 小范围 Tushare route-validation packet，过后才可另起 materialization，再另起新 data-integrity audit。
30. 2026-06-04 A-long 小范围 Tushare route validation 已真实执行但未通过：`runners/a_long_tushare_route_validation_packet.py` 固定 23 次现有 Tushare 调用，summary 为 `docs/a_long_tushare_route_validation_execution_summary_20260604.json`，raw 只写入 gitignored `data/a_long/raw/tushare/route_validation_20260604/`。简单说：能证明一部分接口字段存在，但 A 股长线数据还不能用来找 alpha。已通过小样本字段检查：交易日历、`stock_basic` 活跃+退市形状、`income` / `balancesheet` / `cashflow` / `fina_indicator` 的 `ann_date` / `end_date`、重述 lineage 所需基础字段、`daily` / `adj_factor` / `dividend`、CSI300 `index_daily`。未通过：SW 行业成员接口缺 `index_code` / `con_code`，退市样本终态 daily price 为空。下一步只能先修这两个数据路线缺口；不得 full materialize、重跑 audit、搜 signal、声称 alpha / production / ship-gate / full-size。
31. 2026-06-04 A-long 两个 route 缺口的小样本 repair 已通过：`runners/a_long_tushare_route_gap_repair_packet.py` 固定 5 次现有 Tushare 调用，summary 为 `docs/a_long_tushare_route_gap_repair_execution_summary_20260604.json`，raw 只写入 gitignored `data/a_long/raw/tushare/route_gap_repair_20260604/`。简单说：SW 行业成员字段和较早退市样本终态价格路线在小样本上修通了，但 A 股长线数据仍不能直接用来找 alpha。SW membership 采用当前 `index_member_all` 字段映射：`ts_code` = 成员股票、`l2_code` / `l2_name` = SW L2、`in_date` / `out_date` = 生效区间；退市样本 `000666.SZ` 在 `20230728..20231026` 窗口有 daily open/close 与 adj_factor。下一步只能是 reviewed incremental materialization packet，之后还要新 data-integrity audit；不得从本 repair summary 直接 full materialize、重跑 spent audit、搜 signal、声称 alpha / production / ship-gate / full-size。
32. 2026-06-04 A-long thin-slice incremental materialization packet 已写好但未执行：`schemas/a_long_tushare_incremental_materialization_packet.schema.json` / `docs/a_long_tushare_incremental_materialization_packet_20260604.json` 固定 2022-2023、`000001.SZ` / `600519.SH` / `000666.SZ`、CSI300 / CSI1000、29 planned calls / max 32、gitignored raw path `data/a_long/raw/tushare/materialization_thin_slice_20260604/`、checkpoint resume、no-secret tracked summary；`runners/a_long_tushare_incremental_materialization_packet.py` 是后续执行入口。简单说：下一次可审后跑小切片真数据，但现在还没有跑，也还不能找 alpha。必须 Claude 独立审查通过 + 用户再次 `执行`，才可带确认参数跑该薄切片；跑完也只能进入新 data-integrity audit，不得直接全量 2018-2025、重跑 spent audit、搜 signal、声称 alpha / production / ship-gate / full-size。
33. 2026-06-04 A-long thin-slice incremental materialization 已按 reviewed packet 真实执行：`runners/a_long_tushare_incremental_materialization_packet.py` 使用双确认参数跑了固定 2022-2023、`000001.SZ` / `600519.SH` / `000666.SZ`、CSI300 / CSI1000 的 29 次现有 Tushare 调用，summary 为 `docs/a_long_tushare_incremental_materialization_execution_summary_20260604.json`，raw 只写入 gitignored `data/a_long/raw/tushare/materialization_thin_slice_20260604/`。简单说：小切片数据已经成功落地，但还不能找 alpha。它只证明薄切片 materialization 机制、字段形状和 raw lineage 可落地；下一步必须另起 reviewed data-integrity audit，audit 通过后才允许信号搜索预注册。不得从本 summary 直接全量 2018-2025、重跑 spent audit、搜 signal、声称 alpha / production / ship-gate / full-size。
34. 2026-06-04 A-long materialized thin-slice data-integrity audit 已本地执行：`runners/a_long_materialized_thin_slice_data_integrity_audit.py` 只读取已落地的 2022-2023 三股票 raw 小切片，写入 `research/results/a_long_materialized_thin_slice_data_integrity_audit_20260604/audit_report.json`，并由 `schemas/a_long_materialized_thin_slice_data_integrity_audit_report.schema.json` 锁定 no-provider-call / no-raw-rows / no-alpha 权限边界。简单说：小切片审计通过，但仍不能找 alpha。它只证明这 3 个样本上的 PIT、退市样本、收益输入、基准输入和覆盖率刻画机制可跑通；报告 self-tests 为 11/11，其中 5 个直接打当前 materialized runner 自己的 check 函数。下一步必须另起 reviewed full-period / incremental materialization packet，再跑完整数据审计。不得从本 report 直接全量 2018-2025、搜 signal、声称 alpha / production / ship-gate / full-size。
35. 2026-06-04 A-long broader materialization 已按 reviewed packet 真实执行但不完整：`runners/a_long_tushare_broader_materialization_packet.py` 使用双确认参数跑了固定 2018-2025、8 只活跃股 + `000666.SZ` 退市样本、CSI300 / CSI1000 的 71 次现有 Tushare 调用，summary 为 `docs/a_long_tushare_broader_materialization_execution_summary_20260604.json`，raw 只写入 gitignored `data/a_long/raw/tushare/materialization_full_period_panel_20260604/`。简单说：更大固定样本池没有落完整，仍不能找 alpha。财报、股票池、行业、基准 shape 通过，但 9 个 `daily` 价格调用全是 0 行；下一步只能先做 reviewed daily 价格路线 / 参数修复，不得 full audit、全市场 / 全 universe 拉取、搜 signal、声称 alpha / production / ship-gate / full-size。

36. 2026-06-04 A-long daily price route diagnostic packet 已写好并随后按 #37 执行：`docs/a_long_tushare_daily_price_route_diagnostic_packet_20260604.json` / `schemas/a_long_tushare_daily_price_route_diagnostic_packet.schema.json` / `runners/a_long_tushare_daily_price_route_diagnostic_packet.py` / `schemas/a_long_tushare_daily_price_route_diagnostic_execution_summary.schema.json` 固定诊断边界为 2 次 `000001.SZ` 的 `daily` probe：2018-2025 八年隔离重测 + 2022 一年对照（max 2 calls、retry 0、raw 进 gitignored `data/a_long/raw/tushare/daily_price_route_diagnostic_20260604/`）。该 packet 不授权 full audit、broader rerun、搜 signal、alpha / production / ship-gate / full-size。
37. 2026-06-04 A-long daily price route diagnostic 已真实执行：`docs/a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604.json` 记录 2/2 fixed `daily` calls 成功，2018-2025 八年隔离 probe 返回 1,942 行，2022 control 返回 242 行。简单说：之前 71-call broader run 里 `daily` 全空，更像突发调用/限速/节流问题，不是 8 年窗口太大。下一步按用户要求合并成一个大任务给 Claude 一次审：pacing / rate-limit price-route repair + 重拉固定 2018-2025 panel + summary + tests + docs。该诊断本身仍不授权 full audit、搜 signal、alpha / production / ship-gate / full-size。
38. 2026-06-04 A-long paced fixed-panel rerun 已真实执行：`runners/a_long_tushare_broader_materialization_packet.py` 现在只在 diagnostic 证明“8 年 daily 隔离可返回行”后，才允许把旧空 `daily` raw refs 用 paced refetch 重探；成功 raw 继续 checkpoint 复用，旧 raw 不覆盖，新 daily raw 写 `_paced_refetch` 版本。`docs/a_long_tushare_broader_materialization_execution_summary_20260604.json` 记录 9 个 `daily` paced refetch 成功、62 个旧 raw 复用、11/11 table rollup 通过。简单说：固定 2018-2025 样本池数据已落地；但这还不是数据完整性 audit，也不能开始找 alpha。下一步只能做 full-period panel data-integrity audit；audit 通过前不得 signal search、alpha / production / ship-gate / full-size。
39. 2026-06-04 A-long materialized full-period data-integrity audit 已本地执行但失败：`runners/a_long_materialized_full_period_data_integrity_audit.py` 只读取已落地的 2018-2025 九股票 raw panel，写入 `research/results/a_long_materialized_full_period_data_integrity_audit_20260604/audit_report.json`，并由 `schemas/a_long_materialized_full_period_data_integrity_audit_report.schema.json` 锁定 no-provider-call / no-raw-rows / no-alpha 权限边界。简单说：全周期固定 panel 还不能用来找 alpha。通过项：PIT `ann_date` gating、退市终态价格输入、收益 / 基准输入、覆盖率可用起点 2018。失败项：`fina_indicator` 有 6 组同一 `ann_date` 重复冲突（差异字段为 `profit_dedt`），且 `000666.SZ` 退市样本缺 SW membership 行业成员记录。下一步只能修这两个数据路线缺口并重跑审计；不得 signal search、alpha / production / ship-gate / full-size。
40. 2026-06-04 A-long full-period audit blocker repair narrowed the failure to one item：`runners/a_long_materialized_full_period_data_integrity_audit.py` now treats same `ts_code` / `end_date` / `ann_date` duplicate rows as resolvable only when the only differing field is an allowed nullable field (`profit_dedt`) and exactly one non-null value exists; all other same-ann-date conflicts still hard-fail. The rerun report records 6 such `profit_dedt` duplicates resolved and `restatement_revision_asof = pass_fixed_panel`, but `survivorship_pit_universe` still fails because delisted sample `000666.SZ` has no SW membership rows. 简单说：A-long 仍不能找 alpha；现在只剩 `000666.SZ` 退市股 SW 行业来源缺口。下一步必须补可审 SW 行业来源，或继续阻塞 A-long 行业归一化信号搜索；不得 signal search、alpha / production / ship-gate / full-size。
41. 2026-06-04 A-long `000666.SZ` SW membership supplement packet was first prepared as a 3-call probe, but Claude review later found two defective legs: `stock_basic` omitted `industry` / `area`, and `index_member` was not a valid Tushare interface for this client. Treat the first packet/execution as historical process evidence, not a reliable no-source finding.
42. 2026-06-04 A-long `000666.SZ` SW membership supplement execution is now classified as inconclusive, not "no usable SW source found": `docs/a_long_000666_sw_membership_supplement_execution_summary_20260604.json` records that `stock_basic` found the delisted symbol but did not request industry fields, `index_member` errored on interface name, and only `index_member_all(ts_code=000666.SZ)` was a valid negative. 简单说：不能用这次结果断定 Tushare 没有 000666 行业来源；A-long 仍不能找 alpha。
43. 2026-06-04 A-share board scope is main-board only because the user only has main-board trading access. A-short already filters out ChiNext / STAR / BSE (`300/301`, `688/689`, `.BJ`, `920`, `8`, `4`) before analysis; A-long materialization / audit runners now enforce the same active-symbol boundary. `002` / `003` Shenzhen main-board names remain allowed. The earlier A-long full-period panel containing `300750.SZ` is historical evidence only and must not be used as the current A-long data-readiness path, audit-rerun input, signal-search basis, production evidence, ship-gate evidence, or full-size basis.
44. 2026-06-04 A-long `000666.SZ` corrected supplement packet is prepared but not executed：`schemas/a_long_000666_sw_membership_supplement_packet.schema.json`, `docs/a_long_000666_sw_membership_supplement_packet_20260604.json`, and `runners/a_long_000666_sw_membership_supplement_packet.py` now lock a corrected 4-call no-access packet. It requests `stock_basic` with `industry` / `area`, uses `index_classify` L2 context, and replaces the invalid `index_member` leg with valid `index_member_all` probes. The packet itself performs no Tushare call, reads no raw payload, and authorizes no audit rerun or signal search. After Claude review and a separate user `执行`, it may run only those four calls; even if it finds a candidate source, A-long still needs a separate reviewed audit repair and passing audit before signal search.
45. 2026-06-04 A-long `000666.SZ` corrected supplement executed after Claude PASS / commit / user `提交并执行下一步`：4/4 calls completed and `docs/a_long_000666_sw_membership_supplement_execution_summary_20260604.json` records `no_candidate_sw_membership_source_found`. Simple result: `000666.SZ` still has no usable SW membership source in this Tushare route. `stock_basic` returned the target row but `industry=false` / `area=false`; `index_classify` L2 returned rows; `index_member_all(ts_code=000666.SZ)` returned 0 rows; unfiltered `index_member_all` returned rows but no 000666 match. This does not authorize audit repair/rerun, signal search, alpha, production, ship-gate, or full-size use. Next requires an explicit reviewed design decision for delisted-name industry handling or another reviewed historical-industry source route.
46. 2026-06-04 A-long delisted missing-industry boundary: if a reviewed no-source execution summary proves an already-delisted fixed-panel symbol has no usable SW membership / coarse industry in the current Tushare route, that symbol may be logged as a bounded exception and excluded only from industry-neutralization / industry-normalized scoring denominators. The symbol must remain in PIT universe, return measurement, terminal delisting return, drawdown, risk, and coverage reporting. Silent industry fill, zero/default industry, dropping the delisted symbol from returns/risk, or using the exception for active symbols is forbidden. The current audit runner enforces max 1 exception and max 12.5% of the fixed panel, with `000666.SZ` backed by `docs/a_long_000666_sw_membership_supplement_execution_summary_20260604.json`. This boundary alone does not authorize signal search, alpha, production, ship-gate, or full-size use.
47. 2026-06-04 A-long main-board-only fixed-panel data route passed and was committed: `docs/a_long_tushare_broader_materialization_execution_summary_20260604.json` records `passed_full_period_panel_materialization_shape`, and `research/results/a_long_materialized_full_period_data_integrity_audit_20260604/audit_report.json` records `passed_fixed_panel_data_integrity_for_signal_preregistration`, hard checks pass, 11/11 self-tests, and usable start year 2018. Simple result: the data route is good enough to register the first A-long signal-search design, but the 9-symbol fixed panel is only route proof. `schemas/a_long_signal_search_preregistration.schema.json` / `research/preregistrations/a_long_signal_search_preregistration_20260604.json` / `research/ledgers/a_long_signal_search_program_test_budget_ledger_20260604.json` run no signal, fetch no data, and do not authorize alpha, full-universe proof, production, ship-gate, or full-size use.
48. 2026-06-04 A-long main-board candidate-universe preflight executed after the signal-search preregistration PASS / commit and user execute: `runners/a_long_main_board_candidate_universe_preflight.py` wrote `docs/a_long_main_board_candidate_universe_preflight_execution_summary_20260604.json` under `schemas/a_long_main_board_candidate_universe_preflight_execution_summary.schema.json`; 4 Tushare probe calls wrote raw wrappers only under gitignored `data/a_long/raw/tushare/main_board_candidate_universe_preflight_20260604/`. Simple result: A-long full main-board alpha search is still blocked. Current raw covers 3,200 main-board active names but 1,193 active names are missing SW membership in the existing raw; `index_member_all(ts_code=...)` can supplement active missing SW rows, and `stock_basic.industry/area` exists as a coarse active-only clue, but 187 main-board names delisted during 2018-2025 still lack SW membership under the current route. Do not start the full alpha pull/search until active SW supplement plus a reviewed delisted-no-industry boundary are handled. This preflight does not compute signals, returns, benchmark excess, alpha, production readiness, ship-gate evidence, or full-size permission.

## AI 协作者在本项目中的工作守则

## 输出结论规则

**`审查` 命令最终输出固定三段（2026-06-23 用户更新；2026-06-24 `下一步` 简化；2026-06-25 Codex PASS 后自动提交；仅影响对话框最终回复，落盘文档规则不变）**：仅当用户明确下达 `审查` 命令或要求按审查流程收口时，面向用户的最终结论只写三块，顺序固定为：`Verdict`、`Required / Optional / Options`、`下一步`。必须用中文；每块都要极简，不铺背景、不复述流程、不堆文件清单；不输出 `Findings` 段，不单列“已验证 / Verify / 验证”项，也不要另起“覆盖范围 / 运行阻塞 / 结论边界”等额外栏目。`Verdict` 第一位，直接写 PASS / FAIL / 未完全验证等结论，并在下一行用 `大白话：...` 说明能不能过；`Required / Optional / Options` 第二位，只写具体审查结果，每条具体项必须包含必要的技术标识和技术现状，并在下一行用 `大白话：...` 解释要修什么、可选什么或怎么选；`下一步` 第三位，只写一行最简单给另一个 LLM 的命令（例：`Claude Code：Pass`、`Claude Code：修复`、`Claude Code：执行`），不写 `大白话`、不写解释、不写修复细节；具体指示必须放在 `docs/SESSION_LOG.md` / `docs/system_risk_register.md`。`审查` PASS 后 Codex 必须在最终回复前自动提交已审查工作树，`下一步` 不再写 `Claude Code：提交`；Claude 只负责实现/修复。没有对应内容时写“无”。

面向用户输出结论时，必须先给**简单、清晰、可行动的结果**，再给必要依据。不要先堆专业术语、内部流程、文件名或审查细节。

对 provider / 数据可用性 / 风险 / 设计漏洞 / 执行阻塞等判断，必须把专业内容翻译成用户能直接理解的话：先回答“能不能用”“意味着什么”“还缺什么”“下一步做什么”，再用简短边界说明证据范围。除非用户要求深入展开，默认保持短、直、明了。

**含 Required / 修复 / 执行结果的输出加「大白话」层（2026-06-15 用户固化）**：凡 chat 输出里告诉用户有问题需要 `修复`（尤其 Codex `审查 FAIL` / PASS-with-Required），或 Claude `修复` 后说明修复结果，或任何 `执行` 后说明执行结果 / 风险 / 阻塞，除了极简结论，必须有一句**最直白的大白话**——用最简单清楚的人话说清「实际发生了什么 + 对你意味着什么 / 为什么要修或继续」，不要废话、越直白越好。**例外**：`审查` 最终回复的 `下一步` 段按上条固定为一行命令，不写 `大白话`。**这层是给用户理解的，和写进 `SESSION_LOG` / `register` / execution summary 的技术细节不是同一个**（文档放 Required ID / 文件名 / 自审 / lineage；chat 的大白话只为让用户秒懂后果）。

> R-ASHORT-M67-EGSSCORE-ARTIFACT-DRIFT
> 代码已经加了 EGS分 和 regime 横幅，但当前 `research/results/a_short/20260612/weekly_m67.json/md` 还是旧产物：JSON 15/15 都没有 EGS分，Markdown 也没有 EGS分 列和横幅。
> **大白话**：代码修了，但你正在看的报告文件没更新，所以你还是会看到「全是两星、看不出区别」。

对 `审查 FAIL`，格式即「技术标识 + 一句技术现状 + 一句『大白话：…』直说为什么要修」。对 `修复`，格式即「技术标识 + 一句技术现状 + 一句『大白话：…』直说后果」。对 `执行`，格式即「执行了什么 + 结果是什么 + 一句『大白话：…』直说这次结果对用户意味着什么、还能不能用、下一步该干什么」。**有歧义 / 有坑 / 出现「代码改了但你看到的产物还没变」或「执行跑完但结果不能直接使用」这类落差时尤其要点破。**

## System risk register discipline

`docs/system_risk_register.md` 是所有未修复系统风险的 durable queue。任何 LLM 发现影响 data integrity、PIT safety、schema contract、execution simulation、security、ship-gate evidence 或 cross-LLM continuity 的实质问题时，必须在同一轮内二选一：修复并验证，或写入该 register。不得只把发现留在 chat / SESSION_LOG / 临时审查文字里。

`执行` 前必须检查 register；open P0 风险默认优先于普通 roadmap work，除非用户明确批准更窄的 override。`审查` 必须确认新发现已被修复或入 register；若漏记 material finding，审查不能给 clean Pass。

**Register = material finding 详情的单一来源（2026-06-13）**：一个 finding 的**完整**内容——Required 文本、风险说明、修复条件/边界、closure evidence（working-tree-repaired 注记 + 验证结果）——只写在 `system_risk_register.md` 这一处。`SESSION_LOG.md` 的评审循环 entry（`审查`/`修复`/PASS）**不得复述完整分析**，只放本轮最小交接事实并**指向 Required ID**（详见 §Session log discipline → 评审循环 entry 极简模板）。理由：本会话反复出现的多轮返工，部分来自同一份修复详情在 register 与 SESSION_LOG **双写**、其一漂移。双写由 `tests/test_doc_governance_guard.py` 守护（评审循环 entry 引用 R-ID 时必须含 register 指针）。

## Multi-LLM Review Protocol

Codex acts as the Independent Reviewer.

Claude acts as the Designer + Implementer.

The user remains the Final Approver.

`AGENTS.md` remains the highest-level project rule. If `docs/AI_REVIEW_PROTOCOL.md`, older handoff text, or an older SESSION_LOG entry conflicts with this role split, `AGENTS.md` wins.

2026-06-07 one-time exception: the user explicitly authorized Codex to land this `AGENTS.md` protocol update and commit it. After that exception, Codex must not use `修复` / `执行` to write business implementation changes; Claude owns implementation and execution.

2026-06-25 review-cycle commit update: after a Codex `审查` PASS, Codex owns the local commit for the reviewed slice and must auto-submit it before the final reply when the PASS-covered worktree can be safely staged as one coherent commit. Claude owns implementation / repair only in the review loop and does not perform the post-PASS commit. If unrelated or overlapping unreviewed changes make safe auto-commit impossible, Codex must record the blocker in `docs/SESSION_LOG.md` and surface the exact boundary instead of staging unreviewed work.

## Short Command Aliases

Command binding is determined by who the user is addressing:

- `审查` = Codex reviews Claude's current changes independently. Codex must not write business code, runner code, schema, preregistration, ledger, or result artifacts during review.
- `修复` = Claude implements the reviewed repair scope and records dispositions, after judging the reviewed findings per the **Claude implementer standard** below (judge before executing; surface a wrong instruction rather than blindly implement). After a Codex `审查`, the user sends `修复` directly to Claude to authorize repairing the reviewed Required findings; a separate `批准修改` is not required. Codex does not perform the repair, and the Claude `修复` `docs/SESSION_LOG.md` entry records the user-directed authorization for cross-LLM continuity.
- `执行` = Claude runs the next approved execution slice, including real data/materialization/search only when the project approval gates and user command allow it.
- `提交` = review-cycle commit is owned by Codex after `审查` PASS; Codex stages only the PASS-covered files and commits them as one coherent commit before replying. Claude does not perform post-PASS commit work; Claude only implements / repairs.
- `批准` / `批准修改` is NOT required between a Codex `审查` and a Claude `修复` (2026-06-07 update): the user's `修复` directly authorizes repairing the reviewed Required findings, and Claude records that user-directed authorization in `docs/SESSION_LOG.md`. `批准` remains available only for a standalone approval the user explicitly chooses to record (e.g. a strategic or spend decision); when used, the addressed LLM records it in `docs/SESSION_LOG.md` before proceeding.

## Codex adversarial review standard

Every Codex `审查` must internalize the full deep review and output only the decision-level result. Before giving a verdict, Codex must:

1. Freeze a review scope manifest: `git status --short --untracked-files=all`, staged / unstaged / untracked files, intended artifacts, producer-to-consumer chain, and claimed design goal.
2. Read the whole changed data flow, not just the diff: design intent, schemas, runner or consumer code, tests, docs, ledgers, and generated artifacts that participate in the claim.
3. Use the repo test wrapper launcher `.tools/run_unittest_with_repo_pythonpath.cmd` (or an exactly equivalent `PYTHONPATH=.tools/python_libs` setup) so `jsonschema` is importable before schema / project tests. The launcher searches `PATH`, then common Windows installs such as `%LOCALAPPDATA%/Programs/Python/Python*`; if a sandbox blocks that executable or no Python is found, set `STOCK_TEST_PYTHON` to the current runtime's `python.exe`. Do not hard-code agent-private runtime paths in shared scripts. If the wrapper cannot make `jsonschema` importable, install it for that runtime; do not accept silent schema-skip behavior.
4. Run the relevant schema and runner tests personally; do not rely on Claude's test report.
5. Independently recompute or re-derive key artifact numbers from raw/source inputs where feasible: t-stat, cohort count, top-N, coverage, min/max dates, pass/fail gates, and ledger spend.
6. Verify guards with adversarial inputs where feasible: corrupted frozen fields, empty sets, duplicated execution, exhausted ledger, pending approvals, bad schema fields, and boundary dates should fail loudly.
7. Check lineage, PIT, and consumption points end to end: each value must come from the promised source, use the promised as-of semantics, avoid look-ahead / survivorship leakage, and be read by the downstream consumer under the documented field name.
8. Check invariants and side effects: a fix must not weaken unrelated contracts, skip existing checks, mutate immutable artifacts silently, or leave partial result / pending state after failure.
9. Check hygiene and security: no token, secret, provider URL, raw row, non-gitignored raw payload, large cache, or unapproved provider sample may enter tracked files; no silent scope expansion beyond the reviewed slice.
10. Check authorization gates: double-confirm, singleton ledger, unspent test budget, research-only / no-ship boundary, and no-provider-call / no-run constraints must be constants or otherwise hard to bypass.
11. Calibrate evidence statistically and economically: effective sample size, overlapping cohorts, HAC / clustered significance, concentration, drawdown, cost, liquidity, time-series / cross-section / distribution slices, and plausible magnitude must match the claim.
12. Mark diagnostic-derived hypotheses explicitly. In-sample leads may become new preregistered hypotheses only through a new ledger and user approval; they are not independent out-of-sample proof.
13. Use negative or weak controls when useful to test the gate, but never tune thresholds after seeing the target result.
14. Separate verdict layers: computation correctness, schema / ledger validity, PIT / data integrity, statistical alpha claim, risk / deployability, and production / ship-gate readiness.
15. Route material unresolved risks into `docs/system_risk_register.md` or require a fix before Pass. A material finding left only in chat or SESSION_LOG cannot receive a clean Pass.
15a. **Doc-drift materiality gate (2026-06-14)**: documentation drift is Required only when it can affect system quality or review quality. Blocking doc-drift includes stale or false text in current authority contracts, required startup route docs, run entries / CLI help, schema descriptions that consumers rely on, test assertions or guard explanations that define expected behavior, live-state gates, or any prose likely to misroute a future implementation/review. Non-blocking doc-drift includes clearly historical / archived / superseded text, low-impact comments, or stale prose that is not used as an active contract and cannot mislead the next execution/review; report these as Optional or ignore them, and do not block PASS for them. If a review FAILs on doc drift, the register entry must state why the drift is material; otherwise record `Register: non-material` and allow PASS.
16. **One-pass defect-class matrix before verdict (2026-06-13)**: Codex must not stop after the first obvious finding in a class. After finding any material defect, guard gap, protocol drift, or design hole, continue the review across the same defect class before replying: enumerate the sibling surfaces / producer-consumer exits, run adversarial variants where feasible, and collapse related findings into one complete repair package. For protocol/doc guards, the default matrix includes same-day vs future entries, PASS / FAIL / `修复` headers, Chinese and English wording, free-form paragraphs, extra labels, missing proof-of-use, verification placeholders, grandfathered-history boundaries, and false-positive controls. For code/schema/data slices, use the analogous matrix for the touched contract: valid vs invalid schema, empty / duplicate / malformed / stale / future / boundary inputs, **same-date but wrong lineage/candidate-set artifacts**, partial coverage (missing current candidates / duplicate candidates / extra stale candidates / order drift), sibling artifact sweep, downstream consumption, positive-control matching-lineage pass, and reverse-failure controls. If a P0 blocker or missing artifact prevents a full matrix, state the exact unreviewed dimensions and residual risk; do not claim a complete review. FAIL output must batch all discovered same-class Required fixes instead of drip-feeding one issue per round.
16b. **First review is slice-complete, not delta-only (2026-06-17)**: the first Codex `审查` in each review/fix cycle is a current-slice full review by default. It must start from current repo files, the current target / route docs, `git status --short --untracked-files=all`, touched tracked/staged/unstaged/untracked files, relevant schemas/tests/docs, downstream consumers, and the open P0/P1/P2 or Required IDs that can affect the slice. It is not a whole-repo line-by-line audit, but it must fully cover the current slice boundary. Do not treat old chat conclusions, the previous FAIL, or the last repair diff as sufficient scope. Later re-`审查` after `修复` may focus on the Required repair, but must still check collateral changes, same-class recurrence, and any new files/status changes in the slice. If Codex cannot cover any relevant dimension, the verdict must say exactly what was not reviewed and the residual risk; it must not present a partial review as complete. User wording such as `重新全量审查` means restart this slice-complete review from current files and discard prior review assumptions.
16c. **Authority-vs-implementation design-code matrix (2026-06-20)**: when the target is a design-code / design-implementation review, Codex must first write the authority ladder in its private notes: latest user instruction + the current **user-supplied authority artifact** (desktop final design, review artifact, issue, or explicit spec) outrank repo baseline; repo owner spec outranks reference/archive files; memory and old chat are only locators. Then compare the current repo truth and touched artifacts against that authority. If there is **no reviewable implementation** or no touched artifact for the requested system, say so and do not pretend a code-level PASS was performed. The default matrix must cover: authority / routing consistency and claimed landing surfaces (verify "single authority", "route docs updated", "register entry added", and "private path guarded" claims against `git status`, `git diff`, and the actual route docs); **design-only / schema-first / user-approval** boundaries; unauthorized **provider / DataHub / runner consumption** including full-universe, FMP, yfinance, Web/X, SEC parser, fallback/status polling, raw parsing, production storage, and fixture generation; lane invariants such as active-only, cadence, session/price-clock, universe, eligibility, rank/action separation, holding-specific actions, and lifecycle state; evidence separation **paper / manual_actual / live_normalized** and ship-gate non-relaxation; output privacy **private / gitignored** paths plus no secret/account/holding/trade leakage; **A/US isolation** for rules, paths, cash buckets, market calendars, thresholds, and ship-gate claims; no-dangling/evidence-ref mapping; and tests/guards that prove the behavior, not just field existence.

### Codex review closeout gate

Before Codex replies to any `审查`, Codex must complete this closeout gate and make the result true in repository state:

1. `docs/SESSION_LOG.md` has been prepended with the review verdict, including scope, Required / Optional, material-risk status, verification run, and next step.
2. Every Required finding has a materiality label. Material means it affects data integrity, PIT safety, schema contract, execution / ledger correctness, security / raw / secret hygiene, ship-gate evidence, cross-LLM continuity, or current docs whose drift can affect system quality / review quality under item 15a. Low-impact historical / superseded / non-contract prose is not material and must not block PASS.
3. Every material Required finding is either fixed in the reviewed slice or recorded in `docs/system_risk_register.md` with status, severity, scope, PIT label, evidence, Required ID, and closure condition. If no register entry is written, the review must state `Register: non-material` or `Register: already covered by <risk id>`.
4. `git status --short --untracked-files=all`, unstaged diff, staged diff when present, and every intentional untracked file have been included in the scope manifest.
5. Relevant schema / runner tests and independent artifact recomputation have been run personally where feasible. If a test or recomputation is not feasible, the review must state the exact gap and residual risk.
6. Guard / mutation checks were attempted for frozen fields, ledgers, approvals, and hygiene gates where feasible; otherwise the review states why not.
7. The verdict layers are not collapsed: computation, schema / ledger, PIT / data, statistical claim, risk / deployability, and production / ship-gate readiness are separated when relevant.
8. Final response confirms the register outcome and must not issue Pass while any material Required finding is neither fixed nor registered.
9. On PASS, Codex must auto-commit the reviewed slice before sending the final response, after rerunning the relevant local verification and confirming the staged files match the PASS scope. Stage only reviewed files; never include unrelated or unreviewed work. If safe auto-commit is blocked, record the reason in `docs/SESSION_LOG.md` and say exactly what remains uncommitted.
10. Final response must end with the fixed `下一步` section containing exactly one standalone command line for the next actor, with no `大白话` line and no repair details. Use the shortest command form, for example `Claude Code：Pass`, `Claude Code：修复`, or `Claude Code：执行`; put detailed instructions in `docs/SESSION_LOG.md` / `docs/system_risk_register.md`, not in chat. Do not use `Claude Code：提交` after a PASS; Codex already owns that commit. If visual emphasis is used, emphasize only the command token; never output raw HTML tags such as `<span>` / `<strong>` in the final reply.

Codex review output must follow `## 输出结论规则`: exactly `Verdict` / `Required / Optional / Options` / `下一步`; `大白话` belongs only to the first two sections, while `下一步` is one command line only. No `Findings`, no standalone chat verification section, and no extra sections. Codex must prepend the review verdict to `docs/SESSION_LOG.md` before replying. If no issue remains, say it is clean; do not invent fixes to appear thorough.

## Claude implementer standard

When the user sends `修复` (or any implementation of a Codex-reviewed Required / Options / fix), Claude must judge the instruction before writing code — `修复` does not make Claude a blind executor. Because the `批准修改` step has been dropped, the user's `修复` is itself the authorization, so this judgment is the main safeguard between review and change.

1. Read the actual reviewed finding(s) in `docs/SESSION_LOG.md` (and any cited code, schema, or artifact). Do not infer the change from the command word alone.
2. Independently verify each Required is correct, sound, in scope, and necessary. For an Options finding, the implementer selects the optimal option and states why; do not auto-defer to the reviewer's recommendation.
3. If any reviewed item is wrong, harmful, out of scope, or based on a misunderstanding, STOP and surface it to the user (Final Approver) with the reason and a better alternative. Do not silently implement something believed wrong, and do not silently refuse.
4. Implement only the reviewed scope. No scope creep. Do not change frozen design values, factor definitions, measurement, thresholds, the universe, or the ledger unless that exact change is the reviewed fix.
5. Record Optional dispositions (accept / reject + reason) and run the relevant schema / runner tests via `.tools/run_unittest_with_repo_pythonpath.cmd` or an exactly equivalent setup that prepends `.tools/python_libs`, with `jsonschema` importable, before handing back for `审查`. The launcher searches `PATH`, then common Windows installs such as `%LOCALAPPDATA%/Programs/Python/Python*`; if a sandbox blocks that executable or no Python is found, set `STOCK_TEST_PYTHON` to the current runtime's `python.exe`. Shared scripts must not hard-code agent-private runtime paths.
6. The Claude `修复` `docs/SESSION_LOG.md` entry must record which findings were fixed, any item pushed back on with its reason, the disposition of each Optional, and the user-directed authorization (since `批准修改` is no longer a separate step).
7. **Pre-Codex self-review gate (run before EVERY `起草`/`修复` handoff).** Repeated avoidable round-trips came from fixing only the named instance and not tracing a fix's ripple. **完整规则正文是单一来源 → `docs/pre_codex_self_review_checklist.md`**(A class-not-instance / B ripple-grep / B2 single-source+drift-guard / C reverse-failure / D ambiguous-NL / E route-doc-single-state / F pre-flight,**含 Proof-of-use 行的格式**)。起草/修复前**必读必走**;本文**只点名、不复述规则正文**(防 AGENTS↔checklist 双写漂移——守护 `tests/test_doc_governance_guard.py`)。`修复`/`起草` 的 SESSION_LOG entry **必带一行 Proof-of-use**(格式见 checklist,**不可砍**——砍掉就退回"每轮漏一个面"):"Tests passing ≠ design closure."

This judge-before-execute duty is symmetric to the Codex adversarial review standard; "reviewed" or "Required" does not remove Claude's responsibility to catch a wrong instruction before it lands.

## 交接记录

任何 AI 助手（ChatGPT / Codex / 其他 LLM）继续 Phase 2-7、A 股短线筛选、rank 回测、analyzer、state、`A-EGS/egs_main.py`、`runners/backtest_rank.py`、`analysis_input.json` 或 findings 相关工作前：**默认不全量读 handoff**；按 `docs/handoff/README.md`（单一带注解索引，每个 handoff 一行"何时点读"）**点读**——只在当前任务触及该 phase / schema / runner / policy / 历史 finding 时打开对应文件。逐文件说明都在该索引,本节不再重复列表（避免与"不要全量读"冲突）。

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

### 归档（防文件膨胀）

`docs/SESSION_LOG.md` 每次会话必读（顶部 1-3 条）、每次 prepend/grep/打开都整文件加载，**不能无限增长**（2026-06-13 曾达 2.68MB / 15k 行 / 891 条）。过大时（经验阈值 >~150 条或 >~500KB）归档：**保留最近 ~30 条 entry + H1 header**，更早 entry **逐字**移到 `docs/archive/session_log/session_log_archive_<oldest>_to_<newest>.md`（reverse-chrono 不变），活跃文件 H1 后留一行归档指针。**零内容丢失**（归档=移位非删除；迁移后断言 `head + kept + archived == 原文`）。用 Python `utf-8` 写盘（**不要** PowerShell `Out-File -Encoding utf8`，它写 UTF-8 BOM）。归档文件是历史档案、不在活跃阅读路径。

### Entry 格式（七节）

reverse-chronological：**新 dated entry prepend 到文件顶部**。若 H1 intro 之后有稳定的归档指针(`> 📦 历史归档…`,见 §Session log discipline → 归档),它是 H1 之后的固定 meta，新 entry 紧跟在**该指针之后**;无指针时紧跟 H1 intro 之后。entry 之间保持 reverse-chronological(最新在上)。

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

### 评审循环 entry 极简模板（`审查` FAIL / `修复` / `审查` PASS）

上面的七节格式用于 **session 级**交接(会话收尾、phase 决策)。**单个评审循环回合**(一次 Codex FAIL、一次 Claude 修复、一次 PASS)**不用**七节——material finding 的完整详情是 `system_risk_register.md` 的单一职责(§System risk register discipline),SESSION_LOG 这里只放最小交接事实、并指向 Required ID:

```markdown
## YYYY-MM-DD — <LLM> <审查 FAIL | 修复 | 审查 PASS> (<Required ID 或 slice 名>)
- **Verdict/Action**: FAIL→一行结论 | 修复→修了什么/主动没修什么+为何 | PASS
- **Required**: <R-ID...> — 完整 Required/风险/边界/closure 见 `system_risk_register.md`(单一来源,本处不复述)
- **Verify**: <命令+结果, 如 "138 tests OK; git diff --check clean; BOM/FFFD=0">
- **Next**: <下一步>
```

`修复` 回合**必须**额外带一行 **Proof-of-use**(§Claude implementer standard item 7,压成一行证据,**不可砍**——砍掉就退回"每轮漏一个面")。`审查` verdict 仍须 prepend 后再回用户。

**精确集合契约(最强不变式,非子集放行)**:compliant-zone(marker 之上)引用 R-ID 的评审 entry,正文 bullet 标签集合必须**恰好**= `{Verdict/Action, Required(指 R-ID + register), Verify, Next}`(`修复` 再加恰好一个 `Pre-Codex self-review`/`Proof-of-use`)。**缺项 / 多项 / 重复标签 / 任何自由段落(任何语言)/ `Verify` 占位符(`N OK`/`<N>`/`TODO`/`TBD`/`XXX`/占位)/ 单条 bullet 超 ~500 字符(把 register 全文塞一条)都会 FAIL**——完整 finding 详情只进 `system_risk_register.md`。守护覆盖三类 header:`审查`/`修复`/`PASS`(纯 `Codex PASS (R-ID)` 也照查)。这是结构化精确集合,不靠列举禁词,换措辞/换语言/换 header 形态都绕不过。守护:`tests/test_doc_governance_guard.py::test_review_cycle_minimal_template_enforced_above_marker` + `test_review_cycle_guard_planted_failures`(九植入失败 + 一合规通过)。

**位置(marker 门,非 date 门)**:`SESSION_LOG.md` 顶部 archive 指针下有一行 `REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER`。**新评审循环 entry 一律 prepend 到该 marker 之上**(compliant zone);marker 之下是 adoption 前的历史,grandfather 不动。守护只校验 marker 之上的 entry(`tests/test_doc_governance_guard.py::test_review_cycle_minimal_template_enforced_above_marker`,配同日/带指针复述/合规三植入测试)——故"今天就是 adoption 日"也照样生效(date 门做不到)。**marker 不要删、不要移**。

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
- `docs/us_short_system_design.md` — US-short 子系统**单一设计权威**（docs-only；移植桌面定稿；§18.0 7 道 P0 硬门已登记 register `R-USSHORT-V1-P0-IMPLEMENTATION-GATES`；不锁 provider / runner / schema / Skill；实现 gated + 不交叉 A 股）
- `docs/us_short_spec.md` — 已降级为指向 `docs/us_short_system_design.md` 的归档指针（2026-06-20；不再是权威）
- `docs/us_long_system_design.md` — US-long（美股中长线，持仓 3-6 月）子系统**单一设计权威**（2026-06-24 移植桌面 `v3_us_long_design.md` 入 repo、桌面稿退役；foundation-first，Tier 2 起 active；只用本地样例，真实数据 / provider / DataHub / 联网 gated 到 Tier 4+；不锁 provider / 最终 schema / Skill；实现逐刀 schema-first + Codex 审查；不交叉 A 股）
- `docs/ALPHA_VALIDATION_ACTION_GUIDE.md` — Phase 7a+ 最高行动指南（alpha 真实性、业务漏洞、执行路线和后续 phase 挂载）
- `docs/alpha_plausibility_audit.md` — Phase 7a alpha plausibility / lane objective owner（schema-first audit route；决定 continue / risk-filter / redesign / defer / do-not-implement）
- `docs/evidence_capital_policy.md` — Phase 7a paper vs live-normalized evidence owner（不改变资金政策；ship gate 证据必须区分 paper / live_normalized）
- `docs/provider_priority_benchmark_contract.md` — Phase 7a-3 provider evidence priority / provisional benchmark owner（不选 provider；不锁最终 ship-gate benchmark）
- `docs/evidence_feasibility_controls.md` — Phase 7a-4 burst promotion / concentration / liquidity / slippage / circuit-breaker owner
- `schemas/evidence_feasibility_controls.schema.json` — Phase 7a-4 evidence feasibility controls 契约，当前 `1.0.0`
- `docs/evidence_report_schema_contract.md` — Phase 7a-5 evidence report schema owner
- `schemas/evidence_report.schema.json` — Phase 7a-5 evidence report 契约，当前 `1.0.0`
- `docs/provider_evidence_drift_monitor.md` — Phase 7b-1 provider evidence / drift monitor contract owner；Phase 7b-2 evidence population 需消费它；§15 记录 US EGS 数据源方向（FMP 主源候选 + SEC EDGAR 基本面审计 + yfinance 仅显式批准后的价格 smoke check）；§20 记录 post-stable-retry remaining-blocker plan；§21 记录 fallback / incident / stability playbook；§22 记录 incident-log contract；§23 记录 license / storage / retention review；§24 记录 SEC EDGAR audit parser scope contract；§25 记录 FMP PIT / observed-date semantics contract；§26 记录 FMP price-adjustment / corporate-action semantics contract；§27 记录 SEC EDGAR field-family mapping contract；§28 记录 coverage-count access-packet plan；§29 记录 approved coverage-count execution summary；§30 记录 missing key-metrics resolution plan；§31 记录 provider validation authorization packet；§32 记录 provider validation execution packet；§33 记录 provider validation execution summary；§34 记录 inactive / delisted gap resolution plan；§35 记录 FMP entitlement / corporate-action no-access diagnostic；§36 记录 SIVB-only FMP 402 re-probe execution packet；§37 记录 SIVB-only FMP 402 re-probe execution summary；§38 记录 FMP paid-tier / license public-docs review
- `schemas/provider_evidence_drift_monitor.schema.json` — Phase 7b provider evidence / drift monitor 契约，当前 `1.1.0`
- `docs/provider_evidence_p1_us_public_sources_20260528.json` — Phase 7b-2 P1 US public-source provider evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_market_data_candidates_20260528.json` — Phase 7b-2 P1 US market-data-candidate provider evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json` — Phase 7b-2 P1 US authorization / cost / stability provider evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_benchmark_gics_candidates_20260528.json` — Phase 7b-2 P1 US benchmark / GICS candidate evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_fundamentals_observed_date_candidates_20260528.json` — Phase 7b-2 P1 US fundamentals observed-date candidate evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `docs/provider_evidence_p1_us_coverage_fallback_incident_candidates_20260528.json` — Phase 7b-2 P1 US coverage / fallback / incident candidate evidence snapshot（partial / blocked；不选 provider、不抓数据）
- `schemas/provider_p1_readiness_review.schema.json` / `docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json` — Phase 7b-2 P1 readiness review matrix（collection complete；Phase 7c / provider selection / broad data fetch blocked）
- `schemas/provider_p1_access_decision_plan.schema.json` / `docs/provider_evidence_p1_us_access_decision_sample_validation_plan_20260531.json` — Phase 7b-2 P1 access-decision / sample-validation plan（plan-only；approved spend = 0；narrow sample approval lives in separate artifact）
- `schemas/provider_p1_sample_validation_access_approval.schema.json` / `docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json` — Phase 7b-2 narrow US EGS sample-validation approval（$0；existing FMP key + SEC EDGAR public API；AAPL / MSFT only；no yfinance / full-market / Phase 7c）
- `schemas/provider_p1_remaining_blocker_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json` — Phase 7b-2 post-stable-retry remaining-blocker plan（plan-only；no new access / no provider selection / no DataHub / no Phase 7c）
- `schemas/provider_p1_fallback_incident_stability_playbook.schema.json` / `docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json` — Phase 7b-2 fallback / incident / stability playbook（schema-first design；no provider status polling / no fallback execution / no provider selection / no DataHub / no Phase 7c）
- `schemas/provider_p1_incident_log_contract.schema.json` / `docs/provider_evidence_p1_us_incident_log_contract_20260602.json` — Phase 7b-2 incident-log contract（schema-first design；no log writer / no provider status polling / no provider calls / no fallback execution / no provider selection / no DataHub / no Phase 7c）
- `schemas/provider_p1_license_storage_retention_review.schema.json` / `docs/provider_evidence_p1_us_license_storage_retention_review_20260602.json` — Phase 7b-2 license / storage / retention review（existing repo evidence only；no current terms web refresh / no legal advice / no provider calls / no DataHub / no Phase 7c）
- `schemas/provider_p1_sec_edgar_audit_parser_scope_contract.schema.json` / `docs/provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json` — Phase 7b-2 SEC EDGAR audit parser scope contract（schema-first；audit-only；no SEC call / no raw parse / no parser implementation / no DataHub / no Phase 7c）
- `schemas/provider_p1_sec_edgar_field_family_mapping_contract.schema.json` / `docs/provider_evidence_p1_us_sec_edgar_field_family_mapping_contract_20260602.json` — Phase 7b-2 SEC EDGAR field-family mapping contract（schema-first；audit-only；no SEC call / no raw parse / no fixture generation / no parser or field mapping implementation / no DataHub / no Phase 7c）
- `schemas/provider_p1_fmp_pit_observed_date_semantics_contract.schema.json` / `docs/provider_evidence_p1_us_fmp_pit_observed_date_semantics_contract_20260602.json` — Phase 7b-2 FMP PIT / observed-date semantics contract（schema-first；no FMP call / no raw parse / no field mapping implementation / no DataHub / no Phase 7c）
- `schemas/provider_p1_fmp_price_adjustment_corporate_action_semantics_contract.schema.json` / `docs/provider_evidence_p1_us_fmp_price_adjustment_corporate_action_semantics_contract_20260602.json` — Phase 7b-2 FMP price-adjustment / corporate-action semantics contract（schema-first；no FMP call / no raw parse / no return calculation / no corporate-action reconciliation / no field mapping implementation / no DataHub / no Phase 7c）
- `schemas/provider_p1_coverage_count_access_packet_plan.schema.json` / `docs/provider_evidence_p1_us_coverage_count_access_packet_plan_20260602.json` — Phase 7b-2 coverage-count access-packet plan（schema-first；no coverage execution / no provider call / no status polling / no raw parse / no fixture generation / no DataHub / no Phase 7c）
- `schemas/provider_p1_coverage_count_access_packet_approval.schema.json` / `docs/provider_evidence_p1_us_coverage_count_access_packet_approval_20260602.json` / `runners/us_egs_coverage_count_packet.py` / `schemas/provider_p1_coverage_count_execution_summary.schema.json` / `docs/provider_evidence_p1_us_coverage_count_execution_summary_20260602.json` — Phase 7b-2 approved 5-symbol FMP stable coverage-count smoke（30/30 HTTP 200；tracked no-secret summary；raw under gitignored `provider_samples/`；no provider selection / no DataHub / no Phase 7c）
- `schemas/provider_p1_missing_key_metrics_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json` — Phase 7b-2 missing key-metrics resolution plan（schema-first；no FMP / SEC call / no raw parse / no derivation implementation / no field mapping implementation / no DataHub / no Phase 7c）
- `schemas/provider_p1_validation_authorization_packet.schema.json` / `docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json` — Phase 7b-2 provider validation authorization packet（FMP Basic；existing FMP key + SEC EDGAR public API；$0；future reviewed 5-10 symbol / max 60 call validation only；no provider call in this slice / no provider selection / no DataHub / no Phase 7c）
- `schemas/provider_p1_validation_execution_packet.schema.json` / `docs/provider_evidence_p1_us_validation_execution_packet_20260603.json` / `runners/us_egs_validation_packet.py` / `schemas/provider_p1_validation_execution_summary.schema.json` / `docs/provider_evidence_p1_us_validation_execution_summary_20260603.json` / `schemas/provider_p1_inactive_delisted_gap_resolution_plan.schema.json` / `docs/provider_evidence_p1_us_inactive_delisted_gap_resolution_plan_20260603.json` — Phase 7b-2 provider validation execution packet / summary and inactive-delisted gap plan（fixed AAPL / MSFT / JPM / TWTR / SIVB；37 actual calls within 41-call budget；tracked no-secret summary；raw under gitignored `provider_samples/`；no provider selection / no DataHub / no Phase 7c）
- `schemas/provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic.schema.json` / `docs/provider_evidence_p1_us_fmp_entitlement_corporate_action_no_access_diagnostic_20260603.json` — Phase 7b-2 FMP entitlement / corporate-action no-access diagnostic（docs-only split / dividend templates；SIVB 402 open hypothesis set；no SIVB re-probe / no FMP split-dividend call / no provider selection / no DataHub / no Phase 7c）
- `schemas/provider_p1_sivb_reprobe_execution_packet.schema.json` / `docs/provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json` — Phase 7b-2 SIVB-only FMP 402 re-probe execution packet contract（SIVB only；5 failed FMP endpoint families only；max 5 calls；zero retry；no provider call in this artifact / no runner implementation / no provider selection / no DataHub / no Phase 7c）
- `runners/us_egs_sivb_reprobe_packet.py` / `schemas/provider_p1_sivb_reprobe_execution_summary.schema.json` / `docs/provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json` — Phase 7b-2 SIVB-only FMP 402 re-probe execution summary（5 fixed FMP calls；5 HTTP 402；raw body capture only under gitignored provider_samples；tracked summary no body / URL / secret；weak category signal only；no provider selection / no DataHub / no Phase 7c）
- `schemas/provider_p1_fmp_paid_tier_license_public_docs_review.schema.json` / `docs/provider_evidence_p1_us_fmp_paid_tier_license_public_docs_review_20260603.json` — Phase 7b-2 FMP paid-tier / license public-docs review（pricing / endpoint-template / public ToS signals only；no API call / no signup / no purchase / no trial / no legal clearance / no provider selection / no DataHub / no Phase 7c）
- `engine/datahub/job_spec_contract.py` / `schemas/datahub_local_resource_budget.schema.json` / `docs/datahub_local_resource_budget_contract_20260602.json` / `schemas/datahub_job_spec.schema.json` / `schemas/examples/datahub_job_spec.example.json` / `schemas/datahub_shared_layer_contract.schema.json` / `docs/datahub_shared_layer_contract_20260603.json` / `schemas/datahub_report_contract.schema.json` / `docs/datahub_report_contract_20260603.json` / `schemas/datahub_reproducibility_manifest.schema.json` / `docs/datahub_reproducibility_manifest_contract_20260603.json` / `schemas/datahub_data_quality_monitor_contract.schema.json` / `docs/datahub_data_quality_monitor_contract_20260603.json` / `schemas/datahub_minimal_a_share_read_path_plan.schema.json` / `docs/datahub_minimal_a_share_read_path_plan_20260603.json` — Phase 7c local resource / job spec enforcement + shared-layer / report / reproducibility / data-quality / minimal A-share read-path planning contracts（schema-first；future executable jobs must validate before running；no provider call / no DataHub implementation / no runner change / no Phase 7c authorization）
- `schemas/a_short_screening_threshold_governance.schema.json` / `presets/a_short_screening_threshold_governance_20260602.json` — A-short screening threshold governance parity contract（mirrors current `A-EGS/egs_main.py::CONF`; no runtime behavior change / no screening run / no provider call）
- `schemas/research_preregistration.schema.json` / `schemas/research_preflight_result.schema.json` / `schemas/program_test_budget_ledger.schema.json` / `schemas/evidence_report.schema.json` / `research/preregistrations/a_share_minimal_data_burst_20260531.json` / `research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json` / `research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json` / `research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json` / `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json` / `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json` / `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/signal_events.csv` / `research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/monthly_stats.csv` / `research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json` — research-only preregistration, preflight, evidence, and ledger artifacts（不进 production、不声称 ship-gate evidence；full-universe redesigned outcome 已失败，任何 further redesigned test 必须新 ledger planned test + reviewed preregistration）
- `schemas/analysis_input.schema.json` — analysis_input 契约，当前 `1.1.0`，JSON Schema Draft 7
- `schemas/deterministic_report.schema.json` — deterministic report 契约，当前 `1.2.0`，Phase 4 runner 输出 JSON 必须通过该 schema
- `schemas/rank_backtest_report.schema.json` — backtest_report 契约，当前 `1.11.0`（含 date_warnings + data_lineage + analyzer veto replay）
- `schemas/provider_capability_catalog.schema.json` — Phase 7 provider capability / field catalog 契约，当前 `1.0.0`（schema-first；不锁最终 provider / adapter / DataHub table）
- `schemas/examples/provider_capability_catalog.example.json` — Phase 7 provider capability catalog 示例（验证 schema；不是生产 provider registry）
- `schemas/analysis_input_coverage.md` — schema 覆盖率与修复记录
- `docs/burst_lane_spec.md` — Phase 6c A / US 短线 burst lane docs-only baseline（独立 signal / risk / sizing / ship gate；不继承 steady lane gate）
- `docs/long_alpha_spec.md` — Phase 6d 长线 alpha 共同规格与 A / US 长线 skeleton（docs-only；不锁 provider / runner / schema）
- `docs/provider_data_requirements_audit.md` — Phase 6e provider / data requirements audit（docs-only；不锁最终 provider / schema / DataHub implementation）
- `docs/handoff/README.md` — **所有 phase handoff 的单一带注解索引**（每个 handoff 一行"何时点读")。本节不再单列各 handoff(避免与 §交接记录 + 该索引重复/漂移);按该索引点读。
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
