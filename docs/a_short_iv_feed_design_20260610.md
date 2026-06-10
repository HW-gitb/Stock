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
- 计算:近月 + 次近月 ATM 期权 BS 反解 → 线性插值到恒定到期(如 30d)→ IV 指数 → 252日滚动分位。
- 产出:独立 IV feed artifact(date、iv_value、iv_percentile_252d、awakening 判定输入),由 **Slice B 的 `market_context.volatility` 消费**。
- 缺失回退:feed 缺 → Slice B coverage 标 `iv_regime_status = observe_only_missing_feed`(父设计 §4),**不得假装执行了 IV 风控**。
- 完整 feed 的构建 + 回测是 probe PASS 之后的实现切片(另走 起草→审查→提交→执行)。

## 5. 边界
- 本切片 = 设计 + probe 评估逻辑 + 结果 schema + 测试。
- 真实 `opt_basic`/`opt_daily` 探测调用 = 用户授权 `执行`(per-run fetch 授权)。
- 不动 production / egs_main / V14.2(冻结);不真钱、不 ship-gate。
- IV feed 全量构建、BS 反解实现、252d 分位、接 Slice B = 后续切片。

## 6. 输出契约(probe summary)
`schemas/a_short_iv_feed_probe_summary.schema.json`:`underlying`(const 510050.SH)、const-pin `thresholds`、`assessment`(**as_of_is_valid_date**/**latest_usable_date**/n_contracts/n_call/n_put/n_strikes/n_maturities/n_valid_date_maturities/n_future_maturities/**n_quotable_future_maturities**/opt_basic_missing_fields/opt_daily_has_required_fields/opt_daily_missing_fields/**opt_pit_coverage_days**/basic_daily_overlap_count/**common_pit_days**/**valid_quote_days**/valid_quote_rows/**underlier_is_510050**/**underlier_valid_days**/spot_ref/n_strikes_with_valid_quotes/atm_bracketed/computable/reasons)、顶层 `computable`(bool,schema `if/then` 强制 == assessment.computable)、`boundary`(全 false)。
