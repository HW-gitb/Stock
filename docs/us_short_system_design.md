# US Short System — Design (in-repo authority, docs-only)

> **状态**：US-short 子系统的**单一权威设计**（docs-only）。设计层定稿、**已写入 repo 路由**；**尚未实现进代码**——任何写实现（schema / runner / provider / Skill / preset / state）均需用户单独授权、schema-first + tests + Codex 审查、多 LLM 串行、**不交叉 A 股**。
> **本稿 = repo 权威**：本文取代 `docs/us_short_spec.md` 成为 US-short 设计权威；`docs/us_short_spec.md` 已降级为指向本稿的**归档指针**（gate ①，不两个权威并存）。本稿是桌面定稿 `us_short_designs_final.md` 的入库版（结构 + 散文统一、去脚手架，零漏项机器核验：§13.1=39 项 / §18.1=30 项 / §18.0=7 道 P0）；更早桌面草稿（`US_Short_System_design_v2_clean.md` / `…v2.md` / `…优化版` / `…v1_Design`）均已弃用、不再当权威。
> **依据**：原桌面设计稿 + grilling 锁定决策 + 多轮对抗式审查（Codex + 自审）+ A 股已完成代码对比（借工程机制、不借 A 股市场规则）。
> **系统只有 v1 线**：不另起架构 v2/v3，延后项一律走 `candidate_active` / lifecycle 候选，不开 v1.1 版本线。
> **三道写 repo 硬闸（gate ①②③）落地状态**：① 旧 `us_short_spec.md` 已降级归档指针；② §18.0 的 7 道 P0 已登记进 `docs/system_risk_register.md`（`R-USSHORT-V1-P0-IMPLEMENTATION-GATES`，open / binding）作**硬规则**、非普通 TODO；③ 本 landing 已实跑 `git check-ignore` 核验全部 private 路径，并补齐 `.gitignore`（runs_private / model_paper_private / lifecycle / shadow_compare_private 四行，weekly_private / account_state_csv 早已覆盖），fail-closed 护栏测试列为实现期 P0 Required（§18.0 / §18.1 #1）。

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

## 2. 总体架构（每周一次一键跑完；决策日 = 周一开盘前）

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
- **决策日 = 周一、美股开盘前跑**。价格用**上周五收盘**（周末无更新价）；新闻/web/LLM 窗口拉到周一、含整个周末突发。
- **北京时间**：美股周一开盘 9:30 ET = 北京周一晚 21:30（夏令时）/ 22:30（冬令时）；北京周一白天/傍晚跑、挂限价单等开盘自动成交，不必盯盘。
- **跳空校准（可手动执行）**：新建仓输出为**限价单 + `valid_entry_band`**，`order_expiry = first_regular_session_only`（只在周一正常交易时段 RTH 有效）。周一 RTH 开盘价超出带子 → 不成交 → 转观察（盘前只作参考、不据此成交；不追高、不接飞刀）；当日 RTH 收盘仍未成交 → 转观察、不留隔日。带宽 = prior（§13）。
- **周中态**：周频、**不盘中重评**；持仓靠周末设好的止损/失效/止盈执行；重大突发（财报跳空/停牌/突发做空报告）由用户手动决定提前离场，下个决策日系统再完整重评。

## 3. 数据源、口径、微结构、手动输入

> **数据授权硬边界（SR-PROVIDER-001 仍 open）**：下面的数据三档 = **目标数据合同（target data contract），不是现有授权**。当前仅授权 2026-06-02 的「$0 小样本」（现有 FMP key + SEC EDGAR 公共 API + 本地小样本存储、几只票、无 full-market、无付费、无 yfinance）。**FMP Basic 全市场调用 / yfinance / Web·X / SEC parser / storage·retention / provider selection / DataHub·runner 消费 一律须单独 reviewed + 用户批准**；未授权前系统不得全 universe 跑、不得当生产数据用。详见 §18.0 P0。

### 3.1 数据三档（目标合同；2026-06-17 小样本 repo 证据仅 FMP + SEC，yfinance 仅目标低信任档、未授权/未纳入 repo 证据）
| 档 | 数据 | 用途 |
|---|---|---|
| **可信**（能打分、能硬否决） | FMP：股价/量、基础财务、分析师目标价/评级 + 历史评级、**财报实际 vs 预期**、估值比率、流通股本；免费 SEC EDGAR：文件、内部人(Form 4/144)、增发/转售(S-3/424B/S-8)、8-K、退市表(25-NSE)、机构持股(13G) | 选股打分 + 安全闸/硬否决 + 催化剂 |
| **低信任**（只标签，不打分/否决；**yfinance 未授权·需单独批准·目前不在 repo 证据**） | yfinance 自算 PCR / IV（当天快照；IV 用于"财报前降仓"提示） | advisory 标签 + 软风控 |
| **拿不到 / 挂登记表** | 借券费、真·期权异动/扫单、暗池；滞后空头比例（FINRA 半月、落后 2-3 周） | 不做，等可靠源（§13） |

- 新闻/做空报告 = WebSearch/WebFetch 语义提示；**未单独批准时 `disabled_unapproved`（不调用）**；授权后也只做语义提示、**不结构化打分 / 不硬否决**，除非后续 schema-first 单独实现并 review。
- 覆盖差异：大票全、小票稀 → "有就用、没有标未知降级"，不静默放行。
- 每字段运行时记 `provider_id / endpoint_or_filing_type / as_of / observed_at / coverage_status / parser_status / lineage`。

