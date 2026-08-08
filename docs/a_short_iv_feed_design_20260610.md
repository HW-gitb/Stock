# A-short IV feed(50ETF)— 可行性探测 + 设计切片(design-only)

**日期**: 2026-06-10
**父设计**: `docs/a_short_theme_overlay_phase5_design_spec_20260610.md`(§4 IV 决策 = 补)。roadmap 步骤 1。
**类型**: design + 可行性探测。**授权:无 production 变更、无真钱、无 ship-gate;真实 Tushare 探测调用是后续用户授权 `执行`。** 本切片冻结 IV feed 的设计契约 + 一个 probe 的可计算性评估逻辑(纯函数可测)。

## 1. 为什么要 IV
V14.2 的 Rule 3(IV>80%分位削半/>90%禁建仓)、M0.5(波动率觉醒)、M1(防御期 IV>90%)全挂在 **50ETF IV 252日分位**上。当前无数据源 → 这层空转。用户已锁定 **补 IV**(父设计 §4)。

## 2. 可行性现实(诚实,决定为什么 probe-first)
**Tushare 不直接提供隐含波动率。** 可得的是:
- `opt_basic`:期权合约静态(ts_code、标的、认购/认沽、行权价、上市/到期日)——含 510050.SH(50ETF)期权。
- `opt_daily`:期权日行情(结算价 settle、收盘 close、成交 vol、持仓 oi 等)。**无 IV 字段。**

→ **50ETF IV 必须自算**:对每张近月平值附近期权用 Black-Scholes **反解隐含波动率**,合成一个 **ATM / 恒定到期 IV 指数**,再算 **252日分位**。这是真计算,不是接口拉取。因此必须先**探测 510050 期权的 `opt_basic`/`opt_daily` 覆盖**,确认可计算,再建完整 feed。

