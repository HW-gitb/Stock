# US Short System — Design (in-repo authority, docs-only)

> **Status**: US-short single in-repo design authority and working baseline. Design is not final; this document must not be treated as a design-completion date or a diagnostic-week anchor. Only a future standalone `设计完成` notice explicitly issued by Codex after a design audit, together with a source-bound start receipt created in the same operation, may set the diagnostic start/epoch. Until both exist, `diagnostic_start=null`, `diagnostic_epoch=unset`, and `clock_status=not_started`. Batch1 offline data contract/input conversion, batch2 pure decision engines, batch3 validator/output/paper/comparison/lifecycle-eval, and batch4 offline weekend pipeline through 4d-ii-o are implemented in repo and reviewed per slice (routes: `docs/README.md`; live handoff: `docs/SESSION_LOG.md`). Batch5 (provider/live) is PARTIALLY implemented: the offline provider/live governance contracts (10-call probe, post-probe disposition, license/storage, SEC parser binding, fallback/incident, incident-log writer), a user-authorized round-1 Massive+SEC universe fetch + Pass1, round-2 momentum/catalyst/GICS industry-heat/provisional-theme-heat producers, Cut 6-a/b/c/d score-block seams, provider-fed batch5→batch4 `data_context` source assembly plus offline official-context (`per_ticker_analysis`/`run_provenance`) assembly from resolved local sources, status-source `run_fetch` wiring for SEC active-listing reference + Nasdaq current halt feed, bounded live Pass2 source-packet runner/execution into local `data_context`, bounded reviewed-plan full theme source-packet producer/execution, bankruptcy 8-K local source-packet screen runner/execution, bounded bankruptcy 8-K selected-candidate SEC source-packet producer/execution, first two 25-symbol bankruptcy 8-K candidate scans/executions, resumable candidate-universe bankruptcy 8-K round01+round02+round03, `run_fetch`/status-record consumption of the completed bankruptcy screen output, `run_fetch` provider-health/fallback run-state summary wiring, full-candidate projection-input merge/preflight/forecast, and a local Batch5 source-packet -> Batch4 weekend E2E bridge to private `weekly_report.md` / `action_table.csv` with subprocess CLI and no-residue failure cleanup, exist in repo. The supported batch4 offline context packet builder/runner path also exists for local fixture execution. Separately gated under `SR-PROVIDER-001`: broader provider stability evidence, automated/broader peer-theme discovery beyond the reviewed local plan, live/real-provider-resolved `per_ticker_analysis`/`provenance` data path beyond reviewed local sources, DataHub, Skill, production evidence, corporate-action reconciliation, and any further live/forward provider authorization. Any future implementation remains schema-first + tests + review, multi-LLM serial, no A-share crossing.
> **本稿 = repo 工作权威**：本文是 US-short 当前设计工作基线；设计尚未完成，不得把本稿、`2026-06-20`、部件完成日期、账户播种日期或任何历史提交当作设计完成日期或诊断起点。未来只有 Codex 在完成设计审计后明确发出独立的 `设计完成` 通知，并在同一操作生成 source-bound 启动 receipt，才可设置诊断起点；通知或 receipt 缺一都不能产生第 1 周。本文取代 `docs/us_short_spec.md` 成为当前唯一设计入口；`docs/us_short_spec.md` 已降级为指向本稿的**归档指针**（gate ①，不两个权威并存）。本稿保留既有结构、约束与机器核验结果；更早桌面草稿（`US_Short_System_design_v2_clean.md` / `…v2.md` / `…优化版` / `…v1_Design`）均已弃用、不再当权威。
> **依据**：原桌面设计稿 + grilling 锁定决策 + 多轮对抗式审查（Codex + 自审）+ A 股已完成代码对比（借工程机制、不借 A 股市场规则）。
> **系统只有 v1 线**：不另起架构 v2/v3，延后项一律走 `candidate_active` / lifecycle 候选，不开 v1.1 版本线。
> **三道写 repo 硬闸（gate ①②③）落地状态**：① 旧 `us_short_spec.md` 已降级归档指针；② §18.0 的 7 道 P0 已登记进 `docs/system_risk_register.md`（`R-USSHORT-V1-P0-IMPLEMENTATION-GATES`，open / binding）作**硬规则**、非普通 TODO；③ `.gitignore` 覆盖 US-short 全部 ticker-bearing private 目录（含 checkpoint bundle），所有 persister 复用 `reject_nonprivate_output_path` 的真实 `git check-ignore` fail-closed 守卫并有生产路径回归测试（§11.6 / §18.1 #1）。

> **2026-07-10 update**: `runners/us_short_yfinance_grades_fetch.py` + `engine/us_short_yfinance_analyst_grades.py` implement the formerly probe-only yfinance analyst-grades sub-signal as a low-trust / non-official / ToS-gray, default-dry-run, per-execution-authorized optional source. The active analyst-grades source is represented by the non-critical `analyst_grades` health family; the capstone validates the yfinance stage summary, while an explicit FMP fallback remains supported. Missing/down analyst grades are neutral non-critical inputs and never gate emit, DataHub, production, or ship-gate.
---

## 0. 定位与总原则

每周一次、一键跑完的**美股短线（只做多、短持有期：几天~几周）**辅助系统：从 NYSE/NASDAQ 选股 → 完整分析 → 给出带价位的操作建议（建仓 / 加仓 / 减仓 / 清仓 / 止盈 / 止损 的状态与价位）。**不接券商、全手动下单**，系统只产建议与证据，钱在用户手上。

**总原则 ——「进攻在选股/发现，克制在执行/下注，同一风险只罚一次」：**
- **选股/发现层尽管进攻**：追强势赛道、捕跨行业新主题、不因小数据缺失乱踢票（= "别太保守"）。
- **下注/执行层必须冷静**：系统 active-only、未验证 alpha，对没毕业的动量策略激进下注 = 最快亏钱。
- **两层物理分开**：激进选股若错，被「小仓（ship-gate 未毕业本就压小）+ 组合熔断 + 试探仓封顶」用美元兜住。**进攻选股 ≠ 激进风险**——每条"更进攻"的设计都必须配着风险侧一起生效。
- **过热/极端价格 = 执行问题、不是选股问题**：美股强趋势票常"高了还能更高"。温和过热（`overextension_warning`）只在**执行侧**克制（强制低吸入场 / 压仓 / 抬 RR），**不踢出选股、不剥夺赛道分**；只有抛物线喷出（`chasing_extreme`，多条件同时成立、非单看涨幅）才在**选股层**剥夺赛道热度分（§4.3）。
- **单舞台原则**：每个风险因子只在 选股分 / 仓位 / 席位 一处罚一次，不重复，不叠成连环罚；硬风险走 §5。

---

## 1. 边界与范围

- 只做**筛选、分析、风控、报告**；不接券商、不自动下单、不接 OS 自动化；所有下单/撤单/调仓手动。
- 模块用状态 `active / candidate_active / shadow_record / disabled`，经提醒机制（§13）启用/降级/校准/删除。
- **做多/做空**：v1 **只做多**；做空只留"标记好的门"——数据模型留 `direction`（恒 `long`）+ 注明"做空以后独立通道，需补 borrow/locate/SSR/Reg SHO + 逼空风控"；v1 不写做空逻辑。
- **不交叉 A 股**：独立 preset / state / 路径；共享 engine 时不污染 A 股行为。
- **资金桶**：仓位只对**美股短线桶** `us_short_bucket_capital = us_market_equity ÷ 3`（§8）；不碰总资产、不借美股长线/现金/A 股的钱；A/US cash 不互通。

---

# 共同基础（§2–§3）

## 2. 总体架构（每周一次一键跑完；canonical 决策日 = 即将到来的交易日、开盘前，§2.1）

```text
load config / state / data  (+ provider 健康检查 §3.7；不健康→restricted/blocked)
  → universe filter (NYSE/NASDAQ active-only)
  → Pass 1（全 universe，便宜/批量）：cheap eligibility gate（交易所/价格/ADV/市值/基础状态）
        + 动量·相对强度 + 赛道热度 + catalyst_recall_lane → 收窄到候选集（几百只）
  → Pass 2（候选集 + 强制含持仓，贵数据）：audit safety gate（SEC 增发/退市/审计，按 §5.1 两层）
        + 催化剂/预期差 + 完整 core_score → Top15
  → holdings merge（持仓并入，即使跌出 Top15 也完整重评 = 全分析 + 重算 core_score）
  → 分析：hard veto → 价格引擎 → 市场环境（两轴）→ 仓位（含熔断/冷静期/现金分配）→ 未来事件 → 操作排名
  → 不悬空 + 证据反查（机器强制）
  → lifecycle eval（`us_short_lifecycle_eval`：先扫 §13.1 全部 comparison-only/forward 项算到期态 → 喂周报生命周期节/顶部横幅 + readiness artifact + 运行时醒目横幅；§13）
  → 输出：weekly_report.md + action_table.csv（+ 私密机器层/纸面账）
```

- **Top15 = `core_top` + `theme_momentum`**，比例随 `theme_opportunity_state` 动态（常 10+5 / 强赛道 8+7 / 无强赛道 12+3，§4.5）。Top5（按 rank）+ 所有持仓完整分析；Top6–15 观察池（轻量）。**强赛道周**额外允许把 Top6–15 里 1–2 只主题龙头（确认优先；严格筛选下可含新兴，§4.5）升级为完整分析（≠自动建仓，是 §8 强赛道试探仓的前置）。
- research / backtest 只用于排雷/调参/版本比较/证据记录，**不能授权实盘/full-size**（§12）。

### 2.1 运行 cadence
- **决策日 = 即将到来的美股交易日（正常周=周一）、美股开盘前跑**（canonical 解析见下「运行窗口」）。价格用 **canonical 决策日前一已收盘交易日收盘**（正常=上周五；周末/开盘前无更新价）；新闻/web/LLM 窗口拉到**运行时刻**（含整个周末 + 周一早间突发）。
- **北京时间**：美股周一开盘 9:30 ET = 北京周一晚 21:30（夏令时）/ 22:30（冬令时）；北京周一白天/傍晚跑、挂限价单等开盘自动成交，不必盯盘。
- **运行窗口 + canonical 决策日解析（允许非交易日/窗口内多次运行；2026-06-22 加，借 A 股 `runners/resolve_canonical_asof.py` 同款）**：用户可在「上周五美股收盘后 → 周一美股开盘前（9:30 ET）」窗口内**任意时刻、可多次**运行（北京时间 ≈ 周六凌晨 → 周一晚 21:30/22:30）；窗口内任何时刻跑都收敛到**同一个 canonical 决策日 = 即将到来/当前尚未开盘的美股交易日**（正常周 = 即将到来的周一）。这样多次试跑/不同时刻跑不会把同一周决策当成多个 cohort 灌 forward 证据。
  - **live canonical 窗口有两条边（关键，US 特异，≠ A 股单一收盘 cutoff）**：① **起点 = 上一交易 session 已收盘（16:00 ET，含半日市 early-close）**——此后该日收盘价才结算、成为下一决策日的价格基准；② **终点 = 目标决策 session 的 RTH 开盘前（9:30 ET）**——必须开盘前决策才能挂该 session 的 RTH 限价单（`first_regular_session_only`）。落在两边之间（= 上一 session 收盘后 → 目标 session 开盘前，含盘后/隔夜/周末/假期）跑 → canonical = 该目标 session（周五收盘后 / 周末 / 周一开盘前 → 周一）。
  - **盘中（某 session 的 RTH 开盘到收盘之间）= 死区，fail-closed / out-of-window**：此刻既不能为当前 session 决策（开盘已过、入场窗关闭），也不能为下一 session 决策（当前 session 未收盘 → 下一 session 的价格基准 = 当前 session 收盘 尚未结算，否则只能用陈旧的更前一日收盘、违反「前一已收盘交易日」价格钟）→ **批4 此时不得 emit 新私密 packet、不得为下一交易日产 forward 证据决策**；**只有当前 session 收盘后** resolver 才滚到下一交易日（价格基准 = 刚收盘的 session）。用户窗口（上周五收盘后 → 周一开盘前）整段落在任何 active session 之外 → 永远在合法窗口、canonical = 周一；死区（如周一 9:30-16:00 ET）在用户窗口之外、为健壮性显式定义为 out-of-window（正常不触发）。
  - **US 市场日历（NYSE/NASDAQ，§3.5）解析**「下一未开盘交易日」+「最近已收盘交易日」：自动处理美股假期（周一逢 MLK / Presidents / Memorial / Independence / Labor / Thanksgiving / Christmas 等休市 → canonical 滚到周二）、半日市（early close 仍是交易日、open 仍 9:30、收盘提前到 13:00 → roll 起点也随之提前）、DST（两边都锚 ET——决策终点 = 9:30 开盘、roll 起点 = 当日收盘；不依赖北京本地夏/冬令时；timezone 记 ET+UTC，§3.5）。
  - **价格基准 = canonical 决策日的前一已收盘交易日**（周一未开盘 → 上周五收盘；逢节自动回退到节前最后交易日）——**由 canonical 窗口起点（上一 session 已收盘）保证该基准恒已结算、不会陈旧**，与本节「价格用上周五收盘」一致。**新闻/语义窗口 = 运行时刻**（PIT `observed_at <= 运行时刻`、物理抓不到未来事件 → 自然含周末 + 周一早间突发）。
  - **幂等不灌前向证据**：窗口内多次跑都收敛到同一 canonical 决策日 → forward 证据按 `(decision_date, symbol)` 去重 + 单一 decision_date；私密周报/机器层（§11.1，按 `<决策日>` 分目录）后跑覆盖前跑；升级闸只数 live forward 观测、桶名 ≠ decision_date 即 fail-closed 弃（§11.4 / §13.1）→ 重跑不重复计数。
  - **live / historical 判据（同 A 股口径）**：`decision_date >= run_date` = live（今日 或 前瞻 canonical）、`decision_date < run_date` = 真·过去回放（research/backtest only，须显式标、**不推进 forward 证据/不写私密实盘产物**）；canonical 恒 live。
  - **实现归属 = 批4 周末 pipeline（§18.2）**：canonical 解析器在编排最前面（运行时刻 + US 日历 → decision_date），把 decision_date 贯穿喂给 universe / Pass1 / Pass2 / engine / output / 转换器（`decision_as_of`）；**批2 引擎 + 批1 转换器保持日历无关**（as_of 由 pipeline 注入、引擎/转换器不自行解析交易日，已核现编码无交易日 gate）。**非交易日运行时不拒、而是解析到 canonical 交易日**（区别于 A 股 egs_main 早期「拒非交易日 as_of、靠 resolver 兜」——US-short 从设计起就按 canonical 解析，无非交易日拒门可踩）。
- **跳空校准（可手动执行）**：新建仓输出为**限价单 + `valid_entry_band`**，`order_expiry = first_regular_session_only`（只在周一正常交易时段 RTH 有效）。周一 RTH 开盘价超出带子 → 不成交 → 转观察（盘前只作参考、不据此成交；不追高、不接飞刀）；当日 RTH 收盘仍未成交 → 转观察、不留隔日。带宽 = prior（§13）。
- **周中态**：周频、**不盘中重评**；持仓靠周末设好的止损/失效/止盈执行；重大突发（财报跳空/停牌/突发做空报告）由用户手动决定提前离场，下个决策日系统再完整重评。

## 3. 数据源、口径、微结构、手动输入

> **数据授权硬边界（SR-PROVIDER-001 仍 open）**：下面的数据三档 = **目标数据合同（target data contract），不是现有授权**。2026-06-02 的「$0 小样本」授权仍只覆盖既定 FMP/SEC 小样本；公司行动源入口另有 2026-07-13 用户指令，只允许默认 dry-run 的单文档 SEC 简单条款解析器与单票 yfinance 日报警实现，真实调用仍须逐次显式确认。**FMP Basic 全市场调用 / Web·X / 广义 SEC fundamentals parser / storage·retention / provider selection / DataHub·生产消费仍须单独 reviewed + 用户批准**；不得把本入口当全 universe、生产或 ship-gate 授权。详见 §18.0 P0。

### 3.1 数据三档（目标合同；2026-06-17 小样本 repo 证据仅 FMP + SEC，yfinance 仅目标低信任档、未授权/未纳入 repo 证据）
| 档 | 数据 | 用途 |
|---|---|---|
| **可信**（能打分、能硬否决） | FMP：股价/量、基础财务、分析师目标价/评级 + 历史评级、**财报实际 vs 预期**、估值比率、流通股本；免费 SEC EDGAR：文件、内部人(Form 4/144)、增发/转售(S-3/424B/S-8)、8-K、退市表(25-NSE)、机构持股(13G) | 选股打分 + 安全闸/硬否决 + 催化剂 |
| **低信任**（只标签，不打分/否决；**yfinance 未授权·需单独批准·目前不在 repo 证据**） | yfinance 自算 PCR / IV（当天快照；IV 用于"财报前降仓"提示） | advisory 标签 + 软风控 |
| **拿不到 / 挂登记表** | 借券费、真·期权异动/扫单、暗池；滞后空头比例（FINRA 半月、落后 2-3 周） | 不做，等可靠源（§13） |