### 3.2 Fallback 与运行状态
非关键字段自动 fallback 标源；关键字段 fallback 必降级保守；硬否决审计字段必须权威源。运行状态 `clean / usable_with_fallback / restricted / blocked`；高频 fallback 进 §13。

### 3.3 数据口径与 Unknown 分层（避免过度保守）
- 关键价格字段（`current_price/OHLCV/ATR/volume/support/resistance`）须同源·同 as-of·同复权·同 session；记 `adjustment_mode / session_scope / timezone`；混源 → `data_degraded`。
- **关键 unknown → 禁新建/加仓**（持仓只给风控/减/清/重评）：结构化审计/状态字段——SEC filing 存在性 / delisting / halt / bankruptcy / major active offering(S-1/S-3/424B/ATM) / critical stock status。
- **非关键 unknown → `restricted_observe`**（不踢出、留观察池、写明缺什么）：SEC 正文语义（going concern/审计师辞任 → `semantic_audit_unavailable`：降信心+观察+manual_review、不硬 block）、网络负面、非核心事件日历缺失。**已读到的高可信做空报告/欺诈指控 → 至少 restricted/manual_review、不 clean 放行。**

### 3.4 美股微结构
缺关键微结构字段标 manual/research-only/blocked、不静默放行：停牌/LULD/陈旧报价、盘前盘后流动性/spread、odd-lot/sub-penny、ADR/外国假期/公司行动/反向拆股/退市破产、PDT。（SSR/Reg SHO/borrow 仅做空用 → v1 留门。）

### 3.5 Calendar / Timezone
记 `as_of / 决策时间戳 / session / timezone`（默认 ET + UTC）；事件证据带 `event_date`(真实发出) + `observed_at`(我们看到)、分开记防偷看未来；半日市/假期/停牌/基准日历错配可见；A/US 跨市场比较须显式市场日历对齐。

### 3.6 手动持仓/成交输入层（镜像 A 股手动表，必备）
- `state/us_short/account_state_csv/`（gitignored 私密；CSV 列名一律 ASCII）：
  - `positions.csv`：`ticker / shares / avg_cost_usd / entry_date / current_stop / notes`；
  - `trades.csv`（= §12 `manual_actual_track` / `execution_log_private` 落地文件）：`decision_date / ticker / suggested_action / executed / fill_price / fill_shares / skip_reason / manual_override`；
  - `account.csv`：`us_market_equity` + `us_short_available_cash` + 可选 `portfolio_total_equity`（仅参考）；短线桶 = `us_market_equity ÷ 3`，系统自己算，不从含糊"总额"瞎猜。
- **转换器 → `us_short_account_state`**（US 自有 schema，不共用 A 股）→ 周报/持仓重评/成绩单消费。
- **lineage**：每张 CSV 记 `sha256 / row_count / facts_as_of / decision_as_of`；trades↔positions 一致性对账（advisory WARN，不覆盖 positions）。CSV canonical 防 Excel 强转。

### 3.7 数据源分层健康检查（跑前必做）
每周跑前分层探活：FMP 关键接口 / SEC EDGAR parser / 价格·状态·财报·事件字段够不够。**未单独批准的源（yfinance / Web / X，§3 边界）：健康检查只记 `disabled_unapproved`——不探活、不调用、不参与 clean 判定**（防"健康检查"被当成调用未授权源的后门）。只查真实 weekly 会用的、已授权的接口、不打印 token、不假 OK。关键源异常 → **不许输出 clean 建仓**，只能 `restricted / observe / data_degraded`。

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

