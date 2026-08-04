# US-short 26 周市场诊断轨 Knife1/Knife2 handoff

## 范围

Knife1 是不读账户、不联网、不调用 provider 的纯计算层。Knife2 在其上增加本地只读适配：校验既有 model-paper store 和本地四基准价格包，再投影为 schema-shaped 逐周记录；两刀都不改变选股、操作建议、sizing、model-paper NAV 或 Ship gate。

本轮已继续落地 Knife3 生命周期读取之后的 Knife4 聚合器：它只在第 26、52、78 等 canonical 边界生成当前 26 周固定区块 + since-inception 双视图，输出确定性的去标识化 JSON/Markdown；当前真实 model-paper 私有根尚未启动，所以没有真实成绩单或真实 10 万美元账户状态被创建。

## 已固化的计算契约

- 策略周收益由 prior NAV/NAV 构造；首周使用 `100000.000000`，`no_count` 周不补零。
- 复利、相对财富、raw excess、最大回撤、Information Ratio 和 Newey-West HAC t 已实现；HAC 的描述性 lag 为 `min(4, n - 1)`。
- 四个基准固定为 VTI/IWB/SPY/QQQ；少于 20 个 joint 周不能给 ahead/behind，price-only 或不可用数据保持降级状态。
- 26 周区块互不重叠；窗口触发是纯函数且按 `window_id` 幂等；epoch 不得静默混入，ruleset 按连续段输出。
- 计算摘要入口与触发入口共用 `window_for_week(end_week)` 的 canonical 锚点；第 5—30 周这类非边界窗口在计算路径也 fail-closed。
- 窗口身份、起止周和 `calendar_weeks` 统一由 `window_containing_week()` 产生；`window_for_week`、单周校验和 lifecycle register 不得各自重写窗口算术。
- 缺失换手率或未成交数输出 `null`；不以 0 代替缺失数据。
- 刀2 读取 `head_manifest.json`、指定结算周的 `settlement.json`、`portfolio_state.json`、`nav_snapshot.json`，并重新核对 settlement/state/NAV digest 绑定；不写 store、不推进 head。
- 刀2 的本地价格包固定 VTI/IWB/SPY/QQQ；SPY/QQQ 可来自 `grouped_market_window`，IWB/VTI 来自 `local_etf_price_packet`；每周保留 price date/source/SHA。
- 刀2 只输出 `price_return_diagnostic`；股息 sidecar 不在本刀消费，缺价格或缺前值输出 `unavailable`，不填零、不换基准。

## 代码和验证入口

- 计算器：`engine/us_short_market_diagnostic.py`
- 本地适配器：`engine/us_short_market_diagnostic_local_adapter.py`
- 合成 fixture / 反向测试 / schema 校验：`tests/test_us_short_market_diagnostic.py`
- 刀2 adapter / 私有 store digest / 本地价格包测试：`tests/test_us_short_market_diagnostic_local_adapter.py`
- 记录 schema：`schemas/us_short_market_diagnostic_weekly_record.schema.json`
- 摘要 schema：`schemas/us_short_market_diagnostic_summary.schema.json`
- 刀2 输入 schema：`schemas/us_short_market_diagnostic_local_price_packet.schema.json`
- 刀3 lifecycle persister：`engine/us_short_market_diagnostic_lifecycle.py`
- 刀3 lifecycle register schema：`schemas/us_short_market_diagnostic_lifecycle_register.schema.json`
- 刀3 计数、幂等、提醒和私有路径反向测试：`tests/test_us_short_market_diagnostic_lifecycle.py`
- 刀4 26 周聚合与发布：`engine/us_short_market_diagnostic_aggregator.py`
- 刀4 报告 schema：`schemas/us_short_market_diagnostic_report.schema.json`
- 刀4 聚合、幂等、半成品保护和 lifecycle 发布测试：`tests/test_us_short_market_diagnostic_aggregator.py`
- 设计入口：`docs/us_short_market_diagnostic_26w_design.md`

## 后续边界

刀3 已接周记录、26 周计数器和 v1.1 reminder 生命周期；Knife4 已在其上增加只读聚合与公开报告发布。聚合器只接受 lifecycle 已校验的 settled 记录；同一 `window_id` 重跑字节级幂等，JSON/Markdown 缺一不可，冲突或半成品拒绝覆盖。ETF 总回报 sidecar 仍留给 Knife5，v1.1 仓位归因仍留给 Knife6；当前真实 model-paper 根尚未启动，因此不会出现真实 26 周成绩单。