- 新闻/做空报告 = WebSearch/WebFetch 语义提示；**未单独批准时 `disabled_unapproved`（不调用）**；授权后也只做语义提示、**不结构化打分 / 不硬否决**，除非后续 schema-first 单独实现并 review。
- 覆盖差异：大票全、小票稀 → "有就用、没有标未知降级"，不静默放行。
- 每字段运行时记 `provider_id / endpoint_or_filing_type / as_of / observed_at / coverage_status / parser_status / lineage`。
- **round-1 已实现的价格源 ≠ 本表"目标合同"（实现登记，2026-06-26；2026-06-29 R2 ADV 多日化 + per-run lineage；2026-07-06 provider-health/fallback summary wiring；2026-08-14 Problem 1 residual repair）**：实际 universe fetch 的 **股价走 Massive grouped-daily，SEC 流通股先走 frames/CompanyFacts；SEC 缺股名的市值残差走 yfinance `Ticker.info`，最后才走 Massive ticker-overview**，不再由 Universe 调用 FMP profile。yfinance 只读 `info` 一次；优先 `sharesOutstanding ×` Massive 实际观测到的 close（通常是 `price_basis_date`，Massive 延迟时允许更早的 `used_date`），只有两者跨 `$300M` 治理阈值时才用正的 `info.marketCap` snapshot；Yahoo shares/marketCap 都保留 retrieval snapshot lineage，不宣称严格 PIT。yfinance 缺包、单票失败、identity/rate/crumb 停止都如实降级，剩余精确残差不丢给 Massive；逻辑 ticker attempt 不冒充物理 HTTP call。**ADV = 截至 price_basis 的 N 个交易日（`ADV_WINDOW_TRADING_DAYS=20`，§13.1 #2 方法学 prior）日均美元成交额（多日均值、非单日；逐交易日 grouped-daily 调用、Massive 延迟未发布日自动跳过；某 ticker 覆盖 < `ADV_MIN_DAYS_REQUIRED` → `adv_usd=null` 保守拒、绝不靠单日 spike 放行——governance floor=$5M/day 即多日日均义）**。每次 fetch 产出 **schema-first per-run 候选 artifact**（`schemas/us_short_universe_candidate_artifact.schema.json`：每行 Pass1 输入+判定+§3.2 lineage，写前 schema+语义校验、summary 从行重算、eligible 行须 ADV 覆盖足且达门槛），输出路径绑 **canonical decision_date（§2.1）**、不再钉死日期，且**含 per-row 价格 → 候选 artifact 路径写前钉死为 canonical `state/us_short/candidate_universe_<decision_date>.json`（须恰等于此 gitignored 文件名；非 canonical/错日期/非 gitignored 一律 fail-closed、不落盘；生产 CLI 不再暴露 `--candidate-list-path` override）**；日历 `verification_status` 随 artifact 披露。当前仍为**单一价格源、无价格 fallback**（Massive 故障即 universe/ADV/市值同时不可用）；市值 fallback 只是 opportunistic rescue，`run_fetch` summary 记录 provider health，但不把 yfinance 可用性/成功率包装成 provider-readiness evidence。Massive 为延迟数据，仅够 §2.1 前收价钟；本 slice 不授权 DataHub/生产/ship-gate。

### 3.2 Fallback 与运行状态
**2026-08-14 Problem 1 implementation route (current Universe path)**：Universe 的价格仍只来自 Massive grouped-daily；SEC frames/CompanyFacts 之后，市值残差严格按 **yfinance `Ticker.info` → Massive ticker-overview** 处理，Universe 不再调用 FMP profile。yfinance 只读一次 `info`，优先 `sharesOutstanding ×` Massive 实际观测到的 close（通常是 `price_basis_date`，Massive 延迟时允许更早的 `used_date`）；两者跨 `$300M` 治理阈值时才采用正的 `info.marketCap` snapshot。Yahoo shares/marketCap 均保留 retrieval snapshot lineage，不宣称严格 PIT；缺包、单票异常、identity mismatch、429/crumb stop 都如实降级，剩余精确残差继续传给 Massive。摘要只记录 logical ticker attempts，不冒充物理 HTTP calls；当前 Pass1 接受的值只对本轮 canonical artifact 有效，不构成 provider-readiness、production 或 ship-gate 证据。
非关键字段自动 fallback 标源；关键字段 fallback 必降级保守；硬否决审计字段必须权威源。运行状态 `clean / usable_with_fallback / restricted / blocked`；高频 fallback 进 §13。

**FMP analyst grades 关键性裁决（2026-07-10）**：周末 capstone 的 `FMP grades` 仅是 §4.2 催化剂里的小分量信号，定位为 **advisory / non-critical**。grades 覆盖不足或不可用时，provider health 仍如实显示 `fmp=down`，整体进入 `usable_with_fallback`，该分量按中性 + `data_quality` 标签处理，但**不阻断 weekly emit**。本裁决只适用于 grades endpoint，不代表其他 FMP 价格、状态或审计字段自动变成非关键。SEC submissions 仍是 audit/veto 的 critical source：覆盖不足继续进入 `restricted / blocked` 并 NO-EMIT。原因是 2026-07-10 freshday 小盘候选实跑确认 grades 198/200 返回 HTTP 402 subscription wall，而 HOOD/MRNA 与 VIX 的 200 仅证明新配额及大盘可用，不能代表真实小盘覆盖。

**yfinance grades 运行边界（2026-07-13）**：weekly runner 的授权、preflight/schema/PIT、输入输出路径与 source-binding 属结构门，失败仍 fail-closed；结构门通过后，非官方低信任 yfinance 的 fetch/解析/组装/summary 任一失败必须在 runner 内原子覆盖为本轮完整目标集的中性 source package + resolved actions + counts-only `advisory_stage_neutralized` summary，再以 degraded-success 返回。capstone 不把它改成 shadow/best-effort，也不从同轮 receipt 移除；Pass2 只消费覆盖后的中性 actions。fallback 自身无法完整写入或验证时仍阻断，禁止下游读取半成品。

### 3.3 数据口径与 Unknown 分层（避免过度保守）
- 关键价格字段（`current_price/OHLCV/ATR/volume/support/resistance`）须同源·同 as-of·同复权·同 session；记 `adjustment_mode / session_scope / timezone`；混源 → `data_degraded`。
- **关键 unknown → 禁新建/加仓**（持仓只给风控/减/清/重评）：结构化审计/状态字段——SEC filing 存在性 / delisting / halt / bankruptcy / major active offering(S-1/S-3/424B/ATM) / critical stock status。
- **非关键 unknown → `restricted_observe`**（不踢出、留观察池、写明缺什么）：SEC 正文语义（going concern/审计师辞任 → `semantic_audit_unavailable`：降信心+观察+manual_review、不硬 block）、网络负面、非核心事件日历缺失。**已读到的高可信做空报告/欺诈指控 → 至少 restricted/manual_review、不 clean 放行。**

### 3.4 美股微结构
缺关键微结构字段标 manual/research-only/blocked、不静默放行：停牌/LULD/陈旧报价、盘前盘后流动性/spread、odd-lot/sub-penny、ADR/外国假期/公司行动/反向拆股/退市破产、PDT。（SSR/Reg SHO/borrow 仅做空用 → v1 留门。）

### 3.5 Calendar / Timezone
记 `as_of / 决策时间戳 / session / timezone`（默认 ET + UTC）；事件证据带 `event_date`(真实发出) + `observed_at`(我们看到)、分开记防偷看未来；半日市/假期/停牌/基准日历错配可见；A/US 跨市场比较须显式市场日历对齐。**§2.1 的 canonical 决策日解析器消费本节的 NYSE/NASDAQ 市场日历**（运行时刻 + 日历 → 即将到来/未开盘交易日 = decision_date；live 窗口两边锚 ET——起点 = 上一 session 已收盘[价格基准结算]、终点 = 目标 session 9:30 开盘前；**盘中[开盘到收盘]= out-of-window fail-closed**；假期/半日市/DST 由日历兜），把灵活运行窗口收敛到单一 decision_date。

### 3.6 手动持仓/成交输入层（镜像 A 股手动表，必备）
- `state/us_short/account_state_csv/`（gitignored 私密；CSV 列名一律 ASCII）：
  - `positions.csv`：`ticker / shares / avg_cost_usd / entry_date / current_stop / notes`；
  - `trades.csv`（= §12 `manual_actual_track` / `execution_log_private` 落地文件）：`decision_date / ticker / suggested_action / executed / fill_price / fill_shares / skip_reason / manual_override`；
  - `account.csv`：`us_market_equity` + `us_short_available_cash` + 可选 `portfolio_total_equity`（仅参考）；短线桶 = `us_market_equity ÷ 3`，系统自己算，不从含糊"总额"瞎猜。
- **转换器 → `us_short_account_state`**（US 自有 schema，不共用 A 股）→ 周报/持仓重评/成绩单消费；公司行动录入器只在显式 `--confirm-account-read` 下读取同一私有 schema 的 `old_ticker` long 持仓，confirmed record 仅留 digest binding，实际处置票据只写 gitignored/external private path。
- **lineage**：每张 CSV 记 `sha256 / row_count / facts_as_of / expected_facts_as_of / decision_as_of`；`expected_facts_as_of` 必须来自同一次 dry-run 的 canonical `price_basis_date`，转换器不联网、不猜日历；`facts_as_of == expected_facts_as_of` 才标 `current`，更早才标 `stale_warning`，晚于该事实钟或事实钟晚于决策日直接拒绝写盘。trades↔positions 一致性对账（advisory WARN，不覆盖 positions）。转换器同时生成 `holding_action_reconciliation`：`remaining_shares / tp1_completed / tp1_completed_at / source_reconciliation_ref`；其中 `tp1_completed` 只能由人工表中已执行的`减仓`成交记录确认，建议本身绝不当作成交。CSV canonical 防 Excel 强转。

### 3.7 数据源分层健康检查（跑前必做）
每周跑前分层探活：FMP 接口 / SEC EDGAR parser / 价格·状态·财报·事件字段够不够，并按 endpoint family 分别判 criticality，不能把同一 provider 的所有接口绑成一个硬门。当前 capstone 中 `FMP grades` 按 §3.2 为 advisory，异常时透明降级为 `usable_with_fallback`；SEC submissions 仍 critical，异常时 `restricted / blocked` 并 NO-EMIT。**未单独批准的源（yfinance / Web / X，§3 边界）：健康检查只记 `disabled_unapproved`——不探活、不调用、不参与 clean 判定**（防"健康检查"被当成调用未授权源的后门）。只查真实 weekly 会用的、已授权的接口、不打印 token、不假 OK。关键源异常 → **不许输出 clean 建仓**，只能 `restricted / observe / data_degraded`。

`runners/us_short_yfinance_grades_feasibility_probe.py` 是唯一例外：它是 20260710 固定样本的独立、低信任、default-dry-run 可行性实验，不属于 provider health 或 weekly runner。只有单独 per-execution 用户授权才可 fetch；即使探针通过，也不能接入 §4.2 打分、emit 门、DataHub、生产或 ship-gate，仍须新的 schema-first 设计与审查。

---

# 选股子系统（§4）

> 决定"选哪些、多强"。只产"强不强 + 排名"，不碰价格/仓位/操作/未来事件（那些在分析子系统）。

## 4. 安全闸 + Top15 打分

### 4.0 Universe 与两遍打分 + 安全闸拆两段
- **Universe** = 全 NYSE/NASDAQ 活跃票（active-only）。
- **Pass 1（全 universe，便宜/批量）**：cheap eligibility gate（交易所/价格/ADV/市值/基础状态，FMP profile 即得）+ 动量·赛道热度 + `catalyst_recall_lane`（批量/市场级 feed：近期财报超预期、评级上修/下调、8-K——把催化强但动量暂弱的票额外拉进候选；feed 拿不到 → 登记 §13、不假装覆盖完整）→ 收窄到候选集（几百只）；不取 per-stock SEC 审计/分析师明细。
- **Pass 2（候选集 + 强制含持仓，贵数据）**：audit safety gate（对候选集+持仓做 SEC/FMP 审计闸，按 §5.1 两层，过不了不进 Top15/建仓）+ 催化剂/预期差 → 完整 core_score → Top15。
- **持仓强制进 Pass 2**（即使没进收窄集），保证完整重评有数据。
- 调用预算/recall 判据 = prior（§13）；实现先验 FMP 基础档速率限内每周跑得完（§18）。**全 universe FMP 调用须先过 SR-PROVIDER-001 授权 + call budget（§3 边界 / §18.0 P0）**——未授权前 Pass 1 只能在已批准的小样本/有限 universe 上跑、不得全市场拉取。

### 4.1 安全闸（硬，"别太保守"不适用于它）
退市/停牌/破产、恶性增发（按 §5.1a recency/materiality 判——挂着的 shelf／陈旧／小额不算，不一刀切）、流动性枯竭、结构化 SEC 审计字段 unknown 等**底线风险 → 直接出局/blocked/restricted、不进排名**。执行分两段（§4.0）：cheap eligibility 在 Pass 1；audit safety gate 在 Pass 2。"别太保守"只对通过闸之后的排名生效。

> **破产筛查只跑一次，且刻意跑在 Pass 2 —— 不是数据获取失败（复核周运行产物前先看这条）。**
> 周运行 `us_short_universe_fetch_summary_*.json` 里的
> `status_source_outcome.per_source.sec_8k_item_103 = "missing"`、`failed_sources = ["sec_8k_item_103"]`、
> `bankruptcy_8k_scan_performed = false`、`bankruptcy_8k_source = "not_supplied"`、
> `provider_call_evidence.sec_bankruptcy_submissions_calls = 0`
> **全是预期状态，不是抓取故障**；真跑复核不应再把它记成数据获取问题。三条依据：
> ① §541 明写周路径 leaves Universe bankruptcy provenance `unscreened`，改为复用 Pass 2 已为增发审计拉取的
> 同一份 SEC company-submissions 记录解析 Item 1.03，**零额外 provider 调用**；
> ② `engine/us_short_status_source.py::FLAG_GATE_POLICY` 把 `bankruptcy` 单列为 `positive_detection_only`
> （只有确凿查到 8-K 才挡），与 `delisted/halted/otc` 的 `conservative_reject`（不知道就挡）刻意分档——
> 否则"破产状态未知"会把整个 universe 清空；
> ③ `run_fetch(scan_bankruptcy_for_eligible=...)` 默认 False、无对应 CLI 开关、无生产调用方，
> `--bankruptcy-screen-path` 注入通道周 capstone 也从不传。全候选池扫描是历史批量能力，不在周路径上。
>
> **已知残留（未决，非缺陷）**：top-K 漏斗是在"未筛查"的破产字段上选出候选的。若某只已提交 Item 1.03 的票
> 靠破产反弹挤进 top-K，它会在 Pass 2 被剔除，但**它占用的名额不会被递补**（第 K+1 名不补进来）。
> 损失是"少一个正常候选"，不是"买到破产股"。要闭合的话最省的补法是 Pass 2 判定 positive 时按序递补一只，
> 而不是把候选池全量扫描前移到 Pass 1（后者每周约 2846 次全新 SEC 调用）。

### 4.2 core_score（仅对过闸标的）
```text
core_score = 40% 动量·相对强度 + 35% 赛道/主题热度 + 25% 催化剂/预期差 − risk_downgrade
```
- **权重 = initial prior**（美股 active-only 回测证明不了 alpha）→ forward + lifecycle 校准（§13 #1）。
- **`scoring_profile`（命名权重档 + 一键回滚）**：`balanced`（40/35/25，**v1 唯一主建议档 / 唯一 `model_paper` 主轨**；系统不自动交易——只有用户真实手动成交 + 完成 reconciliation 后才进 `manual_actual`/`live_normalized` 并计 ship-gate，§12）、`theme_plus`（加重赛道，仅 shadow 比较）、`theme_aggressive`（更激进赛道，仅 shadow 比较）、`theme_off`（赛道权重归 0、重分配给动量+催化，仅 shadow——归因基准 + 回滚锚，§12.2）。回滚/调权重 = 改配置不改码；比较档只 shadow、不交易、不计入 ship-gate（§12.2）。
- **A1 live shadow policy heads（只作 shadow）**：除命名权重档外，`catalyst_off` 只关催化剂权重并按原 40:35 比例重分给动量/赛道；`overextension_selection_off` 只恢复 `chasing_extreme` 的赛道分/赛道席位，不改观测到的过热状态或执行旗标。两者和命名权重档都在同一决策时点 PIT 快照即时分叉并 live 物化；`overextension_execution_off` 只关 warning 的执行旗标，待后续影子分支账本接通后才从该时点起 second-wave-live 跑，账本前周数不算该头的 forward 证据。所有头不改 `balanced` 主轨、不计 ship-gate。
- **标准化（v1 锁定默认）**：三块都映射 0–100——动量 = 全池分位、赛道 = GICS/主题池内分位（确认门内再按 `heat × persistence × fit` 连续合成，§4.3；行业热与跨行业主题热正交去重，§4.3）、催化剂 = 规则映射分（非分位）；z-score 挂 lifecycle。
- **缺分量**：某块算不出（小票无分析师、`FMP grades` 覆盖不足/付费墙 → 催化剂中的 analyst-grades 分量缺）→ 该分量按中性 + `data_quality` 降级 + 标签；不偷偷重新归一放大权重，也不因这个 advisory 分量单独阻断 emit（§3.2）。
- **三块细分**：动量（1月/3月趋势、5-10日动量、相对 SPY/QQQ、相对 sector、放量）；赛道（§4.3）；催化剂（财报实际vs预期、分析师修正、8-K/订单/产品/监管/LLM 语义——**仅已实现/当前**，未来事件不进选股分、归 §8.1）。
- **`risk_downgrade`** = 只含"让票作为'选股'不那么吸引人"的软旗标：`earnings_reaction_history_score`（财报坏反应习惯，跨季、慢变） + `current_good_data_bad_reaction_event`（本期事件，瞬时、soft、带 SPY/QQQ 相对豁免，§5.2） + 分析师集体下调；不含数据质量/主题拥挤/临近财报（各归 §4.4/§4.5/§8）。
- **财报质量趋势（可选 advisory、非门，默认不启用）**：毛利率压缩 / 应收增速>营收 / 存货堆积等财报趋势恶化（借 A 股 `financial_trends` type-agnostic 框架，可得自 FMP 财务）——**若启用，最多作 `risk_downgrade` 软标签，绝不设门/硬否决**。短线动量系统对深度财报趋势优先级低、易增保守，**v1 默认不开**，挂 §13 候选（#39）。