### 4.2 core_score（仅对过闸标的）
```text
core_score = 40% 动量·相对强度 + 35% 赛道/主题热度 + 25% 催化剂/预期差 − risk_downgrade
```
- **权重 = initial prior**（美股 active-only 回测证明不了 alpha）→ forward + lifecycle 校准（§13 #1）。
- **`scoring_profile`（命名权重档 + 一键回滚）**：`balanced`（40/35/25，**v1 唯一主建议档 / 唯一 `model_paper` 主轨**；系统不自动交易——只有用户真实手动成交 + 完成 reconciliation 后才进 `manual_actual`/`live_normalized` 并计 ship-gate，§12）、`theme_plus`（加重赛道，仅 shadow 比较）、`theme_aggressive`（更激进赛道，仅 shadow 比较）、`theme_off`（赛道权重归 0、重分配给动量+催化，仅 shadow——归因基准 + 回滚锚，§12.2）。回滚/调权重 = 改配置不改码；比较档只 shadow、不交易、不计入 ship-gate（§12.2）。
- **标准化（v1 锁定默认）**：三块都映射 0–100——动量 = 全池分位、赛道 = GICS/主题池内分位（确认门内再按 `heat × persistence × fit` 连续合成，§4.3；行业热与跨行业主题热正交去重，§4.3）、催化剂 = 规则映射分（非分位）；z-score 挂 lifecycle。
- **缺分量**：某块算不出（小票无分析师→催化剂缺）→ 该块按中性 + `data_quality` 降级 + 标签；不偷偷重新归一放大权重。
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
- **来源诚实**：每主题带 `theme_source`（`gics_established` / `provisional_discovered`）+ `theme_lifecycle_state`；provisional 席位行带 `provisional_theme` 标（advisory——新发现、未经周期验证、人工给信心打折），喂 §13 累加器。
- **纯软信号**（无市场确认的网络/X/LLM/人工 watchlist）：只标签/封顶小加分（≤ `manual_watchlist_boost` 5 分），不单独变硬分。
- **过热分档（防追喷出的票，但不误杀强趋势）**：两档**互斥**，同一风险只罚一次（§4.2 单舞台），字段 `overextension_state ∈ {none, warning, chasing_extreme}` 入 action_table。
  - `overextension_warning`（温和：现价高于 MA10 + k1×ATR、趋势完好未喷出）：**保留全额赛道分、不踢出选股**；只在执行侧罚——强制 `pullback_mode` 入场（不追突破）+ 压到试探/最小仓 + 抬 RR 门（复用 §6/§8 既有杠杆，不新增惩罚 stage）。
  - `chasing_extreme`（抛物线，**多条件同时（AND）成立才触发——绝不因单条件如"仅涨幅大"误判**：连续垂直 + 当日涨幅 ≥ m×ATR + 量能高潮 + 远离全部均线 + 回撤结构差，需 ≥K 项共现）：**才**从 core_score 剥掉赛道热度分 → 退回动量+催化 base。
  - 分档用 MA5/MA10/MA20 + ATR + 量比判定；阈值 k1/k2/m = prior（§13 #36）。强趋势票"高了还能更高"默认落 `warning`、不被误杀，仅真喷出才降权。

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
  - `pullback_mode`（回踩）：有效支撑 + ATR 定入场/止损。
  - `breakout_mode`（突破）：`breakout_entry_price` 入场 + 追价上限 = `valid_entry_high`（不追飞）+ **突破失效线 = 止损**（取突破位/近期盘整下沿，不用远端结构支撑——否则止损太远 RR 不够、强势突破被过早误转观察）+ tp 用 ATR 倍数兜底。参数 = prior（§13 #20/#33）。
  - 两模式都仍过 `min_rr_gate` + tick 取整 + 取整后 RR 复校。
- **优先级链**：① hard_veto（new→否决/不建；holding→强制减/清/重评）② data_degraded（holding→只风控/不伪造价；new→观察/restricted）③ holding→`holding_exit_engine` ④ new→`support_atr_engine`。**加仓**：持仓+触发加仓 → `support_atr_engine` 算加仓入场、`holding_exit_engine` 管原仓，两者并存。
- **有效支撑/压力去插针**（美股无涨跌停、长影线更夸张）：`effective_support / effective_resistance / structure_quality / structure_adjustment_reason`；单日极值比次值远 >1×ATR（prior §13 #24）判插针、取次值；止损/入场/止盈/RR 全用**有效**值算；结构差 → 降观察/降仓。
- **`min_rr_gate`**：`risk_reward_ratio =（盈一−入场）/（入场−止损）`；RR < gate → 不建仓、转观察（prior，突破型可更高）。突破票无上方阻力时用 `breakout_mode` 的 ATR 兜底 tp1 再过 RR 闸，不因"无阻力"把突破票直接转观察；trace 标结构 tp 还是 ATR 兜底。
- **tick 取整 + 取整后 RR 复校**：算理论价 → 按方向取整可执行价（美股 $0.01，留 sub-penny/低价例外）→ 用取整后真实价**重算 RR**，破了降观察；字段 `execution_tick / rounded_price_used / post_round_rr_status`。
- 缺可靠 ATR/支撑压力/财报日期/持仓成本 → 降级观察或只风控。

### 6.1 持仓价位映射（v1 出基础价位、只推迟主动逻辑）
- v1 不做复杂主动持仓管理，但**必须输出基础价位映射**（满足"清仓/减仓/止盈/止损价位"原始要求）——这些价 = `holding_exit_engine` 的被动 levels：`stop_clear_price`（止损清仓价）、`take_profit_reduce_price`（盈一减仓价）、`take_profit_exit_price`（盈二/跟踪止盈价）、`event_clear_reference_price`（事件硬风险清仓参考价，标"人工执行、非技术价"）。
- 主动 scale-out 的**逻辑**（何时减、减多少、移保本、跨周持久 ratchet）= lifecycle 候选 `active_scale_out_candidate`（`candidate_active`），攒够持仓管理数据后经 §13 #34 决定是否启用。即 v1 给价位、不给主动动态减仓逻辑。
- **启用时直接借 A 股持仓主动管理 advisory 设计作模板**——止损只升不降 ratchet、`disposition` severity-max（只升档不降）、浮盈 ≥1R 移保本、到价提示、跨周持久化（私密 sidecar）；全 advisory、不自动下单。仍属 `active_scale_out_candidate`（§13 #34），v1 不实现。

