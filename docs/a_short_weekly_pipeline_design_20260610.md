# A-short 周末 pipeline(批②)— 设计 + 实现切片

**日期**: 2026-06-10
**父设计**: `docs/a_short_theme_overlay_phase5_design_spec_20260610.md`(§0 定位契约 + §3 四层 + §9 周频边界)。roadmap 步骤:把已审过的各块串成一次周末跑。
**类型**: design + code + tests(打包,一次 `审查`)。**授权:无 production 变更、无真钱、无 ship-gate、不接券商/不自动下单;真实前复权价抓取是用户授权 `执行`。**

## 1. 这一批做什么(把"零件"装成"流水线")
批① 已落:Slice A overlay runner、50ETF IV feed build、Phase 5 引擎(逐票 M6.7)。它们是**纯零件**,各自单测,但**没有一条线把它们串起来产出一周的报告**。批② = 这条线:

```
EGS top-N(analysis_input.json)
        │  normalize_candidate(逐票字段映射 → 引擎输入)
        ├── Slice A overlay artifact(eligible / crowding_hit)
        ├── IV feed(252d 分位,市场级:取 feed 最新一天)
        ├── 前复权价序列(执行期抓,PIT ≤ as_of)
        └── 账户状态(available_cash / positions / Rule12 / Rule13;手工维护,不接券商)
        ▼
   Phase 5 引擎 build_m67_report(逐票)
        ▼
   一份周报 a_short_weekly_report(top-N 张 M6.7)←—— 用户只读这个
```

## 2. 关键设计决定
- **IV 是市场级,不是个股级。** 50ETF IV 252d 分位是 V14.2 Rule3/M0.5/M1 的**市场波动率闸门**,对当周所有候选取**同一个值**(feed 最新一天的 `iv_percentile_252d`)。feed 缺/最新分位为 None → 引擎按 `observe_only_missing_feed` 保守处理(不 fail-open)。`latest_iv_percentile()` 取 `series[-1]`。
- **normalize 是唯一映射点,且必须用 EGS *真实* 契约键。** `normalize_candidate(...)` 把 EGS analysis_input 候选翻成引擎归一化输入。**硬风险字段按真实契约**(对齐 `A-EGS/egs_main.py` 产出):`derived_flags.is_lock`→引擎 `limit_locked`、`event_risk.suspension.is_suspended`→`suspended`、`derived_flags.hard_veto`→引擎独立硬否决输入(即使分解原因未单独命中也硬杀)、`derived_flags.{overheat_flag,chasing_high,is_breakout,has_crash_veto}` / `event_risk.{holder_reduction.active_plan, delisting.st_flag/delisting_warning}` 照映。字段缺失 → 引擎保守/observe,不抛。**`derived_flags.vol_confirm` 可选**(EGS 已导出,见 §5):缺失/false → 保守非突破路径(低吸/观察);true → 启用 Phase 5 突破入场(is_breakout∧站稳 MA10∧vol_confirm)。
- **四道消费方/边界护栏(写入校验,不只声明):**
  - *IV feed PIT 跨-as_of*:`validate_weekly_report` 先 `validate_feed_summary_consistency(iv_feed)`(历法/PIT/升序/iv>0),**再拒 `feed.as_of > weekly.as_of` 与最新 `trade_date > weekly.as_of`**(防用未来波动率)。
  - *价格覆盖 + PIT/新鲜度不 fail-open*:`_fetch_price_series` 用 A 股 `asset="E"`,**provider 异常 → `SystemExit` 中止**(不吞成 `[]`);**每个 `trade_date` 校历法、拒任何 `> as_of` 的未来 bar、最新 bar 必须 == `as_of`(否则数据陈旧)→ 违反即中止不写**;`main` 价格覆盖门(`MIN_PRICE_OBS=20`)对任一纳入候选缺序列即**中止不写**(不静默退化成"观察")。
  - *输出路径边界*:`write_weekly_report` 经 `_reject_production_output_path`——**输出路径由调用方指定(约定 `research/results/`),但路径含 `result/a_short/` 即硬拒写**(诚实窄契约:不声称"只写 research/results",只保证绝不落 production 根)。
  - *overlay 消费校验*:`--overlay` 经 `_load_validated_overlay` = overlay JSON schema + `validate_overlay_summary_consistency` + `as_of == weekly.as_of`(拒未来/陈旧)。
  - 逐票 `validate_m67_consistency`(§4 不变量);`write_weekly_report` 还对每张 report 单独跑 m67 schema。**注:register 的 P2 是 *probe summary* 消费方义务;本 pipeline 读的是 IV feed 不读 probe summary,故对 feed 应用同形校验,但 P2(probe-summary reader)仍 open,未关。**
- **价格抓取在执行期。** 纯核(normalize / build / validate / write)合成 fixture 全可测;`main` 薄层读 artifacts + 抓前复权价(`--confirm-fetch-authorized`,可注入 `price_provider` 供测试),不在引擎/纯核里碰网络。

