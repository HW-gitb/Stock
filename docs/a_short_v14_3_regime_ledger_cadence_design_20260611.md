# A-short V14.3 regime daily-feature ledger — cadence 设计(切片2b-cadence)

**日期**: 2026-06-11
**类型**: schema-first 设计 + 纯 cadence 逻辑。解决切片1/2a 留下的 cadence 缺口,**不抓数据、不接 EGS、不写文件、不碰生产**。
**前置**: 切片1(governance/daily 契约,`c7ca3c4`)、切片2a(raw classifier + 对比记录,`b0d31f5`)。

## 0. 要解决的缺口
切片1 §3 阈值要 **252 交易日滚动分位**,但 EGS run 是**周频**、当日只产一行,拿不到 252 日 breadth 历史。两种朴素做法都不行:每周回算 252×(`daily`+`stk_limit`) 调用太重;只算当日则永远攒不够窗口(每周一行,252 日要 ~5 年)。

## 1. 方案:持久化增量 daily-feature ledger
落 a_short lane 的一个 append-only ledger,存**逐交易日**的 regime 特征行(每行匹配 `a_short_market_regime_daily`)。一次性回填最后 252 交易日,之后每周 append 自上次以来的新交易日(稳态 ~5/周)。252d 分位从 ledger 读,不重算。

- **只存特征、不存派生 regime** —— 单一真相源;regime 读时由 `classify_raw_regime` 现算(切片2a),避免派生状态漂移。
- **落点**:`research/results/a_short/regime_daily_ledger.json`(guard-safe lane;`_reject_production_output_path` 只拒 `/result/a_short/`)。**绝不**写 `result/a_short`。

## 2. Cadence 语义(钉死在 governance policy + 纯逻辑)
- **plan_append(existing, as_of, calendar)**:返回要算&append 的升序交易日。
  - PIT 上限:绝不返回 `> as_of` 的日(无 look-ahead)。
  - 空 ledger → bootstrap:`<= as_of` 的**最后 252 交易日**。
  - 非空 → `(max(existing), as_of]` 内全部交易日(稳态 ~5;**漏跑几周自动补齐缺口**)。
  - `max(existing) == as_of`(已到当期)→ 返回 `[]`(同周重跑幂等);`max(existing) > as_of`(超过/未来污染)→ **raise**(不静默当"已最新")。
  - 非法输入即拒:`backfill_min<=0`、重复 existing 日期、非规范日期均 raise。
- **merge_rows(existing, new, as_of)**:append-only。拒未来日(>as_of);拒已存在日的**不同** payload(已写行**不可变**——数据修订须显式处理,不静默覆盖);相同日相同 payload 幂等 no-op。
- **bootstrap 是一次性重 API `执行`**(252 daily + 252 stk_limit + 指数历史),与周度廉价 append 分离;切片2b 实现时单独授权。

## 3. 完整性(两层,JSON Schema 表达不了的)
- **`validate_ledger_envelope`(context-free,非 sanctioned 门)**:envelope 过 ledger schema;rows 按 as_of 升序、无重复;coverage(start/end/n)与 rows 一致;`policy` 等于 const-pinned `LEDGER_POLICY`(parity);boundary = comparison-only / 非生产 / `lane_root` 不在 `result/a_short`;每行过 `a_short_market_regime_daily` 契约。**不含 PIT / 连续性**(那两项要 run 上下文)。
- **两个 sanctioned 门(都强制 as_of+calendar,行校验恒开、无旁路)**——拆门是为解决 append-前置矛盾(`R-V143-SLICE2B-APPEND-PREGATE-CONTRADICTION`):新鲜度对"最终/读"正确,但会拒掉**正常 append 前**那个收在上一 run 日的 ledger。
  - **`validate_ledger_for_append(ledger, *, as_of, trade_calendar)`(append 前置历史门,**无**新鲜度)**:envelope + 规范日期 + PIT(无行 `>as_of`)+ 既有覆盖内连续。给 `plan_append`/`merge_rows` 前校验 existing(它合法地收在上一 run 日)。`plan_append` 只从 `max(existing)` 向前规划、不修内部缺口,故必须先过此门拒 gappy(fail-closed)。
  - **`validate_ledger(ledger, *, as_of, trade_calendar)`(最终/读门 = 前置门 + **新鲜度**)**:有行时 `last_row == <= as_of 的最新交易日`,拒"连续但陈旧";合并后写盘前 / 读分位窗前调(读还须非空)。空 ledger(bootstrap 前)放行。
  - **`validate_ledger_envelope`** 仍是 context-free schema-only,**非** sanctioned 门。
