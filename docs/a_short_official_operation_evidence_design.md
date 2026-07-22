# A-short 正式 M6.7 操作建议证据

## 定位

该 program 评价用户已经看到的、账户约束后的正式 M6.7 建议后来在统一日线规则下会怎样；它不是账户驾驶模拟器，也不证明用户实际成交。正式建议的唯一真相源仍是完整发布的 `weekly_m67.json` 与匹配 receipt。

## 冻结与来源

- 只接受同目录、`complete` receipt 绑定的 JSON/Markdown bundle；capture 再校验 weekly/M6.7 schema 与 `validate_m67_consistency`。
- 每条已展示建议以 `run_id`、`as_of`、候选摘要、账户快照摘要、M6.7/receipt hash 及「主动作 + 持仓处置」生成稳定 `decision_id`；capture 不重算或覆盖 M6.7。
- 新建仓计划冻结 QFQ 的入场/止损/TP1/TP2、当周 regime 的 ATR 参数、`price_data_through` 与 M6.7 的 QFQ 入场参考价；共享核心只在同一缓存能证明该参考日 `raw × observed adj_factor` 时换算到 execution scale。缺参考、缺复权或参考不一致均 `no_count`；既有持仓没有独立冻结入场基础也诚实 `no_count`，绝不伪造账户成本或仓位。
- `weekly_screening.ps1` 仅在 live canonical 周接线，且仅在 bundle 成功发布后 capture；sidecar 失败不影响已发布 M6.7。

## 结果、cache 与唯一评价核心

- P5a 的 `a_short_factor_comparison_v2_cache_build.py` 是唯一日线 writer。正式建议是其最低优先级 consumer，不得挤占 v2/P5/P2/P3 的预算、不得自建 fetcher 或联网回退。
- 结果只读取 P5a 同一份 `daily_cache.json` 的 execution projection，并只调用 `engine/a_short_managed_exit.py`。official policy 仅显式增加 TP2、TP1 后剩余仓位和同根歧义可观测性；P2/P3 默认 policy 的输入输出保持不变。
- H20 未成熟或共享行情尚未取得时为 `pending`；价格、复权或公司行动无法证明时为 `no_count`；正式建议仅在可买且开盘价落入冻结入场区间时才记为成交，区间外一路空过为 `no_count`；同根止损与止盈并发按 stop-first，并记录 `same_bar_both_triggered` 与 `execution_path_ambiguous`。
- 每个 `decision_id + live_normalized + policy_version` 最多一个终态结果。pending 可推进；后续周的 progress 日期或整份 cache digest 增长不改变终态，只有冻结来源、H20 输入窗口或结果本身漂移才写 hash conflict 并 fail closed。

## ledger、cohort 与隐私

- 私有 `ledger.json` 只记录 capture/pending/maturity/no-count/结果 hash 的决策级进度；它不是 `portfolio_state`、positions、cash、NAV、head manifest 或资金流水。
- 私有逐笔 outcome 与 tracked 脱敏汇总分离。汇总按 scope、动作/处置、入场类型、regime、V14.3、风险/覆盖、阻断、成交与同根歧义切分；小于 5 个可评价样本的 cohort 只显示计数。
- `live_normalized` 与未来 `manual_actual` 永远分列。没有独立人工账户事件账本时不得从建议推断真实成交、费用或账户盈亏。

## 硬边界

- 不创建或维护跨周现金、持仓、NAV、名义本金、账户盈亏、自动调仓或券商下单。
- 不修改 selection、排序、M6.7、receipt、P2/P3/P4/P5 ledger/verdict、V14.3 或生产参数。
- 完成本 program 仅开始积累前向证据；不得自动改变止损、止盈、股数、regime 或任何生产动作。