## 3. 输出契约(周报)
`schemas/a_short_weekly_report.schema.json`:`schema_name`(const)/`schema_version`(const)/`generated_at`/`as_of`(8位)/`iv_feed_ref`/`n_stocks`/`reports`(每项 ≥ {schema_name=a_short_m67_report, as_of, ts_code, m67, machine, boundary};**完整 m67 校验由 `write_weekly_report` 逐条另跑 m67 schema + `validate_m67_consistency`**)/**`run_lineage`**(`{analysis_input, selection_bucket, iv_feed, account_ref, account_status∈{provided,absent}, sizing_mode∈{sized,observation_only_no_account}, price_freshness}`,机器可读绑定 selection↔M6.7;Slice 3b-2;`price_freshness={mode∈{strict_as_of,intraday_prior_settled}, run_date, accepted_prior_settled_date, price_data_through}` 诚实标注 M6.7 价格特征实际用到的最新已结算 bar 日期——实盘盘中 as_of 当日 EOD 未发布时显式 intraday 模式容忍前一交易日并记录,`.md` 同步显示该价格时钟)/`boundary`(全 false)。`additionalProperties:false`。

不变量(`validate_weekly_report`):`n_stocks==len(reports)`;`boundary` 全 false;每张 `report.as_of==weekly.as_of`;`ts_code` 不重复;逐票 §4 不变量;读入的 feed 过 `validate_feed_summary_consistency`;`run_lineage` 一致(account_status=absent ⇒ sizing_mode=observation_only_no_account、sized ⇒ provided)。

## 4. 边界
- 非 production、不真钱、不 ship-gate、不接券商/不自动下单;A-short 仍 `risk_filter_only`,M6.7 为辅助建议、**edge 未验证**。
- 不动 `egs_main` / V14.2 / final_score / tier / admission(冻结)。
- 真实前复权价抓取(`pro_bar adj=qfq`)= 用户授权 `执行`;输出路径调用方指定(约定 `research/results/`),**绝不写 production 根 `result/a_short/<date>`**(写入路径硬校验)。
- 本切片 = 设计 + pipeline 纯核(normalize / build_weekly_report / validate_weekly_report / write_weekly_report)+ 周报 schema + `main` 执行接线 + 测试。
- **仍未来:** 常态化每周授权 `执行` 的正式周报产出;comparison-track ≥12 周与 12 个月 ship-gate 的前向验证(纯执行,等数据)。(首次端到端授权 `执行` 已跑通并据此修复 §5 首跑缺口。)

## 5. 首跑缺口修复(2026-06-11 follow-up,首次端到端 `执行` 后)
首跑(as-of 20260609)暴露并修复:
- **vol_confirm 解休眠**:EGS 一直在算 `vol_confirm`(up/down 量能,egs_main 2052-2093)但没导出 → 加 `derived_flags.vol_confirm` 到 analysis_input + schema(可选,旧 artifact 仍合法);normalize 早已映射 → **突破入场不再永久休眠**(is_breakout∧站稳 MA10∧vol_confirm)。**这一项动了生产 egs_main(仅多导出一个已算字段,加性低风险)。**
- **market_regime 取自 analysis_input**:pipeline 不再用账户配置里的硬编码 regime;改为读 `market_context.market_regime.status`(EGS 英文枚举 attack/shock/defense/contraction → `REGIME_MAP` 映射到 进攻/震荡/防御/收缩)。**unknown/missing 不允许被账户配置覆盖成进攻期**:按 2026-06-14 决策统一 `unknown → 震荡期 + market_regime downgrade + 保守减半 + M6.7 明确提示`。**注:EGS 当前仍可能输出 `unknown`(真正的 regime 分类器尚未在生产 egs_main 接线,V14.3 另立切片 2a/2b 在建;见 §5 末「仍未来」);本改只是消除"pipeline 侧硬编码占位"并给 unknown 加保守处理。**
- **账户状态契约(Slice 3b-2/4.2 升级)**:`--account` 现在是完整手工账户状态 JSON,契约为 `schemas/a_short_account_state.schema.json`,示例为 `schemas/examples/a_short_account_state.example.json`。它记录 `available_cash`、当前 `positions`(持仓股票/股数/均价/建仓日/手动止损)、`rule12` 组合层冷静/恢复状态、`rule13_cooldowns` 单票止损后再入状态;`manual_order_only=true` / `broker_connection_allowed=false` 被 schema 钉死。建议真实本地文件放 `state/a_short/account_state.json`(gitignored,用户手工维护,不由系统抓券商账户)。
- **M6.7 消费账户状态的规则**:`--account` 提供则必须 schema-valid、`as_of == --as-of`、正数 `available_cash`,否则 **FATAL 拒跑**(不静默退化无 sizing);未提供 `--account` → **observation-only**,周报标 `run_lineage.account_status=absent` / `sizing_mode=observation_only_no_account` + `.md` no-sizing banner。提供有效账户 → `sized`,并逐票衍生 `stateful_risk`:已有持仓输出 `持有`(按持仓管理/不按新开仓/禁止自动加仓);Rule12 `active_cooldown` 对空仓候选硬否决新开仓、对已有持仓仅提示不加仓/手动管理;Rule12 `recovery_1` 按 `recovery_position_multiplier` 限仓;Rule13 `active_cooldown`/未完成 catalyst 或 M4 复核时阻断止损后再入,`cleared_for_reentry` 或复核通过后按 `max_reentry_position_pct` 限仓。止损/清仓仍由用户盘中手动无条件执行,系统不自动下单。
- **控制台中文乱码**:非代码缺陷,是 Windows 控制台 GBK 显示;产物已是干净 UTF-8。运行 egs_main 时设 `PYTHONIOENCODING=utf-8`(或 chcp 65001)即可避免日志乱码。
- **Slice A overlay 数据装载接线(M6.7 赛道红利星级)已接线**:`build_overlay_summary_from_panels` 在 EGS run 内(pit-mode)写 `result/a_short/<as_of>/overlay.json`,`weekly_screening.ps1` 存在即传 `--overlay`,pipeline 经 `_load_validated_overlay` 消费(见 §2 overlay 消费校验 + `docs/README.md`)。
- **仍未来(不在本修复)**:EGS regime 分类器(生产 egs_main 仍可能输出 `unknown`;V14.3 分类器在 slice 2a/2b 在建,尚未生产接线)。