- **规范日期(加严)**:`_is_canonical_date` 要求 str + 恰好 8 个 ASCII 数字 + `strftime("%Y%m%d")==s` 往返(`strptime` 单用会把 `2024011`/`202401 1` 解析成 2024-01-01,lexicographic 比较不成立)——`R-V143-SLICE2B-CANONICAL-DATE-LENIENCY-GAP`。
- **周度工作流(fail-closed 顺序)**:读 existing → `validate_ledger_for_append(existing,...)` → `plan_append` → 算新行 → `merge_rows` → `validate_ledger(merged,...)` → 写;读取时 `validate_ledger` + 非空。
- **plan_append / merge_rows 也防未来污染**:`plan_append` 对 `max(existing)>as_of` 的污染 ledger 直接 raise(不再静默当"已最新"返回空);`merge_rows` 既拒新行 `>as_of`,也拒**已存在行** `>as_of`,并拒 `existing_rows` 内**重复日期**(dict 推导前检出,杜绝静默去重掩盖损坏)。
- **行级语义(`daily_row_semantic_errors`,jsonschema 收不了的)**:6 个 nullable float 字段(promotion_rate/failed_limit_rate/iv/csi300·csi1000_ret/pct_above_ma20)必须**有限**(拒 NaN/+Inf/-Inf,null 保留);`net_limit == limit_up_count - limit_down_count`(派生量,喂 defense/attack,不一致能翻 regime);`as_of` 是**真 YYYYMMDD 日期**(strptime,拒 20240231 等);envelope 对每行跑。
- **日期语义**:`as_of` / trade_calendar / 行日期在 lexicographic 比较前都过 `_is_canonical_date`(真日历日),否则不可能日期会通过 PIT/新鲜度检查。
- **无旁路**:sanctioned `validate_ledger` 移除 `validate_rows` 参数——行校验恒开,证据时钟输入门不暴露关闭项(旁路仅留在明确非 sanctioned 的 `validate_ledger_envelope`)。

## 4. 边界(硬)
comparison-only / 非生产 / V14.2 仍冻结;不驱动 Phase 5 / veto / 仓位;只写 guard-safe research lane。本切片纯逻辑,零数据抓取、零 EGS 接线、零文件写。

## 5. 分阶段(本切片之后)
- **本切片(2b-cadence)**:ledger 契约 + 纯 cadence 逻辑(plan_append / merge_rows / validate_ledger / build_ledger)+ 测试 + 本文。
- **切片2b-impl(待本切片审过)**:EGS run 内的 daily-feature **生产**(从内存 `all_daily` + `stk_limit` + `index_daily` 算一行特征,落 ledger via merge/validate)+ bootstrap 回填 runner(一次性授权 `执行`)+ 面板 comparison-only 段(读 ledger → `classify_raw_regime` → `build_comparison_record`)+ 前向收益回填。
- **切片3(更远)**:跨周状态机 + 评分 + switch-candidate 提醒。

## 6. 本切片交付物
- 本设计文档。
- `schemas/a_short_regime_daily_ledger.schema.json`(ledger envelope + const policy + 边界)。
- `engine/a_short_regime_ledger.py`(纯:`plan_append` / `merge_rows` / `build_ledger` / `validate_ledger` + `LEDGER_POLICY` const)。
- `tests/test_a_short_regime_ledger.py`(bootstrap / 稳态 / 缺口自愈 / 幂等 / 无未来 / append-only 不可变 / 连续性 / coverage / policy parity / 边界 / lane-guard / 逐行契约)。
- **无数据抓取 / 无 EGS 接线 / 无文件写 / V14.2 不动。**