## 7. 市场环境（两轴：风控刹车 vs 赛道机会，别只 worst_of）
- **三类输入**：① VIX 风险温度（**目标使用 FMP `^VIX`；未过 provider 授权门（§3 边界）前禁用或标 `unapproved`**，不当已验；**VIX 未授权 / unavailable → 该轴按 unknown，`market_risk_regime` 退到 `SPY/QQQ + breadth` 并按 unknown 降级规则保守处理**）② 大盘趋势 `SPY + QQQ`（必须含 QQQ——池偏 AI/半导体/成长）③ 板块/市场广度（走基础 universe 成分股；行业 ETF 据公开档为付费、不依赖）。
- **两轴拆分**（关键反保守）：
  - `market_risk_regime` = `worst_of(VIX, SPY/QQQ 趋势, breadth)` → **决定仓位上限**（进攻 1.0 / 震荡 0.8 / 防御 0.5 / 极度防御 0）。
  - `theme_opportunity_state` = 赛道机会强度 → **决定赛道机会优先级**。
  - 弱市但有极强赛道时，允许"低仓位试探建仓"，不直接全转观察——**仓位落点见 §8「强赛道试探名额」**（`theme_probe`：防御 ≤1 / 进攻+极强 ≤2、最小仓、超出常规周建仓上限；极度防御 / hard veto / 熔断冷静期一律不放行）。
- **防抖**（快防守慢进攻）：降档立即；升档要确认（连续 2 次周跑更好或站回阈值上方缓冲）。
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
- `selection_rank`（多强）与 `action_rank`（这周先干哪个）分开。
- **5 组骨架（保命优先）**：① 持仓强制减/清（触发止损或 position veto）→ ② 可建仓新机会（过闸+可操作+触发/临近，按选股排名）→ ③ 加仓 → ④ 持有/观察 → ⑤ 否决/放弃。理由：不处理已触发止损损失会继续；错过新机会只是少赚。
- **组内细排输入**（都有落点、不悬空）：是否持仓=主分组轴；是否触发进出=落哪组；选股名次=组②排序；可操作性=组②门槛+排序；数据质量=降 confidence/太差→blocked；风险=硬→①/⑤、软→组②往后+降仓；集中度=同主题挤→降级；未来事件(§8.1)=临近财报/解禁→降级或转观察、持仓侧并入①/③。用分组不用加权（防把必须止损的持仓排到新买点后）。
- **`observe_reason_type`（观察必拆原因，别混"没账户"和"系统不看好"）**：`signal_not_ready / price_not_executable / cash_or_account_missing / risk_cooldown / data_restricted / event_window / cost_inefficient_min_size`（最后一项 = 试探仓小到佣金/滑点/点差吃掉期望、不下无效小单）。

## 10. 不悬空 + 证据反查 + 字段 registry（机器强制）
- **正向 no-dangling**：每个算出来的因子/字段/结论申报 ① 大白话名 ② `landing_surface`（落最终表哪格/标签）③ 影响强度（硬否决/降仓/调信心/仅标签）。validator：有计算无落点 → 报告不合格、生成不出来。"落成带说明标签"只对 advisory/shadow 软提示算合法落点。
  - **核心字段（hard veto / risk downgrade / data quality / selection / price / sizing / trigger / `market_risk_regime` / `theme_opportunity_state` / `theme_lifecycle_state`）必须影响 `final_action / action_rank / position_size / price / action_confidence / risk_tags` 至少一个**，否则转 shadow_record 或删。（`market_risk_regime` 经环境乘数+周建仓上限落地、`theme_opportunity_state` 经 §8 强赛道试探名额落地、`theme_lifecycle_state` 经席位/`theme_probe`/降仓/§9 重评落地。）
- **反向证据反查（防造假）**：报告每个 claim（临近财报/S-3/FDA/做空报告/赛道热度/新闻催化）机器层**必须反查到 provider row / SEC filing / source_id**，查不到 → 不许输出成操作影响。
- **完整字段 registry**：每字段登记 `field_id / owner_module / data_source / pit_basis / privacy_class / current_landing_surface / terminal_surface_target / operation_impact / evidence_ref_kind / lifecycle_item_id`。答不出"最后影响哪列/动作/价/仓/标签"→ 不进主系统。
- **报告生成前必检**：每字段有落点 + 每 claim 可反查；hard veto 覆盖 final_action；risk downgrade 影响仓位/信心/标签；selection vs action_rank 差异有解释；无 dangling、无无证据 claim。失败 → 报告不 clean。

## 11. 输出