### 4.3 赛道/主题热度（进攻所在）
- **硬分主力 = 官方行业组（GICS）**：行业强度、赛道内上涨广度、创新高比例、龙头强度、相对 SPY/QQQ 强度（全用 FMP 价格 + 行业分类，不依赖付费行业 ETF）。计算基准来自 scoring 前的基础 universe / GICS 行业同组 / 已转正主题表，**不能用候选池/Top15/人工 watchlist 自证**。
- **`provisional_theme_lane`（新兴跨行业赛道，进攻通道）**：web/X/LLM 负责**发现**新主题（AI 存储/核电/量子/机器人…），但不单独拍板；进 `theme_momentum` 竞争席位须**市场确认（机器可判公式）**——字段 `theme_source_count / theme_member_count / theme_breadth_up_frac / theme_volume_confirm_frac / theme_leader_rs / theme_persistence_weeks / theme_fit_score`，规则 = **至少满足 3 项 + 个股自身也强**（阈值/项数 = prior §13 #32）。
  - **防偷看未来/防循环**：成员名单按 `observed_at` 冻结；`breadth/volume/RS` 一律用独立价格数据算（不拿发现源自证）；薄来源（`theme_source_count` 低）`theme_fit_score` 降权。
  - **个股闸**：拿到席位/加分的票须**自身也强 + 且在已通过市场确认门（≥3 项，见上 `provisional_theme_lane`）的主题里**（`provisional_active` 起即算、**不特指 `confirmed_active` 生命周期态**——防蹭热点的弱票、又不把刚确认的新主题挡在席位外，保住 provisional 进攻通道）。
- **热度去重/正交化（防双重计数 + 防伪分散）**：35% 赛道块里两类热度会对同一票重复加分——`industry_heat`（GICS 官方行业强度，即上方"硬分主力"）与 `theme_heat`（跨行业 provisional 主题强度）。**打分时把二者正交化、重叠只计一次**，**方向用固定规则（可执行、不靠主观）**：存在已确认跨行业主题时 → `theme_heat` 为基、`industry_heat` 只贡献正交残差；纯单一 GICS 行业行情（无跨界主题）→ `industry_heat` 为基（镜像 A 股 overlay `orthogonalize_industry_on_theme`；残差合成系数 = prior §13 #38）。**`macro_cluster` 不硬扣分**，但 AI 存储/半导体/AI 基建/核电同属 `ai_complex` 时进**重复热度检查**——不让同一宏观大注被当成 N 个独立赛道各自加满分（结果落 §11.2 横幅 + §8 集群暴露，伪分散在席位层可见）。
- **确认门内连续打分（别把强新主题压平）**：market confirmation（上方 ≥3 项门）只决定"够不够格拿赛道分"；**门内的赛道得分用连续式 `theme_score = heat × persistence_mult(0–1) × fit_mult`**（镜像 A 股 overlay `theme_eff`），不再把 `theme_persistence_weeks`/`theme_fit_score` 当布尔项后给平铺分——让刚过门、热度爆表的 2–3 周新主题拿到与热度成比例的分。`persistence_mult` = 主题近窗口处于高强度的占比、`fit_mult` 由 `theme_fit_score` 映射；**门后 `persistence_mult` 设地板（≥ floor）**——确认门一过即给有意义下限，防刚过门的爆发主题被低乘子重新压扁；窗口/映射/floor 并入 §13 #32（与门阈值同条）。
- **赛道生命周期（进 / 确认 / 转正 / 降温 / 退场——三段都要，不能只进不出）**：`theme_lifecycle_state ∈ {provisional_active, confirmed_active, cooling, decayed, retired}`。
  - **升**：`provisional_active` → `confirmed_active`；持续达标（`theme_persistence_weeks` 够 + §13.2 门槛）→ 转正为 GICS 同级硬主题（`theme_source` 变 `gics_established`）。
  - **降档触发**：广度走坏（`theme_breadth_up_frac` 跌破）/ 龙头破位（`theme_leader_rs` 转弱）/ 持续性重置 → `cooling` → `decayed` → `retired`（阈值 = prior §13 #30）。
  - **状态转移动作表（每态如何影响输出，机器执行）**：
    - `provisional_active / confirmed_active` = 正常给席位、可试探；
    - `cooling` = 停该主题新 `theme_probe` + theme 席位减半（向下取整）+ 该主题持仓降 `action_confidence`；
    - `decayed` = 不再给 `theme_momentum` 席位 + 该主题新建仓一律转观察；
    - `retired` = 从主题表移除、只留历史成绩单。
    - cooling/decayed/retired 的持仓都加 `theme_decay` 标 + 触发 §9 重评，**但不机械清仓**——清不清仍看个股价格/止损/hard veto。
  - **状态防抖（同 §7 regime，防席位忽给忽收）**：降档快（首次走坏即 `cooling`）、升档慢（连续确认才回升）；`retired` 后再进须走完整 `provisional` 重新确认、不直接弹回（防抖参数 = prior §13 #30）。
- **来源诚实**：每主题带 `theme_source`（`industry_heat_v1` / `gics_established` / `provisional_discovered`）+ `theme_lifecycle_state`；当前行业热度来源必须诚实写 `industry_heat_v1`，不得冒充 GICS；provisional 席位行带 `provisional_theme` 标（advisory——新发现、未经周期验证、人工给信心打折），喂 §13 累加器。
- **Top15 接线事实（2026-07-12）**：Top15 只消费与当次 `decision_date` 精确绑定、逐 ticker 覆盖的 `theme_selection_contract`（主题身份、来源、生命周期、龙头 RS、自动/人工席位身份、市场确认、个股主题闸与追高态）；该本地来源文件与 source-packet digest / `selection_inputs` provenance 绑定，缺失、漂移或与 Pass2-clean 集不一致即 fail-closed。full-candidate one-click 必须在本轮 resolved Pass2 sources 得出后 materialize 此 contract、再建本地 source packet，不能要求操作员预置或复用旧 contract。当前默认模式是 `industry_heat_v1_cross_industry_disabled`：只如实消费已提供的 industry-heat v1 身份，**不把它写成 GICS 已确认主题，也不宣称跨行业发现已启用**；刀2 的 `theme_soft_boost_enabled` 仍默认 OFF，显式开启还必须通过 provisional artifact 的 decision-date/digest receipt 消费门。`provisional_cross_industry_enabled` 只在另有同样来源绑定、市场确认和个股闸均通过的 contract 时可用；本接线不启用 discovery/provider。
- **结果联动接线事实（2026-07-19）**：Top15 的同一份 `theme_selection_contract` 原样延续到分析行和 machine row；逐票 evidence 同时绑定 contract SHA256、`selection_inputs` run-provenance SHA256、decision date 与 ticker。持仓主题只来自私有 `holding_theme_reconciliation`（须恰覆盖账户持仓）；缺失时保护性退出照常输出，但新增仓位与集中度容量 fail-closed，不得猜 `unclassified`。
- **纯软信号 / US-short 跨行业软发现（2026-07-25 刀2，2026-07-27 K4b 接线）**：底层 score/data-context/forward-policy API 继续显式精确 bool、缺省 OFF；正式一键路径显式 ON，且只有同决策日 `valid_nonempty` 的 4a stage receipt 与 validation artifact 在 path/digest/identity 全绑定时才消费，其他上游状态均按类型归零并继续主链。K4b 先生成严格的 OFF 基线，再运行完整可选 ON/归因/证据生命周期；任一步失败都回到同一 OFF 结果并记录 typed zero，不得打断 strict Pass2。独立 immutable consumption receipt 记录上游 path+sha、实际逐票 boost、core/Top15 影响，不回写 4a 收据也不提前声称操作意见影响；三件证据以 capstone 注入的 gitignored state root 为唯一根，测试/回放不得回落到操作员 state。同次运行以完全相同输入本地重算 `soft_boost_off` shadow（不复用 `theme_off`、不追加 provider 调用），绑定冻结 evidence epoch 与 pairwise statistical plan。本刀 ledger 只是一决策周 capture，固定 `continue_accumulation`，不得执行正式 adjudication、生成 pending 用户决定或自动切换路由；跨周聚合与推荐留给 4c。逐票 `web+x` = `both` 固定 +5、单边 web 或 x = `single` 固定 +2、仅 LLM/无独立源 = 0。同一 ticker 跨多个主题只取最高档一次，合计硬封顶 5；加分只进入 `core_score`/core Top15 竞争，不进入 `theme_momentum` 席、不改席位/试探仓/生命周期、不放松 hard veto/数据质量/价格/RR/成本/组合闸。**软加分是主题派生信号，凡是刻意移除主题贡献的地方一律不得幸存（2026-07-25 定）**：①`chasing_extreme`（`strips_theme_score=true`）的票在 selection 侧被剥掉赛道贡献后，软加分同步压成 0（记 `boost_applied=false`，保留 `validated_theme_ids`/`source_ref_ids`/`observed_at` 供审计），绝不让未证实主题退还任何一部分抛物线惩罚；②A1 `theme_off` 消融头同样不带该加分，否则 §12.2 归因量的是加分而非赛道块；③`overextension_selection_off` 头按定义不剥离，故对未被剥离的票照常带加分；但被剥离的票其点数已在 seam 侧压成 0、该头无法还原，因此对这类票它会低估过热惩罚 ≤5 分——**已记录的影子归因限制**（仅 §12.2 对比，不影响主轨选股）。分析消费面仅重加带 validation identity binding 的 fail-closed boost 以保持既有 selection/analysis 一致性；A1 forward-policy shadow 同样校验并重算该可选字段；行业代码先 canonicalize（NFKC+trim+upper，须为 SEC SIC 两位主组）再做跨行业门，且消费端用成员实际 `industry_code` 重推 `industry_codes` 与 ≥2 门，不改既有 veto/价格分支；后续操作意见只能沿正常 Top15→完整分析链联动，不能由软发现直接生成动作。
- **过热分档（防追喷出的票，但不误杀强趋势）**：两档**互斥**，同一风险只罚一次（§4.2 单舞台），字段 `overextension_state ∈ {none, warning, chasing_extreme}` 入 action_table。
- `overextension_warning`（温和：`close ≥ MA10 + k1×ATR` 且**趋势完好梯** `close > MA5 > MA10 > MA20`、未喷出；任一 MA 非有限则不判 warning）：**保留全额赛道分、不踢出选股**；只在执行侧罚——强制 `pullback_mode` 入场（不追突破）+ 压到试探/最小仓 + 抬 RR 门（复用 §6/§8 既有杠杆，不新增惩罚 stage）。
- `chasing_extreme`（抛物线，`close ≥ MA10 + k2×ATR` **且**多条件同时（AND）成立才触发——绝不因单条件如"仅涨幅大"误判：连续垂直 + 当日涨幅 ≥ m×ATR + 量能高潮 + 远离全部均线 + 回撤结构差，需 ≥K 项共现）：**才**从 core_score 剥掉当前 profile 的赛道热度贡献（不重分配给其它块，惩罚后分数不得高于原分）并清空 theme 席位分；`theme_off` 的重分配只用于 §12.2 shadow 归因。仅 ≥K 但未过 k2 的票按 warning/none 继续判定，不得剥赛道分。
- 分档用 MA5/MA10/MA20 + ATR + 量比判定；`k1=1.75`、`k2=2.50`、m/K/量能/均线距离均为 §13.1 #36 **forward prior**（非冻结）。强趋势票"高了还能更高"默认落 `warning`、不被误杀，仅真喷出才降权。

### 4.4 三个移出打分、各有去处的因子
| 因子 | 去处 |
|---|---|
| 数据质量 | 能否进排名 / `action_confidence` / clean·usable·restricted·blocked / 降仓 / 只观察 |
| 技术可操作性 | 分析定价阶段：能否构造入场·止损·止盈 / 能否建仓 / `final_action` / `price_engine_used` / 降观察 |
| 流动性/执行 | 安全闸门槛 + `liquidity_cap` + 执行约束标签（spread 大 → 限价/拆单） |

### 4.5 Top15 席位规则（动态 core/theme 比例；prior，§13）
- **动态席位（由 `theme_opportunity_state` 驱动，总数恒 15）**：常 `10 + 5`；强赛道周 `8 + 7`；无强赛道周 `12 + 3`——真遇 AI 存储/半导体/核电这类主线不被固定席位压住、平庸周也不强凑赛道。比例触发 = prior（§13 #29）。**这是选股层放开、不是下注放开**——同主题上限 30% + 每周同主题 ≤2（§8）是后闸，保证"7 个赛道席位"不会变成押注集中。
- **theme 席位构成**：≥2 来自市场自动发现/非 watchlist 高动量（含 `provisional_theme_lane`）；≤2 主要人工 watchlist 且须市场确认；同主题 >3 → 拥挤降仓/降级（不 hard veto）；与 core 重叠只留一行标 `overlap`、席位顺延；不足则从 core_rank 续位补 `core_backfill`。
- **强赛道周额外完整分析名额**：`theme_opportunity_state` 强/极强周，把固定"仅 Top5 完整分析"扩成"Top5 + 1–2 只 Top6–15 主题龙头"（按 `theme_leader_rs` 取最强、非 `chasing_extreme`）。**默认取 `confirmed_active` 龙头；亦可纳入极少量 `provisional_active` 龙头，但门更严**——自身 RS 强 + 量能强 + `theme_leader_rs` 高 + `theme_fit_score` 高，且其任何建仓**只给最小/试探仓**（不自动大仓）。**只是完整分析、不是自动建仓**——仍过价格引擎/RR/§8 仓位/每周建仓上限/风控。理由：否则 8+7 扩席后排 6 之后的赛道票无价位/RR，§8 `theme_probe` 对非 Top5 票会**空转**；刚冒头的强新主题也不必等确认数周才被分析；名额数/纳入门 = prior（§13 #37）。

### 4.6 选股排名 ≠ 建仓名单（故意的）
`selection_rank` 管"多强"；通过分析阶段（数据质量/可操作性/RR/审计）后才定"真能建仓的"——某周 Top5 真能下手的可能不到 5 只。与 `action_rank`（§9）分开。

---

# 分析子系统（§5–§11）

## 5. Hard Veto 分层
| 层级 | 影响 |
|---|---|
| `entry_hard_veto` | 禁新建/加仓 |
| `position_hard_veto` | 持仓强制重评/减/清（不是沉默） |
| `strong_downgrade` | 降优先级/仓位/可信度 |
| `soft_risk_tag` | 提示/小幅扣分 |
| `shadow_record` | 只记录、不影响输出 |

- **5.1a 文件类型/状态/价格类（可靠自动 → 直接硬否决）**：退市/停牌/破产/OTC；SEC 增发/转售 S-1/S-3/424B/ATM（带 `filing_recency / offering_status / materiality`——挂着的 shelf ≠ 马上增发，陈旧/未激活/小额不当硬否决；近期+已激活+重大才否决）；严重流动性/spread；关键数据缺失。
- **5.1b 正文语义/新闻类（先 advisory，证据可靠才升）**：going concern/审计师辞任/重大会计、正式做空报告/欺诈指控。① 没读到/parser 未实现 = `semantic_audit_unavailable` → 降信心+观察+manual_review、不硬 block；② 已读到高可信 → 至少 restricted/manual_review、不 clean。
- **5.2 候选否决（进 §13，攒触发+人工复核才升）**：财报好数据坏反应、期权/空头异常、极端 gap 禁追、insider 减持强度、分析师集体下调、borrow fee/DTC、网络负面。（依赖拿不到数据的项 = 双重卡：先有数据源、再攒证据。）
  - **好数据坏反应 v1 先 soft、带市场相对豁免**：该项数据（财报实际vs预期 + 次日收益）在"可信"档（FMP，§3.1）即得 → v1 即实现为 **soft `risk_downgrade`**（§4.2 扣分 + risk_tag，**不硬杀**），并带 **SPY/QQQ 相对豁免**（次日个股收益 > 大盘 − X% → 判市场系统性、不降级）。**拆两字段**：`earnings_reaction_history_score`（多季习惯、慢变）vs `current_good_data_bad_reaction_event`（本期事件、瞬时、带相对豁免）——本期事件不写进习惯分、不因一次大盘普跌日反应把票长期贴成"坏反应股"。**升成 hard veto 仍走本条候选**（攒 ≥N 触发 + 人工复核才升，防指引/估值/风格混杂误杀）；soft/hard 阈值 = prior §13 #7。
- **5.3 不应单独硬否决**：单独高 SI / 单独网络热度 / 单个技术指标 / 目标价低于现价 / 主题拥挤 / 高波动。

## 6. 价格引擎 + 交易质量（v1 只 2 个真引擎）
- **2 个真引擎**：`support_atr_engine`（新建/加仓默认）、`holding_exit_engine`（持仓止损/止盈/跟踪）。非引擎但必须：`hard_veto` gate、`data_degraded_policy`。只登记不实现（挂 §13 #6）：`ema_trailing_engine`、`earnings_gap_engine`。
- **`support_atr_engine` 内拆两子模式**（仍 2 引擎、不加第三个；强赛道多突破型），字段 `price_sub_mode ∈ {pullback, breakout}`：
  - `pullback_mode`（回踩）：`valid_entry_low = max(effective_support, close − PULLBACK_BAND_ATR×ATR)`、`valid_entry_high = close`；止损 = `valid_entry_low − ATR_MULT[regime]×ATR`。TP1 必须是严格高于入场上沿的有效压力，缺失/空间不足即观察，不由 RR 门槛反推 TP1。
  - `breakout_mode`（突破）：`trigger_raw = effective_resistance`，`breakout_entry_price = max(close, trigger_raw)`，追价上限 `valid_entry_high = trigger_raw + BREAKOUT_CHASE_ATR×ATR`（超过即观察）；**突破失效线 = 止损** = `trigger_raw − BREAKOUT_FAIL_ATR×ATR`（不用远端结构支撑）+ TP1 = `trigger_raw + BREAKOUT_TP_ATR×ATR`。参数 = prior（§13 #20/#33），缺有效压力不出 breakout 几何。
  - 两模式都仍过 `min_rr_gate` + tick 取整 + 取整后 RR 复校；RR 一律按最不利可接受成交价 `valid_entry_high` 计算。