## 3. 探测内容(probe,PIT-safe)
`computable` = **PIT 安全地 BS 反解 ATM IV 所需输入齐全**,不是"表里有几行"。对 510050.SH 期权 + 标的:
- **真日期 + PIT**:`as_of / trade_date / maturity_date` 必须是合法**日历**日期(`20260631`、`yyyyyyyy` 均作废,用 `pd.to_datetime` 解析而非字符串比大小);opt_daily / underlier **只取 `trade_date <= as_of`**(杜绝未来数据泄漏)。
- **标的身份 + 覆盖**:underlier 必须是 **510050.SH**(核 ts_code,`000300.SH` 不算),且 **close>0 的 PIT 有效天数 ≥15**(不是"任意一天正")。
- `opt_basic`:必需字段(ts_code/call_put/exercise_price/**maturity_date**);合约数 ≥20、认购∧认沽齐、行权价档 ≥5。
- `opt_daily`:必需字段;**PIT 覆盖天数 ≥15**;**basic↔daily 合约重叠 ≥20**。
- **共同 PIT 日 ≥15**(期权 PIT 日 ∩ 标的有效 PIT 日,BS 需同日配对);**共同日有效报价天数 ≥15**(按**天**计,杜绝集中单日;限重叠合约,settle/close>0)。
- **可报价未来到期 ≥2**:有有效报价的合约要覆盖 ≥2 个未来到期(只在 opt_basic 里、无报价的到期不算)。
- **ATM 可选性(最新可用估值日)**:取**最新有有效报价的共同 PIT 日**(`latest_usable_date`)当天的标的现价,且用**当天**有有效报价的合约的行权价(>0)**跨越它**(≤现价 ∧ ≥现价);**不用全窗口历史报价**(否则最新日全 0 时会用陈旧报价虚报)。
- 任一不满足 → `computable=false` + `reasons`;`computable=true` 必须无 blocking reasons、顶层 == `assessment.computable`、且**每个 PIT/质量门都达标**(防手搓 summary 虚报)。

纯函数 `assess_opt_coverage(opt_basic_df, opt_daily_df, underlier_daily_df, as_of)` 评估 + `validate_probe_summary_consistency`(顶层↔assessment + computable⇒门全达标)(合成 fixture 可测);真实 Tushare 调用在 `main` 薄层,**执行期授权**。

**Summary consistency hard gate**: for `computable=true`, the official summary must also prove `latest_usable_date` is a real YYYYMMDD date and `latest_usable_date <= as_of`, `spot_ref > 0`, `n_strikes_with_valid_quotes >= 1`, and `atm_bracketed=true`. These are contract gates, not just runner implementation details.

## 4. IV feed 设计(probe PASS 后的后续切片落地)

> **实现(批① part 1,2026-06-10)**:`runners/a_short_iv_feed_build.py` + `schemas/a_short_iv_feed.schema.json` + `tests/test_a_short_iv_feed_build.py`。探测已证 2000 积分可行(`84044dd`),故落地。下方为设计;runner 与之一致。

- 计算:近月 + 次近月 ATM 期权 BS 反解 → 线性插值到恒定到期(如 30d)→ IV 指数 → 252日滚动分位。
- 产出:独立 IV feed artifact(date、iv_value、iv_percentile_252d、awakening 判定输入),由 **Slice B 的 `market_context.volatility` 消费**。
  - **#6 扩展(2026-06-17,schema 1.1.0):** series 增 `hv_value`(50ETF 末 `hv_window`=21 交易日对数收益年化的已实现波动,与恒定到期 30d IV 同源可比),params 增 `hv_window`;供 Phase 5 引擎产**市场级 IV-HV advisory 标签**(`iv_rich`/`iv_inline`/`iv_cheap`,纯信息、绝不翻动 decision)。Rule3 的 IV 分位闸门不变。
- 缺失回退:feed 缺或状态非 `ready` → Slice B coverage 标 `iv_regime_status = observe_only_missing_feed`(父设计 §4),**不得假装执行了 IV 风控**。M0.5 schema 1.2.0 由本 feed 生成唯一觉醒/Rule3 状态；weekly/Phase5 只消费这一路径，不从 EGS 重新推导。
- **wrapper 五态（2026-08-08）**：`not_requested` / `build_failed` / `digest_failed` / `clock_mismatch` / `ready` 由周启动器显式计算并同步写入 analysis_input、sidecar outcome、M6.7 receipt；EGS 只渲染状态。非 `ready` 不传 feed、不崩溃，继续 canary/forward tracker，M6.7 保持 fail-closed。
- **读门内容重算（2026-08-08）**：`validate_feed_artifact` 用 producer 同一 `rolling_percentile_252()` 反推每行 `iv_percentile_252d`，并拒绝所有进入 M0.5 状态计算的非有限数值；`validated_feed` 只代表重算与 source/calendar binding 均通过。
- **M0.5 交易日血缘（2026-08-02）**：schema 1.2.0 顶层 `calendar` 必须来自同一次 exchange `trade_cal` probe。delta 与五日觉醒窗口都按该交易日列表的相邻索引判定：周末/交易所休市日不制造缺口；列表中真实开市日缺少 IV 时 fail-closed，不触发觉醒。交易日历不可用时写明 `calendar.status=calendar_unavailable`，不以 weekday/business-day 代理，也不得静默触发。
- **M0.5 日历完整性绑定（2026-08-02 第三轮）**：feed envelope 同时保存 `coverage_start/end`、`n_trade_dates`、交易日列表 SHA-256，以及 producer 逐日探测清单和其 SHA-256。1.2.0 重算不再把 `calendar.trade_dates` 当作自己的真值，而使用 producer probe 清单或调用方独立提供的同窗口 `trade_cal`；日历删行、插入非交易日、边界/条数/哈希不一致均 fail-closed。weekly 的 `validate_weekly_report` 与 `--iv-feed` 读入口都经过 schema + binding 校验，7 位日期等 schema 绕过被拒。
- **M0.5 独立日期对账（2026-08-02 第六轮）**：真实 build producer 还把同次已取得的 `fund_daily` PIT 日期作为 `independent_source` 写入 envelope。生产 source 固定为 `tushare.trade_cal+fund_daily`；validator 要求该独立日期集完整覆盖 feed calendar 窗口、校验哈希，并用它重算 M0.5，再把 `trade_cal` 与 probe 清单作为交叉证据。独立日期缺口、插入非交易日、外部日期集错配或 source/字段缺失均 fail-closed；不新增 provider、不把自声明 calendar 当独立真值。
- **M0.5 schema-version 内容绑定（2026-08-02 第五轮）**：兼容判定按 artifact 实际形状而非自述 `schema_version`。只要 feed 携带 `calendar`、`awakening` 或任一逐行 M0.5 字段，就必须是显式 1.2.0 并完成 schema + calendar binding + 状态重算；真正 1.1.0 只能是不含这些字段的旧形状。`latest_m05_state` 通过同一验证门，旧 1.1.0 只返回不可用空状态，不能把伪造版本或未验证字段带入 M6.7。
- **状态(2026-06-10)**:probe(`84044dd`)+ 完整 feed 构建(批① part 1:`a_short_iv_feed_build.py` 的 BS 反解 / ATM / 30d 恒定到期 / 252d 分位 / write_feed)均**已实现**(下方 §5 区分已实现 vs 仍未来)。

## 5. 边界

**已实现(代码+测试已落):** ① probe 设计 + 评估逻辑 + 结果 schema + 执行 wiring(commit `84044dd` + 执行); ② **IV feed 全量构建**(批① part 1:BS 反解 / ATM / 30d 恒定到期 / 252d 分位 / `write_feed` 强校验,`a_short_iv_feed_build.py`)。
**仍未来:** ① 真实历史回填的**授权 `执行`**(跑 build main 拉 ≥252 交易日生成 feed artifact); ② feed 的回测 / 前向验证(feasibility-grade r/q 的影响)。M0.5 的 Slice B / 周末 pipeline 接线已落在 `runners/a_short_weekly_pipeline.py` 与 `runners/a_short_phase5_engine.py`；本轮不做历史回填、不做 provider 调用。

- 本切片(probe)= 设计 + probe 评估逻辑 + 结果 schema + **执行 wiring** + 测试。
- **执行 wiring(已加)**:`init_tushare_pro`(pin base URL,**不调 set_token**;pin 不上硬 RuntimeError) → `fetch_probe_inputs`(拉 `opt_basic`(SSE)/`opt_daily`(逐交易日)/`fund_daily`(510050);每端点 sanitized status,终端只打 class/category 不打 raw 异常) → `run_probe`(过滤 50ETF + 限定 opt_daily + assess + build) → **`write_probe_summary`(写盘前强制 JSON schema + `validate_probe_summary_consistency`,唯一 sanctioned 写盘路径**,关闭 consumer-validation forward-item)。`main` 需 `TUSHARE_TOKEN` + `--confirm-fetch-authorized`。
- **provider 错误血缘(关键)**: `opt_daily` 每个交易日最多三次有界指数退避重试；仍失败即停止后续逐日请求，`main` 中止且绝不写 partial feed / `computable=false` summary。build 可原子写 schema-validated、每次运行独有的 `iv_feed_failure_<pid>.json`，只含端点、失败/尝试数、日期范围、分类、已恢复重试数和 fail-fast 状态；不保留 raw 异常、URL、token、proxy 或 provider rows。其他端点异常同样中止；**仅成功返回但覆盖不足**才写 `computable=false` summary。
- 真实 `opt_basic`/`opt_daily`/`fund_daily` 调用 = 用户授权 `执行`(per-run fetch 授权)。Tushare 接口签名 / 2000 积分访问以执行期实测为准(异常 → 中止;成功但 0 行 → not-computable + sanitized fetch report)。
- 不动 production / egs_main / V14.2(冻结);不真钱、不 ship-gate。
- IV feed 全量构建 / BS 反解 / 252d 分位 = **已实现(批① part 1)**;**M0.5 接 Slice B / 周末 pipeline = 已实现(本轮仅离线合成验证)**;历史回填执行 + 回测 = 后续。

### M0.5 觉醒期的当前保守降级（Option (c)，2026-08-02）

当前实现选择 **M0.5 保守降级模式**：觉醒 active 时本周 100% 停止新建仓，严格于 v14.2 原本的 20% 现金回收/降额模式。20% 仍作为审计字段记录（回收前、回收额、回收后），但周报的实际可分配现金与新增敞口额度都写成 0，并明确显示“本周不新建仓”；不能把 80% 余额写成可用却又分配为 0。

恢复到较宽松的 Option (b) 的唯一触发条件是：账户契约能够把**同日卖出成交的金额/结算现金**明确归因到本次决策日的可用现金。当前已核对手工账户转换器：`trades` 只有 `trade_date/side/shares/price` 等成交字段，`account.available_cash` 是账户快照，没有同日结算现金流或成交金额归因字段，因此本轮不实施 (b)，该恢复条件保持未满足（NOT_VERIFIED for any real account export beyond the checked schema/code）。

## 6. 输出契约(probe summary)
`schemas/a_short_iv_feed_probe_summary.schema.json`:`underlying`(const 510050.SH)、const-pin `thresholds`、`assessment`(**as_of_is_valid_date**/**latest_usable_date**/n_contracts/n_call/n_put/n_strikes/n_maturities/n_valid_date_maturities/n_future_maturities/**n_quotable_future_maturities**/opt_basic_missing_fields/opt_daily_has_required_fields/opt_daily_missing_fields/**opt_pit_coverage_days**/basic_daily_overlap_count/**common_pit_days**/**valid_quote_days**/valid_quote_rows/**underlier_is_510050**/**underlier_valid_days**/spot_ref/n_strikes_with_valid_quotes/atm_bracketed/computable/reasons)、顶层 `computable`(bool,schema `if/then` 强制 == assessment.computable)、`boundary`(全 false)。