### 11.1 路径与分层
- **`state\us_short\weekly_private\<决策日>\` 只放** `weekly_report.md` + `action_table.csv`；设计稿/测试/research/debug/decision packet/run summary/原始数据都不得放入。
- **机器层**（operation_impact + 全字段 + 原始分数 + decision_trace + registry）→ `state/us_short/runs_private/<决策日>/`（gitignored），不进 weekly_private、不进 tracked 工作目录；周报/csv 从机器层渲染、validator 在机器层焊死。
- **纸面账**（§12）→ `state/us_short/model_paper_private/`（gitignored）。

### 11.2 weekly_report.md 节
本周运行状态 / 账户风控状态(`portfolio_guard_status`) / 市场环境(两轴：`market_risk_regime` + `theme_opportunity_state`) / 本周核心结论 / 最终操作表(精简一眼表) / 当前持仓复核 / Top15 选股 / Top6-15 观察池 / 本周剔除摘要(exclusion_summary) / 风险与降级 / 数据源健康摘要 / 字段·模块生命周期提醒 / 本周不 clean 项。lifecycle 提醒条数第 1 节与对应节须一致。
- **顶部诚实横幅（借 A 股 M6.7）**：① 真/假观察拆分——把 `observe_reason_type` 聚合成"本周 X 只观察：A 只因没账户/没现金、B 只价格不可执行、C 只信号不够、D 只风控冷静期、E 只因最小仓成本无效——没账户/没现金那类是 sizing 假象、不是系统不看好"；② 宏观集群预警（§8）——"N 个建仓同属 X 集群、合计 Y% 仓位"；③ ship-gate 进度 + 达标 lifecycle 项数量对账；④ **price clock（必显）**——`price_data_through=上周五收盘 / news_window_through=周一跑前（含周末突发）/ session_scope=RTH / decision_date=周一`，杜绝误以为用了周一盘中价；⑤ **高热度被剔除提示**——"本周 N 只高赛道热度票被剔除（安全闸/流动性/数据），见 `hot_excluded`（§11.4）"。

### 11.3 action_table.csv（完整列）
`ticker, row_source, selection_bucket, theme_source, theme_lifecycle_state, final_action, action_rank, action_confidence, observe_reason_type, order_type, entry_plan, pullback_entry_price, breakout_entry_price, limit_order_price, valid_entry_low, valid_entry_high, order_expiry, gap_policy, effective_support, effective_resistance, structure_quality, stop_clear_price, take_profit_reduce_price, take_profit_exit_price, event_clear_reference_price, risk_reward_ratio, min_rr_gate_status, post_round_rr_status, price_engine_used, price_sub_mode, model_position_size_amount, model_position_size_shares, live_permission_status, live_size_warning, cash_allocation_status, portfolio_guard_status, symbol_cooldown_status, coverage_status, coverage_gap_tags, trigger_conditions, invalid_conditions, risk_tags, overextension_state, macro_cluster, macro_cluster_exposure_frac, macro_cluster_warning_level, macro_cluster_size_adjustment, data_quality_tags, execution_constraints, upcoming_events, decision_trace`（+ 候选增强字段）。
- **精简一眼表**（周报内 ~8 列）：操作 / 模型股数+实盘权限 / 入·盈一·盈二·损 / 类型 / 优先级 / 触发条件 / 未来大事 / 关键标签。

### 11.4 exclusion_summary（剔除摘要 + 隐私拆分）
周报告知本周剔除 N 只 + 分类（流动性/价格市值/停牌退市破产/增发SEC/数据unknown/事件unknown/数据源失败/分不够）；覆盖 Pass-1 资格剔除 + Pass-2 审计闸剔除。防误杀 + 看是否过度保守。**隐私**：暴露"真实持仓被剔" → 私密路径；纯公开 universe 计数 → 可 tracked。
- **`hot_excluded`（高热度被剔除审计）**：在 exclusion_summary 内单列"被剔除**但赛道热度高**"的票（有 `theme_heat_score` 且达分位、却在安全闸/流动性/数据 gate 出局者）+ 各自剔除原因（镜像 A 股 overlay `dropped_at_l0_l5`）。**只用于发现误杀，绝不救回 hard veto / 不改准入**；持仓票走私密拆分（同上），纯公开 universe 热票计数可 tracked。意义：把"系统是不是太保守"从感觉变成每周可见清单，喂 §13 复审赛道权重/安全闸阈值。

### 11.5 持仓覆盖诚实度
`row_source`（`top15_candidate / holding_in_top15 / holding_pass2_only / holding_account_only`）+ `coverage_status`（`full/partial/restricted/blocked`）+ `coverage_gap_tags`。即使强制进 Pass 2，缺分析师/SEC parse/事件数据 → 明示 partial/未核查、不写 clean。

### 11.6 输出路径护栏
- `.gitignore` 须覆盖**所有 private 目录**：`state/*/weekly_private/`、`state/*/account_state_csv/`、`state/*/runs_private/`、`state/*/model_paper_private/`、`state/*/lifecycle/`、`state/*/shadow_compare_private/`。**本 docs-only landing 已实跑 `git check-ignore` 核验并补齐 `.gitignore`**：`weekly_private` / `account_state_csv` 早已覆盖；本轮新增 `runs_private` / `model_paper_private` / `lifecycle` / `shadow_compare_private` 四行（沿用既有 `state/*/<private_dir>/` scheme，覆盖 a_short/a_long/us_short/us_long）。**仍待实现期（P0 Required，§18.0 / §18.1 #1）**：fail-closed 护栏测试（用 `git check-ignore` 真值，任何 private 输出路径落点在仓库内且未被忽略 → fail-fast；绕过脚本直接调管线也拦得住）——该 test = 代码，须随首个实现 slice 一起 schema-first + tests + review。
- **lifecycle / shadow 状态文件隐私规则**：含票名/表现/成交/持仓的计数（`lifecycle_register.json`、比较轨 shadow 选股明细）→ **必须 private/gitignored**；要 tracked 只能放脱敏汇总（无票名、无 $、只归一化指标）。稳定规则文字仍进 tracked `docs/system_risk_register.md`。
- **fail-closed 护栏**：用 `git check-ignore` 真值——任何 private 输出路径落点在仓库内且未被忽略 → fail-fast 报错；绕过脚本直接调管线也拦得住。

---

# 系统级治理（§12–§17）

## 12. Ship-gate / 上真钱 / Active-only / 纸面成绩单
- **满仓线 = 12 个月 forward-live（= `live_normalized` 证据，非纸面）+ 月度 alpha t≥2.0 / Sharpe≥1.0 / 回撤≤15% 四指标 AND 门**；不给美股开后门。
- **美股 active-only**：历史回测因幸存者偏差等永远只能排雷/找灵感/版本比较，证明不了 alpha、不解锁 ship-gate、不授权 full-size/DataHub/production；只能 forward 攒。forward universe 须 PIT 冻结于起点、真实捕捉退市/停牌/并购/无法成交，不删除（落地物 = `forward_universe_snapshot`，§18.1）。
- **成熟度 = 提醒 + 手动控仓**（不搞系统分档帽）：系统带每周成绩单——paper 成绩单是**进度/设计提醒**，**ship-gate 累加器只累计 `live_normalized`**（manual_actual + 对账，见下双轨）。
- **双轨（角色对齐 `docs/evidence_capital_policy.md`：纯 paper 不得判满仓 ship-gate）**：
  - `model_paper_track`（**paper 级、设计迭代轨**）：按当周 action_table + 限价 + valid_entry_band + 止损/止盈确定性模拟成交，**仅用于**设计迭代/校准/变体对比（§12.2）/pre-live 验证；不受用户是否买入影响。**`evidence_level=paper`，绝不判 full-size ship-gate**（evidence_capital_policy §2/§4：paper 不得 claim 满仓毕业）。
  - `manual_actual_track` / `execution_log_private`（§3.6 trades.csv）：用户真实（最小仓）成交/跳过/改价/提前离场 + **最小 reconciliation（实际持仓/override 记录）→ 归一化成 `live_normalized` 证据**。**这才是 ship-gate 的唯一证据源**（evidence_capital_policy §5：流程稳定 + 决策先于结果 + 成本/容量/scaling 显式 + 持仓对账齐全才算 `live_normalized`；`scaling_mode ∈ {linear, capped, not_valid, not_assessed}`、小仓不得盲目线性放大到满仓）。无真实成交 + 对账 → 证据停留 paper 级、ship-gate 不动。
- **ship-gate 只改"下多大注、信几分"，不改价位/时机**。

### 12.1 model_paper_track 纸面成交规则（写死、可复现）
- 存储 `state/us_short/model_paper_private/`：`paper_orders.csv / paper_positions.csv / paper_performance.csv`；归一化指标（t/Sharpe/回撤，无 $）可出 tracked 无密摘要。
- 只用日线 OHLCV。**复权/公司行动硬门**：未确认 `adjustment_mode` + split/dividend 处理 + 除权日价位一致性前，`paper_performance` 一律 `not_evaluable / data_degraded`，**不进任何 ship-gate / alpha 判断**（repo SR-PROVIDER-001：active price adjustment / corporate-action reconciliation 未证明、FMP 公司行动 endpoint 未 reviewed → 当前调用数为 0）。
- **订单有效期（v1 锁定）= `first_regular_session_only`**：只按周一 RTH 判定成交，盘前盘后不算；当日 RTH 收盘未成交 → `not_filled` → 转观察（不留隔日）。多日 GTC 挂单 = lifecycle 候选 `multi_day_order_expiry_candidate`（`candidate_active`）、v1 不做，靠纸面成交数据后经 §13 #35 决定是否启用。
- **成交判定（确定性顺序）**：
  - **Step 0**：`open` 不在 `[valid_entry_low, valid_entry_high]` → `not_filled`（资金算现金、不计收益）。
  - **Step 1（open 在带内，按 `order_type`）**：`pullback_limit`：`low ≤ limit_order_price` → 成交 @ `limit_order_price`；`breakout_stop_limit`：`high ≥ breakout_entry_price` → 成交 @ `min(max(open, breakout_entry_price), valid_entry_high)`；否则 `not_filled`。
- **同日多事件（日线看不出盘中先后，一律保守、防纸面虚高）**：① 入场成交当日若 `low ≤ 止损` → 按"入场后即止损"记（不假设它活过当天，daily 数据下的保守近似）；② 同日止损与止盈都触发 → 止损优先。
- **净结果口径**：`paper_performance.csv` 含 `commission_fee / slippage_bps / spread_cost / unfilled_cash / net_return`——算净收益、未成交按现金（不把没买上的当收益）。成本假设 = prior（§13 #18）。

### 12.2 赛道权重比较轨 + 错过成绩单（借 A 股 comparison-track；shadow-only）
- **目的**：每周用 `theme_plus` / `theme_aggressive`（§4.2）在 shadow 各跑一遍选股，记"它们会选哪些、`balanced` 实际选哪些"，攒证据答：主系统是否常错过强赛道？加重赛道权重是否真更好？是否该升 §13 #1 权重？防系统因太稳长期错过主线。
- **PIT + 无幸存者偏差**：比较档选股与"本来会选 X"必须决策时点 PIT 冻结、复用 §12.1 确定性纸面成交 + universe 冻结；事后重构不算数。
- **复权门连带（§12.1）**：若 §12.1 复权/公司行动门致 `paper_performance = not_evaluable/data_degraded`，则 shadow 比较轨净值同样 `not_evaluable`、**不输出升级/降级结论**（与 §12.1"不进任何 alpha 判断"一致；升级闸此时不推进）。
- **双向诚实（防"挑好看的影子结果骗自己"）**：成绩单必须报每档全口径——不只"`balanced` 错过的大牛"，还要报 **多买的亏损票、回撤、成本（佣金/滑点/点差）、空仓/现金拖累影响、坏票率**；否则永远得出"赛道越激进越好"的偏结论。
- **禁止挑样本展示**：shadow 报告必须按固定 TopN + 固定成交规则全量输出，不许只展示上涨票/热门票/事后表现好的票。
- **ship-gate 隔离**：只有 `balanced`（实际运行主轨）**经其 `live_normalized` 证据**计入 ship-gate（§12）；`theme_plus / theme_aggressive` 永远 shadow（paper-only、不交易）——只能证明"是否值得升级主系统"，绝不能直接算毕业、不能绕过正式验证。
- **`theme_off` 归因基准**：除 `theme_plus`/`theme_aggressive` 外再跑一档 **`theme_off`（赛道权重归 0、重分配给动量+催化）** 的 shadow——量"35% 赛道权重到底贡献多少 alpha"（`balanced − theme_off` = 赛道边际贡献），兼作一键回滚锚。同样 PIT 冻结 + 双向全口径 + **永不计 ship-gate**（§13 #28）。
- **顺带量"进场偏晚"**：确认门槛天然滞后 → 系统偏晚进场；`theme_aggressive`（更早进）shadow 若长期更差，说明滞后在保护你、更好则说明太晚。结果挂 §13 复审。
- **存储隐私**：比较轨含票名的 shadow 选股/成绩 → `state/us_short/shadow_compare_private/`（gitignored，§11.6）；tracked 只出脱敏归一化指标（无票名/无 $）。
- **升级闸防自欺机制（借 A 股 `a_short_overlay_eval.py`）**：① 只数 **live forward** 观测（决策当日 PIT、无 look-ahead）入升级时钟；② **胜出 margin 必须先冻**（governance 填死数值阈值后才允许触发升级复审，防"先看数据再定胜出线"）；③ 陈旧/错位 artifact **fail-closed** 不计入（桶名≠as_of 即弃）；④ 每周运行时**醒目横幅**（见 §13 `us_short_lifecycle_eval`）。升级仍需用户决定、绝不自动切生产。

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
20. 突破 tp ATR 倍数 k
21. `catalyst_recall_lane` 判据/数量
22. 组合熔断阈值（连续止损/回撤）+ 各状态档
23. 单票冷静期长度 + 恢复条件
24. 去插针 ATR 倍数
25. 全局现金分配排序权重
26. provider 健康检查阈值
27. `theme_opportunity` 强赛道试探仓封顶（防御1 / 进攻+极强2）+ 试探仓最小仓成本地板（安全倍数）
28. `scoring_profile` 比较档权重（theme_plus / theme_aggressive / theme_off 归因基准）+ 最低比较周数
29. 动态席位比例（强赛道 8+7 / 无强赛道 12+3 的触发与配比）
30. 赛道退场/衰减阈值（breadth / leader_rs 跌破线、persistence 重置）+ 状态转移防抖（降快升慢）
31. `macro_cluster` 定义 + `warning_level` 分档 + 集群暴露硬上限
32. `provisional_theme` 公式阈值（≥3 项、各字段判定线、薄来源降权、门内连续乘子窗口/映射、`persistence_mult` 门后地板 floor）
33. `breakout_mode` 参数（突破失效线、追价上限）
34. `active_scale_out_candidate`（主动减仓/移保本/ratchet 持仓管理；攒持仓管理数据再决定启用）
35. `multi_day_order_expiry_candidate`（多日 GTC 订单有效期；靠纸面成交数据决定启用）
36. 过热分档阈值（`overextension_warning` 的 k1；`chasing_extreme` 的 k2/m×ATR + 量能高潮 + 均线距离 + 回撤结构 + 多条件 AND 共现项数 K；两档互斥、绝不单条件触发）
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
1. `.gitignore` 私密路径覆盖：`weekly_private` / `account_state_csv` / `runs_private` / `model_paper_private` / `lifecycle` / `shadow_compare_private` 各行（**本 docs-only landing 已补齐缺的 4 行并以 `git check-ignore` 核验**，§11.6）+ fail-closed 护栏测试（覆盖所有 private 路径；**= 实现期代码，随首个实现 slice schema-first + tests + review**）。
2. 两遍打分可行性：先验 FMP 基础档速率限内每周跑完 Pass 1（全 universe）+ Pass 2（候选集+持仓）；定 universe 上限/候选集大小为可跑值。**前置：全 universe FMP 调用须先过 §18.0 provider 授权门（SR-PROVIDER-001），未授权只在已批准小样本上跑。**
3. provider 分层健康检查（FMP/SEC）：关键源坏 → restricted/blocked/data_degraded、不输出 clean；**未授权源（yfinance/Web/X）只记 `disabled_unapproved`、不探活/不调用/不参与 clean**（单测：健康检查绝不触达未授权源）。
4. 手动状态输入层（§3.6）：CSV(ASCII 列名) + 转换器 + lineage(sha256/row_count/as_of) + trades↔positions 对账。
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
28. provider 授权门（§3/§18.0，SR-PROVIDER-001）：全市场 FMP / yfinance / SEC parser / storage 未授权时 fail-closed、不全 universe 跑、不当生产数据；call budget + storage 留存须显式批准。
29. 复权/公司行动门（§12.1）：无 `adjustment_mode` + split/dividend + 除权价位一致确认 → `paper_performance=not_evaluable/data_degraded`，不进 ship-gate/alpha 单测。
30. `forward_universe_snapshot` artifact（§12）：forward 起点 PIT 冻结落地物——active symbol list + listing status + provider/as_of + hash + row_count + 后续 delist/halt/merger/no-trade 事件保留规则（不删除、真实捕捉）。

### 18.2 实现执行顺序（并轮策略；有边界地批量化）

> **可审查依据，非 memory 口述**：实现要省时间可以**并轮**——把可离线、同依赖、同审查面的实现刀合成批次，明显减少交接和审查往返。但**并的只是离线实现 + 审查 overhead**：**不并 provider 授权门、不并 provider/live、不免 Codex 审查、不放宽 §18.0 P0**。（2026-06-20 Claude 起草 + Codex 有边界地认可。）

- **并轮判据**：两刀共用一次起草/审查/执行，当且仅当 ① 都纯/离线（fixture 可单测、不碰 provider/真数据/真钱）或同被一个授权门 gated；② 彼此无 schema 契约的跨批先后依赖；③ 一次审查覆盖得动。必须拆轮：**跨模块消费的共享契约要先冻结**（schema-first，否则按规则打回）；任何 live/数据刀被 provider 门 gated；ship-gate 12 月时间门压不掉。
- **批次（~4 离线批 + gated provider，替代 ~30 串行小轮）**：

| 批 | 内容（§18.1 项） | 性质 | 依赖 |
|---|---|---|---|
| 批1 数据契约 + 手工输入 | 全部 schema + governance preset（§13.1 priors + scoring_profile 权重）+ CSV→`us_short_account_state` 转换器/对账（#1,#4,#11/#13-schema） | 纯/声明式 | **最先**（共享契约先冻） |
| 批2 纯决策引擎 | 价格引擎 + 两轴环境 + 仓位（含试探仓成本地板/现金分配/熔断/冷静期）+ hard veto 分层 + core_score/赛道正交/确认门连续打分/过热分档/赛道生命周期/动态席位/macro_cluster + 未来事件效应 + action_rank（#5–#7,#14–#17,#22,#23,#25,#26） | 纯（VIX 等走 unknown 路径） | 批1 冻结后 |
| 批3 校验+输出+纸面+比较+lifecycle eval | no-dangling validator + 证据反查 + registry 强制 + 输出渲染（price clock/exclusion_summary/hot_excluded/覆盖诚实）+ 纸面成交确定性规则 + 比较轨 shadow + 升级闸防自欺 + lifecycle eval 运行时阶段 + 提醒机制 + 边界回归 + **provider 健康检查的离线策略/结构 + 「绝不触达未授权源」单测**（#3-离线,#8–#10,#12,#13,#19–#21,#24） | 纯 | 消费批2 |
| 批4 周末 pipeline 接线（离线） | universe→Pass1→Pass2→engine→output 编排 + consumer-validation，全程 fixture/注入、不 live 抓数 | 纯 | 消费批2/3 |
| 批5+ provider/live | **GATED，单独授权、小样本先行**：FMP 全市场 / SEC parser / yfinance / Web·X / 生产存储 / DataHub 消费 / 两遍打分真跑 / 复权·公司行动门 live / `forward_universe_snapshot` 真捕获（#2,#3-live；§18.0 provider 门 / `SR-PROVIDER-001`） | gated | **不与批1–4 同批** |

- **批内纪律（不是把 30 项塞一个大 diff）**：每批内部仍要清楚的 **per-slice 边界 + 测试清单 + 反向失败用例 + hunk/stage 边界**；契约+直接消费者可同批，但跨模块消费的共享契约先冻结。批越大 FAIL 时重判 diff 越大、blast radius 越广——甜点是「一个子系统的纯刀 + 严格自审」、非 monolith。
- **健康检查拆分**：provider 健康检查的离线策略/结构 + 「健康检查绝不触达未授权源」单测属离线批（live 调用前就证明 fail-closed）；只有对已授权 FMP/SEC 的 **live 探活**进批5。
- **真正的省时杠杆**：并轮省的是交接 overhead；真正吃时间的是 **FAIL→修复 来回**。批次大小不是主因，**自审反向用例不足才是主要耗时源**（本设计落地时一条 guard 因缺 dual-live 反向用例连续 FAIL = 典型自致来回）。所以每批交 Codex 前必跑足 `docs/pre_codex_self_review_checklist.md`——尤其**对自己的 validator/guard 用对抗坏输入打一遍**——让每批 1 轮 PASS、而非 2–3 轮。

---

## 19. 设计结论
US Short System 是一次性完整设计；进攻在选股/发现、克制在执行/下注、同一风险只罚一次；所有"暂定值"挂 forward 校准提醒（§13）。**设计层定稿；本 docs-only landing 已将设计写进 repo（本稿 = 单一权威）+ 降级旧 `docs/us_short_spec.md` 为归档指针 + 更新路由（`docs/README.md` / `AGENTS.md` / `docs/CURRENT.md` / `docs/strategy_design_synthesis.md`）+ 补 `.gitignore` private 路径 + 登记 §18.0 P0 硬门进 register**。**尚未实现进代码**。下一步：schema-first 分片实现（执行顺序 / 并轮策略见 §18.2——离线实现 + 审查 overhead 可并批，provider 授权门 / provider·live / Codex 审查 / §18.0 P0 不并），每片 tests + Codex 审查、多 LLM 串行、不交叉 A 股；每个实现 slice 均需用户单独授权。