- **优先级链**：① hard_veto（new→否决/不建；holding→强制减/清/重评）② data_degraded（holding→只风控/不伪造价；new→观察/restricted）③ holding→`holding_exit_engine` ④ new→`support_atr_engine`。**加仓**：持仓+触发加仓 → `support_atr_engine` 算加仓入场、`holding_exit_engine` 管原仓，两者并存。
- **有效支撑/压力去插针**（美股无涨跌停、长影线更夸张）：`effective_support / effective_resistance / structure_quality / structure_adjustment_reason`；单日极值比**最近的非并列值**远 >1×ATR（prior §13 #24）判插针、取该非并列值（US-short 刻意比 A 股 phase5「取单一次值」更稳健：美股长影更夸张、可多根并列同极值，单一次值会漏判并列长影；§13 #24 倍数不变）；止损/入场/止盈/RR 全用**有效**值算；结构差 → 降观察/降仓。
- **`min_rr_gate`**：`risk = valid_entry_high − stop`、`risk_reward_ratio =（盈一−valid_entry_high）/risk`；RR < gate → 不建仓、转观察（prior，突破型可更高）。`t2 = max(tp1 + ATR_MULT[regime]×ATR, valid_entry_high + TP2_RISK_MULT×risk)`；pullback trace 标结构 TP，breakout trace 标 `trigger_raw` 锚定的 ATR TP，不从 RR 门槛反推 TP1。
- **tick 取整 + 取整后 RR 复校**：算理论价 → 按方向取整可执行价（美股 $0.01，留 sub-penny/低价例外）→ 用取整后真实价**重算 RR**，破了降观察；字段 `execution_tick / rounded_price_used / post_round_rr_status`。
- 缺可靠 ATR/支撑压力/财报日期/持仓成本 → 降级观察或只风控。

### 6.1 持仓价位映射与第一层行动闭环
- `holding_exit_engine` 给基础价位：`stop_clear_price`（止损清仓价）、`take_profit_reduce_price`（盈一减仓价 / TP1）、`take_profit_exit_price`（盈二/跟踪止盈价 / TP2）、`event_clear_reference_price`（事件硬风险清仓参考价，标"人工执行、非技术价"）。
- **第一层已启用、全 advisory、不自动下单**：正常且可信输入下优先级为 `清仓-事件` > `清仓-止损` > `清仓-止盈` > `减仓` > `持有`。TP1 到达上一轮已发布的私有目标价且未确认完成时，建议减 **剩余股数的固定 10%**；TP2 到达时建议清仓全部已对账的剩余股数。正常情况下每个减/清动作必须同时有 `final_action / recommended_action_shares / 对应价格`；**保命例外**：`清仓-事件`或`清仓-止损`已触发但本次股数对账不可信时，仍必须输出动作和对应价格，`recommended_action_shares` 留空、`decision_trace` 标记需人工核对股数，绝不猜测数量、更不能静默改成`观察`。`model_position_size_shares`只代表建仓目标仓位，不能充当一次性卖出数量。
- 为避免“本周用本周收盘价重算目标而永远触不到目标”，私有 `runs_private/holding_action_state.json` 保存上一轮 TP1/TP2、价格日期/时段/复权口径、`tp1_completed / tp1_completed_at / remaining_shares / source_reconciliation_ref`。首次仅播种价位；建议减仓不会标记完成，只有人工 `trades.csv` 已执行`减仓`才会确认 TP1。
- TP1 向下取整后不足 1 股，或成本地板不可验证/不通过时，不出 0 股订单，保持并记 `tp1_deferred_below_min` 或成本递延原因。加仓、移保本、主动 ratchet 和多日主动管理仍不启用。

## 7. 市场环境（两轴：风控刹车 vs 赛道机会，别只 worst_of）
- **三类输入**：① VIX 风险温度（**目标使用 FMP `^VIX`；未过 provider 授权门（§3 边界）前禁用或标 `unapproved`**，不当已验；**VIX 未授权 / unavailable → 该轴按 unknown，`market_risk_regime` 退到 `SPY/QQQ + breadth` 并按 unknown 降级规则保守处理**）② 大盘趋势 `SPY + QQQ`（必须含 QQQ——池偏 AI/半导体/成长）③ 板块/市场广度（走基础 universe 成分股；行业 ETF 据公开档为付费、不依赖）。
- **两轴拆分**（关键反保守）：
  - `market_risk_regime` = `worst_of(VIX, SPY/QQQ 趋势, breadth)` → **决定仓位上限**（进攻 1.0 / 震荡 0.8 / 防御 0.5 / 极度防御 0）。
  - `theme_opportunity_state` = 赛道机会强度 → **决定赛道机会优先级**。
  - 弱市但有极强赛道时，允许"低仓位试探建仓"，不直接全转观察——**仓位落点见 §8「强赛道试探名额」**（`theme_probe`：防御 ≤1 / 进攻+极强 ≤2、最小仓、超出常规周建仓上限；极度防御 / hard veto / 熔断冷静期一律不放行）。
- **防抖**（快防守慢进攻）：降档立即；升档要确认（连续 2 次周跑更好或站回阈值上方缓冲）。
- **跨周状态正式持久化（问题16-B）**：市场环境、holding action、portfolio guard、symbol cooldown 四项状态与 machine record 一起写入成功周跑的 `runs_private/<decision_date>/` 日期事务；下一周只从该目录的直接子目录选择严格早于当前决策日的最新真实日期。四个消费者共享同一个已选 prior，不读取根目录 legacy、不向更老日期回退；选定状态缺失、损坏或 `as_of` 不匹配时按不可用/保守失败关闭。市场状态记录固定为 `us_short_market_regime_state` `1.0.0` 的五键记录，`as_of` 等于其日期目录。
- **unknown 按防御**：关键输入缺 → 不默认进攻；缺一项降级、缺关键项至少防御、严重 restricted。
- **作用域**：影响仓位/新建仓许可/(可选)`action_confidence`；不影响 hard veto、不替代个股分析。阈值全 prior（§13 #3）。

## 8. 仓位与风险预算
- **按风险定仓位**：`能亏的钱 = 短线桶 × 单笔最大风险%`；`每股风险 = 入场−止损`；`底仓股数 = ⌊能亏的钱 ÷ 每股风险⌋`。
- **v1 起点准数**（prior，§13 #4）：单笔风险 0.75%(0.5-1)、单票上限 10%(8-12)、总仓上限 60%(50-70)、同主题上限 30%(25-35)。
- **每周新增建仓上限**（只限 `final_action=建仓`）：进攻 3 / 震荡 2 / 防御 1（高置信）/ 极度防御 0；同主题每周 ≤2；超限其余转观察。
- **强赛道试探名额**（`theme_opportunity_state` 的仓位落点；反保守的实际抓手）：
  - 市场确认的强赛道（§4.3/§7）额外允许 `theme_probe` 建仓名额（超出该 regime 常规周建仓上限）——**默认 防御 ≤1 / 进攻+极强赛道 ≤2 / 极度防御 = 0**（数/封顶 = prior §13 #27）。
  - 该名额仓位**强制 = 最小可执行仓 + 仅高置信（coverage 非 restricted）**，绕过常规风险预算放大，但仍受 单票/总仓/同主题/现金/`hard_veto`/`symbol_cooldown`/`portfolio_guard` 全部约束；极度防御 / cooldown / veto = 0、不放行。该行 `risk_tags` 带 `theme_probe_min_size`、`model_position_size_*` 自然显示其小仓。
  - **防御档入场方式**：`market_risk_regime=防御` 时，新建仓（含 `theme_probe`）**默认只走 `pullback_mode`**、关突破追高（避免弱势盘追飞）。**唯一例外**：`theme_opportunity_state=extreme` 且**当周不跳空、入场在 `valid_entry_band` 内** → 允许 **1 个最小仓 `breakout_mode` `theme_probe`**（仍占"防御 ≤1"名额、仍受全部 §8 约束；极度防御/veto/cooldown = 0）。保住 §7 两轴"弱市强赛道仍能试探"的本意，又不在防御档普遍开放突破；参数沿用 §13 #27。
  - **最小仓成本地板**：口径 = 若 `预计到盈一的净利润空间 ≤（佣金 + 滑点 + 点差）往返成本 × 安全倍数`，则不试探、转观察（`observe_reason_type = cost_inefficient_min_size`）；安全倍数 = prior（§13 #27）。实现时必须真拦单、不只打标签。
  - 意义：这是"两轴拆分"真正区别于旧 `worst_of` 的地方——否则防御档仍只 1 建仓、拆分无意义。
- **削减叠法**：① 底仓股数 ② × 环境乘数（`market_risk_regime`）③ × 风险折扣（数据降级/主题拥挤/集群超集中/财报前——**取最狠的一个、不连乘**）④ 取最小(单票上限/剩余总仓/剩余主题容量/流动性上限/可用现金/全局现金分配额) ⑤ < 最小可执行 → 降观察。
- **宏观集群集中度（伪分散后闸；v1 先轻量）**：同主题上限拦不住"不同主题、同一宏观大注"（AI 存储 / 半导体 / AI 基建 / 数据中心核电 同属 `ai_complex`）。
  - 每票打粗标 `macro_cluster`（如 `ai_complex / rates_sensitive / commodity / defensive`…）+ 算 `macro_cluster_exposure_frac`（该集群占总仓比）+ `macro_cluster_warning_level`（`none / elevated / high`，按 frac 分档 = prior §13 #31）。
  - **v1 不设硬上限（阈值无证据），先做软影响 + 横幅**：`warning_level=high` → 进 `risk_tags`、压 `action_confidence`、缩 `model_position_size`（作为削减叠法③风险折扣的一项、并入"取最狠的一个"、不额外连乘），实际压减额写进 `macro_cluster_size_adjustment`（表里看得见压了多少）；报告横幅预警"本周 N 个建仓候选同属 X 集群、合计 Y% 仓位，存在伪分散风险"。硬集群上限挂 §13 #31，攒几个月再校准。
  - **运行时接线（2026-07-19）**：先从原始已决策行做一次 provisional sizing，以当前持仓市值 + 拟建仓市值除以 US-short bucket 计算压减前 cluster fraction；`high` 只向统一 `result_effects` 追加一个命名折扣候选和 confidence cap，再从原行终算一次。最终仍取最狠单一折扣、不连乘；横幅只从 machine rows 聚合，禁止 caller 注入自由文本。
- **组合级熔断（账户层风控，借概念不借 A 股原文）**：`portfolio_guard_status ∈ {normal, caution, cooldown, recovery}`；**主触发 = `model_paper_track`（§12）当其可评估时**：连续止损 / 纸面账户回撤超阈值；手动真实账户回撤(§3.6)+账户态缺失 = 次要/advisory。**若 paper track 因数据门（§12.1 复权/公司行动未确认）= `not_evaluable/data_degraded`，则 `portfolio_guard_status` 不得 clean、默认 `restricted/caution` 或只允许持仓风控**（fail-safe：没数据不当"安全"）。cooldown→禁新建/加仓、只持仓风控；caution→降仓+减每周新增数；recovery→只少量高置信新仓。只影响建议、不自动交易；阈值 prior（§13 #22）。
- **单票再入场冷静期**：`symbol_cooldown_status / cooldown_until / reentry_allowed_reason`；**突破单未成交 = 不进冷静期（没进场不罚）**；**成交后触发止损 / 突破失败 → 进冷静期**，期内动作降观察；除非新催化剂 + 新结构 + 期满才恢复完整买入（防 revenge-buy）。参数 = prior（§13 #23）。
- **全局现金分配**：可建仓票按 排名/置信/RR/流动性 排序，用最保守 `valid_entry_high` 算占用现金依次分配，轮到现金不够 → 降观察；字段 `cash_allocation_rank / cash_required_at_entry_high / allocated_model_shares / remaining_cash_after / cash_allocation_status`（排序权重 = prior §13 #25）。
- **ship-gate 成熟度 = 提醒、不是算式帽**：按正常口径出 `model_position_size_amount / model_position_size_shares` + `live_permission_status`（`paper_or_minimal_only / not_full_size_eligible / full_size_eligible`）+ `live_size_warning`；未毕业不得当真金满仓许可，真金投多少手动定。
- **hard veto = 0 仓**。

### 8.1 未来已知事件日历（forward events）
- **范围**：有已知日期的未来事件——财报日、指数/基金纳入生效日、FDA/PDUFA、解禁日、除息日；窗口默认未来 3 周（prior §13 #15）。"大订单"等不可预知的不在此列。
- **数据档**：财报日 FMP 可靠；指数纳入/FDA/解禁 难/部分 → 有就用、没有标未知。
- **`event_sensitive_type`（缺数据≠普通 unknown）**：生医缺 FDA/PDUFA → 至少 restricted/观察；近期 IPO/SPAC 缺解禁 → restricted/降仓；普通大票缺指数事件 → 只标签。类型用 GICS + IPO 日期判。
- **不进选股分**：前瞻事件只在分析阶段影响仓位/风控/显示。
- **方向感知影响仓位/风险（焊进 §10）**：临近财报→降仓/可转观察；临近解禁→减/谨慎；指数纳入→有界正向（提前 price in 则打折）；FDA/PDUFA→降仓/谨慎；除息日→价格口径提示（adjusted 已处理、raw 口径会跳；普通股只标签，高/特殊股息才影响价位/仓位）。
- **显示** `upcoming_events`（票 + 日期 + 来源）。PIT 同 §3.5。效应/窗口 = prior（§13 #15）。

## 9. 操作排名 action_rank
- **`final_action` 词表（与 §6.1 价位一一对应，避免状态/价位脱钩）**：`建仓` / `加仓`（→ entry 价）、`减仓`（部分止盈 → `take_profit_reduce_price`）、`清仓-止损`（→ `stop_clear_price`）、`清仓-止盈`（→ `take_profit_exit_price`）、`清仓-事件`（→ `event_clear_reference_price`）、`持有`、`观察`（带 `observe_reason_type`）、`否决/避开`。
- 第一层中持仓减/清正常均须带已对账的 `recommended_action_shares`；仅已触发的`清仓-事件`/`清仓-止损`可在对账不可信时保留动作+价格并留空数量，且必须标记人工核对。`加仓`仍是冻结词表而非可产生动作。
- `selection_rank`（多强）与 `action_rank`（这周先干哪个）分开。
- **5 组骨架（保命优先）**：① 持仓强制减/清（触发止损或 position veto）→ ② 可建仓新机会（过闸+可操作+触发/临近，按选股排名）→ ③ 加仓 → ④ 持有/观察 → ⑤ 否决/放弃。理由：不处理已触发止损损失会继续；错过新机会只是少赚。
- **组内细排输入**（都有落点、不悬空）：是否持仓=主分组轴；是否触发进出=落哪组；选股名次=组②排序；可操作性=组②门槛+排序；数据质量=降 confidence/太差→blocked；风险=硬→①/⑤、软→组②往后+降仓；集中度=同主题挤→降级；未来事件(§8.1)=临近财报/解禁→降级或转观察、持仓侧并入①/③。用分组不用加权（防把必须止损的持仓排到新买点后）。
- **`observe_reason_type`（观察必拆原因，别混"没账户"和"系统不看好"）**：`signal_not_ready / price_not_executable / cash_or_account_missing / risk_cooldown / data_restricted / event_window / cost_inefficient_min_size / capacity_or_budget_deferred`（`cost_inefficient_min_size` = 试探仓小到佣金/滑点/点差吃掉期望、不下无效小单；`capacity_or_budget_deferred` = 过闸可执行但被每周新增建仓上限/同主题上限/极度防御仓位上限挤出本周名额、转观察、非系统不看好）。

## 10. 不悬空 + 证据反查 + 字段 registry（机器强制）
- **正向 no-dangling**：每个算出来的因子/字段/结论申报 ① 大白话名 ② `landing_surface`（落最终表哪格/标签）③ 影响强度（硬否决/降仓/调信心/仅标签）。validator：有计算无落点 → 报告不合格、生成不出来。"落成带说明标签"只对 advisory/shadow 软提示算合法落点。
  - **核心字段（hard veto / risk downgrade / data quality / selection / price / sizing / trigger / `market_risk_regime` / `theme_opportunity_state` / `theme_lifecycle_state`）必须影响 `final_action / action_rank / position_size / price / action_confidence / risk_tags` 至少一个**，否则转 shadow_record 或删。（`market_risk_regime` 经环境乘数+周建仓上限落地、`theme_opportunity_state` 经 §8 强赛道试探名额落地、`theme_lifecycle_state` 经席位/`theme_probe`/降仓/§9 重评落地。）
- **反向证据反查（防造假）**：报告每个 claim（临近财报/S-3/FDA/做空报告/赛道热度/新闻催化）机器层**必须反查到 provider row / SEC filing / source_id**，查不到 → 不许输出成操作影响。
- **完整字段 registry**：每字段登记 `field_id / owner_module / data_source / pit_basis / privacy_class / current_landing_surface / terminal_surface_target / operation_impact / evidence_ref_kind / lifecycle_item_id`。答不出"最后影响哪列/动作/价/仓/标签"→ 不进主系统。
- **结果 effect 单源（第二刀）**：事件窗口、事件数据缺口、`portfolio_guard`、`symbol_cooldown` 不得各自留在中间对象；它们先合并为每票 `result_effects`（动作覆盖、取最严单一仓位折扣、信心上限、触发/失效条件、风险标签、事件及证据），再投影到 `final_action / action_confidence / risk_tags / trigger_conditions / invalid_conditions / upcoming_events / portfolio_guard_status / symbol_cooldown_status / cooldown_until / reentry_allowed_reason`。§10 机器记录对每个已接入 producer 发 registry record，并反向校验这些最终字段和证据；缺任一项即不生成正式结果。
- **报告生成前必检**：每字段有落点 + 每 claim 可反查；hard veto 覆盖 final_action；risk downgrade 影响仓位/信心/标签；selection vs action_rank 差异有解释；无 dangling、无无证据 claim。失败 → 报告不 clean。

## 11. 输出

### 11.1 路径与分层
- **`state\us_short\weekly_private\<决策日>\` 只放** `weekly_report.md` + `action_table.csv`；设计稿/测试/research/debug/decision packet/run summary/原始数据都不得放入。
- **机器层**（operation_impact + 全字段 + 原始分数 + decision_trace + registry）→ `state/us_short/runs_private/<决策日>/`（gitignored），不进 weekly_private、不进 tracked 工作目录；周报/csv 从机器层渲染、validator 在机器层焊死。
- **纸面账**（§12）→ `state/us_short/model_paper_private/`（gitignored）。

### 11.2 weekly_report.md 节
本周运行状态 / 账户风控状态(`portfolio_guard_status`) / 市场环境(两轴：`market_risk_regime` + `theme_opportunity_state`) / 本周核心结论 / 最终操作表(精简一眼表) / 当前持仓复核 / Top15 选股 / Top6-15 观察池 / 本周剔除摘要(exclusion_summary) / 风险与降级 / 数据源健康摘要 / 字段·模块生命周期提醒 / 本周不 clean 项。lifecycle 提醒条数第 1 节与对应节须一致。
- **顶部诚实横幅（借 A 股 M6.7）**：① 真/假观察拆分——把 `observe_reason_type` 按**冻结 observe_reason_type 词表全口径**聚合（含 `capacity_or_budget_deferred` = 过闸可执行但被本周建仓上限/同主题/极度防御仓位上限挤出名额、非系统不看好），其中"没账户/没现金"（`cash_or_account_missing`）那类是 sizing 假象、不是系统不看好；② 宏观集群预警（§8）——"N 个建仓同属 X 集群、合计 Y% 仓位"；③ ship-gate 进度 + 达标 lifecycle 项数量对账；④ **price clock（必显）**——`price_data_through=上周五收盘（=canonical 决策日前一已收盘交易日，逢节回退）/ news_window_through=运行时刻（决策日开盘前任意时刻；含周末+周一早间突发）/ session_scope=RTH / decision_date=canonical（即将到来的美股交易日，§2.1）`，杜绝误以为用了周一盘中价；窗口内多次跑同一 decision_date 即同一价格钟；⑤ **高热度被剔除提示**——"本周 N 只高赛道热度票被剔除（安全闸/流动性/数据），见 `hot_excluded`（§11.4）"。

### 11.3 action_table.csv（完整列）
`ticker, row_source, selection_bucket, theme_id, theme_source, theme_lifecycle_state, final_action, recommended_action_shares, action_rank, action_confidence, observe_reason_type, order_type, entry_plan, pullback_entry_price, breakout_entry_price, limit_order_price, valid_entry_low, valid_entry_high, order_expiry, gap_policy, effective_support, effective_resistance, structure_quality, stop_clear_price, take_profit_reduce_price, take_profit_exit_price, event_clear_reference_price, risk_reward_ratio, min_rr_gate_status, post_round_rr_status, price_engine_used, price_sub_mode, model_position_size_amount, model_position_size_shares, live_permission_status, live_size_warning, cash_allocation_status, portfolio_guard_status, symbol_cooldown_status, cooldown_until, reentry_allowed_reason, coverage_status, coverage_gap_tags, trigger_conditions, invalid_conditions, risk_tags, overextension_state, macro_cluster, macro_cluster_exposure_frac, macro_cluster_warning_level, macro_cluster_size_adjustment, data_quality_tags, execution_constraints, upcoming_events, decision_trace`（+ 候选增强字段）。`recommended_action_shares` 是本周手动动作数量：建仓=已定仓股数，持仓减/清=私有对账后的卖出股数，持有/观察/否决留空；只有已触发的事件/止损清仓在对账不可信时可留空，但动作、价格和`decision_trace`的人工核对标记必须保留。
- **精简一眼表**（周报内 ~8 列）：操作 / 模型股数+实盘权限 / 入·盈一·盈二·损 / 类型 / 优先级 / 触发条件 / 未来大事 / 关键标签。

### 11.4 exclusion_summary（剔除摘要 + 隐私拆分）
周报告知本周剔除 N 只 + 分类（流动性/价格市值/停牌退市破产/增发SEC/数据unknown/事件unknown/数据源失败/分不够）；覆盖 Pass-1 资格剔除 + Pass-2 审计闸剔除。防误杀 + 看是否过度保守。**隐私**：暴露"真实持仓被剔" → 私密路径；纯公开 universe 计数 → 可 tracked。
- **`hot_excluded`（高热度被剔除审计）**：在 exclusion_summary 内单列"被剔除**但赛道热度高**"的票（有 `theme_heat_score` 且达分位、却在安全闸/流动性/数据 gate 出局者）+ 各自剔除原因（镜像 A 股 overlay `dropped_at_l0_l5`）。**只用于发现误杀，绝不救回 hard veto / 不改准入**；持仓票走私密拆分（同上），纯公开 universe 热票计数可 tracked。意义：把"系统是不是太保守"从感觉变成每周可见清单，喂 §13 复审赛道权重/安全闸阈值。
- **运行时审计接线（2026-07-19）**：只在真实 `exclusion_records` 形成后，按同 ticker / decision date / theme-contract digest join 同轮全池主题分位；只接安全/流动性/数据 gate，Pass2 hard veto 与 Top15 分数淘汰永不进入。缺热度单列 `hot_excluded_unevaluable_count`，不得当作低热度后显示 0；该轨不进入 `result_effects`。

### 11.5 持仓覆盖诚实度
`row_source`（`top15_candidate / holding_in_top15 / holding_pass2_only / holding_account_only`）+ `coverage_status`（`full/partial/restricted/blocked`）+ `coverage_gap_tags`。即使强制进 Pass 2，缺分析师/SEC parse/事件数据 → 明示 partial/未核查、不写 clean。

**来源到结果绑定（Cut4）**：Batch5 对每个正式分析行生成封闭的 `source_result_facts`，绑定 ticker、决策日、价格基准日、来源包 digest、各来源检查、既有 catalyst 投影、数据质量与执行约束。`coverage_status / coverage_gap_tags / data_quality_tags / execution_constraints` 只能从该事实投影到 machine row、`action_table.csv` 与周报；`report_context.coverage_inputs` 仅保留给完全 legacy fixture，不能覆盖来源行。只有同 ticker、同 price basis、同 session、同 adjustment_mode、带真实 `observed_at` 和来源 digest 的本地 OHLCV 才可进入价格引擎；只有收盘价必须转观察（`price_not_executable`），绝不伪造 ATR/支撑阻力。partial 降低置信度并保留具名缺口；restricted/blocked 禁止新建但不得吞掉已触发的持仓止损/事件清仓。该 bridge 只搬运和校验来源事实，不接收调用方写入的 `result_effects`、portfolio guard、cooldown 或最终动作。

### 11.6 输出路径护栏
- `.gitignore` 须覆盖**所有 private 目录**：`state/*/weekly_private/`、`state/*/account_state_csv/`、`state/*/runs_private/`（含 `holding_action_state.json`）、`state/*/model_paper_private/`、`state/*/lifecycle/`、`state/*/shadow_compare_private/`、`state/*/capstone_checkpoints_private/`。checkpoint bundle 含 ticker 级中间产物与 digest manifest，必须与官方私密输出执行同一 `reject_nonprivate_output_path` 守卫：仓内路径须由真实 `git check-ignore` 证明，仓外绝对路径允许，未证明即在 mkdir/write 前 fail-fast；生产 `state/us_short/capstone_checkpoints_private/...` 路径由回归测试直接覆盖。
- **lifecycle / shadow 状态文件隐私规则**：含票名/表现/成交/持仓的计数（`lifecycle_register.json`、比较轨 shadow 选股明细）→ **必须 private/gitignored**；要 tracked 只能放脱敏汇总（无票名、无 $、只归一化指标）。稳定规则文字仍进 tracked `docs/system_risk_register.md`。
- **fail-closed 护栏**：用 `git check-ignore` 真值——任何 private 输出路径落点在仓库内且未被忽略 → fail-fast 报错；绕过脚本直接调管线也拦得住。

---

# 系统级治理（§12–§17）

## 12. Ship-gate / 上真钱 / Active-only / 纸面成绩单
- **满仓线 = 12 个月 forward-live（= `live_normalized` 证据，非纸面）+ 月度 alpha t≥2.0 / Sharpe≥1.0 / 回撤≤15% 四指标 AND 门**；不给美股开后门。
- **美股 active-only**：历史回测因幸存者偏差等永远只能排雷/找灵感/版本比较，证明不了 alpha、不解锁 ship-gate、不授权 full-size/DataHub/production；只能 forward 攒。forward universe 须 PIT 冻结于起点、真实捕捉退市/停牌/并购/无法成交，不删除（落地物 = `forward_universe_snapshot`，§18.1）。现有私有 lifecycle observation 以已绑定状态候选和冻结快照比对：inactive/缺席只标 `inactive_or_ticker_change_unresolved` 或 manual-review block，绝不误称已确认并购/换股；不自动换股、现金折算或强制平仓。
- **公司行动处置票据（私有、手动落地）**：仅当人工已确认且 source-bound 的事件明确 old ticker、effective date、换股比例和/或每股现金对价时，纯规划器才用精确分数/整数分生成换股、现金或强制退出的**人工确认票据**；它不读写真实账户、不接券商、不自动改持仓/记现金/强平，且不计算收益或改变选股。inactive/缺席本身永远不满足该输入门。
- **人工公司行动事件录入器（纯离线）**：人工从 SEC 读到 accession/URL 后，录入 old ticker、事件类型、精确整数换股分数、两位小数现金和 effective date；SEC EDGAR URL 的 CIK 必须匹配 old 身份，或换股时匹配 identity-bound successor，防止复制错发行人链接。只有显式确认才生成 planner 可消费的 source-bound event。输出只保留 accession、证据 CIK 与 canonical evidence digest，不保留 URL；CVR 或缺失/不一致输入一律冻结该 ticker 并人工复核，不猜条款、不产票据。此录入器不 fetch/parse SEC、不能证明原始 SEC 语义；只有显式 `--confirm-account-read` 才只读同一私有 `us_short_account_state` 并把实际票据写到 gitignored/external 私有路径，不修改账本或应用处置。
- **证券身份与源故障隔离（纯离线地基）**：证券身份以 `CIK + 受控 share_class` 固定、ticker 只是可变标签；同发行人不同股份类别不合并。源故障只冻结该身份绑定的 ticker 并要求人工复核，不停全局、不冻结其他股票、不自动重试。`engine/us_short_offline_provider_boundary.py` 仍是默认拒 fetch、未读 raw 的地基，不构成 provider 选择、公司行动语义或选股依据。
- **公司行动源入口（默认 dry-run、逐次授权）**：SEC 路只接受一个 operator-reviewed、CIK/accession/Archives URL 严格绑定、预算固定 1 call 的文档；只对 8-K/8-K-A 中唯一且明确的现金/换股/股加现模板生成**待人工确认 candidate**。DEFM14A、CVR、选举/proration、比例调整、零碎股或多值歧义一律单票冻结；raw 文档只在内存读取，输出只留 digest，不自动进入 planner。yfinance 路只按显式 expected price date 读取单票 `Close/Stock Splits/Dividends` 作低信任日报警；缺包、源错、空行、畸形、ticker/date 不符均降为该票 `source_unavailable/manual_review`，不拖垮全局，不参与选股、provider-health、paper confirmation、alpha 或 ship-gate。
- **公司行动离线人工串链**：单条私有命令把同一证券身份下的 lifecycle observation、SEC candidate、yfinance alarm 和可选 Massive assessment 绑定到一个人工复核状态；这些输入都只是线索，不能确认事件。只有既有 manual event recorder 已明确确认且与严格 SEC candidate 条款一致时，才可在显式账户只读确认后调用既有 disposition planner 准备私有票据；身份、ticker、条款或 digest 不一致即 fail-closed。工作流输出和票据仅写 gitignored/external 私有路径，不改账户；三项 §12.1 paper confirmation 永远为 false，也不授权 provider/live、自动换股/记现金/强平、收益、选股、DataHub、production 或 ship-gate。
- **成熟度 = 提醒 + 手动控仓**（不搞系统分档帽）：系统带每周成绩单——paper 成绩单是**进度/设计提醒**，**ship-gate 累加器只累计 `live_normalized`**（manual_actual + 对账，见下双轨）。
- **双轨（角色对齐 `docs/evidence_capital_policy.md`：纯 paper 不得判满仓 ship-gate）**：
  - `model_paper_track`（**paper 级、设计迭代轨**）：按当周 action_table + 限价 + valid_entry_band + 止损/止盈确定性模拟成交，**仅用于**设计迭代/校准/变体对比（§12.2）/pre-live 验证；不受用户是否买入影响。**`evidence_level=paper`，绝不判 full-size ship-gate**（evidence_capital_policy §2/§4：paper 不得 claim 满仓毕业）。
  - `manual_actual_track` / `execution_log_private`（§3.6 trades.csv）：用户真实（最小仓）成交/跳过/改价/提前离场 + **最小 reconciliation（实际持仓/override 记录）→ 归一化成 `live_normalized` 证据**。**这才是 ship-gate 的唯一证据源**（evidence_capital_policy §5：流程稳定 + 决策先于结果 + 成本/容量/scaling 显式 + 持仓对账齐全才算 `live_normalized`；`scaling_mode ∈ {linear, capped, not_valid, not_assessed}`、小仓不得盲目线性放大到满仓）。无真实成交 + 对账 → 证据停留 paper 级、ship-gate 不动。
- **ship-gate 只改"下多大注、信几分"，不改价位/时机**。

### 12.1 model_paper_track 纸面成交规则（写死、可复现）
- 存储 `state/us_short/model_paper_private/`：`paper_orders.csv / paper_positions.csv / paper_performance.json`（**`paper_performance` v1 实现为 JSON**——每条 = 一笔 net result 的嵌套 typed 记录[含 `None` / `bool` / `float` + per-outcome 不变式],JSON 无损表达,而 CSV 的扁平字符串须 type-coerce 回读且 0-条目丢 `as_of`;2026-06-23 design-owner 决定,见 register `R-USSHORT-BATCH3-PAPER-LEDGER-FORMAT-DRIFT`）；归一化指标（t/Sharpe/回撤，无 $）可出 tracked 无密摘要。
- 只用日线 OHLCV。**复权/公司行动硬门**：未确认 `adjustment_mode` + split/dividend 处理 + 除权日价位一致性前，`paper_performance` 一律 `not_evaluable / data_degraded`，**不进任何 ship-gate / alpha 判断**（repo SR-PROVIDER-001：active price adjustment / corporate-action reconciliation 仍未证明；有界 Massive 样本已捕获，私有 raw adapter 也只生成 source-bound 的本地规范化包，均不证明语义或对账）。在经审查的 source-semantics / tolerance contract 落地前，split 的双口径因子最多作**零容忍 exact-match partial diagnostic**；任何 mismatch/rounding 仍 unresolved，dividend 语义也仍 unresolved，均不得单独把三项确认置 true。
- **订单有效期（v1 锁定）= `first_regular_session_only`**：只按周一 RTH 判定成交，盘前盘后不算；当日 RTH 收盘未成交 → `not_filled` → 转观察（不留隔日）。多日 GTC 挂单 = lifecycle 候选 `multi_day_order_expiry_candidate`（`candidate_active`）、v1 不做，靠纸面成交数据后经 §13 #35 决定是否启用。
- **成交判定（确定性顺序）**：
  - **Step 0**：`open` 不在 `[valid_entry_low, valid_entry_high]` → `not_filled`（资金算现金、不计收益）。
  - **Step 1（open 在带内，按 `order_type`）**：`pullback_limit`：`low ≤ limit_order_price` → 成交 @ `limit_order_price`；`breakout_stop_limit`：`high ≥ breakout_entry_price` → 成交 @ `min(max(open, breakout_entry_price), valid_entry_high)`；否则 `not_filled`。
- **同日多事件（日线看不出盘中先后，一律保守、防纸面虚高）**：① 入场成交当日若 `low ≤ 止损` → 按"入场后即止损"记（不假设它活过当天，daily 数据下的保守近似）；② 同日止损与止盈都触发 → 止损优先。
- **净结果口径**：`paper_performance.json` 每条 net result = `{outcome, realized, gross_return, cost_fraction, net_return, unfilled_cash}`——算净收益、未成交按现金（不把没买上的当收益）。**成本 = prior（§13 #18）**：三成分（commission / slippage_bps / spread）合成单一往返 return-drag `cost_fraction = commission_fee + spread_cost + slippage_bps/10000`（无 $、归一化口径），仅 realized-closed 扣；不变式 `net_return == gross_return − cost_fraction`。

### 12.2 赛道权重比较轨 + 错过成绩单（借 A 股 comparison-track；shadow-only）
- **目的**：每周用 `theme_plus` / `theme_aggressive`（§4.2）在 shadow 各跑一遍选股，记"它们会选哪些、`balanced` 实际选哪些"，攒证据答：主系统是否常错过强赛道？加重赛道权重是否真更好？是否该升 §13 #1 权重？防系统因太稳长期错过主线。
- **PIT + 无幸存者偏差**：比较档选股与"本来会选 X"必须决策时点 PIT 冻结、复用 §12.1 确定性纸面成交 + universe 冻结；事后重构不算数。
- **复权门连带（§12.1）**：若 §12.1 复权/公司行动门致 `paper_performance = not_evaluable/data_degraded`，则 shadow 比较轨净值同样 `not_evaluable`、**不输出升级/降级结论**（与 §12.1"不进任何 alpha 判断"一致；升级闸此时不推进）。
- **双向诚实（防"挑好看的影子结果骗自己"）**：成绩单必须报每档全口径——不只"`balanced` 错过的大牛"，还要报 **多买的亏损票、回撤、成本（佣金/滑点/点差）、空仓/现金拖累影响、坏票率**；否则永远得出"赛道越激进越好"的偏结论。
- **禁止挑样本展示**：shadow 报告必须按固定 TopN + 固定成交规则全量输出，不许只展示上涨票/热门票/事后表现好的票。
- **ship-gate 隔离**：只有 `balanced`（实际运行主轨）**经其 `live_normalized` 证据**计入 ship-gate（§12）；`theme_plus / theme_aggressive` 永远 shadow（paper-only、不交易）——只能证明"是否值得升级主系统"，绝不能直接算毕业、不能绕过正式验证。
- **`theme_off` 归因基准**：除 `theme_plus`/`theme_aggressive` 外再跑一档 **`theme_off`（赛道权重归 0、重分配给动量+催化）** 的 shadow——量"35% 赛道权重到底贡献多少 alpha"（`balanced − theme_off` = 赛道边际贡献），兼作一键回滚锚。同样 PIT 冻结 + 双向全口径 + **永不计 ship-gate**（§13 #28）。
- **A1 选择层网格**：`catalyst_off`（催化剂 25% 按原 40:35 比例改为动量 8/15、赛道 7/15）与 `overextension_selection_off`（只撤销 `chasing_extreme` 的赛道 strip/seat）同命名权重档一起从同一 PIT 快照即时分叉并 live 物化；后者保留过热观测与执行旗标，不能冒充执行层 A/B。`overextension_execution_off` 是后续影子分支账本接通后的 second-wave-live 槽，只从账本接通后开始攒自身的 forward 证据，绝不补算此前周数。所有这些 shadow 仍按固定 TopN/成交规则和双向成绩单报告，均不改变 `balanced` 主建议或 ship-gate（§13 #28/#36）。
- **顺带量"进场偏晚"**：确认门槛天然滞后 → 系统偏晚进场；`theme_aggressive`（更早进）shadow 若长期更差，说明滞后在保护你、更好则说明太晚。结果挂 §13 复审。
- **存储隐私**：比较轨含票名的 shadow 选股/成绩 → `state/us_short/shadow_compare_private/`（gitignored，§11.6）；tracked 只出脱敏归一化指标（无票名/无 $）。
- **升级闸防自欺机制（借 A 股 `a_short_overlay_eval.py`）**：① 只数 **live forward** 观测（决策当日 PIT、无 look-ahead）入升级时钟；② **胜出 margin 必须先冻**（A1 唯一 pre-count v2.1 预注册为 `presets/us_short_forward_policy_statistical_plan_20260718.json`：执行拓扑固定为**仅两刀、每刀一次完整执行、禁止子刀**；第1刀以语义化 effect segment 记录版本（公共池成员、各臂选择差、H10 计算三项来源绑定不变量逐记录校验），并以**单一合格 epoch 的块级推断为权威**；segment-mean 的 REML 合并仅作展示。**跨 epoch 多段的正式裁决（REML + Hartung-Knapp 区间 + 冻结异质性门 + 方向冲突）推迟到后续 reviewed cut**——计数窗口一旦跨 ≥2 段即 `inconclusive`，绝不在 fixed-effect 拼接上跨段采用（2026-07-18 用户拍板选项 ii；register R-RE）。注释/空白/文档字符串与 JSON 格式不换段，真实选择/结果依赖闭包变动才新开 segment。H10 扣成本收益只在固定 24/36 divergence looks 以合计 0.025 的单侧 α 预算判定；同题多 arm 必经直接两两最终裁决，不能任意留待持续 peek。第2刀才是另行授权的公司行动证据与 maturity 接线；旧 `engine/us_short_forward_policy_statistical_evaluation.py` 仍只是离线诊断，不能产生正式采用/保留/舍弃建议）；③ 陈旧/错位 artifact **fail-closed** 不计入（桶名≠as_of 即弃）；④ 每周运行时**醒目横幅**（见 §13 `us_short_lifecycle_eval`）。升级仍需用户决定、绝不自动切生产。
- **A1 现行落地链**：决策时从已抓取的全市场 OHLCV 冻结所有 Pass2-clean 候选的一套 pullback-only 价格/成本控制，后续周只成熟该私有冻结记录；私有账本的脱敏建议注入周报顶部 banner ⑥。公司行动/复权未获独立核验时必须写整周 no-count、不得推进时钟；这条提示链不阻断正式周报，也不改变 `balanced`。
- **A1 v2.1 第 2 刀（已实现、无 provider 调用）**：成熟消费必须把当前决策时点作为绝对 `maturity_as_of` 写入 outcome/private-week；任何 H20 晚于该时点均 whole-week no-count，且成熟汇总按原因可观测。公司行动 evidence sidecar 必须同时绑定冻结决策、共同池事件范围和同一成熟 OHLCV 包 SHA256；它不凭外部文件名或“evaluable”字样放行。真实取数仍逐次授权。

### 12.3 model_paper_track 周度组合记账（weekly portfolio wiring）

> 2026-07-20 用户定：无实盘期，主系统按真实周自维护模拟组合（orders/positions/cash/NAV），自动结周度+累计盈亏，作为主系统账户级风控、校准与诊断轨（本轮**只建主系统 paper 侧**，不改 §12.2 comparison-only 预注册计划）。**comparison-only 只做单一部件的配对实验，不进行主系统与影子系统的整体账户或整体策略盈利比较。**未来只有在评估路径依赖的单一部件（如执行、仓位、持仓规则）时，才能从同一冻结 prior state 分出 baseline 与该单一变体的影子分支；NAV 只可作该部件的配对 outcome，绝不能作整套系统优劣或整体替换依据。当前实现 = 主系统"建议 → 跨周模拟组合 → 组合 NAV"的周度连接层已接入（`default_pipeline()` 的 `model_paper_adapter` / `model_paper_weekly` 与 one-click store 续接路径）；问题 16-A 已将真实 `adapter["paper_track"]` 贯通 capstone context → weekly bridge → Batch5→Batch4 packet → `portfolio_guard` / result-effects 消费端，正式运行仍由既有 design-completion start receipt 门保持 dormant，只有用户明确说 `US-short 设计完成` 后才可激活并进入 Week 1。§12.1 的单笔 fill/net、§12.2 的 per-ticker H10 与本节的比较轨边界仍保持不变。register `R-USSHORT-MODEL-PAPER-WEEKLY-PORTFOLIO-WIRING`；桌面完整设计（评估后修订版）= `us_short主系统模拟盘方案.md`。

- **账户模式 `run_account_mode ∈ {paper_only, manual_actual, dual}`（显式、不隐式替换）**：paper state **永不**覆盖/回写/伪装成真实 `us_short_account_state`；候选分析/来源事实/价格时钟可共享，但**持仓重评、`portfolio_guard`、sizing、现金分配、action_table 必须各自消费自己的账户状态**；paper 分支产独立标记的 `paper_action_bundle`，不把真实分支 `action_table.csv` 无条件当 paper 成交。
- **时序铁律：先成熟旧周、再冻结新周（防 look-ahead）**：决策日 `D_N`（价格基准 `P_N`）一次 run 内——① 成熟旧决策**只用日期 ≤ `P_N` 的已到达 OHLCV** 结算此前冻结 bundle 的入场/被动退出/持仓动作，**绝不消费 `D_N` 之后的 bar**；② 以 `P_N` 同源 mark 出 `nav_snapshot` → 派生 paper account adapter；③ 用该 adapter 生成 `D_N` 的私有 `paper_action_bundle`，**只冻结、不提前成交**（等下一次有相应日线的 run 再成熟）。合法 delayed materialization（决策当时已 PIT 冻结、行情后到再成熟）≠ 历史 backfill；**禁事后重建/修改当时的选择或订单**。
- **同 `decision_date` 重跑**：同输入 digest → 幂等 no-op（不重复下单/记账）；盘前来源变更 → 只替换**尚未成熟**的 pending bundle 且留 `supersedes_digest`、不改已结算 state；目标 session 开盘后当前 bundle immutable（capstone 本就 out-of-window fail-closed）；日期乱序/缺前态/重复成熟/price receipt 不符 → 整次状态迁移拒绝、**不写半套文件**。
- **组合会计不变式（锁死）**：$100k 名义本金**只播种一次**；金额用 canonical Decimal（禁二进制 float 跨周累积，指标层才转 float）；买入 `cash -= shares×fill_price` 且成交时一次性扣 `shares×fill_price×cost_fraction`（与 §12.1 net_result round-trip 成本一致、退出不重复扣），卖出 `cash += sold_shares×exit_price`；**`NAV = cash + Σ(remaining_shares × mark_price)`；已实现盈亏只作归因字段、绝不再加进 NAV（防双重记账）**；须满足 `NAV − initial_capital = cumulative_total_pnl`（Decimal 容差）；同 session 卖出回款不反向放大当时已冻结的新建仓 shares；任何迁移无负 cash/负 shares/重复 ticker position/无源 mark/凭空资产。
- **持仓动作成交合同（先写死、单测；不能把"建议"当"已成交"）**：`建仓`=复用 §12.1 `simulate_fill`、仅 `first_regular_session_only`、未成交即现金不隔夜；`减仓`=只卖 `recommended_action_shares`、**仅模拟成交后**才置 `tp1_completed=true`；`清仓-止损`=卖全部 remaining、**gap-aware**（开盘穿越 stop 不得按更好 stop 价虚构成交）；`清仓-止盈`=卖全部 remaining、目标价触发/开盘越过目标的保守成交写死；`清仓-事件`=仅 source-bound 事件 + 可执行价语义齐全才成交、否则单票冻结/manual review；`持有/观察/否决`=不交易；`加仓`=当前主决策引擎不产出 → 独立多 lot/加仓合同落地前 **fail-closed**、不提前假设。v1 = **每 ticker 单一活动 lot + 一次 TP1 部分卖，不做加仓/多 lot**。
- **诊断 NAV vs `paper_evaluable`（用户定"每周照算照显示"= 选项 A 的严格含义）**：复权三项（§12.1）未确认时可出 `diagnostic_nav` 供观察，但 canonical `paper_evaluable=false` / `paper_performance_status=data_degraded`，**不进 alpha / 策略升级 / comparison 胜负 / ship-gate**；注入 `portfolio_guard` 须守 §18.1 #7 fail-safe（不伪装 clean、默认 restricted/caution 或只做持仓风控）；后续 source-bound 证据到达只成熟当时已冻结的真实周 bundle。**选项 A 不是绕过复权硬门，而是"保留诊断数字 + 证据/风控门关闭"**。
- **名义本金与 schema**：独立 `us_short_model_paper_portfolio_state` schema（`capital_kind=normalized_notional`、`base_currency=USD`、`initial_bucket_capital=100000`）；运行时一次性派生 adapter（`us_short_bucket_capital=100000`、`us_market_equity=300000` 仅满足现有 ÷3 不变式），**绝不持久化成用户真实美股资产或进真实账户报告**；adapter 带 source state digest + valuation date + decision date 绑定。
- **私密存储（事务化、幂等）**：`state/us_short/model_paper_private/`（`head_manifest.json` + `weeks/<decision_date>/{decision_bundle,settlement,portfolio_state,nav_snapshot}.json`）；全 gitignored + 先过 `reject_nonprivate_output_path`；`head_manifest` 绑 `prior_state_sha256 / decision_bundle_sha256 / source_receipt_sha256 / price_packet_sha256 / valuation_as_of / status`；先写临时目录、全校验过再**原子推进** head，失败不留可消费半状态。
- **一键操作路径（operator one-click；2026-07-22 用户批准 Codex 优化 + Claude 3 收紧）**：一键 paper 入口先读 `head_manifest`——**仅当无历史态才播种 $100k、以后绝不重建空仓账户**；每周喂 sizing / paper action 生成的账户输入 = model_paper store **成熟后派生的 adapter**（结转 cash + 持仓，即 `build_paper_account_adapter`），不是每周新写的空仓 `us_short_account_state`。model_paper 周度驱动器（`run_paper_weekly_transition` / `run_offline_model_paper_capstone`）接进 capstone pipeline 作**后置离线 stage**（本轮 OHLCV packet 到达后跑：先成熟旧周 → 派生 adapter → 冻结新周），不新增 provider 调用。**周报固定露出七项**：`initial_capital` / `current_cash` / `holdings_market_value` / `current_nav` / `cumulative_pnl` / `cumulative_return_pct` / `consecutive_weeks`（复权未确认时 NAV 为 diagnostic、`paper_evaluable=false`，照本节诊断规则）。**预算**：一键 paper 路径不要求用户预先计算/填写任何 Pass2 预算数字（§18.1 #32）；运行一键命令本身 = 该次 provider 授权动作。**验收**：offline fixture/replay **连跑 5 周**，证 week5 `cumulative_pnl = current_nav − 100000` 且中途任一周都无重新初始化（对齐刀3 offline 双账户分支；刀4 = 首个真实周）。
- **边界**：不接券商 / 不发订单 / 不读真实券商账户 / 不自动换股或记现金或强平；不碰 A 股 / US-long；paper **永不**判 full-size ship-gate（ship-gate 仍只认 §12 `live_normalized`）。

## 13. 跨 LLM 提醒机制（硬规则）
- 复用 `docs/system_risk_register.md` + standing reminder index；**不新造** `evidence_lifecycle_registry`。
- **落点分离（动态计数不进 route doc）**：register 只放稳定规则+指针；可变累加器/计数放 `state/us_short/lifecycle/lifecycle_register.json`；周报对应节从状态文件渲染。含票名/表现/持仓的计数 → 该 json 走 private/gitignored（§11.6）；tracked 只放脱敏汇总。
- **永久硬规则**：凡"需 forward 攒数据、靠未来验证才能定去留/校准/启用/替换"的，都必须挂完整提醒路径（现在+将来无一例外，达标必提醒）。
- **完整路径 = 累加器 + 登记条目 + 运行时露出（达标醒目横幅 + 数量对账，谁跑都看见）+ 覆盖保险**（这类项只能经统一注册入口引入、强制填阈值+大白话+待决问题+自动接累加器/露出；guard 测试扫漏网，缺任一层不通过）。
- **`us_short_lifecycle_eval`（运行时阶段）**：每周**在渲染周报前**独立跑一个 eval 阶段——先**遍历 §13.1 全部条目**（动态、不硬编码条数）算出本周到期态 → **喂周报"生命周期提醒"节 + 顶部横幅** + 写 readiness artifact + 打 GBK-safe 运行时横幅，**不只靠周报文字、不靠某个 LLM 记得读 register**（镜像 A 股 `a_short_overlay_eval.py` + weekly Stage 6）。**顺序硬约束：eval 必须在 weekly_report 渲染之前**，否则周报会漏本周新到期项。升级仍需用户决定（防自欺四机制见 §12.2），**绝不自动切生产**。
- **诚实边界**：guard 焊死正常路径 + 抓常见绕过 + 审查兜底，非数学上不可绕。

### 13.1 待校准清单（v1 起点，全进提醒机制；编号稳定，正文按号引用）
1. 选股权重 40/35/25
2. 安全闸阈值（流动性/价格/市值）
3. 环境阈值（VIX 18/25/35、均线、广度线、两轴拆分阈值）
4. 仓位参数（单笔/单票/总仓/同主题/环境乘数 + 每周建仓上限 3/2/1 + 财报前窗口）
5. benchmark
6. 候选价格引擎（`ema_trailing_engine` / `earnings_gap_engine`）
7. §5.2 候选硬否决（含好数据坏反应 soft/hard 阈值 + 相对豁免 X）
8. 赛道软信号 + AI 发现候选主题 + `provisional_theme_lane` 拉入数量/席位
9. 低信任 yfinance PCR/IV（需先授权）
10. 挂账付费数据（借券费/期权异动/暗池/实时空头）
11. provider/源 fallback 频率
12. ship-gate 毕业门槛 + `live_permission_status` / 成熟度提醒阈值（提醒，非自动 sizing 档）
13. 周一跳空 `valid_entry_band` 带宽
14. 打分标准化口径
15. 未来事件窗口 + 各事件效应
16. `min_rr_gate`（突破型更高）
17. S-3 / offering recency / materiality
18. 纸面成交成本（佣金/滑点/spread）
19. universe 上限 / 候选集大小 / FMP 调用预算
20. 突破 tp ATR 倍数 k（`trigger_raw + k×ATR`）
21. `catalyst_recall_lane` 判据/数量
22. 组合熔断阈值（连续止损/回撤）+ 各状态档
23. 单票冷静期长度 + 恢复条件
24. 去插针 ATR 倍数
25. 全局现金分配排序权重
26. provider 健康检查阈值
27. `theme_opportunity` 强赛道试探仓封顶（防御1 / 进攻+极强2）+ 试探仓最小仓成本地板（安全倍数）
28. `scoring_profile` + `catalyst_off` 选择层影子网格（theme_plus / theme_aggressive / theme_off / catalyst_off）+ 最低比较周数
29. 动态席位比例（强赛道 8+7 / 无强赛道 12+3 的触发与配比）
30. 赛道退场/衰减阈值（breadth / leader_rs 跌破线、persistence 重置）+ 状态转移防抖（降快升慢）
31. `macro_cluster` 定义 + `warning_level` 分档 + 集群暴露硬上限
32. `provisional_theme` 公式阈值（≥3 项、各字段判定线、薄来源降权、门内连续乘子窗口/映射、`persistence_mult` 门后地板 floor）
33. `breakout_mode` 参数（突破失效线、追价上限）
34. 主动持仓管理的第二层：移保本、止损 ratchet、多日主动管理与任何加仓逻辑（第一层固定 TP1=10%减仓 / TP2=全清已启用；攒更多持仓管理数据再决定）
35. `multi_day_order_expiry_candidate`（多日 GTC 订单有效期；靠纸面成交数据决定启用）
36. 过热分档阈值（forward prior：`overextension_warning` 的 `k1=1.75` + MA5>MA10>MA20 趋势梯；`chasing_extreme` 的 `k2=2.50`/m×ATR + 量能高潮 + 均线距离 + 回撤结构 + 多条件 AND 共现项数 K；两档互斥、绝不单条件触发）+ 选择/执行拆分影子对照（`overextension_selection_off` / 影子分支账本接通后才 second-wave-live 的 `overextension_execution_off`）
37. 强赛道周 Top6–15 额外完整分析名额数（1–2，按 `theme_leader_rs`；确认优先，严格筛选下可含 `provisional_active`、仅最小/试探仓的纳入门）
38. 赛道热度正交残差合成系数 + `macro_cluster` 重复热度检查口径（方向已固定为规则：跨界主题→theme 基、纯 GICS→industry 基；macro_cluster 不硬扣、只去重+横幅）
39. `financial_trends` 财报质量趋势（候选、默认不启用；启用仅 advisory `risk_downgrade`、绝不设门/否决；指标口径借 A 股框架）

### 13.2 默认提醒门槛（prior）
| 对象 | 最低提醒条件 |
|---|---|
| scoring weight | ≥12 周 forward 或 ≥30 有效样本 |
| price_engine | ≥20 触发样本，覆盖 ≥2 种市场环境 |
| hard_veto candidate | ≥10 次触发 + 人工复核 |
| provider fallback | ≥8 次 + 口径一致性对比 |
| X/网络/LLM / 主题发现 | ≥12 周记录 + 市场数据交叉确认 |
| future_event / 熔断 / 冷静期 等 | ≥12 周 + 足量实例后复审效应 |
| 赛道退场 / 集群上限 / 比较档权重 | ≥12 周 + 双向全口径净值（含亏损票）对比后再升硬约束 |

## 14. 复杂度 / 可行性
一键自动跑、"手动"只在下单；已大幅精简（便宜数据 + 2 引擎 + 简化打分 + 语义只 advisory + 两遍打分控调用）；语义/网络/LLM 只 advisory、每轮限次、失败降级、不卡关键路径；Top5 完整 + 强赛道额外 1–2 只完整 + 持仓全评 + 其余 Top6-15 观察/触发（集中本 ≈ 6-10 持仓），自动跑合理；认知负担由精简一眼表解决。

## 15. Benchmark
暂定 **Russell 1000** 为 provisional primary（不继承 A 股 CSI）；benchmark 是"有没有跑赢市场"的尺子、不是选股范围；池偏科技/成长，forward 期间同时对 SPY/QQQ/Russell 1000 多把尺子报，最后定主基准（§13 #5）——避免把"科技整体涨(beta)"误当"选股有本事(alpha)"。

## 16. Reference 使用原则
`skills/us_short_analysis/reference/` 两份只作进攻思路参考、非权威，不机械照搬 M 编号/话术/chatbox 流程（手写 prior、非最优）。已废弃：投资目标/固定期限/时间效率评分/时间损耗。保留重构：美股交易日历/SEC 审计/财报窗口/盘前盘后限制/hard veto/价格·仓位·输出联动。可结构化的进 Python/schema/config/state；需语义判断的进 Skill prompts。

## 17. 不可碰 / 边界 / 不借
- 不交叉 A 股；不接券商/不自动下单/不接 OS 自动化、全手动；真实持仓只进 weekly_private（gitignored + 护栏）；不因任何工程/audit 放松 ship-gate；A/US cash 不互通；写实现/改系统前须用户明确授权。
- **不借 A 股专属**：涨跌停、T+1、龙虎榜、北向、融资融券、ST/退市规则、A 股 Rule12/13 原文、Tushare/CNInfo。**US 替代**：SEC filing / 8-K / Form 4 / 144 / S-3、halt/LULD、退市破产、财报日、盘前盘后缺口、splits/dividends、spread/odd-lot、active-only forward。
- **借 A 股的是工程机制、不是市场规则**：可借 private path / no-dangling / lifecycle eval / shadow comparison / ratchet advisory 等工程骨架；**不借** A 股市场规则·路径·Tushare/CNInfo·涨跌停/T+1/龙虎榜。**本稿现为 repo 设计权威**（取代 `docs/us_short_spec.md`，后者已降级为指向本稿的归档指针，见 header / §19）。

---

## 18. 实现阶段必验清单

### 18.0 P0 硬门（v1 不可省，逐条都要落地）

> **硬规则、非普通 TODO（gate ②）**：下面 7 道 P0 已登记进 `docs/system_risk_register.md`（Required ID `R-USSHORT-V1-P0-IMPLEMENTATION-GATES`，status `open` / binding）。任何 US-short 实现 slice 在 `执行` 前必须先过 register 检查；**违反任一 P0 的实现不得提交、不得当生产数据/证据**。这些是 binding 前置约束，不是"以后再说"的待办。

- **数据源分层健康检查**（§3.7）：关键源坏 → restricted/blocked/data_degraded、不输出 clean。
- **试探仓最小仓成本地板**（§8）：净利润空间 ≤ 往返成本×安全倍数 → 真拦单转观察（`cost_inefficient_min_size`），不只打标签。
- **赛道生命周期**（§4.3）：5 态 + 状态转移动作表 + 防抖 + 生命周期 validator。
- **比较轨三铁律**（§12.2）：双向全口径成绩、禁挑样本、ship-gate 隔离（shadow 永不计毕业）。
- **provider 授权 + 调用预算 + storage 权**（§3 边界，SR-PROVIDER-001 open）：全市场 FMP fetch / yfinance / SEC parser / production storage / provider selection 未单独 reviewed+批准前，不得全 universe 跑、不得当生产数据；调用预算 + 存储留存须显式批准。
- **ship-gate 证据级**（§12，`evidence_capital_policy`）：full-size 只认 `live_normalized`（manual_actual + 最小 reconciliation + `scaling_mode`）；**纯 `model_paper_track` 永不判满仓毕业**。
- **复权/公司行动门**（§12.1，SR-PROVIDER-001）：未确认 `adjustment_mode` + split/dividend + 除权价位一致前，`paper_performance = not_evaluable/data_degraded`，不进 ship-gate / alpha。

### 18.1 逐条验真
1. `.gitignore` 私密路径覆盖：`weekly_private` / `account_state_csv` / `runs_private` / `model_paper_private` / `lifecycle` / `shadow_compare_private` / `capstone_checkpoints_private` 各行（§11.6）+ fail-closed 护栏测试（覆盖所有 private 路径）。
2. 两遍打分可行性：先验 FMP 基础档速率限内每周跑完 Pass 1（全 universe）+ Pass 2（候选集+持仓）；定 universe 上限/候选集大小为可跑值。**前置：全 universe FMP 调用须先过 §18.0 provider 授权门（SR-PROVIDER-001），未授权只在已批准小样本上跑。**
3. provider 分层健康检查（FMP/SEC）：关键源坏 → restricted/blocked/data_degraded、不输出 clean；**未授权源（yfinance/Web/X）只记 `disabled_unapproved`、不探活/不调用/不参与 clean**（单测：健康检查绝不触达未授权源）。
4. 手动状态输入层（§3.6）：CSV(ASCII 列名) + 转换器 + lineage(sha256/row_count/facts_as_of/expected_facts_as_of/decision_as_of) + trades↔positions 对账；同一次 dry-run 的 `price_basis_date` 必须绑定转换器 `--price-basis-date`。Live/budget capstone 同时需要 account JSON 与默认同 stem 的 `_lineage.json`；转换器若使用自定义 `--lineage-out`，启动时须显式传 `--account-lineage-path`，两份产物的资金基数与日期必须配对。
5. 价格层单测：有效支撑/压力去插针、tick 取整、取整后 RR 复校、突破 tp 兜底、加仓分支、持仓价位映射(stop_clear/tp_reduce/tp_exit/event_clear_ref)。
6. 两轴环境 + 强赛道试探仓封顶（极防/veto/cooldown 不放行）。
7. 仓位：组合熔断（主用 paper track；**paper 因数据门 not_evaluable → portfolio_guard 不得 clean、默认 restricted/caution**）+ 单票冷静期 + 全局现金分配 + model_size 与 live_permission 分开 + `theme_probe` 最小仓成本地板（小到无效 → observe=`cost_inefficient_min_size`）。
8. 纸面成交确定性单测（`order_expiry=first_regular_session_only` + Step0 gap precheck → Step1 order_type + 同日入场后止损保守序 + 同日止损优先）+ 净结果口径，保证 **paper 证据可复现**（paper 仅设计迭代、不判满仓 ship-gate，§12）。
9. no-dangling validator（正向落点）+ 证据反查（反向）+ 完整字段 registry，覆盖全部字段；高漂移风险字段（`theme_lifecycle_state` / `macro_cluster_size_adjustment` / `cost_inefficient_min_size` / `overextension_state` / paper-fill 规则）必须有"真影响输出"的行为断言、非仅存在性。
10. coverage_status 诚实度（full/partial/restricted/blocked + gap_tags）；exclusion_summary（+ 隐私拆分）；observe_reason_type。
11. 提醒机制：register 稳定规则、`lifecycle_register.json` 计数、周报渲染、覆盖保险 guard；§13.1 **全部条目**各配累加器+登记+横幅（按号引用，新增条目自动纳入，不在别处复述条数以免漂移）。
12. 边界回归测试：不接券商/全手动/不交叉 A 股/cash 不互通/ship-gate 12 月不放松。
13. `scoring_profile` + 比较轨（§4.2/§12.2）：`balanced` = 唯一主建议档 / 唯一 model_paper 主轨（**系统不自动交易**；ship-gate 只经用户真实成交 + reconciliation → live_normalized 计入）、`theme_plus`/`theme_aggressive`/`theme_off` 仅 shadow + PIT 冻结 + 双向全口径成绩（含多买亏损票/回撤/成本/现金拖累/坏票率）、shadow 永不计毕业。
14. 赛道生命周期（§4.3）：`theme_lifecycle_state` 5 态 + 状态转移动作表（cooling 席位减半 / decayed 不给席位+新建仓转观察 / retired 移除）+ 防抖（降快升慢、retired 需重新确认）；持仓加 `theme_decay` 标 + §9 重评、不机械清仓；`provisional_theme` 公式（≥3 项、成员名单 observed_at 冻结、独立价格算 breadth/RS）。生命周期 validator：`theme_lifecycle_state` 必须影响 席位/仓位/信心/risk_tags/观察原因 之一，否则判 dangling、报告不 clean。
15. 动态席位（§4.5，10+5 / 8+7 / 12+3）+ `macro_cluster` 集中度：字段 `macro_cluster_exposure_frac / warning_level / size_adjustment`（表里看得见压了多少）；v1 软影响（risk_tags/action_confidence/model_size）+ 横幅、无硬上限（硬上限挂 §13 #31 攒数据再校准）（§8/§11.2）。
16. `breakout_mode`/`pullback_mode`（§6）单测：突破失效线作止损、追价上限=`valid_entry_high`、仍过 min_rr_gate + tick + 取整后 RR；突破单未成交不进冷静期、成交后失败才进 `symbol_cooldown`（§8）。
17. 过热分档（§0/§4.3）：`overextension_state` 三值分类（MA/ATR/量比）；`warning`→执行侧（强制 pullback + 压仓 + 抬 RR、**不剥夺赛道分**）、`chasing_extreme`→选股层剥夺赛道热度分退回 base；两档互斥单测（同一票不双罚，符合 §4.2 单舞台）。
18. 强赛道完整分析名额（§2/§4.5）：强赛道周从 Top6–15 选 1–2 只主题龙头（`confirmed_active`，或严格筛选的 `provisional_active`、仅最小/试探仓）升级完整分析；非强赛道周不扩；升级≠建仓（仍过 RR/仓位/风控）；验证 `theme_probe` 对被升级的非 Top5 票不再空转。
19. hot_excluded 审计（§11.2/§11.4）：高 `theme_heat` 但被 gate 剔除的票进 `hot_excluded` + 原因；不救回 hard veto / 不改准入；持仓票私密拆分；周报顶部横幅计数与 §11.4 明细一致。
20. `us_short_lifecycle_eval`（§12.2/§13）：独立运行时阶段（渲染周报前）扫全部 §13.1 forward 项 + 醒目横幅；只数 live forward 观测、margin 未冻不触发升级、陈旧 artifact fail-closed；与周报 lifecycle 节数量对账。
21. price clock（§11.2）：周报顶部必显 `price_data_through / news_window_through / session_scope=RTH / decision_date`；与 §3.5 机器层 as_of/session/timezone 一致；混合/陈旧价格 fail-closed 标注。
22. 热度去重/正交化（§4.3）：`industry_heat` 对 `theme_heat` 正交化（残差归一）后再合成，单测"同属一票的行业热+主题热重叠只计一次"；`macro_cluster` 同集群多主题进重复热度检查 + §11.2 横幅、**不硬扣分**。
23. 确认门内连续打分（§4.3）：门（≥3 项）不变；门内 `theme_score = heat × persistence × fit` 连续合成 + `persistence_mult` 门后地板，单测"刚过门的高热新主题得分随热度上升、不被布尔平铺压平"。
24. `theme_off` 基准（§4.2/§12.2）：shadow 档赛道权重归 0；单测 `balanced − theme_off` = 赛道边际贡献可算；theme_off 永不计 ship-gate、PIT 冻结、双向全口径。
25. 防御档入场方式（§8）：`市场=防御` 新建仓（含 `theme_probe`）默认 `pullback_mode`；单测唯一例外 = `theme_opportunity_state=extreme` + 不跳空 + 入场在 `valid_entry_band` 内 → 放行 1 个最小仓 `breakout_mode` probe；极度防御/veto/cooldown = 0 仍拦死。
26. 好数据坏反应 soft-only（§4.2/§5.2）：v1 实现为 `risk_downgrade` 软扣分（不 hard veto），带 SPY/QQQ 相对豁免（次日个股 > 大盘−X% 不降级）单测；**两字段分离**（`earnings_reaction_history_score` vs `current_good_data_bad_reaction_event`）单测：本期事件不写进习惯分、不长期污染；hard veto 路径保持 §5.2 候选（不在 v1 触发）。
27. ship-gate 证据级（§12，`evidence_capital_policy`）：单测 paper-only 不得 claim 满仓毕业；`live_normalized` 须 manual_actual + 最小 reconciliation（实际持仓/override）+ `scaling_mode`，小仓不盲目线性放大；无对账 → 证据停留 paper 级。
28. provider 授权门（§3/§18.0，SR-PROVIDER-001）：全市场 FMP、广义 SEC parser、storage，或本轮 SEC/yfinance 入口的任何真实调用未获对应授权时 fail-closed、不全 universe 跑、不当生产数据；call budget + storage 留存须显式批准。
29. 复权/公司行动门（§12.1）：无 `adjustment_mode` + split/dividend + 除权价位一致确认 → `paper_performance=not_evaluable/data_degraded`，不进 ship-gate/alpha 单测。
30. `forward_universe_snapshot` artifact（§12）：forward 起点 PIT 冻结落地物——active symbol list + listing status + provider/as_of + hash + row_count + 后续 delist/halt/merger/no-trade 事件保留规则（不删除、真实捕捉）。

31. model_paper 周度组合记账（§12.3，`R-USSHORT-MODEL-PAPER-WEEKLY-PORTFOLIO-WIRING`）：`D_N` run 不读/不结算 `> P_N` 的 bar（下一 run 才成熟）；同 decision_date 同 digest no-op、盘前 drift 只 supersede pending、成熟后拒覆盖；`NAV = cash + 持仓 mark` 且已实现盈亏不重复加、买卖/成本/部分卖后可从 ledger 重算；空仓首周/未成交现金/建仓/TP1 精确减股/TP2 全平/止损 gap/事件冻结/held MTM；建议未成交不得置 `tp1_completed=true`；同日卖出回款不反向放大已冻结买单、cash 永不为负；manual/paper 状态与 action bundle 互不覆盖、`paper_only` 不读真实账户；paper holdings 缺 source coverage → fail-closed 不偷数；复权未确认 → 诊断 NAV 可出但 `paper_evaluable=false`、guard 不 clean、比较/alpha/ship-gate 不推进；私密路径/digest 绑定/原子失败无残留/乱序·缺周·重复成熟拒绝；Decimal/超大数/NaN/inf/负股数/重复 ticker/错 adjustment·session/未来 observed_at 全 fail-closed。
32. 一键自动预算（auto-derived weekly Pass2 budget, no user-typed number, **no cap**；`R-USSHORT-CAPSTONE-STANDING-PASS2-BUDGET-CAP-ONECLICK`；2026-07-22 final）：§18.0 provider 门的**兼容细化、不放宽 P0**——一键 paper 周跑**不要求用户预先计算/填写任何预算数字，也不设任何配额上限/内部天花板**；系统同一次 run 内从 preflight 漏斗**自动派生** Pass2 call 数并直接用之（只记录供审计、非需预配置的门）。**结构性边界 = `momentum_top_k`**（选股参数、非预算；默认 200、硬上限 250、代码强制）+ 顶 K 漏斗：FMP grades = 每 Pass2 目标 1 次调用、目标数 ≤ `top_k ∪ 持仓` ≤ ~250 → 默认 K 下 grades 日量结构上就 ≤ 免费档日上限，**无需任何单独 cap**；Massive 走既有 pacing + retry-on-429，SEC 公共源。**运行一键命令本身 = 该次 provider 授权动作**（§18.0"调用预算须显式批准"由"命令调用=授权 + `top_k` 硬上限 250=代码强制的预算上界"满足，非放宽 P0）。**诚实降级替代拒跑**：FMP grades 已定 advisory（§0 2026-07-10）→ 配额耗尽 → grades 中性、run 照常出（research 模式），**不 fail-closed 拒跑**；仅 health-critical 源坏才 NO-EMIT（§3.2/§3.7）。auto-derive 仅 paper 一键路径默认（`auto_authorize_pass2_budget`，代码已 gate 到 executing paper run），显式 `--pass2-call-budget` 精确路径保留供其它受控用途；不授权 provider selection/storage/全 universe 之外任何新边界，SR-PROVIDER-001 其余门不动。

**实现落地说明（2026-07-24）**：用户侧 PowerShell 周度/capsule 入口不再要求先执行 `PrepareBudget` 再手填 `Pass2Budget`；显式 `-Live` 在同一次默认 pipeline 中自动派生并冻结精确 Pass2 调用数。`Pass2BudgetApproval`、目标重算、provider 速率/429/物理尝试上限和 downstream digest binding 仍保留。Python API/CLI 的显式预算参数仅作为受控兼容路径，不是标准用户入口。

### 18.2 实现执行顺序（并轮策略；有边界地批量化）

> **可审查依据，非 memory 口述**：实现要省时间可以**并轮**——把可离线、同依赖、同审查面的实现刀合成批次，明显减少交接和审查往返。但**并的只是离线实现 + 审查 overhead**：**不并 provider 授权门、不并 provider/live、不免 Codex 审查、不放宽 §18.0 P0**。（2026-06-20 Claude 起草 + Codex 有边界地认可。）

- **并轮判据**：两刀共用一次起草/审查/执行，当且仅当 ① 都纯/离线（fixture 可单测、不碰 provider/真数据/真钱）或同被一个授权门 gated；② 彼此无 schema 契约的跨批先后依赖；③ 一次审查覆盖得动。必须拆轮：**跨模块消费的共享契约要先冻结**（schema-first，否则按规则打回）；任何 live/数据刀被 provider 门 gated；ship-gate 12 月时间门压不掉。
- **批次（~4 离线批 + gated provider，替代 ~30 串行小轮）**：

| 批 | 内容（§18.1 项） | 性质 | 依赖 |
|---|---|---|---|
| 批1 数据契约 + 手工输入 | 全部 schema + governance preset（§13.1 priors + scoring_profile 权重）+ CSV→`us_short_account_state` 转换器/对账（#1,#4,#11/#13-schema） | 纯/声明式 | **最先**（共享契约先冻） |
| 批2 纯决策引擎 | 价格引擎 + 两轴环境 + 仓位（含试探仓成本地板/现金分配/熔断/冷静期）+ hard veto 分层 + core_score/赛道正交/确认门连续打分/过热分档/赛道生命周期/动态席位/macro_cluster + 未来事件效应 + action_rank（#5–#7,#14–#17,#22,#23,#25,#26） | 纯（VIX 等走 unknown 路径） | 批1 冻结后 |
| 批3 校验+输出+纸面+比较+lifecycle eval | no-dangling validator + 证据反查 + registry 强制 + 输出渲染（price clock/exclusion_summary/hot_excluded/覆盖诚实）+ 纸面成交确定性规则 + 比较轨 shadow + 升级闸防自欺 + lifecycle eval 运行时阶段 + 提醒机制 + 边界回归 + **provider 健康检查的离线策略/结构 + 「绝不触达未授权源」单测**（#3-离线,#8–#10,#12,#13,#19–#21,#24） | 纯 | 消费批2 |
| 批4 周末 pipeline 接线（离线） | **canonical 决策日解析器（§2.1：运行时刻 + US 市场日历 → decision_date；live 窗口两边=上一 session 收盘后起、目标 session 9:30 开盘前止；盘中 out-of-window fail-closed、不 emit packet/forward；收盘后才 roll[基准=刚收盘 session]；允许非交易日/多次跑收敛单一 decision_date、幂等不灌 forward）** + universe→Pass1→Pass2→engine→output 编排 + consumer-validation，全程 fixture/注入、不 live 抓数。**注入日历测试期望**：周五收盘后/周末/周一盘前→周一；周一 RTH 盘中(9:30-16:00)→out-of-window 拒(不出 packet/forward)；周一收盘后→周二(基准=周一收盘)；US 假期→滚下一交易日；半日市(13:00 收盘)；DST 两边锚 ET | 纯 | 消费批2/3 |
| 批5+ provider/live | **部分已实现**：round-1 Massive+SEC 全市场 fetch+Pass1（chat 授权 SR-PROVIDER-001）/ round-2 momentum+catalyst-block+GICS industry-heat+provisional-theme-heat producers / Cut 6-a/b/c/d score-block seams（momentum/theme/catalyst projection + same-source score composer）/ provider-fed batch5→batch4 `data_context` source assembly + offline official-context (`per_ticker_analysis`/`run_provenance`) assembly from resolved local sources / local Batch5 source-packet→Batch4 weekend E2E bridge to private `weekly_report.md`+`action_table.csv` with subprocess CLI + no-residue failure cleanup / batch4 offline context packet builder+runner / 离线 provider-live 契约（probe·disposition·license·SEC binding·fallback·incident·status-source binding）/ SEC active-listing + Nasdaq halt-feed `run_fetch` status-source wiring / bounded live Pass2 source-packet runner+execution / bounded reviewed-plan full theme source-packet producer+execution / SEC submissions-to-`bankruptcy_screen` local runner+execution / bounded selected-candidate SEC submissions producer+execution / first two 25-symbol bankruptcy candidate scans+executions / resumable candidate-universe bankruptcy round01+round02+round03 / completed bankruptcy screen output → `run_fetch` status-record consumption / `run_fetch` provider-health+FMP fallback run-state summary / corporate-action·price-adjustment offline evidence-to-paper-gate derivation / default-dry-run 单文档 SEC 简单公司行动 candidate parser + 单票 yfinance 日报警 已在 repo。**仍 GATED（SR-PROVIDER-001、单独授权）**：broader provider stability evidence / automated·broader peer-theme discovery beyond reviewed local plan / live·real-provider-resolved `per_ticker_analysis`·`provenance` data path beyond reviewed local sources / 广义 SEC fundamentals/DEFM14A 语义解析 / 本入口真实调用 / Web·X / 生产存储 / DataHub 消费 / 复权·公司行动对账门 live / `forward_universe_snapshot` 真捕获（#2,#3-live；§18.0 provider 门） | 部分 done / 其余 gated | **不与批1–4 同批** |

- **批内纪律（不是把 30 项塞一个大 diff）**：每批内部仍要清楚的 **per-slice 边界 + 测试清单 + 反向失败用例 + hunk/stage 边界**；契约+直接消费者可同批，但跨模块消费的共享契约先冻结。批越大 FAIL 时重判 diff 越大、blast radius 越广——甜点是「一个子系统的纯刀 + 严格自审」、非 monolith。
- **健康检查拆分**：provider 健康检查的离线策略/结构 + 「健康检查绝不触达未授权源」单测属离线批（live 调用前就证明 fail-closed）；只有对已授权 FMP/SEC 的 **live 探活**进批5。
- **真正的省时杠杆**：并轮省的是交接 overhead；真正吃时间的是 **FAIL→修复 来回**。批次大小不是主因，**自审反向用例不足才是主要耗时源**（本设计落地时一条 guard 因缺 dual-live 反向用例连续 FAIL = 典型自致来回）。所以每批交 Codex 前必跑足 `docs/pre_codex_self_review_checklist.md`——尤其**对自己的 validator/guard 用对抗坏输入打一遍**——让每批 1 轮 PASS、而非 2–3 轮。
- **批4 build-vs-wire + 实现决策（2026-06-24 grounding 实测；语义仍以 §2.1/§3.5 为唯一权威、本条不复述）**：批4 不止「接线」——实测仓内**无** universe filter / cheap-eligibility gate / catalyst_recall / Pass2 audit-safety-gate 的 engine 模块，**也无** eligibility 阈值 governance preset（17 个 us_short governance 均不含），故批4 **自建**：① Pass1 cheap-eligibility 谓词；② Pass2 audit-safety-gate 序列（否决层复用已建 `hard_veto`、不重写）；③ catalyst_recall **注入槽**（真 feed = 批5）；④ 新 `eligibility governance preset/schema`（阈值 = prior §13）。**现有 52 个 `engine/us_short_*.py` + 批1 转换器一律不改**——编排器只**注入 as_of 调用**它们（§2.1 line 65「批2 引擎/批1 转换器保持日历无关」已核），`render_weekly_report` 本就内容无关、上游拼好 `report_data` 喂入即可。关键实现决策：① canonical resolver = **纯函数 `resolve_canonical_asof(now_et, sessions)`**（注入日历即全量测、镜像 A 股 `runners/resolve_canonical_asof.py` 工程骨架），**盘中死区 = raise `OutOfWindowError`**（非返回 status；编排器据此 no-emit）；② 日历源 = **静态冻结 NYSE 日历 artifact + 薄 session-builder**（离线/可审/确定性，非规则生成器、非 provider）；③ 北京→ET 转换在薄 runner（纯函数只认 ET 墙钟）；④ 编排器单一 **`data_context` 注入 seam**（批4 fixture / 批5 真 provider 同签名）。**slice**：4a 纯 resolver｜4b 静态日历源 + builder｜4c eligibility 门 + gate 谓词｜4d 编排器（stage 序列 + decision_date 穿线 + consumer-validation + machine_record 装配 + lifecycle-eval-先于-render + out-of-window no-emit + 内容无关输出装配 + 幂等私密写）。每 slice schema-first + Codex 审、纯/离线、不交叉 A 股。

---

### 18.3 US-short v1 engineering closure plan (2026-07-06)

**Completion definition**: US-short v1 engineering closure means a weekly one-click path can use authorized real data inputs to produce an honest weekly report and action table. This is not production, DataHub, ship-gate, full-size authorization, broker/order execution, or A-share crossing.

**Engineering closure route = 6 cuts in 2 batches**:

**Batch I - offline engineering closure, may be built in one parallel planning batch, then handed off/reviewed by cut**:

1. `per_ticker_analysis` / `provenance` offline assembler: implemented for resolved local sources; live/real-provider-resolved data path remains gated.
2. `forward_universe_snapshot` offline freeze artifact: implemented as a local gitignored active-listing input -> canonical snapshot builder/schema with row_count/hash/retention policy; live true event capture remains gated.
3. Corporate-action / price-adjustment gate detection logic, offline half: implemented as a local evidence-packet schema + engine derivation of the existing three §12.1 confirmation bits into `paper_performance_evaluability`; live split/dividend/ex-date evidence capture remains gated.
4. `run_fetch` provider-health outcome -> run-state summary wiring: implemented for Massive/SEC critical-source clean/no-emit policy plus opportunistic FMP market-cap fallback (`usable_with_fallback`; not provider-readiness evidence). Broader provider stability evidence remains gated.

Corporate-action follow-through is also implemented as one private offline/manual workflow over the existing lifecycle, SEC/yfinance intake, optional Massive diagnostic, manual recorder, validated account-state read, and disposition planner. It deliberately stops at manual review unless a human-confirmed event is supplied; it does not settle complex semantics or the §12.1 paper gate.

Two P3 hardening items may be folded into Batch I only when they stay same-file / low-risk; if they expand review scope, defer them and do not let them block the 6-cut engineering closure.

Batch I discipline: if the four cuts share schema or run-state contracts, freeze the shared contract first; do not treat "parallel batch" as permission to blur review boundaries.

**Batch II - gated live, sequential authorization only**:

5. Full-candidate local coverage + target-narrowed Pass2 source packet live run, including the live fetch half of the corporate-action / price-adjustment gate: local projection-input coverage and preflight/forecast are implemented as `runners/us_short_batch5_full_candidate_projection_inputs.py` + `docs/us_short_batch5_full_candidate_projection_inputs_summary_20260706.json` and `runners/us_short_batch5_full_candidate_pass2_preflight.py` + `docs/us_short_batch5_full_candidate_pass2_preflight_summary_20260706.json`. The canonical preflight uses full scored+neutral coverage as its local basis, then narrows expensive Pass2 by a deterministic momentum+theme cheap-score top-K, bounded eligible-only catalyst recall, and the mandatory account-holdings lane. Score projections carry the single shared `us_short_score_projection_binding`, binding candidate-set digest, decision/source clock, session/adjustment, producer, source-artifact digests, and payload digest; live execution revalidates those bindings and the preflight artifact digests before any fetch. The one-click capstone derives holdings from validated `account_state.positions`, freezes K plus the exact operator-authorized logical call budget before preflight, and forwards the same holdings/recall/K/budget into live re-derivation; CAT5's separate physical HTTP-attempt cap remains enforced during fetch. The weekly path leaves Universe bankruptcy provenance `unscreened` and reuses each existing Pass2 SEC submissions record for both offering audit and Item 1.03 screening; it rebuilds the target candidate subset with current status provenance, excludes positive candidates from eligible projections/data-context, retains positive holdings with a bankruptcy hard veto, and fails closed on missing or malformed target records. This adds no provider call, raw copy, budget, or separate bankruptcy artifact. The live runner writes target-scoped candidate projections plus separate holding signals and must not loop candidate consumers over full-candidate neutral fill. `engine/us_short_numeric_catalyst_entitlement.py` adds the offline entitlement-aware FMP numeric catalyst seam for `earnings_surprises` + `analyst_estimate_revisions`: not-entitled statuses neutral-skip, entitled normalized rows flow through `resolve_catalyst_signals` into `catalyst_block`, malformed 200 payloads fail safe to neutral. A no-access Massive alternative access/budget/source-packet plan also exists as `schemas/us_short_batch5_massive_alt_cut5_access_budget_source_packet_plan.schema.json` + `docs/us_short_batch5_massive_alt_cut5_access_budget_source_packet_plan_20260706.json` + `tests/schema/test_us_short_batch5_massive_alt_cut5_access_budget_source_packet_plan_schema.py`; a follow-on no-access Massive quota/access bounded probe packet exists as `schemas/us_short_batch5_massive_quota_access_bounded_probe_packet.schema.json` + `docs/us_short_batch5_massive_quota_access_bounded_probe_packet_20260706.json` + `tests/schema/test_us_short_batch5_massive_quota_access_bounded_probe_packet_schema.py`. These artifacts authorize no provider call, source switch, source-packet write, yfinance, DataHub, production, or ship-gate path; real provider execution remains gated by explicit call budget, separate network execution approval, and SR-PROVIDER-001 provider entitlement/storage/PIT/corporate-action evidence.
6. Capstone local E2E from an already authorized/local Batch5 source packet to private Batch4 weekly report / action table output: implemented via an explicit batch4 template + provider-health + account/private-root bridge, subprocess CLI execution, redacted stdout/stderr, scoped private/state outputs, and no-residue cleanup on downstream failure.

Batch II discipline: each live cut needs separate authorization and review; do not parallelize provider/live execution.

**Live provider t=0 clock rule (Problem7)**: a real provider run may proceed only when the requested and internally resolved actual ET wall clock map to the same current canonical `decision_date` and `price_basis_date`. Historical anchors, future anchors, intraday dead-zone clocks, and non-current canonical windows fail closed before provider or private-output side effects; historical analysis uses frozen raw/offline replay. The actual wall clock, not a caller-supplied explanatory timestamp, is the provider observation clock.

**One-click checkpoint / resume contract (2026-07-13)**: the capstone may resume only from an operator-supplied `--resume <checkpoint_manifest.json>` bundle; it never infers validity from file existence and never scans another worktree. `us_short_weekly_capstone_checkpoint_manifest` v1 binds the decision/price clocks, ordered stage contracts, non-file preflight inputs (authorized Top-K/call budget, catalyst recall, frozen holdings), exact logical input/output identities, SHA-256 digests, original result digest, and original stage clocks. Frozen-input stages may be restored only when all of those bindings still validate. `universe_fetch` is refreshed on every resumed run; its old source-bound candidate artifact may be restored only when the refreshed artifact is identical after removing observation clocks, otherwise that stage and all digest-dependent downstream stages execute normally. News/SEC/ratings/corporate-action resolution (`pass2_fetch`), yfinance grades, and VIX/regime remain `never` reusable. Bundle writes and restores use temp-file replacement, and the existing capstone transaction recovery remains the sole crash-recovery boundary for current official outputs.

`us_short_weekly_capstone_receipt` v2 records each required stage as `executed`, `reused`, or `refreshed_equivalent` with its real original generation/observation clock and result digest. Finalization has its own current clock; implementations must not rewrite old clocks to imitate a single-process run. Cross-worktree continuation is therefore an explicit digest-verified bundle import, not an implicit state search. This is engineering resilience only: it authorizes no extra provider call, production/ship-gate claim, DataHub, broker/order path, A-share, or US-long work.

## 19. 设计结论
US Short System remains the single v1 design: offense lives in selection/discovery, restraint lives in execution/sizing, and the same risk is penalized only once; all provisional values still require forward calibration under section 13. Implementation status for the offline engineering track: batch1, batch2, batch3, and batch4 weekend pipeline through 4d-ii-o are implemented in repo and reviewed per slice. Batch5 (provider/live) is PARTIALLY implemented — offline provider/live governance contracts + a user-authorized round-1 Massive+SEC universe fetch/Pass1 + round-2 producers + Cut 6-a/b/c/d score-block seams + full-candidate local projection-input merge/preflight + provider-fed `data_context` source assembly + offline official-context (`per_ticker_analysis`/`run_provenance`) assembly from resolved local sources + local Batch5 source-packet→Batch4 weekend E2E bridge to private weekly/action outputs + SEC active-listing/Nasdaq halt-feed status-source `run_fetch` wiring + bounded live Pass2 source-packet runner/execution + bounded reviewed-plan full theme source-packet producer/execution + bankruptcy 8-K local source-packet screen runner/execution + bounded selected-candidate SEC submissions producer/execution + first two 25-symbol bankruptcy candidate scans/executions + resumable candidate-universe bankruptcy round01+round02+round03 + completed bankruptcy screen output to `run_fetch`/status-record consumption + corporate-action / price-adjustment offline evidence-to-paper-gate derivation + the supported batch4 offline context packet builder/runner path exist.
Broader provider stability evidence, automated/broader peer-theme discovery beyond the reviewed local plan, live/real-provider-resolved `per_ticker_analysis`/`provenance` data path beyond reviewed local sources, live split/dividend/ex-date evidence capture, DataHub, Skill, production evidence, and further live/forward provider authorization remain separately gated and require separate implementation/review (SR-PROVIDER-001). No DataHub, Skill, production evidence, broker/order path, A-share crossing, or full-size ship-gate claim is authorized by this batch closure.
